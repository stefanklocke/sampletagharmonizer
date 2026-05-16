# WAV Parser

## Purpose

This package contains the low-level RIFF/WAVE parser used by both metadata scanning and dataset indexing.

The parser currently supports two main workflows:

- enumerate RIFF chunks while avoiding loading the audio `data` chunk into memory
- compute a stable audio identity by hashing the WAV `data` chunk

The public import surface is re-exported from `__init__.py`, so callers can use:

```python
from sampletagharmonizer.parsers.wav import inspect_audio_identity, iter_riff_chunks
```

## Structure

- `models.py`: typed domain objects for RIFF chunks and WAV audio identity.
- `riff.py`: RIFF chunk iteration, bounds handling, chunk padding tolerance, and `fmt ` parsing.
- `identity.py`: audio-content identity extraction and `data` chunk hashing.

## Parser Tolerances

The dataset contains several WAV files with minor RIFF irregularities. The parser currently tolerates:

1. A single physical padding byte after the RIFF-declared end.
2. Missing padding after an odd-sized chunk when the next bytes already form a valid RIFF chunk header.
3. A `data` chunk that extends past an incorrect RIFF-declared end, as long as the declared `data` payload fits within the actual file size.

For indexing, `inspect_audio_identity()` returns as soon as both `fmt ` and `data` have been read. This keeps audio identity extraction independent from exotic or malformed metadata chunks after the audio payload.
