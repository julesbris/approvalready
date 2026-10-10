"""Email outbox (Milestone 20): every email the application sends, queued for the worker.

A request (or a background job) adds a row and returns at once; the worker hands it to the
email provider and retries with back-off when the provider is unavailable, so a slow or
failing mail server never slows sign-up or loses a password reset.

The message itself (address, subject, text, links) is sealed with AES-GCM (``app.core.crypto``,
purpose ``email_outbox``) because it can carry sign-in links, and it is erased once the email
is sent or given up on. What stays is the kind, status, attempts and error, for
``/admin/ops``. Platform data, not tenant data: no row-level security.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, Integer, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, enum_check


class OutboxStatus(StrEnum):
    PENDING = "PENDING"  # waiting for its first or next attempt
    SENT = "SENT"  # accepted by the email provider
    FAILED = "FAILED"  # refused for good, or still failing after every retry


class OutboxEmail(Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        enum_check("status", OutboxStatus),
        Index(
            "ix_email_outbox_due",
            "next_attempt_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_email_outbox_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Machine-readable kind (``auth.verify_email``); never the address or the content.
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    # The sealed message; null once it is sent or has failed for good.
    sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
