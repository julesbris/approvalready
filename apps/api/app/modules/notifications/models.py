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

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, UUIDPrimaryKeyMixin, enum_check, tenant_fk


class NotificationKind(StrEnum):
    REMINDER = "REMINDER"  # a project or system reminder fell due
    GRANT_ROUND = "GRANT_ROUND"  # a round of a program the project matched opens or closes
    SOURCES_DUE = "SOURCES_DUE"  # staff: source references due for review
    LEAD_OFFERED = "LEAD_OFFERED"  # partner: a referral was offered to them
    LEAD_CLAIMED = "LEAD_CLAIMED"  # customer: a partner accepted their referral
    OPS_ALERT = "OPS_ALERT"  # platform admins: backups, background jobs or disk need attention
    QUOTE_RECEIVED = "QUOTE_RECEIVED"  # customer: a partner sent them a quote
    QUOTE_ANSWERED = "QUOTE_ANSWERED"  # partner: the customer accepted or declined a quote
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"  # customer or partner: a message about a referral


class NotificationCategory(StrEnum):
    """What a member chooses about (Milestone 21): one or more notification kinds."""

    REMINDERS = "REMINDERS"
    GRANT_ROUNDS = "GRANT_ROUNDS"
    REFERRALS = "REFERRALS"
    SOURCE_REVIEWS = "SOURCE_REVIEWS"  # staff only


# Kinds missing here (ops alerts) can't be turned off: they are how platform admins hear
# that backups or background jobs have stopped.
CATEGORY_OF: dict[NotificationKind, NotificationCategory] = {
    NotificationKind.REMINDER: NotificationCategory.REMINDERS,
    NotificationKind.GRANT_ROUND: NotificationCategory.GRANT_ROUNDS,
    NotificationKind.LEAD_OFFERED: NotificationCategory.REFERRALS,
    NotificationKind.LEAD_CLAIMED: NotificationCategory.REFERRALS,
    NotificationKind.QUOTE_RECEIVED: NotificationCategory.REFERRALS,
    NotificationKind.QUOTE_ANSWERED: NotificationCategory.REFERRALS,
    NotificationKind.MESSAGE_RECEIVED: NotificationCategory.REFERRALS,
    NotificationKind.SOURCES_DUE: NotificationCategory.SOURCE_REVIEWS,
}


class NotificationChannel(StrEnum):
    ALL = "ALL"  # in the app and by email (the default)
    IN_APP = "IN_APP"  # in the app only
    OFF = "OFF"  # not at all


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


class NotificationPreference(Base):
    """A member's choice for one category (Milestone 21). Belongs to the person, not an
    organisation, so it applies in every organisation they are in; no row means ``ALL``.
    Unsubscribe links in emails set ``IN_APP``."""

    __tablename__ = "notification_preference"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "category"),
        enum_check("category", NotificationCategory),
        enum_check("channel", NotificationChannel),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
