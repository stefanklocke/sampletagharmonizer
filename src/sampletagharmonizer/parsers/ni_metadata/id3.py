from __future__ import annotations

from .models import Id3Frame


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
