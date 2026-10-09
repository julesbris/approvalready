"""Projects (one per customer goal, in one product vertical), their status history, tasks and
reminders. All tenant-owned."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedByMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    tenant_fk,
)


class Vertical(StrEnum):
    PLANNING = "PLANNING"
    VESSEL = "VESSEL"
    BUSINESS = "BUSINESS"
    GRANT = "GRANT"
    SELL = "SELL"
    RENT = "RENT"


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    ASSESSED = "ASSESSED"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TaskSource(StrEnum):
    USER = "USER"
    RULE = "RULE"  # generated from an assessment finding (Milestone 4)
    REVIEWER = "REVIEWER"  # added by a professional reviewer (Milestone 7)


class ReminderChannel(StrEnum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"


class ReminderStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class Recurrence(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class Project(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "project"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("property_id", "property"),
        tenant_fk("vessel_id", "vessel"),
        tenant_fk("business_profile_id", "business_profile"),
        enum_check("vertical", Vertical),
        enum_check("status", ProjectStatus),
        Index("ix_project_organisation_id_updated_at", "organisation_id", "updated_at"),
    )

    vertical: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ProjectStatus.DRAFT, server_default=ProjectStatus.DRAFT
    )
    # Short human-readable reference for support conversations and documents, e.g. PLN-7K3F9Q.
    reference_code: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    business_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class ProjectStatusEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Append-only status history (the app role may only insert and read)."""

    __tablename__ = "project_status_event"
    __table_args__ = (
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        enum_check("from_status", ProjectStatus, nullable=True),
        enum_check("to_status", ProjectStatus),
        Index("ix_project_status_event_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Task(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "task"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("finding_id", "assessment_finding"),
        enum_check("status", TaskStatus),
        enum_check("source", TaskSource),
        CheckConstraint("finding_id IS NULL OR source = 'RULE'", name="finding_only_for_rule"),
        CheckConstraint(
            "(status = 'DONE') = (completed_at IS NOT NULL)", name="completed_when_done"
        ),
        Index("ix_task_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=TaskStatus.OPEN, server_default=TaskStatus.OPEN
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default=TaskSource.USER, server_default=TaskSource.USER
    )
    # The assessment finding that suggested this task (source RULE).
    finding_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    due_on: Mapped[date | None] = mapped_column(Date)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reminder(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """A scheduled nudge about a project (or one of its tasks), delivered by the scheduler as
    a notification (and an email for the ``EMAIL`` channel) once ``fires_at`` passes.

    System reminders (Milestone 11) are kept in step with the dates they come from (a lease
    end, a certificate expiry): ``source_key`` names that date, e.g.
    ``tenancy:<id>:end:60``, and they may have no project (a vessel certificate)."""

    __tablename__ = "reminder"
    __table_args__ = (
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("task_id", "task", ondelete="CASCADE"),
        enum_check("channel", ReminderChannel),
        enum_check("status", ReminderStatus),
        enum_check("recurrence", Recurrence, nullable=True),
        CheckConstraint(
            "project_id IS NOT NULL OR source_key IS NOT NULL", name="project_or_system"
        ),
        Index("ix_reminder_project_id", "project_id"),
        Index("ix_reminder_source_key", "organisation_id", "source_key"),
        Index(
            "ix_reminder_due",
            "fires_at",
            postgresql_where=text("status = 'SCHEDULED'"),
        ),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    fires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=ReminderStatus.SCHEDULED,
        server_default=ReminderStatus.SCHEDULED,
    )
    recurrence: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_key: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(String(1000))
    link_path: Mapped[str | None] = mapped_column(String(300))
