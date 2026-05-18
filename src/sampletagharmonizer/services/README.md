# Service Layer

## Purpose

This package contains workflow-level services. Services coordinate parsers, database models, progress callbacks, retry behavior, and resume behavior. They are used by the CLI, but they do not depend on argparse.

## Structure

- `files.py`: filesystem iteration helpers.
- `indexer.py`: WAV dataset indexing, audio identity upsert, indexing retries, and indexing resume.
- `metadata_observer.py`: NI metadata extraction from indexed files, metadata retries, and metadata resume.
- `write_safety_samples.py`: read-only sample reports from stored write-safety results.

## Dataset Indexing

`indexer.py` scans WAV files, computes a stable audio-content identity from the `data` chunk, and stores path information in PostgreSQL.

Typical CLI use:

```bash
sth index --limit 100
```

For each file, indexing:

1. Reads WAV format information from `fmt `.
2. Streams the `data` chunk through SHA-256.
3. Upserts one `audio_assets` row keyed by `data_sha256`.
4. Upserts one `file_instances` row keyed by file path.
5. Records per-file failures in `scan_errors`.

The indexer intentionally returns as soon as both `fmt ` and `data` are known. It does not need later metadata chunks, which keeps audio-content indexing independent from malformed or exotic metadata chunks.

## Index Retry

Every indexing run creates a `scan_runs` row. Per-file failures are stored in `scan_errors`. After parser fixes, re-index only the failed files from a previous run:

```bash
sth retry-errors <scan_run_id>
```

If no scan run ID is provided, the command retries the latest run with errors:

```bash
sth retry-errors
```

The retry creates a new `scan_runs` row whose `dataset_path` is prefixed with `retry-errors:`. Existing `file_instances` are updated in place when a previously failed file is successfully indexed.

## Index Resume

Indexing commits progress in batches. If the user presses `Ctrl+C`, the current run is marked as `interrupted` and already written `audio_assets`, `file_instances`, and `scan_errors` stay in the database.

Resume the latest interrupted index run:

```bash
sth index --resume
```

Resume a specific interrupted index run:

```bash
sth index --resume-scan-run-id <scan_run_id>
```

Resume determines remaining files from the source run:

- successful files are detected through `file_instances.last_scan_run_id`
- failed files are detected through `scan_errors`
- everything not yet represented by either source is processed in a new `index-resume:<scan_run_id>` run

## Metadata Extraction

`metadata_observer.py` scans existing `file_instances`, reads NI metadata from the corresponding WAV files, and stores one or more rows in `metadata_observations`.

Typical CLI use:

```bash
sth extract-metadata --limit 100
```

Currently supported observation sources:

| Source type | Meaning |
| --- | --- |
| `ni_soundinfo_utf16` | GEOB SoundInfo payload summarized from length-prefixed UTF-16LE strings |
| `ni_msgpack` | MessagePack tag object candidate found in a metadata chunk |

The command creates a new `scan_runs` row with `dataset_path` set to `metadata-observations:indexed-files`. Per-file extraction errors are written to `scan_errors`. Per-file extraction states are written to `metadata_file_results`.

Existing observations for a file are replaced when that file is successfully re-extracted. This makes parser fixes repeatable and prevents duplicate observations for the same file/source/index.

## Metadata Retry

After parser fixes, re-extract only the files that failed in a previous metadata extraction run:

```bash
sth retry-metadata-errors <scan_run_id>
```

If no scan run ID is provided, the command retries the latest metadata extraction run with errors:

```bash
sth retry-metadata-errors
```

The retry creates a new `scan_runs` row whose `dataset_path` is prefixed with `metadata-retry-errors:`. Existing observations for successfully retried files are replaced in place.

## Metadata Resume

Metadata extraction also commits progress in batches. If the user presses `Ctrl+C`, the current run is marked as `interrupted`, and already written observations, file results, and errors stay in the database.

Resume the latest interrupted metadata run:

```bash
sth extract-metadata --resume
```

Resume a specific interrupted metadata run:

```bash
sth extract-metadata --resume-scan-run-id <scan_run_id>
```

Resume uses `metadata_file_results` to skip files already processed by the source run. Files with `observed`, `no_metadata`, or `error` states are all considered processed for that source run. Error-specific retry is handled separately through `sth retry-metadata-errors`.

## Batch Commits

Both indexing and metadata extraction support batch commits:

```bash
sth index --batch-size 500
sth extract-metadata --batch-size 500
```

A batch size greater than zero updates the active `scan_runs` row and commits pending database changes every N scanned files. This limits work lost on interruption and makes long NAS-backed scans safer.

## Write-Safety Samples

`write_safety_samples.py` reads stored `write_safety_results` rows and returns a compact sample set per write strategy. This is used for manual policy inspection before implementing any writer.

Typical CLI use:

```bash
sth write-safety-samples --pretty
```

Inspect a specific run and include three files per strategy:

```bash
sth write-safety-samples --scan-run-id <scan_run_id> --per-strategy 3 --pretty
```

Focus on one strategy:

```bash
sth write-safety-samples --write-strategy unsupported_missing_id3_chunk --pretty
```

The command does not parse WAV files and does not modify the database. It only reads the latest or selected `write-safety:` scan run.
