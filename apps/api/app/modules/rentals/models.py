"""RentReady (Milestone 11): a rental's listing, applications, tenancies, inspections and
maintenance. All tenant-owned; one rental per ``RENT`` project.

Applications record objective facts and missing documents only. There is no score, ranking
or automated selection: the owner or their agent decides, and the record shows what they
looked at.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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


class ListingStatus(StrEnum):
    NOT_LISTED = "NOT_LISTED"
    ADVERTISED = "ADVERTISED"
    LEASED = "LEASED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationStatus(StrEnum):
    RECEIVED = "RECEIVED"
    SHORTLISTED = "SHORTLISTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class RentPeriod(StrEnum):
    WEEK = "WEEK"
    FORTNIGHT = "FORTNIGHT"
    MONTH = "MONTH"


class TenancyStatus(StrEnum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class InspectionKind(StrEnum):
    ENTRY = "ENTRY"
    ROUTINE = "ROUTINE"
    EXIT = "EXIT"


class InspectionStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ItemCondition(StrEnum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    DAMAGED = "DAMAGED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MaintenancePriority(StrEnum):
    EMERGENCY = "EMERGENCY"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class MaintenanceStatus(StrEnum):
    REPORTED = "REPORTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class Rental(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """The rental property's details and its current listing."""

    __tablename__ = "rental_property"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("project_id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        enum_check("listing_status", ListingStatus),
        CheckConstraint("bedrooms IS NULL OR bedrooms BETWEEN 0 AND 30", name="bedrooms"),
        CheckConstraint("bathrooms IS NULL OR bathrooms BETWEEN 0 AND 30", name="bathrooms"),
        CheckConstraint("parking IS NULL OR parking BETWEEN 0 AND 30", name="parking"),
        CheckConstraint("rent_cents IS NULL OR rent_cents > 0", name="rent_positive"),
        # An advertised rental states a fixed rent (no rent bidding).
        CheckConstraint(
            "listing_status <> 'ADVERTISED' OR rent_cents IS NOT NULL", name="advertised_rent"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    bathrooms: Mapped[int | None] = mapped_column(Integer)
    parking: Mapped[int | None] = mapped_column(Integer)
    furnished: Mapped[bool | None] = mapped_column(Boolean)
    pets_considered: Mapped[bool | None] = mapped_column(Boolean)
    listing_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=ListingStatus.NOT_LISTED,
        server_default=ListingStatus.NOT_LISTED,
    )
    headline: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(4000))
    rent_cents: Mapped[int | None] = mapped_column(BigInteger)
    rent_period: Mapped[str] = mapped_column(
        Text, nullable=False, default=RentPeriod.WEEK, server_default=RentPeriod.WEEK
    )
    available_from: Mapped[date | None] = mapped_column(Date)


class TenantApplication(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "tenant_application"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("rental_id", "rental_property", ondelete="CASCADE"),
        enum_check("status", ApplicationStatus),
        CheckConstraint("jsonb_typeof(checks) = 'object'", name="checks_object"),
        CheckConstraint(
            "household_size IS NULL OR household_size BETWEEN 1 AND 30", name="household"
        ),
        Index("ix_tenant_application_rental_id", "rental_id"),
    )

    rental_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    applicant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    applicant_contact: Mapped[str | None] = mapped_column(String(200))
    household_size: Mapped[int | None] = mapped_column(Integer)
    preferred_start_on: Mapped[date | None] = mapped_column(Date)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=ApplicationStatus.RECEIVED,
        server_default=ApplicationStatus.RECEIVED,
    )
    # Which documents the applicant has provided, by check key (see ``APPLICATION_CHECKS``).
    checks: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(String(2000))


class Tenancy(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "tenancy"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("rental_id", "rental_property", ondelete="CASCADE"),
        tenant_fk("application_id", "tenant_application"),
        enum_check("rent_period", RentPeriod),
        CheckConstraint("rent_cents > 0", name="rent_positive"),
        CheckConstraint("bond_cents IS NULL OR bond_cents >= 0", name="bond"),
        CheckConstraint("end_on IS NULL OR end_on >= start_on", name="ends_after_start"),
        CheckConstraint("ended_on IS NULL OR ended_on >= start_on", name="ended_after_start"),
        Index("ix_tenancy_rental_id", "rental_id"),
    )

    rental_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    application_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tenant_names: Mapped[str] = mapped_column(String(300), nullable=False)
    tenant_contact: Mapped[str | None] = mapped_column(String(200))
    start_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Null for a periodic agreement.
    end_on: Mapped[date | None] = mapped_column(Date)
    rent_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rent_period: Mapped[str] = mapped_column(Text, nullable=False)
    bond_cents: Mapped[int | None] = mapped_column(BigInteger)
    bond_lodged_on: Mapped[date | None] = mapped_column(Date)
    bond_reference: Mapped[str | None] = mapped_column(String(60))
    last_rent_increase_on: Mapped[date | None] = mapped_column(Date)
    next_rent_review_on: Mapped[date | None] = mapped_column(Date)
    # When the tenancy actually ended (the tenant moved out); the status follows the dates.
    ended_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(2000))


class Inspection(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "inspection"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("rental_id", "rental_property", ondelete="CASCADE"),
        tenant_fk("tenancy_id", "tenancy"),
        enum_check("kind", InspectionKind),
        enum_check("status", InspectionStatus),
        CheckConstraint(
            "(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="completed_when_done"
        ),
        Index("ix_inspection_rental_id", "rental_id"),
    )

    rental_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenancy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=InspectionStatus.SCHEDULED,
        server_default=InspectionStatus.SCHEDULED,
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(2000))


class InspectionItem(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "inspection_item"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("inspection_id", "room", "item"),
        tenant_fk("inspection_id", "inspection", ondelete="CASCADE"),
        enum_check("condition", ItemCondition, nullable=True),
        Index("ix_inspection_item_inspection_id", "inspection_id", "position"),
    )

    inspection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    room: Mapped[str] = mapped_column(String(100), nullable=False)
    item: Mapped[str] = mapped_column(String(100), nullable=False)
    # Null until someone has looked at it.
    condition: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(String(1000))
    # Clean uploads on the same project (checked when set).
    photo_document_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )


class MaintenanceItem(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "maintenance_item"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("rental_id", "rental_property", ondelete="CASCADE"),
        tenant_fk("tenancy_id", "tenancy"),
        enum_check("priority", MaintenancePriority),
        enum_check("status", MaintenanceStatus),
        CheckConstraint("cost_cents IS NULL OR cost_cents >= 0", name="cost"),
        CheckConstraint("(status = 'DONE') = (resolved_on IS NOT NULL)", name="resolved_when_done"),
        Index("ix_maintenance_item_rental_id", "rental_id"),
    )

    rental_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenancy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(2000))
    priority: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=MaintenanceStatus.REPORTED,
        server_default=MaintenanceStatus.REPORTED,
    )
    reported_on: Mapped[date] = mapped_column(Date, nullable=False)
    reported_by: Mapped[str | None] = mapped_column(String(200))
    scheduled_on: Mapped[date | None] = mapped_column(Date)
    resolved_on: Mapped[date | None] = mapped_column(Date)
    tradesperson: Mapped[str | None] = mapped_column(String(200))
    cost_cents: Mapped[int | None] = mapped_column(BigInteger)
