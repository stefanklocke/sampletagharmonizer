from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Id3Frame:
    frame_id: str
    offset: int
    size: int
    data: bytes


@dataclass(frozen=True)
class LengthPrefixedString:
    offset: int
    length: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "offset": self.offset,
            "length": self.length,
            "text": self.text,
        }


@dataclass(frozen=True)
class NiSoundInfoSummary:
    title: str | None
    vendor: str | None
    product: str | None
    category_paths: list[list[str]]
    attributes: dict[str, str | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "vendor": self.vendor,
            "product": self.product,
            "category_paths": self.category_paths,
            "attributes": self.attributes,
        }


@dataclass(frozen=True)
class GeobFrameMetadata:
    encoding: int
    mime: str
    object_id: str | None
    payload_size: int
    summary: NiSoundInfoSummary
    utf16le_strings: list[LengthPrefixedString]

    def to_dict(self) -> dict[str, Any]:
        return {
            "encoding": self.encoding,
            "mime": self.mime,
            "object_id": self.object_id,
            "payload_size": self.payload_size,
            "summary": self.summary.to_dict(),
            "utf16le_strings": [item.to_dict() for item in self.utf16le_strings],
        }
