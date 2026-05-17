from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sampletagharmonizer.db.models import AudioAsset, Base, FileInstance, MetadataFileResult, MetadataObservation, ScanError, ScanRun
from sampletagharmonizer.metadata import METADATA_FILE_STATUS_OBSERVED, SOURCE_NI_SOUNDINFO_UTF16
from sampletagharmonizer.parsers.ni_metadata import NI_SOUNDINFO_MIME
from sampletagharmonizer.services.metadata_observer import (
    extract_metadata_from_file_instances,
    latest_interrupted_metadata_scan_run_id,
    latest_metadata_error_scan_run_id,
    metadata_error_file_instances_for_scan_run,
    metadata_resume_file_instances_for_scan_run,
)


def riff_chunk(chunk_id: bytes, payload: bytes) -> bytes:
    data = chunk_id + len(payload).to_bytes(4, "little") + payload
    return data + (b"\x00" if len(payload) % 2 else b"")


def wav_bytes(chunks: list[bytes]) -> bytes:
    body = b"WAVE" + b"".join(chunks)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def fmt_payload() -> bytes:
    return b"".join(
        [
            (1).to_bytes(2, "little"),
            (1).to_bytes(2, "little"),
            (44_100).to_bytes(4, "little"),
            (88_200).to_bytes(4, "little"),
            (2).to_bytes(2, "little"),
            (16).to_bytes(2, "little"),
        ]
    )


def encoded_string(text: str) -> bytes:
    return len(text).to_bytes(4, "little") + text.encode("utf-16le")


def synchsafe(value: int) -> bytes:
    return bytes(
        [
            (value >> 21) & 0x7F,
            (value >> 14) & 0x7F,
            (value >> 7) & 0x7F,
            value & 0x7F,
        ]
    )


def id3_payload(frames: list[bytes]) -> bytes:
    body = b"".join(frames)
    return b"ID3\x04\x00\x00" + synchsafe(len(body)) + body


def geob_frame(data: bytes) -> bytes:
    return b"GEOB" + len(data).to_bytes(4, "big") + b"\x00\x00" + data


class MetadataObserverTest(unittest.TestCase):
    def test_extracts_soundinfo_observation_from_indexed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.wav"
            geob_data = b"".join(
                [
                    b"\x00\x00",
                    NI_SOUNDINFO_MIME.encode("latin-1"),
                    b"\x00",
                    encoded_string("Kick Tight"),
                    encoded_string("Native Instruments"),
                    encoded_string("Native Instruments"),
                    encoded_string("Factory Library"),
                    encoded_string("\\:Drums\\:Kick"),
                    encoded_string("\\@color"),
                    encoded_string("Bright"),
                ]
            )
            path.write_bytes(
                wav_bytes(
                    [
                        riff_chunk(b"fmt ", fmt_payload()),
                        riff_chunk(b"data", b"\x01\x02\x03\x04"),
                        riff_chunk(b"ID3 ", id3_payload([geob_frame(geob_data)])),
                    ]
                )
            )

            engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
            Base.metadata.create_all(engine)
            with Session(engine) as session:
                asset = AudioAsset(data_sha256="0" * 64, data_size=4)
                file_instance = FileInstance(
                    audio_asset=asset,
                    path=str(path),
                    file_name=path.name,
                    suffix=".wav",
                    file_size=path.stat().st_size,
                    mtime_ns=path.stat().st_mtime_ns,
                )
                session.add(file_instance)
                session.flush()

                result = extract_metadata_from_file_instances(
                    session=session,
                    file_instances=[file_instance],
                    dataset_path="test",
                )
                session.commit()

                observation = session.scalars(select(MetadataObservation)).one()
                file_result = session.scalars(select(MetadataFileResult)).one()

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.observed_files, 1)
            self.assertEqual(result.observation_count, 1)
            self.assertEqual(result.error_count, 0)
            self.assertEqual(observation.source_type, SOURCE_NI_SOUNDINFO_UTF16)
            self.assertEqual(observation.source_chunk_id, "ID3 ")
            self.assertIsNotNone(observation.source_chunk_offset)
            self.assertEqual(observation.source_frame_id, "GEOB")
            self.assertEqual(observation.source_frame_offset, 10)
            self.assertIsNotNone(observation.source_payload_offset)
            self.assertEqual(observation.source_payload_size, len(geob_data) - 2)
            self.assertEqual(observation.title, "Kick Tight")
            self.assertEqual(observation.vendor, "Native Instruments")
            self.assertEqual(observation.product, "Factory Library")
            self.assertEqual(observation.category_paths, [["Drums", "Kick"]])
            self.assertEqual(observation.attributes, {"color": "Bright"})
            self.assertEqual(file_result.status, METADATA_FILE_STATUS_OBSERVED)
            self.assertEqual(file_result.observation_count, 1)
            engine.dispose()

    def test_finds_metadata_error_file_instances_for_retry(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            asset = AudioAsset(data_sha256="0" * 64, data_size=4)
            file_instance = FileInstance(
                audio_asset=asset,
                path="/samples/error.wav",
                file_name="error.wav",
                suffix=".wav",
                file_size=4,
                mtime_ns=1,
            )
            scan_run = ScanRun(
                dataset_path="metadata-observations:indexed-files",
                scanner_version="test",
                error_count=1,
            )
            session.add_all([file_instance, scan_run])
            session.flush()
            session.add(ScanError(scan_run=scan_run, path=file_instance.path, error="boom"))
            session.commit()

            self.assertEqual(latest_metadata_error_scan_run_id(session), scan_run.id)
            retry_files = metadata_error_file_instances_for_scan_run(session, scan_run.id)

        self.assertEqual([item.path for item in retry_files], ["/samples/error.wav"])
        engine.dispose()

    def test_marks_run_interrupted_and_keeps_committed_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.wav"
            geob_data = b"".join(
                [
                    b"\x00\x00",
                    NI_SOUNDINFO_MIME.encode("latin-1"),
                    b"\x00",
                    encoded_string("Kick Tight"),
                ]
            )
            path.write_bytes(
                wav_bytes(
                    [
                        riff_chunk(b"fmt ", fmt_payload()),
                        riff_chunk(b"data", b"\x01\x02\x03\x04"),
                        riff_chunk(b"ID3 ", id3_payload([geob_frame(geob_data)])),
                    ]
                )
            )

            engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
            Base.metadata.create_all(engine)
            with Session(engine) as session:
                asset = AudioAsset(data_sha256="0" * 64, data_size=4)
                file_instance = FileInstance(
                    audio_asset=asset,
                    path=str(path),
                    file_name=path.name,
                    suffix=".wav",
                    file_size=path.stat().st_size,
                    mtime_ns=path.stat().st_mtime_ns,
                )
                session.add(file_instance)
                session.commit()

                def interrupted_files():
                    yield file_instance
                    raise KeyboardInterrupt

                result = extract_metadata_from_file_instances(
                    session=session,
                    file_instances=interrupted_files(),
                    dataset_path="test",
                    batch_size=1,
                )

                observations = list(session.scalars(select(MetadataObservation)))
                scan_run = session.scalars(select(ScanRun)).one()
                file_result = session.scalars(select(MetadataFileResult)).one()

            self.assertEqual(result.status, "interrupted")
            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.observation_count, 1)
            self.assertEqual(len(observations), 1)
            self.assertEqual(scan_run.status, "interrupted")
            self.assertEqual(file_result.status, METADATA_FILE_STATUS_OBSERVED)
            engine.dispose()

    def test_finds_unprocessed_file_instances_for_resume(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            asset = AudioAsset(data_sha256="0" * 64, data_size=4)
            processed = FileInstance(
                audio_asset=asset,
                path="/samples/a.wav",
                file_name="a.wav",
                suffix=".wav",
                file_size=4,
                mtime_ns=1,
            )
            pending = FileInstance(
                audio_asset=asset,
                path="/samples/b.wav",
                file_name="b.wav",
                suffix=".wav",
                file_size=4,
                mtime_ns=1,
            )
            scan_run = ScanRun(
                dataset_path="metadata-observations:indexed-files",
                scanner_version="test",
                status="interrupted",
            )
            session.add_all([processed, pending, scan_run])
            session.flush()
            session.add(
                MetadataFileResult(
                    scan_run=scan_run,
                    file_instance=processed,
                    path=processed.path,
                    status=METADATA_FILE_STATUS_OBSERVED,
                    observation_count=1,
                )
            )
            session.commit()

            self.assertEqual(latest_interrupted_metadata_scan_run_id(session), scan_run.id)
            resume_files = metadata_resume_file_instances_for_scan_run(session, scan_run.id)

        self.assertEqual([item.path for item in resume_files], ["/samples/b.wav"])
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
