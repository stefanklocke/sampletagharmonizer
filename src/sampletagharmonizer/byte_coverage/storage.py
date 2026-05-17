from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from sampletagharmonizer import __version__
from sampletagharmonizer.db.models import ByteCoverageResult, FileInstance, ScanRun
from sampletagharmonizer.services.files import iter_wav_files

from .models import CoverageDiagnostic
from .summary import ByteCoverageValidation, DatasetByteCoverageValidation, validate_byte_coverage


@dataclass(frozen=True)
class StoredDatasetByteCoverageValidation:
    scan_run_id: str
    status: str
    result: DatasetByteCoverageValidation

    def to_dict(self, include_files: bool = True, include_diagnostics: bool = True) -> dict[str, Any]:
        data = self.result.to_dict(include_files=include_files, include_diagnostics=include_diagnostics)
        data["scan_run_id"] = self.scan_run_id
        data["status"] = self.status
        return data


def validate_dataset_byte_coverage_to_db(
    session: Session,
    root: Path,
    limit: int | None = None,
    only_problematic: bool = False,
    progress: Callable[[int, int, int], None] | None = None,
    batch_size: int = 500,
) -> StoredDatasetByteCoverageValidation:
    scan_run = ScanRun(dataset_path=f"byte-coverage:{root}", scanner_version=__version__)
    session.add(scan_run)
    session.commit()

    file_instance_ids_by_path = {
        path: file_id
        for path, file_id in session.execute(select(FileInstance.path, FileInstance.id))
    }
    files: list[ByteCoverageValidation] = []
    files_by_safety: Counter[str] = Counter()
    diagnostics_by_code: Counter[str] = Counter()
    diagnostics_by_severity: Counter[str] = Counter()
    scanned = 0
    failed = 0
    status = "running"

    try:
        for wav_path in iter_wav_files(root):
            if limit is not None and scanned >= limit:
                break
            scanned += 1
            try:
                validation = validate_byte_coverage(wav_path)
            except Exception as exc:  # noqa: BLE001 - validation should keep going across bad files.
                failed += 1
                validation = ByteCoverageValidation(
                    path=wav_path,
                    file_size=None,
                    safety="invalid",
                    diagnostic_count=1,
                    diagnostics_by_code={"coverage_exception": 1},
                    diagnostics_by_severity={"error": 1},
                    region_counts_by_kind={},
                    diagnostics=[
                        CoverageDiagnostic(
                            severity="error",
                            code="coverage_exception",
                            message=str(exc),
                        )
                    ],
                )

            files_by_safety.update([validation.safety])
            diagnostics_by_code.update(validation.diagnostics_by_code)
            diagnostics_by_severity.update(validation.diagnostics_by_severity)
            _store_result(session, scan_run, validation, file_instance_ids_by_path.get(str(validation.path)))
            if not only_problematic or validation.safety != "safe_to_rewrite":
                files.append(validation)
            if batch_size > 0 and scanned % batch_size == 0:
                _update_scan_run(scan_run, scanned, failed, "running")
                session.commit()
            if progress is not None:
                progress(scanned, files_by_safety["safe_to_rewrite"], failed)

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

    return StoredDatasetByteCoverageValidation(
        scan_run_id=scan_run.id,
        status=status,
        result=DatasetByteCoverageValidation(
            dataset_path=root,
            scanned_files=scanned,
            failed_files=failed,
            files_by_safety=dict(sorted(files_by_safety.items())),
            diagnostics_by_code=dict(sorted(diagnostics_by_code.items())),
            diagnostics_by_severity=dict(sorted(diagnostics_by_severity.items())),
            files=files,
        ),
    )


def _store_result(
    session: Session,
    scan_run: ScanRun,
    validation: ByteCoverageValidation,
    file_instance_id: str | None,
) -> None:
    session.add(
        ByteCoverageResult(
            scan_run_id=scan_run.id,
            file_instance_id=file_instance_id,
            path=str(validation.path),
            file_size=validation.file_size,
            coverage_safety=validation.safety,
            diagnostic_count=validation.diagnostic_count,
            diagnostics_by_code=validation.diagnostics_by_code,
            diagnostics_by_severity=validation.diagnostics_by_severity,
            region_counts_by_kind=validation.region_counts_by_kind,
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
