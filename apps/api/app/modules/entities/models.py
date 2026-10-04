"""Customer entities shared across products: addresses, properties, vessels, businesses.

All tables are tenant-owned (row-level security on ``organisation_id``). Facts that need
provenance (zoning, overlays) are not stored here until the regulatory sources module can
cite them (Milestone 4/5): a property only holds what the customer told us.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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


class AustralianState(StrEnum):
    NSW = "NSW"
    VIC = "VIC"
    QLD = "QLD"
    SA = "SA"
    WA = "WA"
    TAS = "TAS"
    NT = "NT"
    ACT = "ACT"


class AddressSource(StrEnum):
    USER = "USER"  # typed by the customer
    PROVIDER = "PROVIDER"  # resolved by an address/geocoding provider (interface, later)


class OwnershipRole(StrEnum):
    OWNER = "OWNER"
    AUTHORISED_AGENT = "AUTHORISED_AGENT"
    LANDLORD = "LANDLORD"
    PROSPECTIVE_BUYER = "PROSPECTIVE_BUYER"
    LESSEE = "LESSEE"


class VesselType(StrEnum):
    MOTOR = "MOTOR"
    SAIL = "SAIL"
    PERSONAL_WATERCRAFT = "PERSONAL_WATERCRAFT"
    PADDLE = "PADDLE"
    BARGE = "BARGE"
    OTHER = "OTHER"


class Propulsion(StrEnum):
    INBOARD = "INBOARD"
    OUTBOARD = "OUTBOARD"
    STERNDRIVE = "STERNDRIVE"
    JET = "JET"
    SAIL = "SAIL"
    SAIL_AUXILIARY = "SAIL_AUXILIARY"
    MANUAL = "MANUAL"
    OTHER = "OTHER"


class EntityType(StrEnum):
    SOLE_TRADER = "SOLE_TRADER"
    PARTNERSHIP = "PARTNERSHIP"
    COMPANY = "COMPANY"
    TRUST = "TRUST"
    INCORPORATED_ASSOCIATION = "INCORPORATED_ASSOCIATION"
    COOPERATIVE = "COOPERATIVE"
    OTHER = "OTHER"


class EmployeeBand(StrEnum):
    NONE = "NONE"
    E1_4 = "1_4"
    E5_19 = "5_19"
    E20_199 = "20_199"
    E200_PLUS = "200_PLUS"


class TurnoverBand(StrEnum):
    UNDER_75K = "UNDER_75K"
    FROM_75K_TO_2M = "75K_2M"
    FROM_2M_TO_10M = "2M_10M"
    FROM_10M_TO_50M = "10M_50M"
    OVER_50M = "OVER_50M"


class Address(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "address"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        enum_check("state", AustralianState),
        enum_check("source", AddressSource),
        CheckConstraint("postcode ~ '^[0-9]{4}$'", name="postcode_format"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude_range"
        ),
    )

    line1: Mapped[str] = mapped_column(String(200), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(200))
    suburb: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    postcode: Mapped[str] = mapped_column(String(4), nullable=False)
    lga_code: Mapped[str | None] = mapped_column(String(20))
    gnaf_pid: Mapped[str | None] = mapped_column(String(30))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default=AddressSource.USER, server_default=AddressSource.USER
    )


class Property(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "property"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("address_id", "address"),
        CheckConstraint("land_area_m2 IS NULL OR land_area_m2 > 0", name="land_area_positive"),
    )

    address_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lot_plan: Mapped[str | None] = mapped_column(String(50))
    title_reference: Mapped[str | None] = mapped_column(String(50))
    land_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class PropertyOwnership(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """How the organisation relates to the property. ``verified_at`` stays empty until there
    is evidence (documents arrive in Milestone 6); a self-declared role is just that."""

    __tablename__ = "property_ownership"
    __table_args__ = (
        UniqueConstraint("organisation_id", "property_id", "role"),
        tenant_fk("property_id", "property", ondelete="CASCADE"),
        enum_check("role", OwnershipRole),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[date | None] = mapped_column(Date)


class Vessel(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "vessel"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        enum_check("vessel_type", VesselType),
        enum_check("propulsion", Propulsion, nullable=True),
        CheckConstraint("length_m IS NULL OR (length_m > 0 AND length_m <= 500)", name="length"),
        CheckConstraint("max_passengers IS NULL OR max_passengers >= 0", name="passengers"),
        CheckConstraint("crew IS NULL OR crew >= 0", name="crew"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vessel_type: Mapped[str] = mapped_column(Text, nullable=False)
    length_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    hull_material: Mapped[str | None] = mapped_column(String(60))
    propulsion: Mapped[str | None] = mapped_column(Text)
    max_passengers: Mapped[int | None] = mapped_column(Integer)
    crew: Mapped[int | None] = mapped_column(Integer)
    # Free text as described by the customer. The AMSA operational area class is a sourced
    # determination, not something we infer here.
    operating_area: Mapped[str | None] = mapped_column(String(200))
    activity: Mapped[str | None] = mapped_column(String(200))
    uvi: Mapped[str | None] = mapped_column(String(20))
    hin: Mapped[str | None] = mapped_column(String(20))
    state_rego: Mapped[str | None] = mapped_column(String(20))


class BusinessProfile(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "business_profile"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("address_id", "address"),
        enum_check("entity_type", EntityType),
        CheckConstraint("abn IS NULL OR abn ~ '^[0-9]{11}$'", name="abn_format"),
        CheckConstraint("acn IS NULL OR acn ~ '^[0-9]{9}$'", name="acn_format"),
        CheckConstraint("anzsic_code IS NULL OR anzsic_code ~ '^[0-9]{1,4}$'", name="anzsic"),
        enum_check("employee_band", EmployeeBand, nullable=True),
        enum_check("turnover_band", TurnoverBand, nullable=True),
    )

    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(200))
    abn: Mapped[str | None] = mapped_column(String(11))
    acn: Mapped[str | None] = mapped_column(String(9))
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    gst_registered: Mapped[bool | None] = mapped_column(Boolean)
    established_on: Mapped[date | None] = mapped_column(Date)
    employee_band: Mapped[str | None] = mapped_column(Text)
    turnover_band: Mapped[str | None] = mapped_column(Text)
    anzsic_code: Mapped[str | None] = mapped_column(String(4))
    address_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
