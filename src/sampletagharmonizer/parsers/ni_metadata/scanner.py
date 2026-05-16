from __future__ import annotations

from pathlib import Path
from typing import Any

from sampletagharmonizer.parsers.msgpack_lite import MsgpackDecodeError, decode_prefix, looks_like_ni_tag_object
from sampletagharmonizer.parsers.wav import RiffChunk, iter_riff_chunks

from .id3 import parse_id3_frames
from .soundinfo import NI_SOUNDINFO_MIME, parse_geob_frame


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
                        frame_info["geob"] = geob.to_dict()
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
