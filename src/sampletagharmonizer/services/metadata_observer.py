from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from sampletagharmonizer import __version__
from sampletagharmonizer.db.models import FileInstance, MetadataObservation, ScanError, ScanRun
from sampletagharmonizer.parsers.ni_metadata import inspect_wav


@dataclass(frozen=True)
class MetadataExtractionResult:
    scan_run_id: str
    scanned_files: int
    observed_files: int
    observation_count: int
    error_count: int


ProgressCallback = Callable[[int, int, int], None]


def count_indexed_files(session: Session, limit: int | None = None) -> int:
    count = 0
    for _ in _iter_indexed_file_instances(session):
        count += 1
        if limit is not None and count >= limit:
            break
    return count


def extract_metadata_from_index(
    session: Session,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> MetadataExtractionResult:
    return extract_metadata_from_file_instances(
        session=session,
        file_instances=_iter_indexed_file_instances(session),
        dataset_path="metadata-observations:indexed-files",
        limit=limit,
        progress=progress,
    )


def extract_metadata_from_file_instances(
    session: Session,
    file_instances: Iterable[FileInstance],
    dataset_path: str,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> MetadataExtractionResult:
    scan_run = ScanRun(dataset_path=dataset_path, scanner_version=__version__)
    session.add(scan_run)
    session.flush()

    scanned = 0
    observed_files = 0
    observation_count = 0
    errors = 0
    try:
        for file_instance in file_instances:
            if limit is not None and scanned >= limit:
                break
            scanned += 1
            try:
                observations = observations_for_file_instance(file_instance, scan_run)
                replace_observations(session, file_instance, observations)
                if observations:
                    observed_files += 1
                    observation_count += len(observations)
            except Exception as exc:  # noqa: BLE001 - extraction should keep going across bad files.
                errors += 1
                session.add(ScanError(scan_run=scan_run, path=file_instance.path, error=str(exc)))

            if scanned % 100 == 0:
                session.flush()
            if progress is not None:
                progress(scanned, observation_count, errors)

        scan_run.status = "completed" if errors == 0 else "completed_with_errors"
        return MetadataExtractionResult(
            scan_run_id=scan_run.id,
            scanned_files=scanned,
            observed_files=observed_files,
            observation_count=observation_count,
            error_count=errors,
        )
    except Exception:
        scan_run.status = "failed"
        raise
    finally:
        scan_run.scanned_files = scanned
        scan_run.indexed_files = observation_count
        scan_run.error_count = errors
        scan_run.finished_at = datetime.now(UTC)


def observations_for_file_instance(
    file_instance: FileInstance,
    scan_run: ScanRun,
) -> list[MetadataObservation]:
    report = inspect_wav(Path(file_instance.path))
    observations: list[MetadataObservation] = []

    for index, soundinfo in enumerate(report["ni_soundinfo"]):
        summary = soundinfo.get("summary", {})
        observations.append(
            MetadataObservation(
                audio_asset_id=file_instance.audio_asset_id,
                file_instance_id=file_instance.id,
                scan_run_id=scan_run.id,
                source_type="ni_soundinfo_utf16",
                observation_index=index,
                title=summary.get("title"),
                vendor=summary.get("vendor"),
                product=summary.get("product"),
                category_paths=summary.get("category_paths"),
                attributes=summary.get("attributes"),
                raw_payload=soundinfo,
            )
        )

    for index, candidate in enumerate(report["msgpack_candidates"]):
        value = candidate.get("value")
        if not isinstance(value, dict):
            continue
        observations.append(_msgpack_observation(file_instance, scan_run, index, candidate, value))

    return observations


def replace_observations(
    session: Session,
    file_instance: FileInstance,
    observations: list[MetadataObservation],
) -> None:
    session.execute(
        delete(MetadataObservation).where(MetadataObservation.file_instance_id == file_instance.id)
    )
    session.add_all(observations)


def _iter_indexed_file_instances(session: Session) -> Iterable[FileInstance]:
    yield from session.scalars(select(FileInstance).order_by(FileInstance.path))


def _msgpack_observation(
    file_instance: FileInstance,
    scan_run: ScanRun,
    observation_index: int,
    candidate: dict[str, Any],
    value: dict[str, Any],
) -> MetadataObservation:
    bankchain = value.get("bankchain")
    product = bankchain[0] if isinstance(bankchain, list) and bankchain else None
    attributes = {
        key: value.get(key)
        for key in ["author", "bankchain", "comment", "modes", "tempo", "__ni_internal"]
        if key in value
    }
    return MetadataObservation(
        audio_asset_id=file_instance.audio_asset_id,
        file_instance_id=file_instance.id,
        scan_run_id=scan_run.id,
        source_type="ni_msgpack",
        observation_index=observation_index,
        title=value.get("name"),
        vendor=value.get("vendor"),
        product=product,
        category_paths=value.get("types"),
        attributes=attributes,
        raw_payload=candidate,
    )
