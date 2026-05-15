from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from sampletagharmonizer import __version__
from sampletagharmonizer.db.models import AudioAsset, FileInstance, ScanError, ScanRun
from sampletagharmonizer.parsers.wav import WavAudioIdentity, inspect_audio_identity
from sampletagharmonizer.services.files import iter_wav_files


@dataclass(frozen=True)
class IndexResult:
    scan_run_id: str
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
) -> IndexResult:
    if not root.exists():
        raise ValueError(f"Dataset path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Dataset path is not a directory: {root}")

    return index_paths(session, iter_wav_files(root), str(root), limit, progress)


def index_paths(
    session: Session,
    paths: Iterable[Path],
    dataset_path: str,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> IndexResult:
    scan_run = ScanRun(dataset_path=dataset_path, scanner_version=__version__)
    session.add(scan_run)
    session.flush()

    scanned = 0
    indexed = 0
    errors = 0
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
            if progress is not None:
                progress(scanned, indexed, errors)

        scan_run.status = "completed" if errors == 0 else "completed_with_errors"
        return IndexResult(
            scan_run_id=scan_run.id,
            scanned_files=scanned,
            indexed_files=indexed,
            error_count=errors,
        )
    except Exception:
        scan_run.status = "failed"
        raise
    finally:
        scan_run.scanned_files = scanned
        scan_run.indexed_files = indexed
        scan_run.error_count = errors
        scan_run.finished_at = datetime.now(UTC)


def latest_error_scan_run_id(session: Session) -> str | None:
    return session.scalar(
        select(ScanRun.id)
        .where(ScanRun.error_count > 0)
        .order_by(desc(ScanRun.started_at))
        .limit(1)
    )


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
) -> IndexResult:
    return index_paths(
        session=session,
        paths=error_paths_for_scan_run(session, source_scan_run_id, limit),
        dataset_path=f"retry-errors:{source_scan_run_id}",
        progress=progress,
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
