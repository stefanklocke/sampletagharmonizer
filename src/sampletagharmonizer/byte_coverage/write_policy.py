from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sampletagharmonizer.services.files import iter_wav_files

from .models import ByteCoverageMap, CoverageDiagnostic
from .wav_map import build_wav_byte_map


KNOWN_TOLERANCE_CODES = {
    "chunk_payload_extends_beyond_declared_riff",
    "declared_riff_end_one_byte_beyond_file",
    "declared_riff_end_one_header_beyond_file",
    "extra_zero_padding_before_chunk",
    "file_extends_beyond_declared_riff",
    "final_padding_outside_declared_riff",
    "missing_chunk_padding",
    "trailing_zero_padding",
    "uncovered_tail",
}


@dataclass(frozen=True)
class WriteSafetyValidation:
    path: Path
    coverage_safety: str
    write_safety: str
    write_strategy: str
    requirements: dict[str, bool]
    normalizations: list[str]
    blockers: list[dict[str, Any]]
    diagnostics: list[CoverageDiagnostic] = field(default_factory=list)

    def to_dict(self, include_diagnostics: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": str(self.path),
            "coverage_safety": self.coverage_safety,
            "write_safety": self.write_safety,
            "write_strategy": self.write_strategy,
            "requirements": self.requirements,
            "normalizations": self.normalizations,
            "blockers": self.blockers,
        }
        if include_diagnostics:
            data["diagnostics"] = [diagnostic.to_dict() for diagnostic in self.diagnostics]
        return data


@dataclass(frozen=True)
class DatasetWriteSafetyValidation:
    dataset_path: Path
    scanned_files: int
    failed_files: int
    files_by_write_safety: dict[str, int]
    files_by_write_strategy: dict[str, int]
    files_by_coverage_safety: dict[str, int]
    blockers_by_code: dict[str, int]
    normalizations_by_code: dict[str, int]
    files: list[WriteSafetyValidation]

    def to_dict(self, include_files: bool = True, include_diagnostics: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "dataset_path": str(self.dataset_path),
            "scanned_files": self.scanned_files,
            "failed_files": self.failed_files,
            "files_by_write_safety": self.files_by_write_safety,
            "files_by_write_strategy": self.files_by_write_strategy,
            "files_by_coverage_safety": self.files_by_coverage_safety,
            "blockers_by_code": self.blockers_by_code,
            "normalizations_by_code": self.normalizations_by_code,
        }
        if include_files:
            data["files"] = [
                file.to_dict(include_diagnostics=include_diagnostics)
                for file in self.files
            ]
        return data


def validate_write_safety(path: Path) -> WriteSafetyValidation:
    return assess_write_safety_map(build_wav_byte_map(path))


def assess_write_safety_map(coverage_map: ByteCoverageMap) -> WriteSafetyValidation:
    audio_count = _count_regions(coverage_map, "audio")
    id3_count = _count_id3_payload_regions(coverage_map)
    soundinfo_count = _count_regions(coverage_map, "ni_soundinfo_payload")
    error_count = _count_diagnostics(coverage_map, "error")
    unknown_tolerances = sorted(
        {
            diagnostic.code
            for diagnostic in coverage_map.diagnostics
            if diagnostic.severity == "warning" and diagnostic.code not in KNOWN_TOLERANCE_CODES
        }
    )
    normalizations = sorted(
        {
            diagnostic.code
            for diagnostic in coverage_map.diagnostics
            if diagnostic.severity == "warning"
        }
    )

    requirements = {
        "coverage_has_no_errors": error_count == 0,
        "only_known_tolerances": not unknown_tolerances,
        "single_audio_data_chunk": audio_count == 1,
        "has_id3_chunk": id3_count > 0,
        "has_ni_soundinfo": soundinfo_count > 0,
        "single_ni_soundinfo_payload": soundinfo_count == 1,
    }
    blockers: list[dict[str, Any]] = []

    if error_count:
        blockers.append(_blocker("coverage_errors", "Coverage diagnostics contain error-level entries.", {"error_count": error_count}))
        return _validation(coverage_map, "read_only", "read_only_coverage_errors", requirements, normalizations, blockers)

    if unknown_tolerances:
        blockers.append(_blocker("unknown_tolerances", "Coverage diagnostics contain warning-level entries not yet approved by the write policy.", {"codes": unknown_tolerances}))
        return _validation(coverage_map, "review_required", "manual_review_unknown_tolerances", requirements, normalizations, blockers)

    if audio_count == 0:
        blockers.append(_blocker("missing_audio_data_chunk", "No audio data chunk was mapped."))
        return _validation(coverage_map, "read_only", "read_only_missing_audio_data_chunk", requirements, normalizations, blockers)

    if audio_count > 1:
        blockers.append(_blocker("multiple_audio_data_chunks", "Multiple audio data chunks were mapped.", {"audio_data_chunks": audio_count}))
        return _validation(coverage_map, "read_only", "read_only_multiple_audio_data_chunks", requirements, normalizations, blockers)

    if id3_count == 0:
        blockers.append(_blocker("missing_id3_chunk", "No ID3 metadata chunk was mapped."))
        return _validation(coverage_map, "read_only", "unsupported_missing_id3_chunk", requirements, normalizations, blockers)

    if soundinfo_count == 0:
        blockers.append(_blocker("missing_ni_soundinfo_payload", "No Native Instruments SoundInfo payload was mapped."))
        return _validation(coverage_map, "read_only", "unsupported_missing_ni_soundinfo_payload", requirements, normalizations, blockers)

    if soundinfo_count > 1:
        blockers.append(_blocker("multiple_ni_soundinfo_payloads", "Multiple Native Instruments SoundInfo payloads were mapped.", {"ni_soundinfo_payloads": soundinfo_count}))
        return _validation(coverage_map, "review_required", "manual_review_multiple_ni_soundinfo_payloads", requirements, normalizations, blockers)

    if normalizations:
        return _validation(
            coverage_map,
            "safe_with_normalization_to_update_existing_metadata",
            "normalize_then_update_existing_id3_geob",
            requirements,
            normalizations,
            blockers,
        )

    return _validation(
        coverage_map,
        "safe_to_update_existing_metadata",
        "preserve_audio_update_existing_id3_geob",
        requirements,
        normalizations,
        blockers,
    )


def validate_dataset_write_safety(
    root: Path,
    limit: int | None = None,
    only_problematic: bool = False,
    progress: Callable[[int, int, int], None] | None = None,
) -> DatasetWriteSafetyValidation:
    files: list[WriteSafetyValidation] = []
    files_by_write_safety: Counter[str] = Counter()
    files_by_write_strategy: Counter[str] = Counter()
    files_by_coverage_safety: Counter[str] = Counter()
    blockers_by_code: Counter[str] = Counter()
    normalizations_by_code: Counter[str] = Counter()
    scanned = 0
    failed = 0

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
                blockers=[_blocker("validation_exception", str(exc))],
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
        if not only_problematic or not validation.write_safety.startswith("safe"):
            files.append(validation)
        if progress is not None:
            progress(scanned, _safe_count(files_by_write_safety), failed)

    return DatasetWriteSafetyValidation(
        dataset_path=root,
        scanned_files=scanned,
        failed_files=failed,
        files_by_write_safety=dict(sorted(files_by_write_safety.items())),
        files_by_write_strategy=dict(sorted(files_by_write_strategy.items())),
        files_by_coverage_safety=dict(sorted(files_by_coverage_safety.items())),
        blockers_by_code=dict(sorted(blockers_by_code.items())),
        normalizations_by_code=dict(sorted(normalizations_by_code.items())),
        files=files,
    )


def _validation(
    coverage_map: ByteCoverageMap,
    write_safety: str,
    write_strategy: str,
    requirements: dict[str, bool],
    normalizations: list[str],
    blockers: list[dict[str, Any]],
) -> WriteSafetyValidation:
    return WriteSafetyValidation(
        path=coverage_map.path,
        coverage_safety=coverage_map.safety,
        write_safety=write_safety,
        write_strategy=write_strategy,
        requirements=requirements,
        normalizations=normalizations,
        blockers=blockers,
        diagnostics=coverage_map.diagnostics,
    )


def _blocker(code: str, message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"code": code, "message": message}
    if metadata:
        data["metadata"] = metadata
    return data


def _count_regions(coverage_map: ByteCoverageMap, kind: str) -> int:
    return sum(1 for region in coverage_map.regions if region.kind == kind)


def _count_id3_payload_regions(coverage_map: ByteCoverageMap) -> int:
    return sum(
        1
        for region in coverage_map.regions
        if region.kind == "metadata" and region.metadata.get("chunk_id") == "ID3 "
    )


def _count_diagnostics(coverage_map: ByteCoverageMap, severity: str) -> int:
    return sum(1 for diagnostic in coverage_map.diagnostics if diagnostic.severity == severity)


def _safe_count(counter: Counter[str]) -> int:
    return sum(count for safety, count in counter.items() if safety.startswith("safe"))
