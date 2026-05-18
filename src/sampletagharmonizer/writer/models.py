from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ByteRangePlan:
    id: str
    start: int
    end: int
    purpose: str
    source_region_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "size": self.size,
            "purpose": self.purpose,
        }
        if self.source_region_id is not None:
            data["source_region_id"] = self.source_region_id
        if self.metadata:
            data["metadata"] = self.metadata
        return data


@dataclass(frozen=True)
class SizeFieldPlan:
    id: str
    start: int
    end: int
    encoding: str
    description: str
    source_region_id: str | None = None

    @property
    def size(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "size": self.size,
            "encoding": self.encoding,
            "description": self.description,
        }
        if self.source_region_id is not None:
            data["source_region_id"] = self.source_region_id
        return data


@dataclass(frozen=True)
class WritePlan:
    source_path: Path
    output_path: Path
    strategy: str
    write_safety: str
    coverage_safety: str
    source_audio_sha256: str
    source_audio_size: int
    target_regions: list[dict[str, Any]]
    preserve_ranges: list[ByteRangePlan]
    replace_ranges: list[ByteRangePlan]
    size_fields_to_recalculate: list[SizeFieldPlan]
    normalizations: list[str]
    preconditions: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "output_path": str(self.output_path),
            "strategy": self.strategy,
            "write_safety": self.write_safety,
            "coverage_safety": self.coverage_safety,
            "source_audio_sha256": self.source_audio_sha256,
            "source_audio_size": self.source_audio_size,
            "target_regions": self.target_regions,
            "preserve_ranges": [item.to_dict() for item in self.preserve_ranges],
            "replace_ranges": [item.to_dict() for item in self.replace_ranges],
            "size_fields_to_recalculate": [item.to_dict() for item in self.size_fields_to_recalculate],
            "normalizations": self.normalizations,
            "preconditions": self.preconditions,
        }
