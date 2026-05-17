from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from sampletagharmonizer.parsers.wav.riff import is_plausible_chunk_id

from .id3_map import add_id3_regions
from .models import ByteCoverageMap, ByteRegion, CoverageDiagnostic
from .validator import classify_safety, validate_regions


def build_wav_byte_map(path: Path) -> ByteCoverageMap:
    file_size = path.stat().st_size
    regions: list[ByteRegion] = []
    diagnostics: list[CoverageDiagnostic] = []
    declared_riff_end: int | None = None
    effective_riff_end: int | None = None

    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            diagnostics.append(
                CoverageDiagnostic(
                    severity="error",
                    code="truncated_riff_header",
                    message="File is too short to contain a RIFF/WAVE header.",
                    offset=0,
                )
            )
            return _coverage_map(path, file_size, None, None, regions, diagnostics)
        regions.append(_region("riff_header", 0, 12, "container_header", "RIFF/WAVE header"))

        if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            diagnostics.append(
                CoverageDiagnostic(
                    severity="error",
                    code="not_riff_wave",
                    message="File does not start with a RIFF/WAVE header.",
                    offset=0,
                )
            )
            return _coverage_map(path, file_size, None, None, regions, diagnostics)

        riff_size = int.from_bytes(header[4:8], "little")
        declared_riff_end = 8 + riff_size
        effective_riff_end = _effective_riff_end(file_size, declared_riff_end, diagnostics)
        _parse_chunks(handle, file_size, effective_riff_end, regions, diagnostics)

    return _coverage_map(path, file_size, declared_riff_end, effective_riff_end, regions, diagnostics)


def _coverage_map(
    path: Path,
    file_size: int,
    declared_riff_end: int | None,
    effective_riff_end: int | None,
    regions: list[ByteRegion],
    diagnostics: list[CoverageDiagnostic],
) -> ByteCoverageMap:
    all_diagnostics = diagnostics + validate_regions(regions, file_size)
    return ByteCoverageMap(
        path=path,
        file_size=file_size,
        declared_riff_end=declared_riff_end,
        effective_riff_end=effective_riff_end,
        regions=_sort_regions(regions),
        diagnostics=all_diagnostics,
        safety=classify_safety(all_diagnostics),
    )


def _sort_regions(regions: list[ByteRegion]) -> list[ByteRegion]:
    by_id = {region.id: region for region in regions}

    def depth(region: ByteRegion) -> int:
        value = 0
        parent_id = region.parent_id
        seen = set()
        while parent_id is not None and parent_id not in seen:
            seen.add(parent_id)
            parent = by_id.get(parent_id)
            if parent is None:
                break
            value += 1
            parent_id = parent.parent_id
        return value

    return sorted(regions, key=lambda region: (region.start, depth(region), region.end, region.id))


def _effective_riff_end(
    file_size: int,
    declared_riff_end: int,
    diagnostics: list[CoverageDiagnostic],
) -> int:
    if file_size == declared_riff_end:
        return declared_riff_end
    if file_size == declared_riff_end + 1:
        diagnostics.append(
            CoverageDiagnostic(
                severity="warning",
                code="final_padding_outside_declared_riff",
                message="Physical file has one byte after the declared RIFF end; treating it as tolerated final padding.",
                offset=declared_riff_end,
            )
        )
        return file_size
    if file_size < declared_riff_end:
        diagnostics.append(
            CoverageDiagnostic(
                severity="error",
                code="declared_riff_end_beyond_file",
                message="Declared RIFF end is beyond the physical file end.",
                offset=file_size,
                metadata={"declared_riff_end": declared_riff_end},
            )
        )
        return file_size

    diagnostics.append(
        CoverageDiagnostic(
            severity="warning",
            code="file_extends_beyond_declared_riff",
            message="Physical file extends beyond the declared RIFF end.",
            offset=declared_riff_end,
            metadata={"extra_bytes": file_size - declared_riff_end},
        )
    )
    return declared_riff_end


def _parse_chunks(
    handle: BinaryIO,
    file_size: int,
    effective_riff_end: int,
    regions: list[ByteRegion],
    diagnostics: list[CoverageDiagnostic],
) -> None:
    while handle.tell() < effective_riff_end:
        skipped = _skip_zero_padding_before_chunk(handle, effective_riff_end)
        if skipped is not None:
            start, end = skipped
            regions.append(_region(f"zero_padding_{start}", start, end, "padding", "Extra zero padding before chunk"))
            diagnostics.append(
                CoverageDiagnostic(
                    severity="warning",
                    code="extra_zero_padding_before_chunk",
                    message="Zero padding before the next RIFF chunk was skipped.",
                    offset=start,
                    metadata={"start": start, "end": end, "size": end - start},
                )
            )

        offset = handle.tell()
        if offset >= effective_riff_end:
            break
        if offset + 8 > effective_riff_end:
            diagnostics.append(
                CoverageDiagnostic(
                    severity="error",
                    code="truncated_chunk_header",
                    message="Not enough bytes remain for a RIFF chunk header.",
                    offset=offset,
                )
            )
            regions.append(_region(f"trailing_bytes_{offset}", offset, effective_riff_end, "unknown", "Trailing bytes"))
            handle.seek(effective_riff_end)
            break

        header = handle.read(8)
        chunk_id = header[:4].decode("ascii", errors="replace")
        size = int.from_bytes(header[4:8], "little")
        payload_start = offset + 8
        payload_end = payload_start + size
        header_id = f"chunk_{offset}_header"
        payload_id = f"chunk_{offset}_payload"
        regions.append(
            _region(
                header_id,
                offset,
                payload_start,
                "chunk_header",
                f"{chunk_id} chunk header",
                metadata={"chunk_id": chunk_id, "declared_payload_size": size},
            )
        )

        if payload_end > file_size:
            diagnostics.append(
                CoverageDiagnostic(
                    severity="error",
                    code="truncated_chunk_payload",
                    message=f"Chunk {chunk_id} payload extends beyond the physical file end.",
                    offset=offset,
                    metadata={"chunk_id": chunk_id, "payload_end": payload_end},
                )
            )
            regions.append(_region(payload_id, payload_start, file_size, _chunk_payload_kind(chunk_id), f"{chunk_id} chunk payload"))
            handle.seek(file_size)
            break

        if payload_end > effective_riff_end:
            if is_plausible_chunk_id(chunk_id):
                diagnostics.append(
                    CoverageDiagnostic(
                        severity="warning",
                        code="chunk_payload_extends_beyond_declared_riff",
                        message=f"Chunk {chunk_id} payload extends beyond the declared RIFF end but fits the file.",
                        offset=offset,
                        metadata={"chunk_id": chunk_id, "payload_end": payload_end, "effective_riff_end": effective_riff_end},
                    )
                )
            else:
                diagnostics.append(
                    CoverageDiagnostic(
                        severity="error",
                        code="implausible_chunk_payload_extends_beyond_declared_riff",
                        message=f"Chunk {chunk_id} payload extends beyond the declared RIFF end.",
                        offset=offset,
                        metadata={"chunk_id": chunk_id, "payload_end": payload_end, "effective_riff_end": effective_riff_end},
                    )
                )

        regions.append(
            _region(
                payload_id,
                payload_start,
                payload_end,
                _chunk_payload_kind(chunk_id),
                f"{chunk_id} chunk payload",
                metadata={"chunk_id": chunk_id, "declared_payload_size": size},
            )
        )
        if chunk_id == "ID3 ":
            handle.seek(payload_start)
            add_id3_regions(handle.read(size), payload_start, payload_id, regions, diagnostics)
        handle.seek(payload_end)
        _add_padding_after_payload(handle, chunk_id, size, payload_end, file_size, effective_riff_end, regions, diagnostics)


def _skip_zero_padding_before_chunk(handle: BinaryIO, effective_riff_end: int, max_padding: int = 32) -> tuple[int, int] | None:
    pos = handle.tell()
    if _looks_like_chunk_header_at(handle, pos, effective_riff_end):
        return None

    for skip in range(1, max_padding + 1):
        candidate = pos + skip
        if candidate + 8 > effective_riff_end:
            break
        if not _all_zero_bytes(handle, pos, candidate):
            break
        if _looks_like_chunk_header_at(handle, candidate, effective_riff_end):
            handle.seek(candidate)
            return pos, candidate
    return None


def _add_padding_after_payload(
    handle: BinaryIO,
    chunk_id: str,
    size: int,
    payload_end: int,
    file_size: int,
    effective_riff_end: int,
    regions: list[ByteRegion],
    diagnostics: list[CoverageDiagnostic],
) -> None:
    if size % 2 == 0 or payload_end >= file_size:
        return

    if _looks_like_chunk_header_at(handle, payload_end, effective_riff_end):
        diagnostics.append(
            CoverageDiagnostic(
                severity="warning",
                code="missing_chunk_padding",
                message=f"Odd-sized chunk {chunk_id} is followed by a valid chunk header without a padding byte.",
                offset=payload_end,
                metadata={"chunk_id": chunk_id},
            )
        )
        return

    padding_end = payload_end + 1
    regions.append(_region(f"chunk_{payload_end}_padding", payload_end, padding_end, "padding", f"{chunk_id} chunk padding"))
    handle.seek(padding_end)


def _looks_like_chunk_header_at(handle: BinaryIO, offset: int, effective_riff_end: int) -> bool:
    if offset + 8 > effective_riff_end:
        return False

    original = handle.tell()
    try:
        handle.seek(offset)
        header = handle.read(8)
    finally:
        handle.seek(original)

    if len(header) != 8:
        return False
    raw_id = header[:4]
    if not all(32 <= byte <= 126 for byte in raw_id):
        return False
    size = int.from_bytes(header[4:8], "little")
    return offset + 8 + size <= effective_riff_end


def _all_zero_bytes(handle: BinaryIO, start: int, end: int) -> bool:
    original = handle.tell()
    try:
        handle.seek(start)
        data = handle.read(end - start)
    finally:
        handle.seek(original)
    return all(byte == 0 for byte in data)


def _chunk_payload_kind(chunk_id: str) -> str:
    if chunk_id == "data":
        return "audio"
    if chunk_id == "ID3 ":
        return "metadata"
    return "chunk_payload"


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
