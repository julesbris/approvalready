"""SellReady (Milestone 11): a sale's lifecycle, its document vault and disclosure, offers
and enquiries. All tenant-owned; one sale per ``SELL`` project.

What a seller must disclose comes from the rules (``property_qld`` and later packs) and the
checklists they add; this module records what the seller did: which documents are in the
vault, which of them went into the disclosure, when and to whom it was given.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

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
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
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


class SaleStatus(StrEnum):
    PREPARING = "PREPARING"
    READY_TO_LIST = "READY_TO_LIST"
    LISTED = "LISTED"
    UNDER_OFFER = "UNDER_OFFER"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class VaultCategory(StrEnum):
    DISCLOSURE_STATEMENT = "DISCLOSURE_STATEMENT"
    TITLE_SEARCH = "TITLE_SEARCH"
    REGISTERED_PLAN = "REGISTERED_PLAN"
    BODY_CORPORATE = "BODY_CORPORATE"
    POOL_SAFETY = "POOL_SAFETY"
    SMOKE_ALARMS = "SMOKE_ALARMS"
    BUILDING_APPROVAL = "BUILDING_APPROVAL"
    RATES_AND_WATER = "RATES_AND_WATER"
    PLANNING_AND_ZONING = "PLANNING_AND_ZONING"
    TENANCY = "TENANCY"
    CONTRACT = "CONTRACT"
    OTHER = "OTHER"


class OfferStatus(StrEnum):
    RECEIVED = "RECEIVED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    LAPSED = "LAPSED"


class EnquiryStatus(StrEnum):
    NEW = "NEW"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"


class Sale(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "sale_project"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("project_id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        enum_check("status", SaleStatus),
        CheckConstraint("asking_price_cents IS NULL OR asking_price_cents >= 0", name="price"),
        CheckConstraint(
            "(disclosure_given_on IS NULL) = (disclosure_given_to IS NULL)",
            name="disclosure_given_together",
        ),
        CheckConstraint(
            "settlement_on IS NULL OR contract_on IS NULL OR settlement_on >= contract_on",
            name="settles_after_contract",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=SaleStatus.PREPARING, server_default=SaleStatus.PREPARING
    )
    asking_price_cents: Mapped[int | None] = mapped_column(BigInteger)
    price_guide: Mapped[str | None] = mapped_column(String(200))
    listed_on: Mapped[date | None] = mapped_column(Date)
    contract_on: Mapped[date | None] = mapped_column(Date)
    settlement_on: Mapped[date | None] = mapped_column(Date)
    # Disclosure: given once, to a named buyer, with the vault documents it contained.
    disclosure_given_on: Mapped[date | None] = mapped_column(Date)
    disclosure_given_to: Mapped[str | None] = mapped_column(String(200))
    disclosure_document_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    # Why no disclosure is needed (the rules or a professional said so), instead of giving one.
    disclosure_not_needed_note: Mapped[str | None] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(String(2000))


class SaleDocument(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """A file in the sale's vault: one of the project's clean uploads, filed by category."""

    __tablename__ = "sale_document"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("sale_id", "uploaded_document_id"),
        tenant_fk("sale_id", "sale_project", ondelete="CASCADE"),
        tenant_fk("uploaded_document_id", "uploaded_document", ondelete="CASCADE"),
        enum_check("category", VaultCategory),
        Index("ix_sale_document_sale_id", "sale_id"),
    )

    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    uploaded_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    in_disclosure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class SaleOffer(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "sale_offer"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("sale_id", "sale_project", ondelete="CASCADE"),
        enum_check("status", OfferStatus),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint(
            "settlement_days IS NULL OR settlement_days BETWEEN 0 AND 730", name="settlement_days"
        ),
        Index("ix_sale_offer_sale_id", "sale_id"),
        Index(
            "uq_sale_offer_one_accepted",
            "sale_id",
            unique=True,
            postgresql_where=text("status = 'ACCEPTED' AND deleted_at IS NULL"),
        ),
    )

    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    buyer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    buyer_contact: Mapped[str | None] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deposit_cents: Mapped[int | None] = mapped_column(BigInteger)
    subject_to_finance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    subject_to_inspection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    settlement_days: Mapped[int | None] = mapped_column(Integer)
    conditions: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=OfferStatus.RECEIVED, server_default=OfferStatus.RECEIVED
    )
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SaleEnquiry(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "sale_enquiry"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("sale_id", "sale_project", ondelete="CASCADE"),
        enum_check("status", EnquiryStatus),
        Index("ix_sale_enquiry_sale_id", "sale_id"),
    )

    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(200))
    channel: Mapped[str | None] = mapped_column(String(60))
    message: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=EnquiryStatus.NEW, server_default=EnquiryStatus.NEW
    )
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000))
