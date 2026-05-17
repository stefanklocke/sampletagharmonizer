from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ByteRegion:
    id: str
    start: int
    end: int
    kind: str
    label: str
    parent_id: str | None = None
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
            "kind": self.kind,
            "label": self.label,
        }
        if self.parent_id is not None:
            data["parent_id"] = self.parent_id
        if self.metadata:
            data["metadata"] = self.metadata
        return data


@dataclass(frozen=True)
class CoverageDiagnostic:
    severity: str
    code: str
    message: str
    offset: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.offset is not None:
            data["offset"] = self.offset
        if self.metadata:
            data["metadata"] = self.metadata
        return data


@dataclass(frozen=True)
class ByteCoverageMap:
    path: Path
    file_size: int
    declared_riff_end: int | None
    effective_riff_end: int | None
    regions: list[ByteRegion]
    diagnostics: list[CoverageDiagnostic]
    safety: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "file_size": self.file_size,
            "declared_riff_end": self.declared_riff_end,
            "effective_riff_end": self.effective_riff_end,
            "safety": self.safety,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "regions": [region.to_dict() for region in self.regions],
        }
