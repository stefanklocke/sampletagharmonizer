from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from sampletagharmonizer.db.models import ScanRun, WriteSafetyResult


def collect_write_safety_samples(
    session: Session,
    scan_run_id: str | None = None,
    per_strategy: int = 5,
    write_safety: str | None = None,
    write_strategy: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    scan_run = _resolve_scan_run(session, scan_run_id)
    strategy_rows = session.execute(
        _strategy_counts_statement(scan_run.id, write_safety, write_strategy)
    ).all()

    strategies = []
    for safety, strategy, total_count in strategy_rows:
        sample_rows = session.scalars(
            _sample_statement(
                scan_run_id=scan_run.id,
                write_safety=safety,
                write_strategy=strategy,
                per_strategy=per_strategy,
            )
        ).all()
        strategies.append(
            {
                "write_safety": safety,
                "write_strategy": strategy,
                "total_count": total_count,
                "samples": [
                    _result_to_dict(result, include_raw=include_raw)
                    for result in sample_rows
                ],
            }
        )

    return {
        "scan_run_id": scan_run.id,
        "dataset_path": scan_run.dataset_path,
        "status": scan_run.status,
        "scanned_files": scan_run.scanned_files,
        "indexed_files": scan_run.indexed_files,
        "error_count": scan_run.error_count,
        "per_strategy": per_strategy,
        "filters": {
            "write_safety": write_safety,
            "write_strategy": write_strategy,
        },
        "strategies": strategies,
    }


def _resolve_scan_run(session: Session, scan_run_id: str | None) -> ScanRun:
    if scan_run_id is not None:
        scan_run = session.get(ScanRun, scan_run_id)
        if scan_run is None:
            raise ValueError(f"Write-safety scan run not found: {scan_run_id}")
        if not scan_run.dataset_path.startswith("write-safety:"):
            raise ValueError(f"Scan run is not a write-safety run: {scan_run_id}")
        return scan_run

    scan_run = session.scalars(
        select(ScanRun)
        .where(ScanRun.dataset_path.like("write-safety:%"))
        .order_by(ScanRun.started_at.desc())
        .limit(1)
    ).first()
    if scan_run is None:
        raise ValueError("No write-safety scan run found.")
    return scan_run


def _strategy_counts_statement(
    scan_run_id: str,
    write_safety: str | None,
    write_strategy: str | None,
) -> Select[tuple[str, str, int]]:
    statement = (
        select(
            WriteSafetyResult.write_safety,
            WriteSafetyResult.write_strategy,
            func.count().label("total_count"),
        )
        .where(WriteSafetyResult.scan_run_id == scan_run_id)
        .group_by(WriteSafetyResult.write_safety, WriteSafetyResult.write_strategy)
        .order_by(func.count().desc(), WriteSafetyResult.write_safety, WriteSafetyResult.write_strategy)
    )
    if write_safety is not None:
        statement = statement.where(WriteSafetyResult.write_safety == write_safety)
    if write_strategy is not None:
        statement = statement.where(WriteSafetyResult.write_strategy == write_strategy)
    return statement


def _sample_statement(
    scan_run_id: str,
    write_safety: str,
    write_strategy: str,
    per_strategy: int,
) -> Select[tuple[WriteSafetyResult]]:
    return (
        select(WriteSafetyResult)
        .where(
            WriteSafetyResult.scan_run_id == scan_run_id,
            WriteSafetyResult.write_safety == write_safety,
            WriteSafetyResult.write_strategy == write_strategy,
        )
        .order_by(WriteSafetyResult.path)
        .limit(per_strategy)
    )


def _result_to_dict(result: WriteSafetyResult, include_raw: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": result.path,
        "coverage_safety": result.coverage_safety,
        "write_safety": result.write_safety,
        "write_strategy": result.write_strategy,
        "requirements": result.requirements or {},
        "normalizations": result.normalizations or [],
        "blockers": result.blockers or [],
        "diagnostic_count": result.diagnostic_count,
        "diagnostics_by_code": result.diagnostics_by_code or {},
        "diagnostics_by_severity": result.diagnostics_by_severity or {},
    }
    if include_raw:
        data["raw_summary"] = result.raw_summary
    return data
