# Byte Coverage

## Purpose

This package builds read-only byte coverage maps for WAV files. The goal is to make parser behavior visible before the project starts writing NI metadata back into arbitrary files.

The first implementation covers the RIFF/WAVE layer:

- RIFF/WAVE header
- RIFF chunk headers
- RIFF chunk payloads
- audio payload regions
- metadata chunk payload regions
- padding bytes
- tolerated extra zero-padding blocks
- diagnostics for gaps, overlaps, truncation, and declared-size mismatches

Later iterations can add nested metadata regions for ID3 headers, ID3 frames, GEOB payloads, NI SoundInfo strings, and MessagePack candidates.

## Structure

- `models.py`: serializable byte-region, diagnostic, and map models.
- `wav_map.py`: RIFF/WAVE byte map builder.
- `validator.py`: generic top-level range validation and write-safety classification.

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
