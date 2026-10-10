"""Operations (Milestone 17): the record of backups and restore checks.

``backup_run`` is written by the ``backup`` service (infrastructure/backup/backup.sh), which
connects as the database owner on the internal network: one row per nightly backup and one
per restore check. The application role may only read it and record the off-site copy that
the worker makes (``offsite_*``). Platform data, not tenant data: no row-level security.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, enum_check


class BackupKind(StrEnum):
    BACKUP = "BACKUP"  # a database dump and an archive of uploaded files
    RESTORE_CHECK = "RESTORE_CHECK"  # the latest dump restored into a scratch database


class BackupStatus(StrEnum):
    OK = "OK"
    FAILED = "FAILED"


class OffsiteStatus(StrEnum):
    PENDING = "PENDING"  # waiting for the worker (or for BACKUP_S3_BUCKET to be set)
    UPLOADED = "UPLOADED"
    FAILED = "FAILED"  # the last attempt failed; retried until the files are pruned
    MISSING = "MISSING"  # the files were pruned before they could be copied


class BackupRun(Base):
    __tablename__ = "backup_run"
    __table_args__ = (
        enum_check("kind", BackupKind),
        enum_check("status", BackupStatus),
        enum_check("offsite_status", OffsiteStatus, nullable=True),
        Index("ix_backup_run_kind_started", "kind", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # File names inside the backups volume (no directories).
    database_file: Mapped[str | None] = mapped_column(Text)
    database_bytes: Mapped[int | None] = mapped_column(BigInteger)
    database_sha256: Mapped[str | None] = mapped_column(Text)
    uploads_file: Mapped[str | None] = mapped_column(Text)
    uploads_bytes: Mapped[int | None] = mapped_column(BigInteger)
    uploads_sha256: Mapped[str | None] = mapped_column(Text)
    # What failed, or what a restore check found (tables, rows, schema version).
    detail: Mapped[str | None] = mapped_column(Text)
    # Off-site copy (worker); null on restore checks and failed backups.
    offsite_status: Mapped[str | None] = mapped_column(Text)
    offsite_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offsite_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    offsite_error: Mapped[str | None] = mapped_column(Text)
