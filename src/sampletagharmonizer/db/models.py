from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid4())


json_type = JSON().with_variant(JSONB, "postgresql")


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
    metadata_observations: Mapped[list[MetadataObservation]] = relationship(back_populates="scan_run")
    metadata_file_results: Mapped[list[MetadataFileResult]] = relationship(back_populates="scan_run")


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
    metadata_observations: Mapped[list[MetadataObservation]] = relationship(back_populates="audio_asset")


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
    metadata_observations: Mapped[list[MetadataObservation]] = relationship(back_populates="file_instance")
    metadata_file_results: Mapped[list[MetadataFileResult]] = relationship(back_populates="file_instance")


class ScanError(Base):
    __tablename__ = "scan_errors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    scan_run: Mapped[ScanRun] = relationship(back_populates="errors")


class MetadataObservation(Base):
    __tablename__ = "metadata_observations"
    __table_args__ = (
        UniqueConstraint(
            "file_instance_id",
            "source_type",
            "observation_index",
            name="uq_metadata_observations_file_source_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    audio_asset_id: Mapped[str] = mapped_column(ForeignKey("audio_assets.id"), nullable=False, index=True)
    file_instance_id: Mapped[str] = mapped_column(ForeignKey("file_instances.id"), nullable=False, index=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    observation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_chunk_id: Mapped[str | None] = mapped_column(String(16))
    source_chunk_offset: Mapped[int | None] = mapped_column(BigInteger)
    source_frame_id: Mapped[str | None] = mapped_column(String(16))
    source_frame_offset: Mapped[int | None] = mapped_column(BigInteger)
    source_payload_offset: Mapped[int | None] = mapped_column(BigInteger)
    source_payload_size: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str | None] = mapped_column(Text)
    vendor: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    category_paths: Mapped[list | None] = mapped_column(json_type)
    attributes: Mapped[dict | None] = mapped_column(json_type)
    raw_payload: Mapped[dict | None] = mapped_column(json_type)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    audio_asset: Mapped[AudioAsset] = relationship(back_populates="metadata_observations")
    file_instance: Mapped[FileInstance] = relationship(back_populates="metadata_observations")
    scan_run: Mapped[ScanRun] = relationship(back_populates="metadata_observations")


class MetadataFileResult(Base):
    __tablename__ = "metadata_file_results"
    __table_args__ = (
        UniqueConstraint(
            "scan_run_id",
            "file_instance_id",
            name="uq_metadata_file_results_scan_run_file",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), nullable=False, index=True)
    file_instance_id: Mapped[str] = mapped_column(ForeignKey("file_instances.id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    scan_run: Mapped[ScanRun] = relationship(back_populates="metadata_file_results")
    file_instance: Mapped[FileInstance] = relationship(back_populates="metadata_file_results")
