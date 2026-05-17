# Database Layer

## Purpose

This package contains the SQLAlchemy database model and session helpers used by the CLI and service layer.

The current schema stores two kinds of information:

- stable audio-content identity and concrete file locations
- parser-derived metadata observations that can later feed normalized tag and taxonomy tables

The database is intentionally used as an intermediate analysis layer. Raw WAV files remain the source of truth, while database rows make repeated scans, duplicate detection, and later data science work practical.

## Structure

- `models.py`: SQLAlchemy ORM models and relationships.
- `schema.py`: `create_schema()`, which creates all currently known tables.
- `session.py`: engine, session factory, scoped session, and healthcheck helpers.

## Architecture

```mermaid
flowchart LR
    nas["NAS dataset<br/>WAV files"]
    index["sth index"]
    metadata["sth extract-metadata"]
    wav["WAV parser<br/>fmt + data chunk"]
    ni["NI metadata parser<br/>ID3, GEOB, SoundInfo, MessagePack"]
    db["PostgreSQL"]

    nas --> index
    index --> wav
    wav --> db

    db --> metadata
    metadata --> ni
    ni --> db

    db --> scan_runs
    db --> audio_assets
    db --> file_instances
    db --> metadata_observations
    db --> metadata_file_results
    db --> scan_errors
```

## Tables

### `audio_assets`

Represents audio content, independent from file name or location.

Important fields:

| Field | Meaning |
| --- | --- |
| `id` | Internal UUID |
| `data_sha256` | SHA-256 hash of the WAV `data` chunk |
| `data_size` | Size of the audio `data` chunk |
| `format_tag` | WAV format tag from `fmt ` |
| `channels` | Channel count |
| `sample_rate` | Sample rate |
| `byte_rate` | Byte rate |
| `block_align` | Block alignment |
| `bits_per_sample` | Bit depth |

`data_sha256` is unique, so byte-identical audio content maps to one asset even if it appears at multiple paths.

### `file_instances`

Represents a concrete file path pointing to an audio asset.

Important fields:

| Field | Meaning |
| --- | --- |
| `id` | Internal UUID |
| `audio_asset_id` | Referenced audio content |
| `last_scan_run_id` | Latest index run that successfully saw this path |
| `path` | Full current path |
| `file_name` | File basename |
| `suffix` | File suffix, e.g. `.wav` |
| `file_size` | Full file size |
| `mtime_ns` | File modification time in nanoseconds |
| `first_seen_at` | First index time |
| `last_seen_at` | Last index time |
| `missing_since` | Reserved for later missing-file detection |

This split lets the project detect duplicate audio content and still track concrete file locations.

### `scan_runs`

Stores one indexing, retry, metadata extraction, or resume run.

Important fields:

| Field | Meaning |
| --- | --- |
| `dataset_path` | Dataset root or synthetic run label such as `retry-errors:<id>` |
| `scanner_version` | Application version used for the run |
| `status` | `running`, `completed`, `completed_with_errors`, `interrupted`, or `failed` |
| `scanned_files` | Number of files attempted |
| `indexed_files` | Indexed file count for indexing runs; observation count for metadata runs |
| `error_count` | Per-file errors recorded in `scan_errors` |

Synthetic `dataset_path` prefixes identify derived runs:

| Prefix | Meaning |
| --- | --- |
| `retry-errors:` | Re-index files from an earlier indexing run's errors |
| `index-resume:` | Continue an interrupted indexing or index-retry run |
| `metadata-observations:` | Extract metadata observations from indexed files |
| `metadata-retry-errors:` | Re-extract metadata for files from an earlier metadata run's errors |
| `metadata-resume:` | Continue an interrupted metadata extraction or metadata retry run |

### `scan_errors`

Stores per-file errors without aborting the whole dataset scan. Both indexing and metadata extraction write to this table.

Important fields:

| Field | Meaning |
| --- | --- |
| `scan_run_id` | Run that produced the error |
| `path` | File path that failed |
| `error` | Parser or filesystem error message |

### `metadata_observations`

Stores extracted metadata facts observed in indexed files. This is intentionally an intermediate layer between raw parser output and future normalized tag/taxonomy tables.

Important fields:

| Field | Meaning |
| --- | --- |
| `id` | Internal UUID |
| `audio_asset_id` | Referenced audio content |
| `file_instance_id` | Concrete file path where the metadata was observed |
| `scan_run_id` | Extraction run that produced the observation |
| `source_type` | Metadata source, e.g. `ni_soundinfo_utf16` or `ni_msgpack`; values are defined in `sampletagharmonizer.metadata` |
| `observation_index` | Stable index within the file/source for idempotent replacement |
| `source_chunk_id` | RIFF chunk ID where the observation was found, e.g. `ID3 ` |
| `source_chunk_offset` | Byte offset of the RIFF chunk within the WAV file |
| `source_frame_id` | Nested frame ID when applicable, e.g. `GEOB` |
| `source_frame_offset` | Byte offset of the nested frame inside its parent payload |
| `source_payload_offset` | Byte offset of the source payload inside the chunk/frame payload |
| `source_payload_size` | Size of the decoded source payload/candidate |
| `title` | Extracted sample title/name when available |
| `vendor` | Extracted vendor when available |
| `product` | Extracted product/bank when available |
| `category_paths` | JSON category paths, e.g. `[["Loops"], ["Loops", "Vocal"]]` |
| `attributes` | JSON map of normalized secondary fields |
| `raw_payload` | Full parser-near JSON snapshot of the parsed source payload/candidate |

Observations are replaced per file when metadata extraction is rerun, so parser fixes can be applied repeatedly without creating duplicate rows for the same file.

`raw_payload` intentionally keeps the complete parser-near source object, including fields that are also copied into query-friendly columns. The duplicated storage is acceptable here because observations are the audit layer: later normalized tag rows should be traceable back to the exact parser output that produced them.

### `metadata_file_results`

Stores per-file metadata extraction state for graceful interruption and resume.

Important fields:

| Field | Meaning |
| --- | --- |
| `scan_run_id` | Metadata run that processed the file |
| `file_instance_id` | Indexed file instance |
| `path` | Path at extraction time |
| `status` | `observed`, `no_metadata`, or `error` |
| `observation_count` | Number of observations written for this file |
| `error` | Error text for failed files |

`sth extract-metadata --resume` uses this table to skip files already processed by the interrupted source run.

## Local PostgreSQL

Start only PostgreSQL:

```bash
docker compose up -d db
```

Initialize tables:

```bash
sth init-db
```

The database URL is read from `DATABASE_URL` in the environment or `.env`.

Example:

```text
DATABASE_URL=postgresql+psycopg://sampletagharmonizer:sampletagharmonizer@localhost:5432/sampletagharmonizer
```

## Current Scope

The schema currently stores enough information to:

1. Identify duplicate audio content through WAV `data`-chunk SHA-256.
2. Track concrete file paths and filesystem metadata.
3. Keep per-run status and per-file errors.
4. Store parser-derived NI metadata observations with byte-location provenance.
5. Resume interrupted indexing and metadata extraction runs.

It does not yet include normalized category, taxonomy, confidence, or harmonization tables. Those belong to the next phase after enough observations have been collected and inspected.
