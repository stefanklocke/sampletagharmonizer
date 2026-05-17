# Byte Coverage

## Purpose

This package builds read-only byte coverage maps for WAV files. The goal is to make parser behavior visible before the project starts writing NI metadata back into arbitrary files.

The implementation currently covers the RIFF/WAVE layer:

- RIFF/WAVE header
- RIFF chunk headers
- RIFF chunk payloads
- audio payload regions
- metadata chunk payload regions
- padding bytes
- tolerated extra zero-padding blocks
- diagnostics for gaps, overlaps, truncation, and declared-size mismatches

It also maps nested Native Instruments metadata regions inside `ID3 ` chunks:

- ID3 header
- ID3 frame headers
- ID3 frame payloads
- GEOB encoding and MIME fields
- NI SoundInfo marker
- NI SoundInfo payload
- length-prefixed UTF-16LE strings
- MessagePack tag-object candidates

## Structure

- `models.py`: serializable byte-region, diagnostic, and map models.
- `id3_map.py`: nested ID3, GEOB, SoundInfo, UTF-16LE string, and MessagePack regions.
- `wav_map.py`: RIFF/WAVE byte map builder.
- `validator.py`: generic top-level range validation and write-safety classification.

## Hierarchy

Regions use absolute file offsets and half-open intervals: `start` is inclusive, `end` is exclusive. Nested regions set `parent_id` to the containing region.

Example hierarchy:

```text
WAV file
├─ RIFF/WAVE header
├─ fmt  chunk header
├─ fmt  chunk payload
├─ data chunk header
├─ data chunk payload
├─ ID3  chunk header
└─ ID3  chunk payload
   ├─ ID3 header
   └─ GEOB frame
      ├─ GEOB frame header
      ├─ GEOB frame payload
      │  ├─ GEOB encoding byte
      │  ├─ GEOB MIME field
      │  ├─ NI SoundInfo marker
      │  ├─ NI SoundInfo payload
      │  │  └─ length-prefixed UTF-16LE strings
      │  └─ MessagePack candidates
```

## CLI

Generate a JSON byte map for one WAV file:

```bash
sth byte-map "/path/to/file.wav" --pretty
```

Write the JSON report to a file:

```bash
sth byte-map "/path/to/file.wav" --pretty --output report.json
```

## Safety Classification

The current classification is intentionally conservative:

| Safety | Meaning |
| --- | --- |
| `safe_to_rewrite` | No coverage diagnostics were found at the current parser depth. |
| `safe_with_known_tolerances` | The file is explainable, but at least one warning-level tolerance was needed. |
| `invalid` | Error-level diagnostics were found. |

This is not yet permission to write files. It is the first read-only safety layer that future writer code should depend on.
