"""Project plans (tenant-owned): a paid, online tracker for one project, built from its
checklist (``plans.checklist``), with a due date, an owner, notes and files on every step.

A plan is one per project. While its payment is waiting it is ``PAYMENT_PENDING`` and its
items exist but aren't shown; once paid (or straight away when the plan isn't on sale) it is
``ACTIVE``. ``sections`` keeps each part's heading, fees, contacts and sources as they were
when the plan was built or last refreshed; the steps are rows in ``project_plan_item``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedByMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    tenant_fk,
)


class PlanStatus(StrEnum):
    PAYMENT_PENDING = "PAYMENT_PENDING"
    ACTIVE = "ACTIVE"


class PlanItemKind(StrEnum):
    PREPARE = "PREPARE"  # something to have ready
    STEP = "STEP"  # a step in an approval's process
    DOCUMENT = "DOCUMENT"  # a document to gather
    TASK = "TASK"  # a project task (kept in step with it)
    CHECK = "CHECK"  # a project checklist item (kept in step with it)
    FOLLOW_UP = "FOLLOW_UP"  # call or chase a partner
    CUSTOM = "CUSTOM"  # added by the customer


class PlanItemStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProjectPlan(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "project_plan"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("project_id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("payment_id", "payment"),
        enum_check("status", PlanStatus),
        CheckConstraint(
            "(status = 'ACTIVE') = (activated_at IS NOT NULL)", name="activated_when_active"
        ),
        CheckConstraint(
            "status <> 'PAYMENT_PENDING' OR payment_id IS NOT NULL", name="pending_has_payment"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # The assessment the plan was built (or last refreshed) from.
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Activated without paying (the plan wasn't on sale at the time).
    complimentary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class ProjectPlanItem(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "project_plan_item"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("plan_id", "source_key"),
        tenant_fk("plan_id", "project_plan", ondelete="CASCADE"),
        enum_check("kind", PlanItemKind),
        enum_check("status", PlanItemStatus),
        CheckConstraint("(status = 'OPEN') = (completed_at IS NULL)", name="completed_unless_open"),
        CheckConstraint(
            "source_key IS NOT NULL OR kind IN ('FOLLOW_UP', 'CUSTOM')", name="source_for_built"
        ),
        Index("ix_project_plan_item_plan_id", "plan_id"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # The checklist step this came from (``plans.checklist.Step.key``); null for the
    # customer's own steps and follow-ups.
    source_key: Mapped[str | None] = mapped_column(String(200))
    section_key: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(2000))
    timeframe: Mapped[str | None] = mapped_column(String(600))
    cost: Mapped[str | None] = mapped_column(String(600))
    link_url: Mapped[str | None] = mapped_column(String(2000))
    link_label: Mapped[str | None] = mapped_column(String(600))
    # A follow-up's partner (shown with their contact details).
    partner_organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_organisation.id", ondelete="SET NULL")
    )
    owner: Mapped[str | None] = mapped_column(String(120))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=PlanItemStatus.OPEN, server_default=PlanItemStatus.OPEN
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(2000))
    # Uploads from the project's documents (checked when attached; deleted ones drop out).
    document_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
