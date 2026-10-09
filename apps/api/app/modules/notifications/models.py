"""Notifications (Milestone 11): what a member is told, in the app and by email.

A notification is tenant-owned: it is about something in one organisation (a reminder on a
project, a certificate, a grant round a project matched) and is listed with that
organisation active. Generated notifications carry a ``dedupe_key`` so a job that runs
twice never tells someone the same thing twice.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, UUIDPrimaryKeyMixin, enum_check, tenant_fk


class NotificationKind(StrEnum):
    REMINDER = "REMINDER"  # a project or system reminder fell due
    GRANT_ROUND = "GRANT_ROUND"  # a round of a program the project matched opens or closes
    SOURCES_DUE = "SOURCES_DUE"  # staff: source references due for review


class EmailStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class Notification(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "notification"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        enum_check("kind", NotificationKind),
        enum_check("email_status", EmailStatus),
        Index("ix_notification_recipient", "recipient_user_id", "organisation_id", "created_at"),
        Index(
            "uq_notification_dedupe",
            "organisation_id",
            "recipient_user_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )

    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(String(1000))
    # A path in the web app (``/projects/…``), never an absolute URL.
    link_path: Mapped[str | None] = mapped_column(String(300))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # The reminder that fired (no foreign key: the notification outlives it).
    reminder_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    email_status: Mapped[str] = mapped_column(
        Text, nullable=False, default=EmailStatus.NOT_REQUESTED
    )
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
