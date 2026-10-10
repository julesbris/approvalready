"""Partner accounts (Milestone 14).

A partner is an organisation of kind ``PARTNER`` (its people are members with
``PARTNER_ADMIN`` or ``PARTNER_USER``; there is no separate partner user table). These
tables hold what the partner tells us and what staff checked:

* ``partner_organisation``: one per partner organisation, with its verification status,
  public contact details and description. Changed to ``ACTIVE``, ``REJECTED`` or
  ``SUSPENDED`` only by staff (audited).
* ``partner_application``: each submission (the first one, and any resubmission after a
  rejection), with a snapshot of what was submitted and the staff decision.
* ``partner_category``: the marketplace categories the partner wants to be referred for;
  staff approve each one. A category that requires a credential names the credential.
* ``partner_credential``: licences, insurance and accreditations; staff check each one.
* ``partner_service_area``: where the partner works (postcodes, council areas, states).

They are platform tables, like ``professional`` (Milestone 7): staff verify partners across
organisations and the lead engine (Milestone 15) matches across them, so they are guarded by
application authorisation, not row-level security. The partner's plan is an ordinary
``subscription`` of the partner organisation (Milestone 13) to a ``PARTNER_PLAN`` product.
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
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedByMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check
from app.modules.entities.models import AustralianState


class PartnerStatus(StrEnum):
    APPLIED = "APPLIED"  # submitted, waiting for staff
    UNDER_REVIEW = "UNDER_REVIEW"  # staff are checking it
    ACTIVE = "ACTIVE"  # approved; every partner has a plan (the free one counts)
    SUSPENDED = "SUSPENDED"  # stopped by staff; can be reinstated
    REJECTED = "REJECTED"  # not approved; the partner can fix things and resubmit


class PartnerApplicationStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PartnerCategoryStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PartnerCredentialKind(StrEnum):
    LICENCE = "LICENCE"
    PI_INSURANCE = "PI_INSURANCE"  # professional indemnity
    PL_INSURANCE = "PL_INSURANCE"  # public liability
    ACCREDITATION = "ACCREDITATION"


class PartnerCredentialStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ServiceAreaKind(StrEnum):
    POSTCODE = "POSTCODE"
    LGA = "LGA"  # a local government (council) area
    STATE = "STATE"  # a whole state or territory


class PartnerOrganisation(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "partner_organisation"
    __table_args__ = (
        UniqueConstraint("organisation_id"),
        enum_check("verification_status", PartnerStatus),
        CheckConstraint(
            "verification_status NOT IN ('REJECTED', 'SUSPENDED') OR status_reason IS NOT NULL",
            name="stopped_has_reason",
        ),
        Index("ix_partner_organisation_status", "verification_status", "submitted_at"),
        CheckConstraint(
            "max_open_leads IS NULL OR max_open_leads BETWEEN 1 AND 500",
            name="max_open_leads_range",
        ),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisation.id", ondelete="RESTRICT"), nullable=False
    )
    verification_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PartnerStatus.APPLIED
    )
    website: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(30))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    description: Mapped[str | None] = mapped_column(String(2000))
    # Why staff rejected or suspended the partner (shown to the partner).
    status_reason: Mapped[str | None] = mapped_column(String(1000))
    status_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The latest submission (first application or resubmission).
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Lead preferences (Milestone 15): stop new referrals for a while, and cap how many
    # claimed referrals can be in progress at once.
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    max_open_leads: Mapped[int | None] = mapped_column(Integer)


class PartnerApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "partner_application"
    __table_args__ = (
        enum_check("status", PartnerApplicationStatus),
        CheckConstraint(
            "status = 'SUBMITTED' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="decided_has_reviewer",
        ),
        Index("ix_partner_application_partner", "partner_organisation_id", "created_at"),
    )

    partner_organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_organisation.id", ondelete="CASCADE"),
        nullable=False,
    )
    # What the partner submitted, as it was then (details, categories, areas, credentials).
    submitted_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PartnerApplicationStatus.SUBMITTED
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_notes: Mapped[str | None] = mapped_column(String(1000))


class PartnerCredential(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "partner_credential"
    __table_args__ = (
        enum_check("kind", PartnerCredentialKind),
        enum_check("status", PartnerCredentialStatus),
        CheckConstraint(
            "status = 'UNVERIFIED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)",
            name="checked_has_checker",
        ),
        CheckConstraint("cover_cents IS NULL OR cover_cents > 0", name="cover_positive"),
        Index("ix_partner_credential_partner", "partner_organisation_id"),
    )

    partner_organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_organisation.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)
    number: Mapped[str] = mapped_column(String(100), nullable=False)
    # Insurance: the amount of cover.
    cover_cents: Mapped[int | None] = mapped_column(BigInteger)
    expires_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PartnerCredentialStatus.UNVERIFIED
    )
    notes: Mapped[str | None] = mapped_column(String(500))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PartnerCategory(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "partner_category"
    __table_args__ = (
        UniqueConstraint("partner_organisation_id", "category_id"),
        enum_check("status", PartnerCategoryStatus),
        CheckConstraint(
            "status = 'PENDING' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="decided_has_reviewer",
        ),
    )

    partner_organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_organisation.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("marketplace_category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PartnerCategoryStatus.PENDING
    )
    # The credential that covers this category (needed when the category requires one).
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_credential.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PartnerServiceArea(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "partner_service_area"
    __table_args__ = (
        UniqueConstraint("partner_organisation_id", "kind", "state", "value"),
        enum_check("kind", ServiceAreaKind),
        enum_check("state", AustralianState),
        CheckConstraint("kind <> 'POSTCODE' OR value ~ '^[0-9]{4}$'", name="postcode_format"),
        CheckConstraint("kind <> 'STATE' OR value = state", name="state_value"),
        Index("ix_partner_service_area_match", "kind", "state", "value"),
    )

    partner_organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_organisation.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    # A postcode ("4870"), a council area name ("Cairns") or the state code again.
    value: Mapped[str] = mapped_column(String(120), nullable=False)
