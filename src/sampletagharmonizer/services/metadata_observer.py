from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlalchemy import delete, desc, or_, select
from sqlalchemy.orm import Session

from sampletagharmonizer import __version__
from sampletagharmonizer.db.models import FileInstance, MetadataFileResult, MetadataObservation, ScanError, ScanRun
from sampletagharmonizer.metadata import (
    METADATA_FILE_STATUS_ERROR,
    METADATA_FILE_STATUS_NO_METADATA,
    METADATA_FILE_STATUS_OBSERVED,
    SOURCE_NI_MSGPACK,
    SOURCE_NI_SOUNDINFO_UTF16,
)
from sampletagharmonizer.parsers.ni_metadata import inspect_wav


@dataclass(frozen=True)
class MetadataExtractionResult:
    scan_run_id: str
    status: str
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
    batch_size: int = 500,
) -> MetadataExtractionResult:
    return extract_metadata_from_file_instances(
        session=session,
        file_instances=_iter_indexed_file_instances(session),
        dataset_path="metadata-observations:indexed-files",
        limit=limit,
        progress=progress,
        batch_size=batch_size,
    )


def extract_metadata_resume(
    session: Session,
    source_scan_run_id: str | None = None,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 500,
) -> tuple[str, MetadataExtractionResult]:
    source_scan_run_id = source_scan_run_id or latest_interrupted_metadata_scan_run_id(session)
    if source_scan_run_id is None:
        raise ValueError("No interrupted metadata extraction run found.")
    result = extract_metadata_from_file_instances(
        session=session,
        file_instances=metadata_resume_file_instances_for_scan_run(session, source_scan_run_id, limit),
        dataset_path=f"metadata-resume:{source_scan_run_id}",
        progress=progress,
        batch_size=batch_size,
    )
    return source_scan_run_id, result


def latest_interrupted_metadata_scan_run_id(session: Session) -> str | None:
    return session.scalar(
        select(ScanRun.id)
        .where(ScanRun.status == "interrupted")
        .where(
            or_(
                ScanRun.dataset_path.like("metadata-observations:%"),
                ScanRun.dataset_path.like("metadata-retry-errors:%"),
                ScanRun.dataset_path.like("metadata-resume:%"),
            )
        )
        .order_by(desc(ScanRun.started_at))
        .limit(1)
    )


def latest_metadata_error_scan_run_id(session: Session) -> str | None:
    return session.scalar(
        select(ScanRun.id)
        .where(ScanRun.error_count > 0)
        .where(
            or_(
                ScanRun.dataset_path.like("metadata-observations:%"),
                ScanRun.dataset_path.like("metadata-retry-errors:%"),
            )
        )
        .order_by(desc(ScanRun.started_at))
        .limit(1)
    )


def metadata_error_file_instances_for_scan_run(
    session: Session,
    scan_run_id: str,
    limit: int | None = None,
) -> list[FileInstance]:
    paths = [
        path
        for path in session.scalars(
            select(ScanError.path)
            .where(ScanError.scan_run_id == scan_run_id)
            .distinct()
            .order_by(ScanError.path)
        )
    ]
    if limit is not None:
        paths = paths[:limit]
    if not paths:
        return []

    file_instances = list(
        session.scalars(
            select(FileInstance)
            .where(FileInstance.path.in_(paths))
            .order_by(FileInstance.path)
        )
    )
    by_path = {file_instance.path: file_instance for file_instance in file_instances}
    return [by_path[path] for path in paths if path in by_path]


def metadata_resume_file_instances_for_scan_run(
    session: Session,
    scan_run_id: str,
    limit: int | None = None,
) -> list[FileInstance]:
    processed_ids = set(
        session.scalars(
            select(MetadataFileResult.file_instance_id).where(MetadataFileResult.scan_run_id == scan_run_id)
        )
    )
    query = select(FileInstance).order_by(FileInstance.path)
    if processed_ids:
        query = query.where(FileInstance.id.not_in(processed_ids))
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))


def retry_metadata_errors(
    session: Session,
    source_scan_run_id: str,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 500,
) -> MetadataExtractionResult:
    return extract_metadata_from_file_instances(
        session=session,
        file_instances=metadata_error_file_instances_for_scan_run(session, source_scan_run_id, limit),
        dataset_path=f"metadata-retry-errors:{source_scan_run_id}",
        progress=progress,
        batch_size=batch_size,
    )


def extract_metadata_from_file_instances(
    session: Session,
    file_instances: Iterable[FileInstance],
    dataset_path: str,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 500,
) -> MetadataExtractionResult:
    scan_run = ScanRun(dataset_path=dataset_path, scanner_version=__version__)
    session.add(scan_run)
    session.commit()

    scanned = 0
    observed_files = 0
    observation_count = 0
    errors = 0
    status = "running"
    try:
        for file_instance in file_instances:
            if limit is not None and scanned >= limit:
                break
            scanned += 1
            try:
                observations = observations_for_file_instance(file_instance, scan_run)
                replace_observations(session, file_instance, observations)
                replace_file_result(
                    session=session,
                    scan_run=scan_run,
                    file_instance=file_instance,
                    status=METADATA_FILE_STATUS_OBSERVED if observations else METADATA_FILE_STATUS_NO_METADATA,
                    observation_count=len(observations),
                )
                if observations:
                    observed_files += 1
                    observation_count += len(observations)
            except Exception as exc:  # noqa: BLE001 - extraction should keep going across bad files.
                errors += 1
                session.add(ScanError(scan_run=scan_run, path=file_instance.path, error=str(exc)))
                replace_file_result(
                    session=session,
                    scan_run=scan_run,
                    file_instance=file_instance,
                    status=METADATA_FILE_STATUS_ERROR,
                    observation_count=0,
                    error=str(exc),
                )

            if scanned % 100 == 0:
                session.flush()
            if batch_size > 0 and scanned % batch_size == 0:
                _update_scan_run(scan_run, scanned, observation_count, errors, "running")
                session.commit()
            if progress is not None:
                progress(scanned, observation_count, errors)

        status = "completed" if errors == 0 else "completed_with_errors"
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception:
        _update_scan_run(scan_run, scanned, observation_count, errors, "failed")
        session.commit()
        raise
    finally:
        _update_scan_run(scan_run, scanned, observation_count, errors, status)
        session.commit()

    return MetadataExtractionResult(
        scan_run_id=scan_run.id,
        status=status,
        scanned_files=scanned,
        observed_files=observed_files,
        observation_count=observation_count,
        error_count=errors,
    )


def _update_scan_run(
    scan_run: ScanRun,
    scanned_files: int,
    observation_count: int,
    error_count: int,
    status: str,
) -> None:
    scan_run.status = status
    scan_run.scanned_files = scanned_files
    scan_run.indexed_files = observation_count
    scan_run.error_count = error_count
    if status != "running":
        scan_run.finished_at = datetime.now(UTC)
    else:
        scan_run.finished_at = None


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
                source_type=SOURCE_NI_SOUNDINFO_UTF16,
                observation_index=index,
                source_chunk_id=soundinfo.get("source_chunk_id"),
                source_chunk_offset=soundinfo.get("source_chunk_offset"),
                source_frame_id=soundinfo.get("source_frame_id"),
                source_frame_offset=soundinfo.get("source_frame_offset"),
                source_payload_offset=soundinfo.get("source_payload_offset"),
                source_payload_size=soundinfo.get("source_payload_size"),
                title=summary.get("title"),
                vendor=summary.get("vendor"),
                product=summary.get("product"),
                category_paths=summary.get("category_paths"),
                attributes=summary.get("attributes"),
                raw_payload=_raw_soundinfo_payload(soundinfo),
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


def replace_file_result(
    session: Session,
    scan_run: ScanRun,
    file_instance: FileInstance,
    status: str,
    observation_count: int,
    error: str | None = None,
) -> None:
    session.execute(
        delete(MetadataFileResult).where(
            MetadataFileResult.scan_run_id == scan_run.id,
            MetadataFileResult.file_instance_id == file_instance.id,
        )
    )
    session.add(
        MetadataFileResult(
            scan_run_id=scan_run.id,
            file_instance_id=file_instance.id,
            path=file_instance.path,
            status=status,
            observation_count=observation_count,
            error=error,
        )
    )


def _iter_indexed_file_instances(session: Session) -> Iterable[FileInstance]:
    return list(session.scalars(select(FileInstance).order_by(FileInstance.path)))


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
        source_type=SOURCE_NI_MSGPACK,
        observation_index=observation_index,
        source_chunk_id=candidate.get("chunk_id"),
        source_chunk_offset=candidate.get("chunk_offset"),
        source_frame_id=candidate.get("frame_id"),
        source_frame_offset=candidate.get("frame_offset"),
        source_payload_offset=candidate.get("offset"),
        source_payload_size=candidate.get("consumed"),
        title=value.get("name"),
        vendor=value.get("vendor"),
        product=product,
        category_paths=value.get("types"),
        attributes=attributes,
        raw_payload=_raw_msgpack_payload(candidate),
    )


def _raw_soundinfo_payload(soundinfo: dict[str, Any]) -> dict[str, Any]:
    return dict(soundinfo)


def _raw_msgpack_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    return dict(candidate)
