from __future__ import annotations

import struct
from typing import Any

from .models import MsgpackDecodeError, MsgpackDecodeResult


class _Decoder:
    def __init__(self, data: bytes, max_depth: int = 64) -> None:
        self.data = data
        self.pos = 0
        self.max_depth = max_depth

    def read(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise MsgpackDecodeError("unexpected end of data")
        value = self.data[self.pos : self.pos + size]
        self.pos += size
        return value

    def decode(self, depth: int = 0) -> Any:
        if depth > self.max_depth:
            raise MsgpackDecodeError("maximum nesting depth exceeded")
        marker = self.read(1)[0]

        if marker <= 0x7F:
            return marker
        if 0x80 <= marker <= 0x8F:
            return self.decode_map(marker & 0x0F, depth)
        if 0x90 <= marker <= 0x9F:
            return [self.decode(depth + 1) for _ in range(marker & 0x0F)]
        if 0xA0 <= marker <= 0xBF:
            return self.read(marker & 0x1F).decode("utf-8")
        if marker >= 0xE0:
            return marker - 0x100

        if marker == 0xC0:
            return None
        if marker == 0xC2:
            return False
        if marker == 0xC3:
            return True
        if marker == 0xCA:
            return struct.unpack(">f", self.read(4))[0]
        if marker == 0xCB:
            return struct.unpack(">d", self.read(8))[0]
        if marker == 0xCC:
            return self.read(1)[0]
        if marker == 0xCD:
            return struct.unpack(">H", self.read(2))[0]
        if marker == 0xCE:
            return struct.unpack(">I", self.read(4))[0]
        if marker == 0xCF:
            return struct.unpack(">Q", self.read(8))[0]
        if marker == 0xD0:
            return struct.unpack(">b", self.read(1))[0]
        if marker == 0xD1:
            return struct.unpack(">h", self.read(2))[0]
        if marker == 0xD2:
            return struct.unpack(">i", self.read(4))[0]
        if marker == 0xD3:
            return struct.unpack(">q", self.read(8))[0]
        if marker == 0xD9:
            return self.read(self.read(1)[0]).decode("utf-8")
        if marker == 0xDA:
            return self.read(struct.unpack(">H", self.read(2))[0]).decode("utf-8")
        if marker == 0xDB:
            return self.read(struct.unpack(">I", self.read(4))[0]).decode("utf-8")
        if marker == 0xDC:
            return [self.decode(depth + 1) for _ in range(struct.unpack(">H", self.read(2))[0])]
        if marker == 0xDD:
            return [self.decode(depth + 1) for _ in range(struct.unpack(">I", self.read(4))[0])]
        if marker == 0xDE:
            return self.decode_map(struct.unpack(">H", self.read(2))[0], depth)
        if marker == 0xDF:
            return self.decode_map(struct.unpack(">I", self.read(4))[0], depth)

        raise MsgpackDecodeError(f"unsupported MessagePack marker 0x{marker:02x}")

    def decode_map(self, size: int, depth: int) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for _ in range(size):
            key = self.decode(depth + 1)
            value = self.decode(depth + 1)
            try:
                result[key] = value
            except TypeError as exc:
                raise MsgpackDecodeError("map key is not hashable") from exc
        return result


def decode_prefix(data: bytes) -> MsgpackDecodeResult:
    decoder = _Decoder(data)
    value = decoder.decode()
    return MsgpackDecodeResult(value=value, consumed=decoder.pos)


def looks_like_ni_tag_object(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = set(value.keys())
    strong_keys = {"modes", "types", "vendor", "name", "__ni_internal"}
    return len(keys & strong_keys) >= 2
