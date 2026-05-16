# Dataset Indexing

The first database milestone is intentionally limited to indexing audio files and
their stable audio-content identity. Tag analysis tables will be added later on top
of this foundation.

## Architecture

```mermaid
flowchart LR
    nas["NAS dataset<br/>WAV files"]
    cli["sth index"]
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
    db --> metadata_observations
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

### `metadata_observations`

Stores extracted metadata facts observed in indexed files. This is intentionally an
intermediate layer between raw parser output and future normalized tag/taxonomy
tables.

Important fields:

| Field | Meaning |
| --- | --- |
| `id` | Internal UUID |
| `audio_asset_id` | Referenced audio content |
| `file_instance_id` | Concrete file path where the metadata was observed |
| `scan_run_id` | Extraction run that produced the observation |
| `source_type` | Metadata source, e.g. `ni_soundinfo_utf16` or `ni_msgpack` |
| `observation_index` | Stable index within the file/source for idempotent replacement |
| `title` | Extracted sample title/name when available |
| `vendor` | Extracted vendor when available |
| `product` | Extracted product/bank when available |
| `category_paths` | JSON category paths, e.g. `[["Loops"], ["Loops", "Vocal"]]` |
| `attributes` | JSON map of normalized secondary fields |
| `raw_payload` | JSON copy of the parsed source payload/candidate |

Observations are replaced per file when metadata extraction is rerun, so parser
fixes can be applied repeatedly without creating duplicate rows for the same file.

## Local PostgreSQL

Start only PostgreSQL:

```bash
docker compose up -d db
```

Initialize tables:

```bash
sth init-db
```

Index a small subset first:

```bash
sth index --limit 100
```

Extract metadata observations from already indexed files:

```bash
sth extract-metadata --limit 100
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

## Retrying Failed Files

Every indexing run creates a `scan_runs` row. Per-file failures are stored in
`scan_errors`. After parser fixes, re-index only the failed files from a previous
run:

```bash
sth retry-errors <scan_run_id>
```

If no scan run ID is provided, the command retries the latest run with errors:

```bash
sth retry-errors
```

The retry creates a new `scan_runs` row whose `dataset_path` is prefixed with
`retry-errors:`. Existing `file_instances` are updated in place when a previously
failed file is successfully indexed.

## Extracting Metadata Observations

`sth extract-metadata` scans existing `file_instances`, reads NI metadata from the
corresponding WAV files, and stores one or more rows in `metadata_observations`.

Currently supported observation sources:

| Source type | Meaning |
| --- | --- |
| `ni_soundinfo_utf16` | GEOB SoundInfo payload summarized from length-prefixed UTF-16LE strings |
| `ni_msgpack` | MessagePack tag object candidate found in a metadata chunk |

The command creates a new `scan_runs` row with `dataset_path` set to
`metadata-observations:indexed-files`. Per-file extraction errors are written to
`scan_errors`.

## Current Scope

The indexer currently stores:

1. WAV `data`-chunk SHA-256.
2. WAV format info from `fmt `.
3. Full file path and filesystem metadata.
4. Scan run status and per-file errors.

Metadata extraction now stores observed NI tag facts in `metadata_observations`.
It does not yet build normalized category/taxonomy tables. Those belong to the
next phase after enough observations have been collected and inspected.

## WAV Parser Tolerance

The audio indexer hashes the WAV `data` chunk and intentionally avoids depending on
later metadata chunks. It currently tolerates several NI WAV variants observed in
the dataset:

1. A single physical padding byte after the RIFF-declared end.
2. Missing padding after an odd-sized chunk when the next bytes already form a
   valid RIFF chunk header.
3. A `data` chunk that extends past an incorrect RIFF-declared end, as long as the
   declared `data` payload fits within the actual file size.
