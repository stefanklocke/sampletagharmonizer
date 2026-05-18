from __future__ import annotations

from pathlib import Path

from sampletagharmonizer.byte_coverage import build_wav_byte_map
from sampletagharmonizer.byte_coverage.models import ByteCoverageMap, ByteRegion
from sampletagharmonizer.byte_coverage.write_policy import assess_write_safety_map
from sampletagharmonizer.parsers.wav.identity import inspect_audio_identity

from .models import ByteRangePlan, SizeFieldPlan, WritePlan


SUPPORTED_WRITE_SAFETY = "safe_to_update_existing_metadata"
SUPPORTED_WRITE_STRATEGY = "preserve_audio_update_existing_id3_geob"


def plan_existing_id3_geob_update(source_path: Path, output_path: Path) -> WritePlan:
    coverage_map = build_wav_byte_map(source_path)
    write_safety = assess_write_safety_map(coverage_map)
    if write_safety.write_safety != SUPPORTED_WRITE_SAFETY or write_safety.write_strategy != SUPPORTED_WRITE_STRATEGY:
        blockers = ", ".join(blocker["code"] for blocker in write_safety.blockers) or write_safety.write_safety
        raise ValueError(
            "File is not supported by the v1 write-plan strategy "
            f"{SUPPORTED_WRITE_STRATEGY}: {blockers}"
        )

    regions = _TargetRegions.from_coverage_map(coverage_map)
    audio_identity = inspect_audio_identity(source_path)
    replace_start = regions.geob_frame_header.start
    replace_end = regions.geob_frame_payload.end

    return WritePlan(
        source_path=source_path,
        output_path=output_path,
        strategy=SUPPORTED_WRITE_STRATEGY,
        write_safety=write_safety.write_safety,
        coverage_safety=write_safety.coverage_safety,
        source_audio_sha256=audio_identity.data_sha256,
        source_audio_size=audio_identity.data_size,
        target_regions=regions.to_target_region_dicts(),
        copy_ranges=[
            ByteRangePlan(
                id="copy_before_target_geob_frame",
                start=0,
                end=replace_start,
                purpose="copy_source_bytes_before_generated_geob_frame",
            ),
            ByteRangePlan(
                id="copy_after_target_geob_frame",
                start=replace_end,
                end=coverage_map.file_size,
                purpose="copy_source_bytes_after_generated_geob_frame",
            ),
        ],
        immutable_ranges=[
            ByteRangePlan(
                id="immutable_audio_data_payload",
                start=regions.audio_payload.start,
                end=regions.audio_payload.end,
                purpose="audio_bytes_must_remain_identical",
                source_region_id=regions.audio_payload.id,
                metadata={"sha256": audio_identity.data_sha256},
            ),
        ],
        replace_ranges=[
            ByteRangePlan(
                id="replace_target_geob_frame",
                start=replace_start,
                end=replace_end,
                purpose="replace_existing_geob_frame_with_generated_ni_metadata",
                source_region_id=regions.geob_frame_header.id,
                metadata={
                    "frame_id": "GEOB",
                    "includes_header": True,
                    "includes_payload": True,
                },
            )
        ],
        patch_fields=[
            SizeFieldPlan(
                id="riff_size",
                start=4,
                end=8,
                encoding="uint32_le",
                description="RIFF size field: output file size minus 8 bytes.",
                source_region_id="riff_header",
            ),
            SizeFieldPlan(
                id="id3_chunk_payload_size",
                start=regions.id3_chunk_header.start + 4,
                end=regions.id3_chunk_header.start + 8,
                encoding="uint32_le",
                description="RIFF ID3 chunk payload size.",
                source_region_id=regions.id3_chunk_header.id,
            ),
            SizeFieldPlan(
                id="id3_tag_size",
                start=regions.id3_header.start + 6,
                end=regions.id3_header.start + 10,
                encoding="synchsafe_uint32",
                description="ID3 tag size excluding the 10-byte ID3 header.",
                source_region_id=regions.id3_header.id,
            ),
            SizeFieldPlan(
                id="geob_frame_payload_size",
                start=regions.geob_frame_header.start + 4,
                end=regions.geob_frame_header.start + 8,
                encoding="uint32_be",
                description="GEOB frame payload size.",
                source_region_id=regions.geob_frame_header.id,
            ),
        ],
        normalizations=write_safety.normalizations,
        preconditions=write_safety.requirements,
    )


class _TargetRegions:
    def __init__(
        self,
        audio_payload: ByteRegion,
        id3_chunk_header: ByteRegion,
        id3_chunk_payload: ByteRegion,
        id3_header: ByteRegion,
        geob_frame_header: ByteRegion,
        geob_frame_payload: ByteRegion,
        soundinfo_payload: ByteRegion,
        msgpack_candidates: list[ByteRegion],
    ) -> None:
        self.audio_payload = audio_payload
        self.id3_chunk_header = id3_chunk_header
        self.id3_chunk_payload = id3_chunk_payload
        self.id3_header = id3_header
        self.geob_frame_header = geob_frame_header
        self.geob_frame_payload = geob_frame_payload
        self.soundinfo_payload = soundinfo_payload
        self.msgpack_candidates = msgpack_candidates

    @classmethod
    def from_coverage_map(cls, coverage_map: ByteCoverageMap) -> _TargetRegions:
        by_id = {region.id: region for region in coverage_map.regions}
        audio_payload = _single_region(coverage_map, "audio")
        soundinfo_payload = _single_region(coverage_map, "ni_soundinfo_payload")
        geob_frame_payload = _required_parent(by_id, soundinfo_payload)
        if geob_frame_payload.kind != "id3_frame_payload":
            raise ValueError("NI SoundInfo payload is not inside an ID3 frame payload.")
        geob_frame_header = _required_parent(by_id, geob_frame_payload)
        if geob_frame_header.kind != "id3_frame_header" or geob_frame_header.metadata.get("frame_id") != "GEOB":
            raise ValueError("NI SoundInfo payload is not inside a GEOB frame.")
        id3_header = _required_parent(by_id, geob_frame_header)
        if id3_header.kind != "id3_header":
            raise ValueError("GEOB frame is not attached to an ID3 header.")
        id3_chunk_payload = _required_parent(by_id, id3_header)
        if id3_chunk_payload.kind != "metadata" or id3_chunk_payload.metadata.get("chunk_id") != "ID3 ":
            raise ValueError("ID3 header is not inside an ID3 RIFF chunk payload.")
        id3_chunk_header = _chunk_header_for_payload(coverage_map, id3_chunk_payload)
        msgpack_candidates = [
            region
            for region in coverage_map.regions
            if region.kind == "msgpack_candidate" and region.parent_id == geob_frame_payload.id
        ]
        return cls(
            audio_payload=audio_payload,
            id3_chunk_header=id3_chunk_header,
            id3_chunk_payload=id3_chunk_payload,
            id3_header=id3_header,
            geob_frame_header=geob_frame_header,
            geob_frame_payload=geob_frame_payload,
            soundinfo_payload=soundinfo_payload,
            msgpack_candidates=msgpack_candidates,
        )

    def to_target_region_dicts(self) -> list[dict]:
        regions = [
            ("audio_payload", self.audio_payload),
            ("id3_chunk_header", self.id3_chunk_header),
            ("id3_chunk_payload", self.id3_chunk_payload),
            ("id3_header", self.id3_header),
            ("geob_frame_header", self.geob_frame_header),
            ("geob_frame_payload", self.geob_frame_payload),
            ("soundinfo_payload", self.soundinfo_payload),
        ]
        regions.extend(
            (f"msgpack_candidate_{index}", region)
            for index, region in enumerate(self.msgpack_candidates)
        )
        return [
            {
                "role": role,
                "region": region.to_dict(),
            }
            for role, region in regions
        ]


def _single_region(coverage_map: ByteCoverageMap, kind: str) -> ByteRegion:
    regions = [region for region in coverage_map.regions if region.kind == kind]
    if len(regions) != 1:
        raise ValueError(f"Expected exactly one {kind} region, found {len(regions)}.")
    return regions[0]


def _required_parent(by_id: dict[str, ByteRegion], region: ByteRegion) -> ByteRegion:
    if region.parent_id is None:
        raise ValueError(f"Region {region.id} has no parent.")
    try:
        return by_id[region.parent_id]
    except KeyError as exc:
        raise ValueError(f"Region {region.id} references missing parent {region.parent_id}.") from exc


def _chunk_header_for_payload(coverage_map: ByteCoverageMap, payload: ByteRegion) -> ByteRegion:
    expected_start = payload.start - 8
    for region in coverage_map.regions:
        if region.kind == "chunk_header" and region.start == expected_start and region.end == payload.start:
            return region
    raise ValueError(f"Could not find RIFF chunk header for payload region {payload.id}.")
