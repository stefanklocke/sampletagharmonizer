from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

from .models import WavAudioIdentity
from .riff import advance_after_payload, can_extend_to_actual_end, parse_fmt_chunk, riff_bounds


def inspect_audio_identity(path: Path, buffer_size: int = 1024 * 1024) -> WavAudioIdentity:
    fmt_data: bytes | None = None
    data_hash: hashlib._Hash | None = None
    data_size: int | None = None

    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ValueError("not a RIFF/WAVE file")
        riff_end, actual_end = riff_bounds(path, header)

        while handle.tell() + 8 <= riff_end:
            offset = handle.tell()
            chunk_header = handle.read(8)

            chunk_id = chunk_header[:4].decode("ascii", errors="replace")
            size = int.from_bytes(chunk_header[4:8], "little")
            payload_end = handle.tell() + size
            if payload_end > riff_end and not can_extend_to_actual_end(chunk_id, payload_end, actual_end):
                raise ValueError(f"truncated chunk payload at byte {offset}")

            if chunk_id == "fmt ":
                fmt_data = handle.read(size)
            elif chunk_id == "data":
                data_hash = hashlib.sha256()
                data_size = size
                _hash_stream(handle, size, data_hash, buffer_size)
                if fmt_data is not None:
                    break
            else:
                handle.seek(size, 1)

            advance_after_payload(handle, size, riff_end, actual_end)

    if data_hash is None or data_size is None:
        raise ValueError("WAV file has no data chunk")

    fmt = parse_fmt_chunk(fmt_data)
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
