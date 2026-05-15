# Dataset Indexing

The first database milestone is intentionally limited to indexing audio files and
their stable audio-content identity. Tag analysis tables will be added later on top
of this foundation.

## Architecture

```mermaid
flowchart LR
    nas["NAS dataset<br/>WAV files"]
    cli["sampletagharmonizer index"]
    wav["WAV parser<br/>fmt + data chunk"]
    hash["SHA-256 over data chunk"]
    db["PostgreSQL"]

    nas --> cli
    cli --> wav
    wav --> hash
    cli --> db

    db --> scan_runs
    db --> audio_assets
    db --> file_instances
    db --> scan_errors
```

## Tables

### `audio_assets`

Represents the audio content, independent from file name or location.

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

`data_sha256` is unique, so byte-identical audio content maps to one asset even if
it appears at multiple paths.

### `file_instances`

Represents a concrete file path pointing to an audio asset.

Important fields:

| Field | Meaning |
| --- | --- |
| `id` | Internal UUID |
| `audio_asset_id` | Referenced audio content |
| `path` | Full current path |
| `file_name` | File basename |
| `suffix` | File suffix, e.g. `.wav` |
| `file_size` | Full file size |
| `mtime_ns` | File modification time in nanoseconds |
| `first_seen_at` | First index time |
| `last_seen_at` | Last index time |
| `missing_since` | Reserved for later missing-file detection |

This split lets the project detect duplicate audio content and still track concrete
file locations.

### `scan_runs`

Stores one indexing run.

### `scan_errors`

Stores per-file errors without aborting the whole dataset scan.

## Local PostgreSQL

Start only PostgreSQL:

```bash
docker compose up -d db
```

Initialize tables:

```bash
sampletagharmonizer init-db
```

Index a small subset first:

```bash
sampletagharmonizer index --limit 100
```

Or without installing the package:

```bash
PYTHONPATH=src python3 -m sampletagharmonizer init-db
PYTHONPATH=src python3 -m sampletagharmonizer index --limit 100
```

The database URL is read from `DATABASE_URL` in the environment or `.env`.

Example:

```text
DATABASE_URL=postgresql+psycopg://sampletagharmonizer:sampletagharmonizer@localhost:5432/sampletagharmonizer
```

## Current Scope

The indexer currently stores:

1. WAV `data`-chunk SHA-256.
2. WAV format info from `fmt `.
3. Full file path and filesystem metadata.
4. Scan run status and per-file errors.

It does not yet store NI tags, MessagePack payloads, category paths, or derived tag
tables. Those belong to the next phase after the file index is reliable.
