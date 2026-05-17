from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sampletagharmonizer.db.models import Base, FileInstance, ScanRun
from sampletagharmonizer.services.indexer import (
    index_paths,
    index_resume,
    index_resume_paths_for_scan_run,
    latest_interrupted_index_scan_run_id,
)


def chunk(chunk_id: bytes, payload: bytes) -> bytes:
    data = chunk_id + len(payload).to_bytes(4, "little") + payload
    return data + (b"\x00" if len(payload) % 2 else b"")


def wav_bytes(audio: bytes) -> bytes:
    fmt = b"".join(
        [
            (1).to_bytes(2, "little"),
            (1).to_bytes(2, "little"),
            (44_100).to_bytes(4, "little"),
            (88_200).to_bytes(4, "little"),
            (2).to_bytes(2, "little"),
            (16).to_bytes(2, "little"),
        ]
    )
    body = b"WAVE" + chunk(b"fmt ", fmt) + chunk(b"data", audio)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


class IndexerTest(unittest.TestCase):
    def test_marks_run_interrupted_and_finds_remaining_paths_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed_path = root / "a.wav"
            pending_path = root / "b.wav"
            processed_path.write_bytes(wav_bytes(b"\x01\x02\x03\x04"))
            pending_path.write_bytes(wav_bytes(b"\x05\x06\x07\x08"))

            engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
            Base.metadata.create_all(engine)
            with Session(engine) as session:
                def interrupted_paths():
                    yield processed_path
                    raise KeyboardInterrupt

                result = index_paths(
                    session=session,
                    paths=interrupted_paths(),
                    dataset_path=str(root),
                    batch_size=1,
                )

                scan_run = session.scalars(select(ScanRun)).one()
                file_instance = session.scalars(select(FileInstance)).one()
                remaining_paths = index_resume_paths_for_scan_run(session, scan_run.id)

            self.assertEqual(result.status, "interrupted")
            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.indexed_files, 1)
            self.assertEqual(scan_run.status, "interrupted")
            self.assertEqual(file_instance.last_scan_run_id, scan_run.id)
            self.assertEqual(remaining_paths, [pending_path])
            engine.dispose()

    def test_resumes_interrupted_index_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed_path = root / "a.wav"
            pending_path = root / "b.wav"
            processed_path.write_bytes(wav_bytes(b"\x01\x02\x03\x04"))
            pending_path.write_bytes(wav_bytes(b"\x05\x06\x07\x08"))

            engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
            Base.metadata.create_all(engine)
            with Session(engine) as session:
                def interrupted_paths():
                    yield processed_path
                    raise KeyboardInterrupt

                source_result = index_paths(
                    session=session,
                    paths=interrupted_paths(),
                    dataset_path=str(root),
                    batch_size=1,
                )

                self.assertEqual(latest_interrupted_index_scan_run_id(session), source_result.scan_run_id)

                source_scan_run_id, result = index_resume(session, source_result.scan_run_id, batch_size=1)
                file_instances = list(session.scalars(select(FileInstance).order_by(FileInstance.path)))

            self.assertEqual(source_scan_run_id, source_result.scan_run_id)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.indexed_files, 1)
            self.assertEqual([Path(item.path) for item in file_instances], [processed_path, pending_path])
            self.assertEqual(file_instances[0].last_scan_run_id, source_result.scan_run_id)
            self.assertEqual(file_instances[1].last_scan_run_id, result.scan_run_id)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
