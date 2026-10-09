"""A project's checklists and their items (tenant-owned).

A checklist row is a copy of a reviewed definition taken when it was added to the project
(by an assessment finding that names it, or by the customer), with the definition's content
hash, so a later change to the file never rewrites a list someone is working through.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class ChecklistOrigin(StrEnum):
    RULE = "RULE"  # named by an assessment finding's outcome
    USER = "USER"  # added by the customer


class ItemStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProjectChecklist(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "project_checklist"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("project_id", "checklist_key"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("finding_id", "assessment_finding"),
        enum_check("origin", ChecklistOrigin),
        CheckConstraint("finding_id IS NULL OR origin = 'RULE'", name="finding_only_for_rule"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    checklist_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    definition_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    finding_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class ChecklistItem(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "checklist_item"
    __table_args__ = (
        UniqueConstraint("checklist_id", "item_key"),
        tenant_fk("checklist_id", "project_checklist", ondelete="CASCADE"),
        enum_check("status", ItemStatus),
        CheckConstraint("(status = 'OPEN') = (completed_at IS NULL)", name="completed_unless_open"),
        Index("ix_checklist_item_checklist_id", "checklist_id"),
    )

    checklist_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_key: Mapped[str] = mapped_column(String(60), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(1000))
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ItemStatus.OPEN, server_default=ItemStatus.OPEN
    )
    note: Mapped[str | None] = mapped_column(String(1000))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
