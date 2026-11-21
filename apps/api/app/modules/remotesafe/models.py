"""RemoteSafe (Stage 1): journey plans for remote workers, their risk assessments, critical
controls and approvals. Every table is tenant-owned (row-level security on
``organisation_id``) and child rows use composite tenant foreign keys.

Stage 1 stores planned places only (names and optional coordinates the planner typed). It
collects no live location: check-in tracking and device positions are later milestones.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
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


class RsRole(StrEnum):
    WORKER = "WORKER"
    SUPERVISOR = "SUPERVISOR"
    MONITOR = "MONITOR"
    WHS_ADMIN = "WHS_ADMIN"


class Tier(StrEnum):
    STARTER = "STARTER"
    PROFESSIONAL = "PROFESSIONAL"
    ENTERPRISE = "ENTERPRISE"


class JourneyStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Remoteness(StrEnum):
    UNKNOWN = "UNKNOWN"
    NOT_REMOTE = "NOT_REMOTE"
    REMOTE = "REMOTE"
    VERY_REMOTE = "VERY_REMOTE"


class RoadSurface(StrEnum):
    UNKNOWN = "UNKNOWN"
    SEALED = "SEALED"
    MIXED = "MIXED"
    UNSEALED = "UNSEALED"


class Coverage(StrEnum):
    UNKNOWN = "UNKNOWN"
    GOOD = "GOOD"
    PATCHY = "PATCHY"
    NONE = "NONE"


class ClosureStatus(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    NONE_KNOWN = "NONE_KNOWN"
    RESTRICTED = "RESTRICTED"
    CONFIRMED_CLOSED = "CONFIRMED_CLOSED"


class ControlStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXCEPTION = "EXCEPTION"


class Rating(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RsSettings(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """RemoteSafe switched on for an organisation: its tier and risk policy overrides."""

    __tablename__ = "rs_settings"
    __table_args__ = (
        UniqueConstraint("organisation_id"),
        enum_check("tier", Tier),
        CheckConstraint("jsonb_typeof(policy) = 'object'", name="policy_object"),
    )

    tier: Mapped[str] = mapped_column(
        Text, nullable=False, default=Tier.STARTER, server_default=Tier.STARTER
    )
    default_timezone: Mapped[str] = mapped_column(
        String(40), nullable=False, default="Australia/Brisbane"
    )
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class RsMemberRole(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """A RemoteSafe role held by a member of the organisation. Product roles live here, not
    in the platform role catalogue, so RemoteSafe never widens ApprovalReady permissions."""

    __tablename__ = "rs_member_role"
    __table_args__ = (
        UniqueConstraint("organisation_id", "user_id", "role"),
        enum_check("role", RsRole),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)


class RsVehicle(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "rs_vehicle"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        CheckConstraint(
            "fuel_range_km IS NULL OR fuel_range_km BETWEEN 1 AND 5000", name="fuel_range"
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    registration: Mapped[str] = mapped_column(String(20), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(60), nullable=False)
    fuel_range_km: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(String(1000))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RsJourney(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "rs_journey"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("organisation_id", "reference"),
        tenant_fk("vehicle_id", "rs_vehicle"),
        enum_check("status", JourneyStatus),
        enum_check("remoteness", Remoteness),
        enum_check("risk_outcome", Rating, nullable=True),
        enum_check("approved_outcome", Rating, nullable=True),
        CheckConstraint("occupants BETWEEN 1 AND 60", name="occupants"),
        CheckConstraint("arrives_at > departs_at", name="arrives_after_departs"),
        CheckConstraint("returns_at IS NULL OR returns_at >= arrives_at", name="returns_after"),
        CheckConstraint(
            "checkin_interval_minutes IS NULL OR checkin_interval_minutes BETWEEN 15 AND 1440",
            name="checkin_interval",
        ),
        CheckConstraint("jsonb_typeof(emergency_contacts) = 'array'", name="contacts_array"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index("ix_rs_journey_worker", "organisation_id", "worker_user_id"),
        Index("ix_rs_journey_supervisor", "organisation_id", "supervisor_user_id"),
        Index("ix_rs_journey_status", "organisation_id", "status"),
    )

    reference: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=JourneyStatus.DRAFT, server_default=JourneyStatus.DRAFT
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # People. Users must be members of this organisation (checked in the service).
    worker_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    supervisor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    monitor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    team: Mapped[str | None] = mapped_column(String(120))
    worker_phone: Mapped[str | None] = mapped_column(String(40))
    # What and where.
    purpose: Mapped[str] = mapped_column(String(1000), nullable=False)
    activities: Mapped[str | None] = mapped_column(String(2000))
    origin: Mapped[str] = mapped_column(String(200), nullable=False)
    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    remoteness: Mapped[str] = mapped_column(
        Text, nullable=False, default=Remoteness.UNKNOWN, server_default=Remoteness.UNKNOWN
    )
    return_journey: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # When (UTC; shown in ``timezone`` unless a leg says otherwise).
    timezone: Mapped[str] = mapped_column(String(40), nullable=False)
    departs_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    returns_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Vehicle: from the register, or described when it isn't a fleet vehicle.
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    vehicle_description: Mapped[str | None] = mapped_column(String(200))
    vehicle_registration: Mapped[str | None] = mapped_column(String(20))
    occupants: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Communications carried.
    comms_mobile: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    comms_uhf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    comms_sat_phone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    comms_sat_messenger: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    comms_notes: Mapped[str | None] = mapped_column(String(1000))
    # [{name, relationship, phone, escalation_order}]
    emergency_contacts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    checkin_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    alternative_route: Mapped[str | None] = mapped_column(String(2000))
    contingency_plan: Mapped[str | None] = mapped_column(String(2000))
    # What the planner checked (Stage 1 fetches no weather data itself).
    weather_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weather_source: Mapped[str | None] = mapped_column(String(200))
    weather_warnings: Mapped[str | None] = mapped_column(String(1000))
    # Assessment and approval. The current assessment is the latest run of the engine (no
    # foreign key: assessments reference the journey, and a cycle would complicate deletes).
    current_assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    risk_outcome: Mapped[str | None] = mapped_column(Text)
    approved_revision: Mapped[int | None] = mapped_column(Integer)
    approved_outcome: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    critical_alternative_process: Mapped[str | None] = mapped_column(String(2000))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RsRouteLeg(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One leg of the route. Surface, coverage, crossings and closures are what the planner
    recorded and where they got it; Stage 1 doesn't look them up."""

    __tablename__ = "rs_route_leg"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("journey_id", "position"),
        tenant_fk("journey_id", "rs_journey", ondelete="CASCADE"),
        enum_check("road_surface", RoadSurface),
        enum_check("mobile_coverage", Coverage),
        enum_check("closure_status", ClosureStatus),
        CheckConstraint("arrives_at > departs_at", name="arrives_after_departs"),
        CheckConstraint("crossings BETWEEN 0 AND 500", name="crossings"),
        CheckConstraint(
            "distance_km IS NULL OR (distance_km > 0 AND distance_km < 10000)", name="distance"
        ),
        CheckConstraint(
            "(origin_lat IS NULL OR origin_lat BETWEEN -45 AND -9) AND "
            "(destination_lat IS NULL OR destination_lat BETWEEN -45 AND -9) AND "
            "(origin_lng IS NULL OR origin_lng BETWEEN 112 AND 155) AND "
            "(destination_lng IS NULL OR destination_lng BETWEEN 112 AND 155)",
            name="in_australia",
        ),
    )

    journey_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(200), nullable=False)
    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    origin_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    origin_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    destination_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    destination_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(String(40), nullable=False)
    departs_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(7, 1))
    road_surface: Mapped[str] = mapped_column(Text, nullable=False, default=RoadSurface.UNKNOWN)
    mobile_coverage: Mapped[str] = mapped_column(Text, nullable=False, default=Coverage.UNKNOWN)
    crossings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closure_status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ClosureStatus.NOT_CHECKED
    )
    closure_source: Mapped[str | None] = mapped_column(String(200))
    closure_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(1000))


class RsCheckinPlan(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A planned check-in. Planning only: receiving and acknowledging check-ins, and raising
    the alarm when one is missed, is Milestone 4 and is not live yet."""

    __tablename__ = "rs_checkin_plan"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("journey_id", "position"),
        tenant_fk("journey_id", "rs_journey", ondelete="CASCADE"),
        CheckConstraint(
            "method IN ('PHONE_CALL', 'SMS', 'SATELLITE_MESSAGE', 'SATELLITE_CALL', 'UHF', 'APP')",
            name="method_valid",
        ),
    )

    journey_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(Text, nullable=False)


class RsRiskAssessment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """One run of the rules engine over one revision (append-only history)."""

    __tablename__ = "rs_risk_assessment"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("journey_id", "rs_journey", ondelete="CASCADE"),
        enum_check("outcome", Rating),
        Index("ix_rs_risk_assessment_journey", "journey_id", "created_at"),
    )

    journey_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    library_version: Mapped[str] = mapped_column(String(20), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # [{key, reason, evidence}]
    stop_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )


class RsHazardFinding(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "rs_hazard_finding"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("assessment_id", "hazard_key"),
        tenant_fk("assessment_id", "rs_risk_assessment", ondelete="CASCADE"),
        enum_check("initial_rating", Rating),
        enum_check("residual_rating", Rating),
        CheckConstraint(
            "likelihood BETWEEN 1 AND 5 AND consequence BETWEEN 1 AND 5 AND "
            "residual_likelihood BETWEEN 1 AND 5",
            name="scales",
        ),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    hazard_key: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    likelihood: Mapped[int] = mapped_column(Integer, nullable=False)
    consequence: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_score: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_rating: Mapped[str] = mapped_column(Text, nullable=False)
    controls: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    residual_likelihood: Mapped[int] = mapped_column(Integer, nullable=False)
    residual_score: Mapped[int] = mapped_column(Integer, nullable=False)
    residual_rating: Mapped[str] = mapped_column(Text, nullable=False)
    responsible: Mapped[str] = mapped_column(Text, nullable=False)


class RsControlCheck(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One pre-departure control for a journey. A mandatory control must be DONE, or carry
    an exception recorded by a WHS administrator, before the journey can start."""

    __tablename__ = "rs_control_check"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("journey_id", "control_key"),
        tenant_fk("journey_id", "rs_journey", ondelete="CASCADE"),
        enum_check("status", ControlStatus),
        CheckConstraint(
            "status = 'PENDING' OR (completed_by IS NOT NULL AND completed_at IS NOT NULL)",
            name="who_and_when",
        ),
        CheckConstraint(
            "status <> 'EXCEPTION' OR (exception_reason IS NOT NULL AND exception_by IS NOT NULL)",
            name="exception_recorded",
        ),
        CheckConstraint("NOT (mandatory AND status = 'NOT_APPLICABLE')", name="mandatory_applies"),
    )

    journey_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    control_key: Mapped[str] = mapped_column(String(60), nullable=False)
    control_group: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_by: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ControlStatus.PENDING, server_default=ControlStatus.PENDING
    )
    note: Mapped[str | None] = mapped_column(String(1000))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_revision: Mapped[int | None] = mapped_column(Integer)
    exception_reason: Mapped[str | None] = mapped_column(String(1000))
    exception_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    # Clean uploads in the documents module, once evidence attachments arrive (Milestone 6).
    evidence_document_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )


class RsJourneyEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """The journey's audit trail: every status change, edit, check and approval
    (append-only: the application role can't change or delete it)."""

    __tablename__ = "rs_journey_event"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("journey_id", "rs_journey", ondelete="CASCADE"),
        Index("ix_rs_journey_event_journey", "journey_id", "occurred_at"),
    )

    journey_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(2000))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RsJourneyRevision(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """A snapshot of the plan as submitted or as changed after approval (append-only)."""

    __tablename__ = "rs_journey_revision"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("journey_id", "revision"),
        tenant_fk("journey_id", "rs_journey", ondelete="CASCADE"),
    )

    journey_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changed_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
