from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dataset_path: Mapped[str] = mapped_column(Text, nullable=False)
    scanner_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scanned_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    file_instances: Mapped[list[FileInstance]] = relationship(back_populates="last_scan_run")
    errors: Mapped[list[ScanError]] = relationship(back_populates="scan_run")


class AudioAsset(Base):
    __tablename__ = "audio_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    data_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    data_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    format_tag: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    byte_rate: Mapped[int | None] = mapped_column(Integer)
    block_align: Mapped[int | None] = mapped_column(Integer)
    bits_per_sample: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    file_instances: Mapped[list[FileInstance]] = relationship(back_populates="audio_asset")


class FileInstance(Base):
    __tablename__ = "file_instances"
    __table_args__ = (
        UniqueConstraint("path", name="uq_file_instances_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    audio_asset_id: Mapped[str] = mapped_column(ForeignKey("audio_assets.id"), nullable=False, index=True)
    last_scan_run_id: Mapped[str | None] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    suffix: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    audio_asset: Mapped[AudioAsset] = relationship(back_populates="file_instances")
    last_scan_run: Mapped[ScanRun | None] = relationship(back_populates="file_instances")


class ScanError(Base):
    __tablename__ = "scan_errors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    scan_run: Mapped[ScanRun] = relationship(back_populates="errors")
