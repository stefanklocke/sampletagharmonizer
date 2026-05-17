# Byte Coverage Map

## Idea

A byte coverage map would make parser behavior visible for a single WAV file. It should show which byte ranges are covered by RIFF chunks, ID3 frames, GEOB payloads, NI SoundInfo strings, MessagePack candidates, padding, gaps, and errors.

This is useful because the current parsing work deals with nested binary structures and vendor-specific quirks. Without a visual or structured byte map, it is hard to understand which parser read which byte range and where malformed chunks or unexpected padding occur.

## Conceptual View

For a simple WAV file:

```text
0        12      36      80              1024084       1025572
| RIFF   | fmt   | data                  | ID3          |
[header ][fmt  ][audio payload...........][metadata.....]
```

For nested metadata:

```text
ID3 chunk @ 1024084 size 1488
  ID3 header @ +0 size 10
  GEOB frame @ +10 size 1040
    GEOB header @ +10 size 10
    SoundInfo marker @ ...
    UTF-16LE string @ ...
    MessagePack candidate @ ...
```

## Regions To Capture

- RIFF header
- RIFF chunks:
  - `fmt `
  - `fact`
  - `acid`
  - `data`
  - `ID3 `
  - unknown or vendor-specific chunks
- Chunk padding bytes
- Extra zero-padding blocks
- Gaps not interpreted by any parser
- Overlaps, if parser regions unexpectedly cover the same bytes
- ID3 headers and frames
- GEOB payloads
- NI SoundInfo marker
- Length-prefixed UTF-16LE strings
- MessagePack candidates
- Error offsets from `scan_errors`

## Possible CLI

Start with JSON output:

```bash
sth byte-map "/path/to/file.wav" --pretty
```

Later, optionally generate an HTML/SVG report:

```bash
sth byte-map "/path/to/file.wav" --html report.html
```

## Possible JSON Shape

```json
{
  "path": "/path/to/file.wav",
  "file_size": 1025572,
  "regions": [
    {
      "label": "RIFF header",
      "start": 0,
      "end": 12,
      "kind": "container_header"
    },
    {
      "label": "data",
      "start": 80,
      "end": 1024076,
      "kind": "audio"
    }
  ]
}
```

Use half-open intervals: `start` is inclusive, `end` is exclusive. This makes sizes easy to compute as `end - start`.

## Open Design Questions

1. Should byte maps be generated directly from parser internals, or should parsers emit structured trace events?
2. Should gaps and overlaps be computed after all regions are collected?
3. Should the first implementation be JSON-only, with HTML/SVG added later?
4. Should error offsets from `scan_errors` be merged into the report by querying PostgreSQL, or passed explicitly?
5. Should byte maps show absolute file offsets only, or also offsets relative to parent containers?

## Suggested First Step

Implement a JSON-only `sth byte-map` command for one file. It should collect regions for RIFF headers/chunks, ID3 frames, GEOB metadata, UTF-16LE strings, and MessagePack candidates. Once the JSON shape proves useful on real parser failures, add an HTML/SVG renderer.
