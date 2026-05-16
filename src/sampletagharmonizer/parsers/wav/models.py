from __future__ import annotations

from dataclasses import dataclass


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
