# Native Instruments WAV Metadata Structure

This document is the high-level project note for the observed Native Instruments WAV metadata layout. Detailed code-adjacent parser documentation lives next to the implementation:

- [`src/sampletagharmonizer/parsers/ni_metadata/README.md`](../src/sampletagharmonizer/parsers/ni_metadata/README.md)

The analysis is based on read-only scans of the dataset configured via `DATASET_PATH_NI` and the reverse-engineering notes in `Reverse Engineering.xlsx`.

## RIFF/WAVE Layer

A valid file starts with:

```text
RIFF <little-endian file size> WAVE
```

After that, the file contains a sequence of RIFF chunks:

```text
<4-byte chunk id> <4-byte little-endian size> <chunk payload> [pad byte if odd size]
```

Observed chunk IDs include:

| Chunk | Purpose |
| --- | --- |
| `fmt ` | Standard WAV audio format information |
| `data` | Audio payload |
| `ID3 ` | Embedded ID3v2 metadata; most relevant for NI tags |
| `fact` | Standard/non-PCM sample count metadata |
| `acid` | ACID loop metadata |
| `JUNK` | Padding/reserved data |
| `LIST` | RIFF list metadata, e.g. labels |
| `bext` | Broadcast WAV extension |
| `cue ` | Cue points |
| `LGWV` | Observed proprietary/vendor-specific waveform data |

The metadata scanner intentionally skips reading the `data` chunk into memory. The database indexer streams that chunk through SHA-256 and returns as soon as `fmt ` and `data` have been read, so exotic metadata chunks after the audio payload do not block audio-content indexing.

## NI Metadata Parser

The NI parser currently focuses on metadata stored in `ID3 ` RIFF chunks, especially GEOB frames containing `com.native-instruments.nisound.soundinfo`.

See the package README for:

- the WAV/ID3/GEOB nesting diagram
- ID3 synchsafe integer details
- observed MessagePack tag objects
- observed length-prefixed UTF-16LE strings
- scanner output shape
- current interpretation and write-safety assumptions
