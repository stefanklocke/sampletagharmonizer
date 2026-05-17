from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

from sqlalchemy import desc, not_, select
from sqlalchemy.orm import Session

from sampletagharmonizer import __version__
from sampletagharmonizer.db.models import AudioAsset, FileInstance, ScanError, ScanRun
from sampletagharmonizer.parsers.wav import WavAudioIdentity, inspect_audio_identity
from sampletagharmonizer.services.files import iter_wav_files


@dataclass(frozen=True)
class IndexResult:
    scan_run_id: str
    status: str
    scanned_files: int
    indexed_files: int
    error_count: int


ProgressCallback = Callable[[int, int, int], None]


def count_wav_files(root: Path, limit: int | None = None) -> int:
    count = 0
    for _ in iter_wav_files(root):
        count += 1
        if limit is not None and count >= limit:
            break
    return count


def index_dataset(
    session: Session,
    root: Path,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 500,
) -> IndexResult:
    if not root.exists():
        raise ValueError(f"Dataset path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Dataset path is not a directory: {root}")

    return index_paths(session, iter_wav_files(root), str(root), limit, progress, batch_size)


def index_resume(
    session: Session,
    source_scan_run_id: str | None = None,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 500,
) -> tuple[str, IndexResult]:
    source_scan_run_id = source_scan_run_id or latest_interrupted_index_scan_run_id(session)
    if source_scan_run_id is None:
        raise ValueError("No interrupted index run found.")
    result = index_paths(
        session=session,
        paths=index_resume_paths_for_scan_run(session, source_scan_run_id, limit),
        dataset_path=f"index-resume:{source_scan_run_id}",
        progress=progress,
        batch_size=batch_size,
    )
    return source_scan_run_id, result


def index_paths(
    session: Session,
    paths: Iterable[Path],
    dataset_path: str,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 500,
) -> IndexResult:
    scan_run = ScanRun(dataset_path=dataset_path, scanner_version=__version__)
    session.add(scan_run)
    session.commit()

    scanned = 0
    indexed = 0
    errors = 0
    status = "running"
    try:
        for wav_path in paths:
            if limit is not None and scanned >= limit:
                break
            scanned += 1
            try:
                identity = inspect_audio_identity(wav_path)
                upsert_file_instance(session, wav_path, identity, scan_run)
                indexed += 1
            except Exception as exc:  # noqa: BLE001 - indexing should keep going across bad files.
                errors += 1
                session.add(ScanError(scan_run=scan_run, path=str(wav_path), error=str(exc)))

            if scanned % 100 == 0:
                session.flush()
            if batch_size > 0 and scanned % batch_size == 0:
                _update_scan_run(scan_run, scanned, indexed, errors, "running")
                session.commit()
            if progress is not None:
                progress(scanned, indexed, errors)

        status = "completed" if errors == 0 else "completed_with_errors"
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception:
        _update_scan_run(scan_run, scanned, indexed, errors, "failed")
        session.commit()
        raise
    finally:
        _update_scan_run(scan_run, scanned, indexed, errors, status)
        session.commit()

    return IndexResult(
        scan_run_id=scan_run.id,
        status=status,
        scanned_files=scanned,
        indexed_files=indexed,
        error_count=errors,
    )


def _update_scan_run(
    scan_run: ScanRun,
    scanned_files: int,
    indexed_files: int,
    error_count: int,
    status: str,
) -> None:
    scan_run.status = status
    scan_run.scanned_files = scanned_files
    scan_run.indexed_files = indexed_files
    scan_run.error_count = error_count
    if status != "running":
        scan_run.finished_at = datetime.now(UTC)
    else:
        scan_run.finished_at = None


def latest_interrupted_index_scan_run_id(session: Session) -> str | None:
    return session.scalar(
        select(ScanRun.id)
        .where(ScanRun.status == "interrupted")
        .where(not_(ScanRun.dataset_path.like("metadata-%")))
        .order_by(desc(ScanRun.started_at))
        .limit(1)
    )


def latest_error_scan_run_id(session: Session) -> str | None:
    return session.scalar(
        select(ScanRun.id)
        .where(ScanRun.error_count > 0)
        .order_by(desc(ScanRun.started_at))
        .limit(1)
    )


def index_resume_paths_for_scan_run(session: Session, scan_run_id: str, limit: int | None = None) -> list[Path]:
    candidates = _candidate_paths_for_resume(session, scan_run_id)
    processed_paths = set(
        session.scalars(
            select(FileInstance.path).where(FileInstance.last_scan_run_id == scan_run_id)
        )
    )
    processed_paths.update(
        session.scalars(
            select(ScanError.path).where(ScanError.scan_run_id == scan_run_id)
        )
    )
    paths = [path for path in candidates if str(path) not in processed_paths]
    return paths[:limit] if limit is not None else paths


def _candidate_paths_for_resume(session: Session, scan_run_id: str) -> list[Path]:
    scan_run = session.get(ScanRun, scan_run_id)
    if scan_run is None:
        raise ValueError(f"Scan run not found: {scan_run_id}")

    dataset_path = scan_run.dataset_path
    if dataset_path.startswith("index-resume:"):
        return _candidate_paths_for_resume(session, dataset_path.removeprefix("index-resume:"))
    if dataset_path.startswith("retry-errors:"):
        return error_paths_for_scan_run(session, dataset_path.removeprefix("retry-errors:"))

    root = Path(dataset_path)
    if not root.exists():
        raise ValueError(f"Dataset path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Dataset path is not a directory: {root}")
    return list(iter_wav_files(root))


def error_paths_for_scan_run(session: Session, scan_run_id: str, limit: int | None = None) -> list[Path]:
    paths = [
        Path(path)
        for path in session.scalars(
            select(ScanError.path)
            .where(ScanError.scan_run_id == scan_run_id)
            .distinct()
            .order_by(ScanError.path)
        )
    ]
    return paths[:limit] if limit is not None else paths


def retry_error_paths(
    session: Session,
    source_scan_run_id: str,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 500,
) -> IndexResult:
    return index_paths(
        session=session,
        paths=error_paths_for_scan_run(session, source_scan_run_id, limit),
        dataset_path=f"retry-errors:{source_scan_run_id}",
        progress=progress,
        batch_size=batch_size,
    )


def upsert_file_instance(
    session: Session,
    path: Path,
    identity: WavAudioIdentity,
    scan_run: ScanRun,
) -> FileInstance:
    stat = path.stat()
    audio_asset = session.scalar(
        select(AudioAsset).where(AudioAsset.data_sha256 == identity.data_sha256)
    )
    if audio_asset is None:
        audio_asset = AudioAsset(
            data_sha256=identity.data_sha256,
            data_size=identity.data_size,
            format_tag=identity.format_tag,
            channels=identity.channels,
            sample_rate=identity.sample_rate,
            byte_rate=identity.byte_rate,
            block_align=identity.block_align,
            bits_per_sample=identity.bits_per_sample,
        )
        session.add(audio_asset)
        session.flush()

    file_instance = session.scalar(
        select(FileInstance).where(FileInstance.path == str(path))
    )
    now = datetime.now(UTC)
    if file_instance is None:
        file_instance = FileInstance(
            audio_asset=audio_asset,
            last_scan_run=scan_run,
            path=str(path),
            file_name=path.name,
            suffix=path.suffix.lower(),
            file_size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            last_seen_at=now,
        )
        session.add(file_instance)
    else:
        file_instance.audio_asset = audio_asset
        file_instance.last_scan_run = scan_run
        file_instance.file_name = path.name
        file_instance.suffix = path.suffix.lower()
        file_instance.file_size = stat.st_size
        file_instance.mtime_ns = stat.st_mtime_ns
        file_instance.last_seen_at = now
        file_instance.missing_since = None
    return file_instance
