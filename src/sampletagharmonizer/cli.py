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


def byte_map(args: argparse.Namespace) -> int:
    from .byte_coverage import build_wav_byte_map

    report = build_wav_byte_map(args.path)
    text = json.dumps(report.to_dict(), ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def validate_byte_coverage(args: argparse.Namespace) -> int:
    from .config import database_url_from_env
    from .byte_coverage import validate_byte_coverage as validate_file_byte_coverage
    from .byte_coverage import validate_dataset_byte_coverage

    if args.dataset:
        if args.store:
            from .byte_coverage import validate_dataset_byte_coverage_to_db
            from .db.session import session_scope

        root = args.path or dataset_path_from_env(args.env)
        if not root.exists():
            raise SystemExit(f"Dataset path does not exist: {root}")
        if not root.is_dir():
            raise SystemExit(f"Dataset path is not a directory: {root}")

        progress = None
        if not args.no_progress:
            from .services.indexer import count_wav_files

            sys.stderr.write("Counting WAV files...\n")
            sys.stderr.flush()
            progress = ProgressBar(count_wav_files(root, args.limit), success_label="safe")
            progress.render(0, 0, 0)

        if args.store:
            database_url = args.database_url or database_url_from_env(args.env)
            with session_scope(database_url, args.env) as session:
                stored_result = validate_dataset_byte_coverage_to_db(
                    session=session,
                    root=root,
                    limit=args.limit,
                    only_problematic=args.only_problematic,
                    progress=progress,
                    batch_size=args.batch_size,
                )
            result = stored_result.result
        else:
            result = validate_dataset_byte_coverage(
                root=root,
                limit=args.limit,
                only_problematic=args.only_problematic,
                progress=progress,
            )
        if progress is not None:
            progress.finish(result.scanned_files, result.files_by_safety.get("safe_to_rewrite", 0), result.failed_files)
        if args.store:
            output = stored_result.to_dict(include_files=not args.summary_only, include_diagnostics=not args.no_diagnostics)
        else:
            output = result.to_dict(include_files=not args.summary_only, include_diagnostics=not args.no_diagnostics)
    else:
        if args.store:
            raise SystemExit("--store is only supported with --dataset.")
        if args.path is None:
            raise SystemExit("A WAV file path is required unless --dataset is set.")
        output = validate_file_byte_coverage(args.path).to_dict(include_diagnostics=not args.no_diagnostics)

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
    from .services.indexer import (
        count_wav_files,
        index_dataset,
        index_resume,
        index_resume_paths_for_scan_run,
        latest_interrupted_index_scan_run_id,
    )

    root = args.path or dataset_path_from_env(args.env)
    database_url = args.database_url or database_url_from_env(args.env)
    progress = None
    source_scan_run_id = None
    resume_requested = args.resume or args.resume_scan_run_id is not None
    if not args.no_progress:
        sys.stderr.write("Counting WAV files...\n" if not resume_requested else "Counting remaining WAV files...\n")
        sys.stderr.flush()
    with session_scope(database_url, args.env) as session:
        if not args.no_progress:
            if resume_requested:
                source_scan_run_id = args.resume_scan_run_id or latest_interrupted_index_scan_run_id(session)
                if source_scan_run_id is None:
                    raise SystemExit("No interrupted index run found.")
                total = len(index_resume_paths_for_scan_run(session, source_scan_run_id, args.limit))
            else:
                total = count_wav_files(root, args.limit)
            progress = ProgressBar(total)
            progress.render(0, 0, 0)

        if resume_requested:
            source_scan_run_id, result = index_resume(
                session=session,
                source_scan_run_id=args.resume_scan_run_id,
                limit=args.limit,
                progress=progress,
                batch_size=args.batch_size,
            )
        else:
            result = index_dataset(session, root, args.limit, progress, args.batch_size)
    if progress is not None:
        progress.finish(result.scanned_files, result.indexed_files, result.error_count)
    output = {
        "scan_run_id": result.scan_run_id,
        "status": result.status,
        "dataset_path": str(root),
        "scanned_files": result.scanned_files,
        "indexed_files": result.indexed_files,
        "error_count": result.error_count,
    }
    if source_scan_run_id is not None:
        output["source_scan_run_id"] = source_scan_run_id
    print(json.dumps(output, indent=2))
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

        result = retry_error_paths(session, source_scan_run_id, args.limit, progress, args.batch_size)

    if progress is not None:
        progress.finish(result.scanned_files, result.indexed_files, result.error_count)
    print(
        json.dumps(
            {
                "source_scan_run_id": source_scan_run_id,
                "scan_run_id": result.scan_run_id,
                "status": result.status,
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
    from .services.metadata_observer import (
        count_indexed_files,
        extract_metadata_from_index,
        extract_metadata_resume,
        latest_interrupted_metadata_scan_run_id,
        metadata_resume_file_instances_for_scan_run,
    )

    database_url = args.database_url or database_url_from_env(args.env)
    progress = None
    source_scan_run_id = None
    resume_requested = args.resume or args.resume_scan_run_id is not None
    with session_scope(database_url, args.env) as session:
        if not args.no_progress:
            if resume_requested:
                source_scan_run_id = args.resume_scan_run_id or latest_interrupted_metadata_scan_run_id(session)
                if source_scan_run_id is None:
                    raise SystemExit("No interrupted metadata extraction run found.")
                total = len(metadata_resume_file_instances_for_scan_run(session, source_scan_run_id, args.limit))
            else:
                total = count_indexed_files(session, args.limit)
            progress = ProgressBar(total, success_label="observations")
            progress.render(0, 0, 0)

        if resume_requested:
            source_scan_run_id, result = extract_metadata_resume(
                session=session,
                source_scan_run_id=args.resume_scan_run_id,
                limit=args.limit,
                progress=progress,
                batch_size=args.batch_size,
            )
        else:
            result = extract_metadata_from_index(session, args.limit, progress, args.batch_size)

    if progress is not None:
        progress.finish(result.scanned_files, result.observation_count, result.error_count)
    output = {
        "scan_run_id": result.scan_run_id,
        "status": result.status,
        "scanned_files": result.scanned_files,
        "observed_files": result.observed_files,
        "observation_count": result.observation_count,
        "error_count": result.error_count,
    }
    if source_scan_run_id is not None:
        output["source_scan_run_id"] = source_scan_run_id
    print(json.dumps(output, indent=2))
    return 0


def retry_metadata_errors(args: argparse.Namespace) -> int:
    from .config import database_url_from_env
    from .db.session import session_scope
    from .services.metadata_observer import (
        latest_metadata_error_scan_run_id,
        metadata_error_file_instances_for_scan_run,
        retry_metadata_errors as retry_metadata_error_file_instances,
    )

    database_url = args.database_url or database_url_from_env(args.env)
    progress = None
    with session_scope(database_url, args.env) as session:
        source_scan_run_id = args.scan_run_id or latest_metadata_error_scan_run_id(session)
        if source_scan_run_id is None:
            raise SystemExit("No metadata extraction scan run with errors found.")

        total = len(metadata_error_file_instances_for_scan_run(session, source_scan_run_id, args.limit))
        if not args.no_progress:
            progress = ProgressBar(total, success_label="observations")
            progress.render(0, 0, 0)

        result = retry_metadata_error_file_instances(session, source_scan_run_id, args.limit, progress, args.batch_size)

    if progress is not None:
        progress.finish(result.scanned_files, result.observation_count, result.error_count)
    print(
        json.dumps(
            {
                "source_scan_run_id": source_scan_run_id,
                "scan_run_id": result.scan_run_id,
                "status": result.status,
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
    index_parser.add_argument("--batch-size", type=int, default=500, help="Commit indexing progress every N scanned files.")
    index_parser.add_argument("--resume", action="store_true", help="Resume the latest interrupted index run.")
    index_parser.add_argument("--resume-scan-run-id", help="Interrupted index run to resume. Implies --resume.")
    index_parser.add_argument("--no-progress", action="store_true", help="Disable the console progress bar.")
    index_parser.set_defaults(func=index)

    retry_parser = subparsers.add_parser("retry-errors", help="Re-index files from a previous scan run's errors.")
    retry_parser.add_argument("scan_run_id", nargs="?", help="Scan run to retry. Defaults to the latest run with errors.")
    retry_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATABASE_URL.")
    retry_parser.add_argument("--database-url", help="SQLAlchemy database URL. Overrides DATABASE_URL.")
    retry_parser.add_argument("--limit", type=int, help="Maximum number of errored files to retry.")
    retry_parser.add_argument("--batch-size", type=int, default=500, help="Commit index retry progress every N scanned files.")
    retry_parser.add_argument("--no-progress", action="store_true", help="Disable the console progress bar.")
    retry_parser.set_defaults(func=retry_errors)

    metadata_parser = subparsers.add_parser(
        "extract-metadata",
        help="Extract NI metadata observations from indexed WAV files into PostgreSQL.",
    )
    metadata_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATABASE_URL.")
    metadata_parser.add_argument("--database-url", help="SQLAlchemy database URL. Overrides DATABASE_URL.")
    metadata_parser.add_argument("--limit", type=int, help="Maximum number of indexed files to inspect.")
    metadata_parser.add_argument("--batch-size", type=int, default=500, help="Commit metadata extraction progress every N scanned files.")
    metadata_parser.add_argument("--resume", action="store_true", help="Resume the latest interrupted metadata extraction run.")
    metadata_parser.add_argument("--resume-scan-run-id", help="Interrupted metadata extraction run to resume. Implies --resume.")
    metadata_parser.add_argument("--no-progress", action="store_true", help="Disable the console progress bar.")
    metadata_parser.set_defaults(func=extract_metadata)

    retry_metadata_parser = subparsers.add_parser(
        "retry-metadata-errors",
        help="Re-extract metadata for files from a previous metadata extraction run's errors.",
    )
    retry_metadata_parser.add_argument("scan_run_id", nargs="?", help="Scan run to retry. Defaults to the latest metadata extraction run with errors.")
    retry_metadata_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATABASE_URL.")
    retry_metadata_parser.add_argument("--database-url", help="SQLAlchemy database URL. Overrides DATABASE_URL.")
    retry_metadata_parser.add_argument("--limit", type=int, help="Maximum number of errored files to retry.")
    retry_metadata_parser.add_argument("--batch-size", type=int, default=500, help="Commit metadata retry progress every N scanned files.")
    retry_metadata_parser.add_argument("--no-progress", action="store_true", help="Disable the console progress bar.")
    retry_metadata_parser.set_defaults(func=retry_metadata_errors)

    scan_parser = subparsers.add_parser("scan", help="Read-only scan for NI metadata in WAV files.")
    scan_parser.add_argument("path", nargs="?", type=Path, help="Dataset root. Defaults to DATASET_PATH_NI from .env.")
    scan_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATASET_PATH_NI.")
    scan_parser.add_argument("--limit", type=int, help="Maximum number of WAV files to inspect.")
    scan_parser.add_argument("--only-hits", action="store_true", help="Only report files with NI metadata or MessagePack candidates.")
    scan_parser.add_argument("--output", type=Path, help="Write JSON report to this file.")
    scan_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    scan_parser.set_defaults(func=scan)

    byte_map_parser = subparsers.add_parser("byte-map", help="Generate a read-only byte coverage map for one WAV file.")
    byte_map_parser.add_argument("path", type=Path, help="WAV file to inspect.")
    byte_map_parser.add_argument("--output", type=Path, help="Write JSON report to this file.")
    byte_map_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    byte_map_parser.set_defaults(func=byte_map)

    coverage_parser = subparsers.add_parser("validate-byte-coverage", help="Validate byte coverage safety for one WAV file or a dataset.")
    coverage_parser.add_argument("path", nargs="?", type=Path, help="WAV file or dataset root. Defaults to DATASET_PATH_NI when --dataset is set.")
    coverage_parser.add_argument("--dataset", action="store_true", help="Validate all WAV files under the dataset root.")
    coverage_parser.add_argument("--env", type=Path, default=Path(".env"), help="Dotenv file containing DATASET_PATH_NI.")
    coverage_parser.add_argument("--database-url", help="SQLAlchemy database URL. Overrides DATABASE_URL when --store is set.")
    coverage_parser.add_argument("--limit", type=int, help="Maximum number of WAV files to validate in dataset mode.")
    coverage_parser.add_argument("--batch-size", type=int, default=500, help="Commit stored coverage results every N scanned files.")
    coverage_parser.add_argument("--store", action="store_true", help="Store compact dataset validation results in PostgreSQL.")
    coverage_parser.add_argument("--only-problematic", action="store_true", help="In dataset mode, include only non-safe files in the file list.")
    coverage_parser.add_argument("--summary-only", action="store_true", help="In dataset mode, omit the per-file list.")
    coverage_parser.add_argument("--no-diagnostics", action="store_true", help="Omit detailed diagnostic objects from output.")
    coverage_parser.add_argument("--no-progress", action="store_true", help="Disable the console progress bar in dataset mode.")
    coverage_parser.add_argument("--output", type=Path, help="Write JSON report to this file.")
    coverage_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    coverage_parser.set_defaults(func=validate_byte_coverage)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
