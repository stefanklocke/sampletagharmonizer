# Writer

## Purpose

This package will contain the WAV metadata writer. It is intentionally starting with a read-only write-plan generator before any code is allowed to create or modify WAV files.

The writer follows the design documented in `docs/WRITER_DESIGN.md`.

## Structure

- `models.py`: serializable write-plan models.
- `planner.py`: read-only planner for the first supported writer strategy.

## Current Scope

The first slice supports only this policy result:

```text
write_safety = safe_to_update_existing_metadata
write_strategy = preserve_audio_update_existing_id3_geob
```

The planner:

- builds the byte coverage map
- runs write-safety validation
- computes the source audio `data` chunk hash
- locates the target ID3 chunk, GEOB frame, and NI SoundInfo payload
- marks byte ranges to copy from the source
- marks byte ranges that must remain byte-identical after writing
- marks the existing GEOB frame as the future replacement range
- lists container size fields that a future writer must patch

It does not write files.

## CLI

Generate a read-only write plan:

```bash
sth plan-write source.wav --output-path tagged.wav --pretty
```

The output path is part of the plan, but no output file is created yet.
