from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from sampletagharmonizer import __version__
from sampletagharmonizer.db.models import FileInstance, ScanRun, WriteSafetyResult
from sampletagharmonizer.services.files import iter_wav_files

from .models import CoverageDiagnostic
from .write_policy import DatasetWriteSafetyValidation, WriteSafetyValidation, validate_write_safety


@dataclass(frozen=True)
class StoredDatasetWriteSafetyValidation:
    scan_run_id: str
    status: str
    result: DatasetWriteSafetyValidation

    def to_dict(self, include_files: bool = True, include_diagnostics: bool = True) -> dict[str, Any]:
        data = self.result.to_dict(include_files=include_files, include_diagnostics=include_diagnostics)
        data["scan_run_id"] = self.scan_run_id
        data["status"] = self.status
        return data


def validate_dataset_write_safety_to_db(
    session: Session,
    root: Path,
    limit: int | None = None,
    only_problematic: bool = False,
    progress: Callable[[int, int, int], None] | None = None,
    batch_size: int = 500,
) -> StoredDatasetWriteSafetyValidation:
    scan_run = ScanRun(dataset_path=f"write-safety:{root}", scanner_version=__version__)
    session.add(scan_run)
    session.commit()

    file_instance_ids_by_path = {
        path: file_id
        for path, file_id in session.execute(select(FileInstance.path, FileInstance.id))
    }
    files: list[WriteSafetyValidation] = []
    files_by_write_safety: Counter[str] = Counter()
    files_by_write_strategy: Counter[str] = Counter()
    files_by_coverage_safety: Counter[str] = Counter()
    blockers_by_code: Counter[str] = Counter()
    normalizations_by_code: Counter[str] = Counter()
    scanned = 0
    failed = 0
    status = "running"

    try:
        for wav_path in iter_wav_files(root):
            if limit is not None and scanned >= limit:
                break
            scanned += 1
            try:
                validation = validate_write_safety(wav_path)
            except Exception as exc:  # noqa: BLE001 - validation should keep going across bad files.
                failed += 1
                validation = WriteSafetyValidation(
                    path=wav_path,
                    coverage_safety="invalid",
                    write_safety="read_only",
                    write_strategy="read_only_validation_exception",
                    requirements={
                        "coverage_has_no_errors": False,
                        "only_known_tolerances": False,
                        "single_audio_data_chunk": False,
                        "has_id3_chunk": False,
                        "has_ni_soundinfo": False,
                        "single_ni_soundinfo_payload": False,
                    },
                    normalizations=[],
                    blockers=[{"code": "validation_exception", "message": str(exc)}],
                    diagnostics=[
                        CoverageDiagnostic(
                            severity="error",
                            code="validation_exception",
                            message=str(exc),
                        )
                    ],
                )

            files_by_write_safety.update([validation.write_safety])
            files_by_write_strategy.update([validation.write_strategy])
            files_by_coverage_safety.update([validation.coverage_safety])
            blockers_by_code.update(blocker["code"] for blocker in validation.blockers)
            normalizations_by_code.update(validation.normalizations)
            _store_result(session, scan_run, validation, file_instance_ids_by_path.get(str(validation.path)))
            if not only_problematic or not validation.write_safety.startswith("safe"):
                files.append(validation)
            if batch_size > 0 and scanned % batch_size == 0:
                _update_scan_run(scan_run, scanned, failed, "running")
                session.commit()
            if progress is not None:
                progress(scanned, _safe_count(files_by_write_safety), failed)

        status = "completed" if failed == 0 else "completed_with_errors"
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception:
        _update_scan_run(scan_run, scanned, failed, "failed")
        session.commit()
        raise
    finally:
        _update_scan_run(scan_run, scanned, failed, status)
        session.commit()

    return StoredDatasetWriteSafetyValidation(
        scan_run_id=scan_run.id,
        status=status,
        result=DatasetWriteSafetyValidation(
            dataset_path=root,
            scanned_files=scanned,
            failed_files=failed,
            files_by_write_safety=dict(sorted(files_by_write_safety.items())),
            files_by_write_strategy=dict(sorted(files_by_write_strategy.items())),
            files_by_coverage_safety=dict(sorted(files_by_coverage_safety.items())),
            blockers_by_code=dict(sorted(blockers_by_code.items())),
            normalizations_by_code=dict(sorted(normalizations_by_code.items())),
            files=files,
        ),
    )


def _store_result(
    session: Session,
    scan_run: ScanRun,
    validation: WriteSafetyValidation,
    file_instance_id: str | None,
) -> None:
    diagnostics_by_code = Counter(diagnostic.code for diagnostic in validation.diagnostics)
    diagnostics_by_severity = Counter(diagnostic.severity for diagnostic in validation.diagnostics)
    session.add(
        WriteSafetyResult(
            scan_run_id=scan_run.id,
            file_instance_id=file_instance_id,
            path=str(validation.path),
            coverage_safety=validation.coverage_safety,
            write_safety=validation.write_safety,
            write_strategy=validation.write_strategy,
            requirements=validation.requirements,
            normalizations=validation.normalizations,
            blockers=validation.blockers,
            diagnostic_count=len(validation.diagnostics),
            diagnostics_by_code=dict(sorted(diagnostics_by_code.items())),
            diagnostics_by_severity=dict(sorted(diagnostics_by_severity.items())),
            raw_summary=validation.to_dict(include_diagnostics=True),
        )
    )


def _update_scan_run(
    scan_run: ScanRun,
    scanned_files: int,
    failed_files: int,
    status: str,
) -> None:
    scan_run.status = status
    scan_run.scanned_files = scanned_files
    scan_run.indexed_files = scanned_files - failed_files
    scan_run.error_count = failed_files
    if status != "running":
        scan_run.finished_at = datetime.now(UTC)
    else:
        scan_run.finished_at = None


def _safe_count(counter: Counter[str]) -> int:
    return sum(count for safety, count in counter.items() if safety.startswith("safe"))
