from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from .models import RiffChunk


def iter_riff_chunks(path: Path, read_data_limit: int = 2_000_000) -> list[RiffChunk]:
    chunks: list[RiffChunk] = []
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ValueError("not a RIFF/WAVE file")
        riff_end, actual_end = riff_bounds(path, header)

        while handle.tell() + 8 <= riff_end:
            skip_zero_padding_before_chunk(handle, riff_end)
            if handle.tell() + 8 > riff_end:
                break
            offset = handle.tell()
            chunk_header = handle.read(8)

            raw_id, raw_size = chunk_header[:4], chunk_header[4:8]
            chunk_id = raw_id.decode("ascii", errors="replace")
            size = int.from_bytes(raw_size, "little")
            payload_end = handle.tell() + size
            if payload_end > riff_end and not can_extend_to_actual_end(chunk_id, payload_end, actual_end):
                raise ValueError(f"truncated chunk payload at byte {offset}")

            should_read = size <= read_data_limit and chunk_id != "data"
            data = handle.read(size) if should_read else None
            if data is None:
                handle.seek(size, 1)
            advance_after_payload(handle, size, riff_end, actual_end)

            chunks.append(RiffChunk(chunk_id=chunk_id, offset=offset, size=size, data=data))
    return chunks


def skip_zero_padding_before_chunk(handle: BinaryIO, riff_end: int, max_padding: int = 32) -> None:
    pos = handle.tell()
    if looks_like_chunk_header_at(handle, pos, riff_end):
        return

    for skip in range(1, max_padding + 1):
        candidate = pos + skip
        if candidate + 8 > riff_end:
            break
        if not _all_zero_bytes(handle, pos, candidate):
            break
        if looks_like_chunk_header_at(handle, candidate, riff_end):
            handle.seek(candidate)
            return


def advance_after_payload(handle: BinaryIO, size: int, riff_end: int, actual_end: int) -> None:
    if size % 2 == 0 or handle.tell() >= actual_end:
        return

    pos = handle.tell()
    if looks_like_chunk_header_at(handle, pos, riff_end):
        return
    if pos < actual_end:
        handle.seek(1, 1)


def can_extend_to_actual_end(chunk_id: str, payload_end: int, actual_end: int) -> bool:
    return payload_end <= actual_end and is_plausible_chunk_id(chunk_id)


def is_plausible_chunk_id(chunk_id: str) -> bool:
    return len(chunk_id) == 4 and all(32 <= ord(char) <= 126 for char in chunk_id)


def looks_like_chunk_header_at(handle: BinaryIO, offset: int, riff_end: int) -> bool:
    if offset + 8 > riff_end:
        return False

    original = handle.tell()
    try:
        handle.seek(offset)
        header = handle.read(8)
    finally:
        handle.seek(original)

    if len(header) != 8:
        return False
    chunk_id = header[:4]
    if not all(32 <= byte <= 126 for byte in chunk_id):
        return False
    size = int.from_bytes(header[4:8], "little")
    return offset + 8 + size <= riff_end


def _all_zero_bytes(handle: BinaryIO, start: int, end: int) -> bool:
    original = handle.tell()
    try:
        handle.seek(start)
        data = handle.read(end - start)
    finally:
        handle.seek(original)
    return all(byte == 0 for byte in data)


def riff_bounds(path: Path, header: bytes) -> tuple[int, int]:
    riff_size = int.from_bytes(header[4:8], "little")
    declared_end = 8 + riff_size
    actual_end = path.stat().st_size
    if actual_end == declared_end + 1:
        return actual_end, actual_end
    return min(declared_end, actual_end), actual_end


def parse_fmt_chunk(data: bytes | None) -> dict[str, int | None]:
    if data is None or len(data) < 16:
        return {
            "format_tag": None,
            "channels": None,
            "sample_rate": None,
            "byte_rate": None,
            "block_align": None,
            "bits_per_sample": None,
        }
    return {
        "format_tag": int.from_bytes(data[0:2], "little"),
        "channels": int.from_bytes(data[2:4], "little"),
        "sample_rate": int.from_bytes(data[4:8], "little"),
        "byte_rate": int.from_bytes(data[8:12], "little"),
        "block_align": int.from_bytes(data[12:14], "little"),
        "bits_per_sample": int.from_bytes(data[14:16], "little"),
    }
