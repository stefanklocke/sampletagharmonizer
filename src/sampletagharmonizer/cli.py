from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cli_progress import ProgressBar
from .config import dataset_path_from_env
from .parsers.ni_metadata import inspect_wav
from .services.files import iter_wav_files


def scan(args: argparse.Namespace) -> int:
    root = args.path or dataset_path_from_env(args.env)
    if not root.exists():
        raise SystemExit(f"Dataset path does not exist: {root}")
    if not root.is_dir():
        raise SystemExit(f"Dataset path is not a directory: {root}")

    reports = []
    scanned = 0
    errors = []
    for wav_path in iter_wav_files(root):
        if args.limit is not None and scanned >= args.limit:
            break
        scanned += 1
        try:
            report = inspect_wav(wav_path)
        except Exception as exc:  # noqa: BLE001 - scan should keep going across bad files.
            errors.append({"path": str(wav_path), "error": str(exc)})
            continue
        if args.only_hits and not report["ni_soundinfo"] and not report["msgpack_candidates"]:
            continue
        reports.append(report)

    output = {
        "dataset_path": str(root),
        "scanned_files": scanned,
        "reported_files": len(reports),
        "errors": errors,
        "files": reports,
    }
    text = json.dumps(output, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def init_db(args: argparse.Namespace) -> int:
    from .db.schema import create_schema

    create_schema(args.database_url, args.env)
    print("Database schema is ready.")
    return 0


def index(args: argparse.Namespace) -> int:
    from .config import database_url_from_env
    from .db.session import session_scope
    from .services.indexer import count_wav_files, index_dataset

    root = args.path or dataset_path_from_env(args.env)
    database_url = args.database_url or database_url_from_env(args.env)
    progress = None
    if not args.no_progress:
        sys.stderr.write("Counting WAV files...\n")
        sys.stderr.flush()
        total = count_wav_files(root, args.limit)
        progress = ProgressBar(total)
        progress.render(0, 0, 0)
    with session_scope(database_url, args.env) as session:
        result = index_dataset(session, root, args.limit, progress)
    if progress is not None:
        progress.finish(result.scanned_files, result.indexed_files, result.error_count)
    print(
        json.dumps(
            {
                "scan_run_id": result.scan_run_id,
                "dataset_path": str(root),
                "scanned_files": result.scanned_files,
                "indexed_files": result.indexed_files,
                "error_count": result.error_count,
            },
            indent=2,
        )
    )
    return 0


def retry_errors(args: argparse.Namespace) -> int:
    from .config import database_url_from_env
    from .db.session import session_scope
    from .services.indexer import error_paths_for_scan_run, latest_error_scan_run_id, retry_error_paths

    database_url = args.database_url or database_url_from_env(args.env)
    with session_scope(database_url, args.env) as session:
        source_scan_run_id = args.scan_run_id or latest_error_scan_run_id(session)
        if source_scan_run_id is None:
            raise SystemExit("No scan run with errors found.")

        total = len(error_paths_for_scan_run(session, source_scan_run_id, args.limit))
        progress = None if args.no_progress else ProgressBar(total)
        if progress is not None:
            progress.render(0, 0, 0)

        result = retry_error_paths(session, source_scan_run_id, args.limit, progress)

    if progress is not None:
        progress.finish(result.scanned_files, result.indexed_files, result.error_count)
    print(
        json.dumps(
            {
                "source_scan_run_id": source_scan_run_id,
                "scan_run_id": result.scan_run_id,
                "scanned_files": result.scanned_files,
                "indexed_files": result.indexed_files,
                "error_count": result.error_count,
            },
            indent=2,
        )
    )
    return 0


def extract_metadata(args: argparse.Namespace) -> int:
    from .config import database_url_from_env
    from .db.session import session_scope
    from .services.metadata_observer import count_indexed_files, extract_metadata_from_index

    database_url = args.database_url or database_url_from_env(args.env)
    progress = None
    with session_scope(database_url, args.env) as session:
        if not args.no_progress:
            total = count_indexed_files(session, args.limit)
            progress = ProgressBar(total, success_label="observations")
            progress.render(0, 0, 0)

        result = extract_metadata_from_index(session, args.limit, progress)

    if progress is not None:
        progress.finish(result.scanned_files, result.observation_count, result.error_count)
    print(
        json.dumps(
            {
                "scan_run_id": result.scan_run_id,
                "scanned_files": result.scanned_files,
                "observed_files": result.observed_files,
                "observation_count": result.observation_count,
                "error_count": result.error_count,
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sampletagharmonizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db_parser = subparsers.add_parser("init-db", help="Create database tables if they do not exist.")
    init_db_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATABASE_URL.")
    init_db_parser.add_argument("--database-url", help="SQLAlchemy database URL. Overrides DATABASE_URL.")
    init_db_parser.set_defaults(func=init_db)

    index_parser = subparsers.add_parser("index", help="Index WAV file paths and audio data hashes into PostgreSQL.")
    index_parser.add_argument("path", nargs="?", type=Path, help="Dataset root. Defaults to DATASET_PATH_NI from .env.")
    index_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATASET_PATH_NI and DATABASE_URL.")
    index_parser.add_argument("--database-url", help="SQLAlchemy database URL. Overrides DATABASE_URL.")
    index_parser.add_argument("--limit", type=int, help="Maximum number of WAV files to inspect.")
    index_parser.add_argument("--no-progress", action="store_true", help="Disable the console progress bar.")
    index_parser.set_defaults(func=index)

    retry_parser = subparsers.add_parser("retry-errors", help="Re-index files from a previous scan run's errors.")
    retry_parser.add_argument("scan_run_id", nargs="?", help="Scan run to retry. Defaults to the latest run with errors.")
    retry_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATABASE_URL.")
    retry_parser.add_argument("--database-url", help="SQLAlchemy database URL. Overrides DATABASE_URL.")
    retry_parser.add_argument("--limit", type=int, help="Maximum number of errored files to retry.")
    retry_parser.add_argument("--no-progress", action="store_true", help="Disable the console progress bar.")
    retry_parser.set_defaults(func=retry_errors)

    metadata_parser = subparsers.add_parser(
        "extract-metadata",
        help="Extract NI metadata observations from indexed WAV files into PostgreSQL.",
    )
    metadata_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATABASE_URL.")
    metadata_parser.add_argument("--database-url", help="SQLAlchemy database URL. Overrides DATABASE_URL.")
    metadata_parser.add_argument("--limit", type=int, help="Maximum number of indexed files to inspect.")
    metadata_parser.add_argument("--no-progress", action="store_true", help="Disable the console progress bar.")
    metadata_parser.set_defaults(func=extract_metadata)

    scan_parser = subparsers.add_parser("scan", help="Read-only scan for NI metadata in WAV files.")
    scan_parser.add_argument("path", nargs="?", type=Path, help="Dataset root. Defaults to DATASET_PATH_NI from .env.")
    scan_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATASET_PATH_NI.")
    scan_parser.add_argument("--limit", type=int, help="Maximum number of WAV files to inspect.")
    scan_parser.add_argument("--only-hits", action="store_true", help="Only report files with NI metadata or MessagePack candidates.")
    scan_parser.add_argument("--output", type=Path, help="Write JSON report to this file.")
    scan_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    scan_parser.set_defaults(func=scan)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
