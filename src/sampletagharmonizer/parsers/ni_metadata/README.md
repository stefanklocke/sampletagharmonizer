# NI Metadata Parser

## Purpose

This package contains parsers for Native Instruments metadata embedded in WAV files. It focuses on the metadata structures observed in NI sample libraries, especially ID3 chunks, GEOB frames, NI SoundInfo payloads, and MessagePack-like tag candidates.

The public import surface is re-exported from `__init__.py`, so callers can use:

```python
from sampletagharmonizer.parsers.ni_metadata import inspect_wav, parse_geob_frame
```

## Structure

- `models.py`: typed domain objects used by the NI metadata parser.
- `id3.py`: low-level ID3 frame parsing helpers.
- `soundinfo.py`: GEOB and NI SoundInfo extraction.
- `scanner.py`: high-level WAV inspection and MessagePack candidate discovery.

## High-Level Layout

NI sample metadata is stored inside normal RIFF/WAVE files. The audio data stays in the usual `data` chunk, while tag metadata is stored in additional chunks, most importantly an `ID3 ` RIFF chunk.

```mermaid
flowchart TD
    wav["WAV file"]
    riff["RIFF header<br/>RIFF + size + WAVE"]
    chunks["RIFF chunks"]

    wav --> riff
    wav --> chunks

    chunks --> fmt["fmt <br/>Audio format"]
    chunks --> data["data<br/>PCM/audio payload"]
    chunks --> optional["Optional chunks<br/>fact, acid, JUNK, LIST, bext, cue, LGWV"]
    chunks --> id3chunk["ID3 <br/>Embedded ID3v2 tag"]

    id3chunk --> id3header["ID3 header"]
    id3chunk --> frames["ID3 frames"]
    frames --> geob["GEOB frame"]

    geob --> marker["Object identifier<br/>com.native-instruments.nisound.soundinfo"]
    geob --> niPayload["NI soundinfo payload"]

    niPayload --> utf16["Length-prefixed UTF-16LE strings"]
    niPayload --> msgpack["MessagePack tag object"]

    utf16 --> paths["Category paths<br/>\\:Loops\\:Guitar\\:Clean"]
    utf16 --> attrs["Attributes<br/>\\@tempo, \\@color, \\@verm"]

    msgpack --> modes["modes<br/>Digital, Acoustic, Lo-Fi"]
    msgpack --> types["types<br/>[['Drums', 'Clap']]"]
    msgpack --> fields["name, vendor, author,<br/>bankchain, tempo, comment"]
```

## ID3 Layer

NI metadata has been observed inside an `ID3 ` RIFF chunk. The payload begins with an ID3 header:

```text
ID3 <version> <flags> <synchsafe tag size>
```

Inside the ID3 tag, the currently relevant frame is:

```text
GEOB
```

`GEOB` is a general encapsulated object frame. In the observed files, NI uses it to store `com.native-instruments.nisound.soundinfo`.

Important detail: some files do not put the NI identifier into the standard GEOB MIME field. Instead, the scanner searches the complete GEOB frame for:

```text
com.native-instruments.nisound.soundinfo\0
```

Everything after this marker is treated as the NI soundinfo payload.

## Synchsafe Integer

`_synchsafe_to_int()` decodes a **synchsafe integer** from ID3 tags.

In ID3v2, the size of the full tag is often not stored as a normal 32-bit integer. Instead, it is stored as 4 bytes where each byte uses only **7 bits** of payload data. The highest bit of each byte always remains `0`.

Why? This prevents byte patterns inside the ID3 metadata block from being misinterpreted by an MP3 decoder as audio sync headers. That is why the encoding is called "sync-safe".

The function:

```python
def _synchsafe_to_int(raw: bytes) -> int:
    value = 0
    for byte in raw:
        value = (value << 7) | (byte & 0x7F)
    return value
```

does this for each byte:

1. Shift the current value left by 7 bits.
2. Keep only the lower 7 bits of the current byte: `byte & 0x7F`.
3. Append these bits to the accumulated value.

Example:

```text
raw = 00 00 02 10
```

is not read as the normal big-endian value `528`, but as:

```text
0 << 7 | 0
0 << 7 | 0
0 << 7 | 2
2 << 7 | 16 = 272
```

In this parser, it is used here:

```python
tag_size = _synchsafe_to_int(data[6:10])
```

These are the 4 bytes for the tag size in the ID3 header. The frame sizes themselves appear to use normal big-endian values in some NI files, so `_frame_size()` handles that separately.

## Observed NI Payload Variants

Two useful variants have appeared so far.

### Variant A: MessagePack Tag Object

Some files contain a compact MessagePack object with clear tag fields:

```json
{
  "__ni_internal": {
    "source": "other"
  },
  "author": "Native Instruments",
  "bankchain": ["Chromatic Fire"],
  "comment": "",
  "modes": ["Digital"],
  "name": "Clap BlackEarth",
  "tempo": 0.0,
  "types": [["Drums", "Clap"]],
  "vendor": "Native Instruments"
}
```

This confirms the finding from `docs/Reverse Engineering.xlsx`: bytes like `0xa8` are not category IDs. They are MessagePack string markers. For example:

```text
0xa8 Acoustic
```

means "fixed-length string with 8 bytes", followed by the UTF-8 string `Acoustic`.

Useful MessagePack markers:

| Marker | Meaning |
| --- | --- |
| `0x80`-`0x8f` | fixed-size map |
| `0x90`-`0x9f` | fixed-size array |
| `0xa0`-`0xbf` | fixed-size UTF-8 string |
| `0xcb` | 64-bit float |
| `0xdc` | array16 |
| `0xde` | map16 |

### Variant B: Length-Prefixed UTF-16LE Strings

Other files expose category and attribute information as length-prefixed UTF-16LE strings. A string is encoded as:

```text
<4-byte little-endian character count> <UTF-16LE string bytes>
```

Example decoded strings:

```text
Guitar[140] C GuitarSlim 1
Native Instruments
Native Instruments
Lilac Glare
\:Loops
\:Loops\:Guitar
\:Loops\:Guitar\:Clean
\@color
0
\@devicetypeflags
0
\@soundtype
0
\@tempo
0
\@verl
1.7.12
\@verm
1.7.12
\@visib
0
```

The scanner summarizes these as:

```json
{
  "title": "Guitar[140] C GuitarSlim 1",
  "vendor": "Native Instruments",
  "product": "Lilac Glare",
  "category_paths": [
    ["Loops"],
    ["Loops", "Guitar"],
    ["Loops", "Guitar", "Clean"]
  ],
  "attributes": {
    "color": "0",
    "devicetypeflags": "0",
    "soundtype": "0",
    "tempo": "0",
    "verl": "1.7.12",
    "verm": "1.7.12",
    "visib": "0"
  }
}
```

## Scanner Output Model

`sth scan` currently emits one JSON report with this shape:

```text
dataset_path
scanned_files
reported_files
errors[]
files[]
  path
  chunks[]
    chunk_id
    offset
    size
  id3_frames[]
    frame_id
    offset
    size
    geob?
      encoding
      mime
      object_id
      payload_size
      summary
      utf16le_strings[]
  ni_soundinfo[]
  msgpack_candidates[]
    chunk_id
    chunk_offset
    offset
    consumed
    value
```

Example command:

```bash
sth scan --limit 20 --only-hits --pretty
```

## Current Interpretation

The important working hypothesis is:

1. NI category names are stored as text, not as opaque category IDs.
2. MessagePack `modes` and `types` are the cleanest source when present.
3. UTF-16LE `\:...` paths are another category representation, probably used by a different NI product/version/export path.
4. Writing support should preserve the exact existing container structure for the file variant being edited.

The project should remain read-only until enough files have been scanned to verify which variant each NI product line uses.
