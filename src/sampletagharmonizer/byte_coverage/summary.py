from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sampletagharmonizer.services.files import iter_wav_files

from .models import ByteCoverageMap, CoverageDiagnostic
from .wav_map import build_wav_byte_map


@dataclass(frozen=True)
class ByteCoverageValidation:
    path: Path
    file_size: int | None
    safety: str
    diagnostic_count: int
    diagnostics_by_code: dict[str, int]
    diagnostics_by_severity: dict[str, int]
    region_counts_by_kind: dict[str, int]
    diagnostics: list[CoverageDiagnostic] = field(default_factory=list)

    def to_dict(self, include_diagnostics: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": str(self.path),
            "file_size": self.file_size,
            "safety": self.safety,
            "diagnostic_count": self.diagnostic_count,
            "diagnostics_by_code": self.diagnostics_by_code,
            "diagnostics_by_severity": self.diagnostics_by_severity,
            "region_counts_by_kind": self.region_counts_by_kind,
        }
        if include_diagnostics:
            data["diagnostics"] = [diagnostic.to_dict() for diagnostic in self.diagnostics]
        return data


@dataclass(frozen=True)
class DatasetByteCoverageValidation:
    dataset_path: Path
    scanned_files: int
    failed_files: int
    files_by_safety: dict[str, int]
    diagnostics_by_code: dict[str, int]
    diagnostics_by_severity: dict[str, int]
    files: list[ByteCoverageValidation]

    def to_dict(self, include_files: bool = True, include_diagnostics: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "dataset_path": str(self.dataset_path),
            "scanned_files": self.scanned_files,
            "failed_files": self.failed_files,
            "files_by_safety": self.files_by_safety,
            "diagnostics_by_code": self.diagnostics_by_code,
            "diagnostics_by_severity": self.diagnostics_by_severity,
        }
        if include_files:
            data["files"] = [
                file.to_dict(include_diagnostics=include_diagnostics)
                for file in self.files
            ]
        return data


def validate_byte_coverage(path: Path) -> ByteCoverageValidation:
    return summarize_byte_coverage_map(build_wav_byte_map(path))


def summarize_byte_coverage_map(coverage_map: ByteCoverageMap) -> ByteCoverageValidation:
    return ByteCoverageValidation(
        path=coverage_map.path,
        file_size=coverage_map.file_size,
        safety=coverage_map.safety,
        diagnostic_count=len(coverage_map.diagnostics),
        diagnostics_by_code=_counter_dict(diagnostic.code for diagnostic in coverage_map.diagnostics),
        diagnostics_by_severity=_counter_dict(diagnostic.severity for diagnostic in coverage_map.diagnostics),
        region_counts_by_kind=_counter_dict(region.kind for region in coverage_map.regions),
        diagnostics=coverage_map.diagnostics,
    )


def validate_dataset_byte_coverage(
    root: Path,
    limit: int | None = None,
    only_problematic: bool = False,
    progress: Callable[[int, int, int], None] | None = None,
) -> DatasetByteCoverageValidation:
    files: list[ByteCoverageValidation] = []
    files_by_safety: Counter[str] = Counter()
    diagnostics_by_code: Counter[str] = Counter()
    diagnostics_by_severity: Counter[str] = Counter()
    scanned = 0
    failed = 0

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
        if not only_problematic or validation.safety != "safe_to_rewrite":
            files.append(validation)
        if progress is not None:
            progress(scanned, files_by_safety["safe_to_rewrite"], failed)

    return DatasetByteCoverageValidation(
        dataset_path=root,
        scanned_files=scanned,
        failed_files=failed,
        files_by_safety=dict(sorted(files_by_safety.items())),
        diagnostics_by_code=dict(sorted(diagnostics_by_code.items())),
        diagnostics_by_severity=dict(sorted(diagnostics_by_severity.items())),
        files=files,
    )


def _counter_dict(values) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))
