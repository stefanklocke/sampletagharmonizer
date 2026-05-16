# MessagePack Lite Parser

## Purpose

This package contains a small MessagePack decoder tailored to the NI metadata scanner. It decodes enough of the MessagePack format to inspect observed Native Instruments tag objects without adding a full third-party MessagePack dependency.

The public import surface is re-exported from `__init__.py`, so callers can use:

```python
from sampletagharmonizer.parsers.msgpack_lite import decode_prefix
```

## Structure

- `models.py`: decode result and parser-specific exception type.
- `decoder.py`: minimal recursive MessagePack decoder and NI tag-object heuristic.

## Scope

The decoder supports the MessagePack markers observed in the current NI dataset, including fixmap, fixarray, fixstr, numeric values, booleans, nil, str8/16/32, array16/32, and map16/32.

It intentionally exposes `decode_prefix()` rather than requiring a full-buffer decode. This is useful for scanning arbitrary binary payloads where a MessagePack object may begin at an offset inside a larger chunk.

## Decoder Flow

`_Decoder` is a tiny stateful reader around a `bytes` object. It owns three pieces of state:

- `data`: the complete byte buffer being decoded
- `pos`: the current read position inside `data`
- `max_depth`: a recursion guard for nested arrays and maps

`read(size)` returns the next `size` bytes and advances `pos`. If the requested bytes would pass the end of the buffer, it raises `MsgpackDecodeError`.

`decode(depth=0)` reads exactly one MessagePack value from the current position. MessagePack is self-describing: the first byte of each value is a marker that determines both the value type and, for some compact encodings, the value length.

The method therefore follows this pattern:

1. Read one marker byte.
2. Decide which MessagePack type the marker represents.
3. Read any additional bytes required by that type.
4. Convert the raw bytes to a Python value.
5. For arrays and maps, recursively decode the nested values.

The `depth` argument is incremented only for nested container values. If nesting exceeds `max_depth`, decoding stops with `MsgpackDecodeError` instead of recursing indefinitely.

## Marker Groups

MessagePack reserves ranges of marker bytes for compact "fixed" encodings. These ranges explain the broad `if` checks at the top of `_Decoder.decode()`.

| Marker range | MessagePack type | Python result | Notes |
| --- | --- | --- | --- |
| `0x00`-`0x7f` | positive fixint | `int` | The marker byte itself is the value. |
| `0x80`-`0x8f` | fixmap | `dict` | Lower 4 bits contain the number of key/value pairs. |
| `0x90`-`0x9f` | fixarray | `list` | Lower 4 bits contain the number of items. |
| `0xa0`-`0xbf` | fixstr | `str` | Lower 5 bits contain the UTF-8 byte length. |
| `0xe0`-`0xff` | negative fixint | `int` | Marker is interpreted as a signed 8-bit value. |

For example, `0xa8` is not a Native Instruments category ID. It is a MessagePack `fixstr` marker:

```text
0xa8 = 0b10101000
          ^^^^^ lower 5 bits = 8
```

So `0xa8 Acoustic` means "read the next 8 bytes as a UTF-8 string", producing `"Acoustic"`.

Markers outside those compact ranges use explicit payload sizes:

| Marker | MessagePack type | Additional bytes | Python result |
| --- | --- | --- | --- |
| `0xc0` | nil | 0 | `None` |
| `0xc2` | false | 0 | `False` |
| `0xc3` | true | 0 | `True` |
| `0xca` | float32 | 4 | `float` |
| `0xcb` | float64 | 8 | `float` |
| `0xcc` | uint8 | 1 | `int` |
| `0xcd` | uint16 | 2 | `int` |
| `0xce` | uint32 | 4 | `int` |
| `0xcf` | uint64 | 8 | `int` |
| `0xd0` | int8 | 1 | `int` |
| `0xd1` | int16 | 2 | `int` |
| `0xd2` | int32 | 4 | `int` |
| `0xd3` | int64 | 8 | `int` |
| `0xd9` | str8 | 1-byte length + payload | `str` |
| `0xda` | str16 | 2-byte length + payload | `str` |
| `0xdb` | str32 | 4-byte length + payload | `str` |
| `0xdc` | array16 | 2-byte item count + items | `list` |
| `0xdd` | array32 | 4-byte item count + items | `list` |
| `0xde` | map16 | 2-byte pair count + key/value pairs | `dict` |
| `0xdf` | map32 | 4-byte pair count + key/value pairs | `dict` |

Multi-byte numeric lengths and values are read as big-endian, matching the MessagePack specification. That is why the code uses `struct.unpack()` with format strings like `">H"`, `">I"`, and `">Q"`.

## Recursive Containers

Arrays and maps do not contain raw Python values directly. They contain nested MessagePack values, each with its own marker. `_Decoder.decode()` handles this by calling itself recursively:

```python
if 0x90 <= marker <= 0x9F:
    return [self.decode(depth + 1) for _ in range(marker & 0x0F)]
```

For maps, it decodes one key and one value for each pair:

```python
if 0x80 <= marker <= 0x8F:
    return {
        self.decode(depth + 1): self.decode(depth + 1)
        for _ in range(marker & 0x0F)
    }
```

This is enough to decode observed NI tag structures such as:

```json
{
  "modes": ["Digital"],
  "types": [["Drums", "Clap"]],
  "vendor": "Native Instruments"
}
```

## Prefix Decoding

`decode_prefix(data)` decodes one value from the start of `data` and returns both:

- `value`: the decoded Python object
- `consumed`: how many bytes were consumed

This matters because the NI scanner searches through larger binary chunks for possible MessagePack objects. When it tries decoding at a candidate offset, the MessagePack object may end before the surrounding chunk ends. `consumed` lets the scanner know how large the decoded object was without requiring the rest of the chunk to also be valid MessagePack.
