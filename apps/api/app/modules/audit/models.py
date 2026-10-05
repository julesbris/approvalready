"""Append-only audit log with a SHA-256 hash chain.

Rows cannot be updated, deleted or truncated (database triggers, see migration 0002).
Each row's ``hash`` covers its own content plus the previous row's hash, so removing or
altering a row (e.g. by someone with direct database access who disables triggers) breaks
the chain and is detected by ``app.modules.audit.service.verify_chain``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, LargeBinary, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_event_organisation_id_seq", "organisation_id", "seq"),
        Index("ix_audit_event_actor_user_id_seq", "actor_user_id", "seq"),
    )

    # Chain order. Inserts are serialised by an advisory lock, so seq order == chain order.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # No foreign keys: the audit trail must outlive the rows it describes.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
