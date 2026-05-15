from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class RiffChunk:
    chunk_id: str
    offset: int
    size: int
    data: bytes | None = None


@dataclass(frozen=True)
class WavAudioIdentity:
    data_sha256: str
    data_size: int
    format_tag: int | None = None
    channels: int | None = None
    sample_rate: int | None = None
    byte_rate: int | None = None
    block_align: int | None = None
    bits_per_sample: int | None = None


def iter_riff_chunks(path: Path, read_data_limit: int = 2_000_000) -> list[RiffChunk]:
    chunks: list[RiffChunk] = []
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ValueError("not a RIFF/WAVE file")

        while True:
            offset = handle.tell()
            chunk_header = handle.read(8)
            if not chunk_header:
                break
            if len(chunk_header) != 8:
                raise ValueError(f"truncated chunk header at byte {offset}")

            raw_id, raw_size = chunk_header[:4], chunk_header[4:8]
            chunk_id = raw_id.decode("ascii", errors="replace")
            size = int.from_bytes(raw_size, "little")
            data = handle.read(size) if size <= read_data_limit and chunk_id != "data" else None
            if data is None:
                handle.seek(size, 1)
            if size % 2:
                handle.seek(1, 1)

            chunks.append(RiffChunk(chunk_id=chunk_id, offset=offset, size=size, data=data))
    return chunks


def inspect_audio_identity(path: Path, buffer_size: int = 1024 * 1024) -> WavAudioIdentity:
    fmt_data: bytes | None = None
    data_hash: hashlib._Hash | None = None
    data_size: int | None = None

    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ValueError("not a RIFF/WAVE file")

        while True:
            chunk_header = handle.read(8)
            if not chunk_header:
                break
            if len(chunk_header) != 8:
                raise ValueError(f"truncated chunk header at byte {handle.tell() - len(chunk_header)}")

            chunk_id = chunk_header[:4].decode("ascii", errors="replace")
            size = int.from_bytes(chunk_header[4:8], "little")
            if chunk_id == "fmt ":
                fmt_data = handle.read(size)
            elif chunk_id == "data":
                data_hash = hashlib.sha256()
                data_size = size
                _hash_stream(handle, size, data_hash, buffer_size)
            else:
                handle.seek(size, 1)

            if size % 2:
                handle.seek(1, 1)

    if data_hash is None or data_size is None:
        raise ValueError("WAV file has no data chunk")

    fmt = _parse_fmt_chunk(fmt_data)
    return WavAudioIdentity(
        data_sha256=data_hash.hexdigest(),
        data_size=data_size,
        **fmt,
    )


def _hash_stream(handle: BinaryIO, size: int, digest: hashlib._Hash, buffer_size: int) -> None:
    remaining = size
    while remaining:
        chunk = handle.read(min(buffer_size, remaining))
        if not chunk:
            raise ValueError("truncated data chunk")
        digest.update(chunk)
        remaining -= len(chunk)


def _parse_fmt_chunk(data: bytes | None) -> dict[str, int | None]:
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
