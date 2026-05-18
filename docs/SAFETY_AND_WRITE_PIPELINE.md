# Safety and Write Pipeline

## Purpose

This document explains the read-only safety layers that sit between raw WAV parsing and the future writer.

The project now has several similarly named concepts:

- byte map
- byte coverage safety
- write safety
- write plan
- writer

They are related, but each layer answers a different question.

## Overview

```text
WAV file
  |
  v
Byte Map
  "Which bytes belong to which structure?"
  |
  v
Byte Coverage Safety
  "Is the byte map complete and internally consistent?"
  |
  v
Write Safety
  "Which write strategy, if any, is allowed for this file?"
  |
  v
Write Plan
  "Which concrete byte ranges would a future writer copy, replace, or patch?"
  |
  v
Writer
  "Generate and validate a new WAV file."
```

The writer itself is not implemented yet. Everything up to the write plan is read-only.

## Byte Map

The byte map is the structural map of a WAV file.

It answers:

```text
Which bytes belong where?
```

Example:

```text
0..12          RIFF/WAVE header
36..44         data chunk header
44..180644     audio bytes
180644..180652 ID3 chunk header
180662..181027 GEOB frame
```

CLI:

```bash
sth byte-map file.wav --pretty
```

The byte map does not decide whether writing is safe. It only makes the file structure visible.

## Byte Coverage Safety

Byte coverage safety validates the byte map.

It answers:

```text
Is the file structurally understood at the current parser depth?
```

It checks for:

- unexplained byte gaps
- overlapping regions
- truncated chunk headers
- truncated chunk payloads
- RIFF size mismatches
- tolerated padding and size quirks

CLI:

```bash
sth validate-byte-coverage file.wav --pretty
```

Dataset mode:

```bash
sth validate-byte-coverage --dataset --store --summary-only
```

Common safety values:

| Value | Meaning |
| --- | --- |
| `safe_to_rewrite` | The file structure is fully covered without diagnostics. |
| `safe_with_known_tolerances` | The file is understandable, but known warning-level tolerances were needed. |
| `invalid` | Error-level structural diagnostics were found. |

This still does not mean the writer should modify the file. It only means the byte structure is understood.

## Write Safety

Write safety is the first writer policy layer.

It answers:

```text
Which writer strategy is allowed for this file?
```

It builds on byte coverage and checks NI-specific writer preconditions:

- exactly one audio `data` payload
- existing `ID3 ` chunk when required
- exactly one NI SoundInfo payload for the first update strategy
- no coverage errors
- only known warning-level tolerances

CLI:

```bash
sth validate-write-safety file.wav --pretty
```

Dataset mode with PostgreSQL storage:

```bash
sth validate-write-safety --dataset --store --summary-only
```

Sample stored results:

```bash
sth write-safety-samples --per-strategy 3 --pretty
```

Common write-safety values:

| Value | Meaning |
| --- | --- |
| `safe_to_update_existing_metadata` | Existing ID3/GEOB/SoundInfo structure is unambiguous and can be targeted by writer v1. |
| `safe_with_normalization_to_update_existing_metadata` | Existing metadata can be targeted, but known container tolerances must be normalized during rewrite. |
| `review_required` | The structure is readable but ambiguous for automated writing. |
| `read_only` | The current policy must not modify this file. |

Common write strategies:

| Strategy | Meaning |
| --- | --- |
| `preserve_audio_update_existing_id3_geob` | Replace existing NI metadata in an existing GEOB frame while preserving audio bytes. |
| `normalize_then_update_existing_id3_geob` | Same target as above, but also normalize known container tolerances. |
| `unsupported_missing_ni_soundinfo_payload` | ID3 exists, but no NI SoundInfo payload was mapped. Later strategy: insert GEOB/SoundInfo into existing ID3. |
| `unsupported_missing_id3_chunk` | No ID3 chunk was mapped. Later strategy: append a new ID3 chunk. |

## Write Plan

The write plan is a concrete, read-only build plan for one file.

It answers:

```text
If a writer were run, which bytes would be copied, replaced, or patched?
```

CLI:

```bash
sth plan-write source.wav --output-path tagged.wav --pretty
```

Important: `plan-write` does not create `tagged.wav`. The output path is part of the plan only.

The current planner supports only:

```text
write_safety = safe_to_update_existing_metadata
write_strategy = preserve_audio_update_existing_id3_geob
```

The plan includes:

- source file
- planned output file
- selected strategy
- source audio hash
- source audio size
- target ID3 chunk
- target GEOB frame
- target NI SoundInfo payload
- byte ranges to copy from source
- byte ranges to replace with generated metadata
- size fields to recalculate
- write-safety preconditions

The current model uses these range groups:

| Group | Meaning |
| --- | --- |
| `preserve_ranges` | Source ranges the future builder should copy. Some copied ranges may contain size fields that are patched later. |
| `replace_ranges` | Source ranges the future builder should replace with generated bytes. |
| `size_fields_to_recalculate` | Length fields that must be patched after output bytes are built. |

The distinction between copied ranges and immutable ranges may be refined later. In particular, the audio payload should remain byte-identical, while copied header ranges may still contain size fields that get recalculated.

## Writer

The actual writer is not implemented yet.

When implemented, it should follow the design in `WRITER_DESIGN.md`:

```text
Read -> Plan -> Build -> Validate -> Commit
```

The default output mode should create a new file, not overwrite the source file.

Mandatory writer invariants:

- source file remains unchanged in default mode
- output audio hash equals source audio hash
- output byte coverage has no errors
- output metadata can be parsed back
- all changed byte ranges are explained by the write plan
- all affected length fields match the generated byte sizes

## Current Project State

Implemented:

- read-only WAV parsing
- dataset indexing
- metadata extraction
- byte maps
- byte coverage validation
- byte coverage PostgreSQL storage
- write-safety validation
- write-safety PostgreSQL storage
- write-safety sample reports
- read-only write-plan generator for writer v1

Not implemented yet:

- metadata generation for new tags
- actual output WAV byte building
- output WAV validation
- copy-mode writer command
- directory-mode writer command
- in-place writing

## Why These Layers Exist

Writing WAV metadata is risky because a small mistake can make a file unreadable or silently alter audio data.

Direct writing could accidentally:

- change audio bytes
- emit incorrect RIFF sizes
- emit incorrect ID3 sizes
- corrupt GEOB payload sizes
- create metadata that Native Instruments tools cannot read

The layer sequence reduces that risk:

1. Make byte structure visible.
2. Validate structural coverage.
3. Decide which writer strategy is allowed.
4. Generate an auditable write plan.
5. Only then build and validate a new file.

The project is currently at step 4.
