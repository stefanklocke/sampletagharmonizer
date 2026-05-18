from __future__ import annotations

from .models import ByteRegion, CoverageDiagnostic


def validate_regions(regions: list[ByteRegion], file_size: int) -> list[CoverageDiagnostic]:
    diagnostics: list[CoverageDiagnostic] = []
    top_level = sorted(
        (region for region in regions if region.parent_id is None),
        key=lambda region: (region.start, region.end),
    )

    previous_end = 0
    previous_region: ByteRegion | None = None
    for region in top_level:
        if region.start < 0 or region.end < region.start:
            diagnostics.append(
                CoverageDiagnostic(
                    severity="error",
                    code="invalid_region_range",
                    message=f"Region {region.id} has an invalid byte range.",
                    offset=region.start,
                )
            )
            continue
        if region.end > file_size:
            diagnostics.append(
                CoverageDiagnostic(
                    severity="error",
                    code="region_beyond_file_end",
                    message=f"Region {region.id} extends beyond the file end.",
                    offset=file_size,
                    metadata={"region_end": region.end},
                )
            )
        if region.start < previous_end and previous_region is not None:
            diagnostics.append(
                CoverageDiagnostic(
                    severity="error",
                    code="overlapping_regions",
                    message=f"Region {region.id} overlaps with {previous_region.id}.",
                    offset=region.start,
                    metadata={"previous_region_id": previous_region.id, "previous_end": previous_end},
                )
            )
        if region.start > previous_end:
            diagnostics.append(
                CoverageDiagnostic(
                    severity="warning",
                    code="uncovered_gap",
                    message="Top-level byte coverage has an uncovered gap.",
                    offset=previous_end,
                    metadata={"start": previous_end, "end": region.start, "size": region.start - previous_end},
                )
            )
        if region.end > previous_end:
            previous_end = region.end
            previous_region = region

    if previous_end < file_size:
        diagnostics.append(
            CoverageDiagnostic(
                severity="warning",
                code="uncovered_tail",
                message="Top-level byte coverage does not reach the physical file end.",
                offset=previous_end,
                metadata={"start": previous_end, "end": file_size, "size": file_size - previous_end},
            )
        )

    return diagnostics


def classify_safety(diagnostics: list[CoverageDiagnostic]) -> str:
    severities = {diagnostic.severity for diagnostic in diagnostics}
    if "error" in severities:
        return "invalid"
    if "warning" in severities:
        return "safe_with_known_tolerances"
    return "safe_to_rewrite"
