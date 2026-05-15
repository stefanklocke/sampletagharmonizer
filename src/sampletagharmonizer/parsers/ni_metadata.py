from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .msgpack_lite import MsgpackDecodeError, decode_prefix, looks_like_ni_tag_object
from .wav import RiffChunk, iter_riff_chunks

NI_SOUNDINFO_MIME = "com.native-instruments.nisound.soundinfo"


@dataclass(frozen=True)
class Id3Frame:
    frame_id: str
    offset: int
    size: int
    data: bytes


def _synchsafe_to_int(raw: bytes) -> int:
    value = 0
    for byte in raw:
        value = (value << 7) | (byte & 0x7F)
    return value


def _frame_size(raw: bytes) -> int:
    normal = int.from_bytes(raw, "big")
    synchsafe = _synchsafe_to_int(raw)
    # NI's embedded ID3v2.4 chunks appear to use normal big-endian sizes.
    return normal if normal <= 16_000_000 else synchsafe


def parse_id3_frames(data: bytes) -> list[Id3Frame]:
    if len(data) < 10 or data[:3] != b"ID3":
        return []

    tag_size = _synchsafe_to_int(data[6:10])
    end = min(len(data), 10 + tag_size) if tag_size else len(data)
    frames: list[Id3Frame] = []
    pos = 10
    while pos + 10 <= end:
        frame_id_raw = data[pos : pos + 4]
        if frame_id_raw == b"\x00\x00\x00\x00":
            break
        frame_id = frame_id_raw.decode("latin-1", errors="replace")
        size = _frame_size(data[pos + 4 : pos + 8])
        frame_data_start = pos + 10
        frame_data_end = frame_data_start + size
        if size <= 0 or frame_data_end > len(data):
            break
        frames.append(Id3Frame(frame_id=frame_id, offset=pos, size=size, data=data[frame_data_start:frame_data_end]))
        pos = frame_data_end
    return frames


def parse_geob_frame(data: bytes) -> dict[str, Any] | None:
    if not data:
        return None
    encoding = data[0]
    mime_end = data.find(b"\x00", 1)
    if mime_end < 0:
        return None

    mime = data[1:mime_end].decode("latin-1", errors="replace")
    payload = data[mime_end + 1 :]
    object_id = None
    metadata_payload = payload
    ni_marker = NI_SOUNDINFO_MIME.encode("latin-1") + b"\x00"
    ni_marker_offset = data.find(ni_marker)
    if ni_marker_offset >= 0:
        object_id = NI_SOUNDINFO_MIME
        metadata_payload = data[ni_marker_offset + len(ni_marker) :]

    utf16le_strings = scan_utf16le_length_prefixed_strings(metadata_payload)
    texts = [item["text"] for item in utf16le_strings]
    return {
        "encoding": encoding,
        "mime": mime,
        "object_id": object_id,
        "payload_size": len(payload),
        "summary": summarize_soundinfo_texts(texts),
        "utf16le_strings": utf16le_strings,
    }


def summarize_soundinfo_texts(texts: list[str]) -> dict[str, Any]:
    category_paths = [
        [part for part in text.split("\\:") if part]
        for text in texts
        if text.startswith("\\:")
    ]
    attributes: dict[str, str | None] = {}
    for index, text in enumerate(texts):
        if not text.startswith("\\@"):
            continue
        key = text[2:]
        next_text = texts[index + 1] if index + 1 < len(texts) else None
        attributes[key] = next_text if next_text and not next_text.startswith("\\") else None

    regular_texts = [
        text
        for text in texts
        if not text.startswith("\\") and not text.isdecimal()
    ]
    product = next(
        (
            text
            for text in regular_texts[1:]
            if text != "Native Instruments" and not text.startswith("1.")
        ),
        None,
    )

    return {
        "title": regular_texts[0] if regular_texts else None,
        "vendor": "Native Instruments" if "Native Instruments" in regular_texts else None,
        "product": product,
        "category_paths": category_paths,
        "attributes": attributes,
    }


def scan_utf16le_length_prefixed_strings(data: bytes) -> list[dict[str, Any]]:
    strings: list[dict[str, Any]] = []
    for offset in range(max(0, len(data) - 4)):
        length = int.from_bytes(data[offset : offset + 4], "little")
        byte_length = length * 2
        start = offset + 4
        end = start + byte_length
        if length < 1 or length > 200 or end > len(data):
            continue
        raw = data[start:end]
        if any(raw[index + 1] != 0 for index in range(0, len(raw), 2)):
            continue
        text = raw.decode("utf-16le", errors="replace")
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            continue
        printable = sum(1 for char in text if char.isprintable())
        if printable < max(1, int(len(text) * 0.8)):
            continue
        strings.append({"offset": offset, "length": length, "text": text})
    return strings


def find_msgpack_candidates(data: bytes, max_candidates: int = 8) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for offset, marker in enumerate(data):
        if not (0x80 <= marker <= 0x8F or marker in {0xDE, 0xDF}):
            continue
        try:
            result = decode_prefix(data[offset:])
        except (MsgpackDecodeError, UnicodeDecodeError):
            continue
        if result.consumed < 16 or not looks_like_ni_tag_object(result.value):
            continue
        candidates.append({"offset": offset, "consumed": result.consumed, "value": result.value})
        if len(candidates) >= max_candidates:
            break
    return candidates


def inspect_wav(path: Path) -> dict[str, Any]:
    chunks = iter_riff_chunks(path)
    id3_frames: list[dict[str, Any]] = []
    msgpack: list[dict[str, Any]] = []

    for chunk in chunks:
        if chunk.data is None:
            continue
        if chunk.chunk_id == "ID3 ":
            for frame in parse_id3_frames(chunk.data):
                frame_info: dict[str, Any] = {
                    "frame_id": frame.frame_id,
                    "offset": frame.offset,
                    "size": frame.size,
                }
                if frame.frame_id == "GEOB":
                    geob = parse_geob_frame(frame.data)
                    if geob is not None:
                        frame_info["geob"] = geob
                        msgpack.extend(_msgpack_candidates_for_bytes(chunk, frame.data))
                id3_frames.append(frame_info)
        else:
            msgpack.extend(_msgpack_candidates_for_chunk(chunk))

    ni_soundinfo = [
        frame["geob"]
        for frame in id3_frames
        if frame.get("geob", {}).get("object_id") == NI_SOUNDINFO_MIME
    ]

    return {
        "path": str(path),
        "chunks": [
            {"chunk_id": chunk.chunk_id, "offset": chunk.offset, "size": chunk.size}
            for chunk in chunks
        ],
        "id3_frames": id3_frames,
        "ni_soundinfo": ni_soundinfo,
        "msgpack_candidates": msgpack,
    }


def _msgpack_candidates_for_chunk(chunk: RiffChunk) -> list[dict[str, Any]]:
    if chunk.data is None:
        return []
    return _msgpack_candidates_for_bytes(chunk, chunk.data)


def _msgpack_candidates_for_bytes(chunk: RiffChunk, data: bytes) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for candidate in find_msgpack_candidates(data):
        results.append(
            {
                "chunk_id": chunk.chunk_id,
                "chunk_offset": chunk.offset,
                **candidate,
            }
        )
    return results
