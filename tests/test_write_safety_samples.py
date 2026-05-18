from __future__ import annotations

import unittest
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sampletagharmonizer import __version__
from sampletagharmonizer.db.models import Base, ScanRun, WriteSafetyResult
from sampletagharmonizer.services.write_safety_samples import collect_write_safety_samples


class WriteSafetySamplesTest(unittest.TestCase):
    def test_collects_samples_from_latest_write_safety_run(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as session:
                older = ScanRun(
                    dataset_path="write-safety:/older",
                    scanner_version=__version__,
                    status="completed",
                    started_at=datetime(2026, 1, 1, tzinfo=UTC),
                    scanned_files=1,
                    indexed_files=1,
                )
                latest = ScanRun(
                    dataset_path="write-safety:/latest",
                    scanner_version=__version__,
                    status="completed",
                    started_at=datetime(2026, 1, 2, tzinfo=UTC),
                    scanned_files=3,
                    indexed_files=3,
                )
                session.add_all([older, latest])
                session.flush()
                session.add_all(
                    [
                        _result(
                            latest.id,
                            "/samples/a.wav",
                            "safe_to_update_existing_metadata",
                            "preserve_audio_update_existing_id3_geob",
                        ),
                        _result(
                            latest.id,
                            "/samples/b.wav",
                            "safe_to_update_existing_metadata",
                            "preserve_audio_update_existing_id3_geob",
                        ),
                        _result(
                            latest.id,
                            "/samples/c.wav",
                            "read_only",
                            "unsupported_missing_id3_chunk",
                            blockers=[{"code": "missing_id3_chunk", "message": "No ID3 metadata chunk was mapped."}],
                        ),
                        _result(
                            older.id,
                            "/samples/older.wav",
                            "read_only",
                            "unsupported_missing_id3_chunk",
                        ),
                    ]
                )
                session.commit()

                report = collect_write_safety_samples(session, per_strategy=1)

            self.assertEqual(report["scan_run_id"], latest.id)
            self.assertEqual(report["dataset_path"], "write-safety:/latest")
            self.assertEqual(len(report["strategies"]), 2)
            self.assertEqual(report["strategies"][0]["total_count"], 2)
            self.assertEqual(len(report["strategies"][0]["samples"]), 1)
            self.assertEqual(report["strategies"][0]["samples"][0]["path"], "/samples/a.wav")
            self.assertEqual(report["strategies"][1]["total_count"], 1)
            self.assertEqual(report["strategies"][1]["samples"][0]["blockers"][0]["code"], "missing_id3_chunk")
        finally:
            engine.dispose()

    def test_filters_samples_by_strategy(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as session:
                scan_run = ScanRun(
                    dataset_path="write-safety:/dataset",
                    scanner_version=__version__,
                    status="completed",
                    scanned_files=2,
                    indexed_files=2,
                )
                session.add(scan_run)
                session.flush()
                session.add_all(
                    [
                        _result(
                            scan_run.id,
                            "/samples/safe.wav",
                            "safe_to_update_existing_metadata",
                            "preserve_audio_update_existing_id3_geob",
                        ),
                        _result(
                            scan_run.id,
                            "/samples/read-only.wav",
                            "read_only",
                            "unsupported_missing_id3_chunk",
                        ),
                    ]
                )
                session.commit()

                report = collect_write_safety_samples(
                    session,
                    scan_run_id=scan_run.id,
                    write_strategy="unsupported_missing_id3_chunk",
                )

            self.assertEqual(len(report["strategies"]), 1)
            self.assertEqual(report["strategies"][0]["write_strategy"], "unsupported_missing_id3_chunk")
            self.assertEqual(report["strategies"][0]["samples"][0]["path"], "/samples/read-only.wav")
        finally:
            engine.dispose()


def _result(
    scan_run_id: str,
    path: str,
    write_safety: str,
    write_strategy: str,
    blockers: list[dict] | None = None,
) -> WriteSafetyResult:
    return WriteSafetyResult(
        scan_run_id=scan_run_id,
        path=path,
        coverage_safety="safe_to_rewrite",
        write_safety=write_safety,
        write_strategy=write_strategy,
        requirements={"coverage_has_no_errors": True},
        normalizations=[],
        blockers=blockers or [],
        diagnostic_count=0,
        diagnostics_by_code={},
        diagnostics_by_severity={},
        raw_summary={},
    )


if __name__ == "__main__":
    unittest.main()
