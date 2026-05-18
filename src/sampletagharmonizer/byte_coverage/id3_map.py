from __future__ import annotations

from sampletagharmonizer.parsers.ni_metadata.id3 import _synchsafe_to_int, parse_id3_frames
from sampletagharmonizer.parsers.ni_metadata.scanner import find_msgpack_candidates
from sampletagharmonizer.parsers.ni_metadata.soundinfo import (
    NI_SOUNDINFO_MIME,
    parse_geob_frame,
    scan_utf16le_length_prefixed_strings,
)

from .models import ByteRegion, CoverageDiagnostic


def add_id3_regions(
    data: bytes,
    payload_start: int,
    payload_region_id: str,
    regions: list[ByteRegion],
    diagnostics: list[CoverageDiagnostic],
) -> None:
    if len(data) < 10 or data[:3] != b"ID3":
        diagnostics.append(
            CoverageDiagnostic(
                severity="warning",
                code="id3_payload_not_parsed",
                message="ID3 chunk payload does not start with an ID3 header.",
                offset=payload_start,
            )
        )
        return

    tag_size = _synchsafe_to_int(data[6:10])
    declared_tag_end = 10 + tag_size if tag_size else len(data)
    regions.append(
        _region(
            f"id3_{payload_start}_header",
            payload_start,
            payload_start + 10,
            "id3_header",
            "ID3 header",
            parent_id=payload_region_id,
            metadata={
                "version_major": data[3],
                "version_revision": data[4],
                "flags": data[5],
                "declared_tag_size": tag_size,
            },
        )
    )

    if declared_tag_end > len(data):
        diagnostics.append(
            CoverageDiagnostic(
                severity="error",
                code="id3_declared_tag_beyond_chunk",
                message="ID3-declared tag size extends beyond the ID3 chunk payload.",
                offset=payload_start,
                metadata={"declared_tag_end": payload_start + declared_tag_end, "chunk_payload_end": payload_start + len(data)},
            )
        )

    frames = parse_id3_frames(data)
    for frame in frames:
        frame_header_start = payload_start + frame.offset
        frame_payload_start = frame_header_start + 10
        frame_payload_end = frame_payload_start + frame.size
        frame_id = _region_id(frame.frame_id)
        header_region_id = f"id3_frame_{frame_header_start}_{frame_id}_header"
        payload_region_id = f"id3_frame_{frame_header_start}_{frame_id}_payload"

        regions.append(
            _region(
                header_region_id,
                frame_header_start,
                frame_payload_start,
                "id3_frame_header",
                f"{frame.frame_id} frame header",
                parent_id=f"id3_{payload_start}_header",
                metadata={"frame_id": frame.frame_id, "declared_payload_size": frame.size},
            )
        )
        regions.append(
            _region(
                payload_region_id,
                frame_payload_start,
                frame_payload_end,
                "id3_frame_payload",
                f"{frame.frame_id} frame payload",
                parent_id=payload_region_id.rsplit("_payload", 1)[0] + "_header",
                metadata={"frame_id": frame.frame_id, "declared_payload_size": frame.size},
            )
        )

        if frame.frame_id == "GEOB":
            _add_geob_regions(
                frame.data,
                frame_payload_start,
                payload_region_id,
                regions,
                diagnostics,
            )
        _add_msgpack_candidate_regions(frame.data, frame_payload_start, payload_region_id, regions)


def _add_geob_regions(
    data: bytes,
    frame_payload_start: int,
    frame_payload_region_id: str,
    regions: list[ByteRegion],
    diagnostics: list[CoverageDiagnostic],
) -> None:
    if not data:
        return

    encoding_region_id = f"geob_{frame_payload_start}_encoding"
    regions.append(
        _region(
            encoding_region_id,
            frame_payload_start,
            frame_payload_start + 1,
            "geob_encoding",
            "GEOB text encoding byte",
            parent_id=frame_payload_region_id,
            metadata={"encoding": data[0]},
        )
    )

    mime_end = data.find(b"\x00", 1)
    if mime_end < 0:
        diagnostics.append(
            CoverageDiagnostic(
                severity="warning",
                code="geob_mime_terminator_missing",
                message="GEOB frame has no MIME terminator.",
                offset=frame_payload_start,
            )
        )
        return

    regions.append(
        _region(
            f"geob_{frame_payload_start}_mime",
            frame_payload_start + 1,
            frame_payload_start + mime_end + 1,
            "geob_mime",
            "GEOB MIME field",
            parent_id=frame_payload_region_id,
            metadata={"mime": data[1:mime_end].decode("latin-1", errors="replace")},
        )
    )

    geob = parse_geob_frame(data)
    marker = NI_SOUNDINFO_MIME.encode("latin-1") + b"\x00"
    marker_offset = data.find(marker)
    if geob is None or marker_offset < 0:
        return

    marker_start = frame_payload_start + marker_offset
    marker_end = marker_start + len(marker)
    soundinfo_payload_start = marker_end
    soundinfo_payload_end = frame_payload_start + len(data)
    soundinfo_region_id = f"soundinfo_{soundinfo_payload_start}_payload"

    regions.append(
        _region(
            f"soundinfo_{marker_start}_marker",
            marker_start,
            marker_end,
            "ni_soundinfo_marker",
            "NI SoundInfo object marker",
            parent_id=frame_payload_region_id,
            metadata={"object_id": NI_SOUNDINFO_MIME},
        )
    )
    regions.append(
        _region(
            soundinfo_region_id,
            soundinfo_payload_start,
            soundinfo_payload_end,
            "ni_soundinfo_payload",
            "NI SoundInfo payload",
            parent_id=frame_payload_region_id,
            metadata={"summary": geob.summary.to_dict(), "payload_size": len(data) - marker_offset - len(marker)},
        )
    )

    metadata_payload = data[marker_offset + len(marker) :]
    for string in scan_utf16le_length_prefixed_strings(metadata_payload):
        start = soundinfo_payload_start + string.offset
        end = start + 4 + string.length * 2
        regions.append(
            _region(
                f"soundinfo_string_{start}",
                start,
                end,
                "utf16le_length_prefixed_string",
                "Length-prefixed UTF-16LE string",
                parent_id=soundinfo_region_id,
                metadata={"text": string.text, "length": string.length},
            )
        )


def _add_msgpack_candidate_regions(
    data: bytes,
    data_start: int,
    parent_id: str,
    regions: list[ByteRegion],
) -> None:
    for candidate in find_msgpack_candidates(data):
        start = data_start + candidate["offset"]
        end = start + candidate["consumed"]
        value = candidate["value"] if isinstance(candidate["value"], dict) else {}
        regions.append(
            _region(
                f"msgpack_candidate_{start}",
                start,
                end,
                "msgpack_candidate",
                "MessagePack candidate",
                parent_id=parent_id,
                metadata={
                    "consumed": candidate["consumed"],
                    "keys": sorted(str(key) for key in value.keys()),
                },
            )
        )


def _region(
    id: str,
    start: int,
    end: int,
    kind: str,
    label: str,
    parent_id: str | None = None,
    metadata: dict | None = None,
) -> ByteRegion:
    return ByteRegion(
        id=id,
        start=start,
        end=end,
        kind=kind,
        label=label,
        parent_id=parent_id,
        metadata=metadata or {},
    )


def _region_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_").lower()
