"""The lead engine (Milestone 15): referral consent, leads, matching, claims, lead fees and
partner credits.

A customer asks to be introduced to partners from an assessment's "who can help"
categories. Nothing reaches a partner until the customer agrees to a versioned consent text
naming the categories, how many partners may contact them and which contact details they
release. Then:

* ``referral_consent`` (tenant row of the customer): what they agreed to, the exact text
  version, the contact details they chose to share and, later, when they withdrew.
* ``lead`` (platform): one per consented category. Only whitelisted, non-identifying facts
  (category, area, timing, the customer's own summary, the approvals their assessment
  identified). Partners see these through ``LeadPublicView`` and nothing else.
* ``lead_contact`` (platform): the released contact details, kept apart from ``lead`` so no
  partner-facing query touches them. Copied into ``lead_claim`` for each partner who claims
  and deleted once the lead closes.
* ``lead_match`` (platform): one per eligible partner, with the explainable score and its
  status. Offered in waves (``policy.py``), so the best-ranked partners see it first.
* ``lead_claim`` (platform): a partner accepted the lead; the fee charged and the contact
  details released to them.
* ``lead_status_event`` (platform, append-only): every match status change.
* ``lead_price`` (platform): what a claim costs in a category beyond the plan's included
  leads, set by staff. Never changed: a new price replaces the old one.
* ``credit_ledger_entry`` (tenant row of the partner, append-only): credits bought, given,
  charged for leads and refunded, with the running balance.
* ``lead_quote`` (platform, Milestone 23): a written quote a partner who accepted the lead
  sends the customer. Its content never changes once sent; a revision is a new version and
  the old one is superseded. The customer accepts or declines it.
* ``lead_message`` (platform, Milestone 26): messages between the customer and a partner who
  accepted their referral. Never edited or deleted; only when the other side read it is
  recorded, once.

Leads are platform rows guarded by the API (partners match across customers), like the
partner tables; the customer's consent and the partner's credits are tenant rows with RLS.
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
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
from app.modules.entities.models import AustralianState


class ConsentPurpose(StrEnum):
    PARTNER_REFERRAL = "PARTNER_REFERRAL"


class ReleasableField(StrEnum):
    NAME = "name"
    EMAIL = "email"
    PHONE = "phone"
    SITE_ADDRESS = "site_address"


class Timing(StrEnum):
    ASAP = "ASAP"
    WITHIN_3_MONTHS = "WITHIN_3_MONTHS"
    LATER = "LATER"
    RESEARCHING = "RESEARCHING"


class LeadStatus(StrEnum):
    OPEN = "OPEN"  # being offered to partners
    FILLED = "FILLED"  # as many partners as the customer allowed have claimed it
    EXPIRED = "EXPIRED"  # the offer period ended
    WITHDRAWN = "WITHDRAWN"  # the customer withdrew their consent


class LeadMatchStatus(StrEnum):
    MATCHED = "MATCHED"  # eligible; offered once ``offered_at`` is set
    VIEWED = "VIEWED"
    CLAIMED = "CLAIMED"
    CONTACTED = "CONTACTED"
    QUOTED = "QUOTED"
    WON = "WON"
    LOST = "LOST"
    EXPIRED = "EXPIRED"  # the lead closed before this partner claimed it
    DECLINED = "DECLINED"


# A match the partner can still claim or decline (once offered).
OPEN_MATCH = (LeadMatchStatus.MATCHED, LeadMatchStatus.VIEWED)
# Claimed and not finished: counts towards ``max_open_leads``.
WORKING = (LeadMatchStatus.CLAIMED, LeadMatchStatus.CONTACTED, LeadMatchStatus.QUOTED)


class QuoteStatus(StrEnum):
    SENT = "SENT"  # waiting for the customer (expired once ``valid_until`` has passed)
    SUPERSEDED = "SUPERSEDED"  # the partner sent a revised version
    WITHDRAWN = "WITHDRAWN"  # the partner took it back
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class MessageSender(StrEnum):
    CUSTOMER = "CUSTOMER"
    PARTNER = "PARTNER"


class GstTreatment(StrEnum):
    INCLUDED = "INCLUDED"  # the prices include GST
    EXCLUDED = "EXCLUDED"  # GST is added on top
    NOT_REGISTERED = "NOT_REGISTERED"  # the partner isn't registered for GST


class CreditKind(StrEnum):
    PURCHASE = "PURCHASE"  # credits bought (a paid Stripe checkout)
    PROMO = "PROMO"  # given by staff
    LEAD_CHARGE = "LEAD_CHARGE"  # a claimed lead's fee
    REFUND = "REFUND"  # a lead fee given back by staff
    ADJUSTMENT = "ADJUSTMENT"  # staff correction (either way)


class ConsentTextVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "consent_text_version"
    __table_args__ = (
        UniqueConstraint("purpose", "version"),
        UniqueConstraint("purpose", "content_hash"),
        enum_check("purpose", ConsentPurpose),
        CheckConstraint("version > 0", name="version_positive"),
    )

    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReferralConsent(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "referral_consent"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("assessment_id", "assessment", ondelete="CASCADE"),
        enum_check("state", AustralianState),
        enum_check("timing", Timing),
        CheckConstraint("cardinality(categories) BETWEEN 1 AND 5", name="categories_count"),
        CheckConstraint("max_providers BETWEEN 1 AND 3", name="max_providers_range"),
        CheckConstraint(
            "fields_released <@ ARRAY['name','email','phone','site_address']::text[] "
            "AND cardinality(fields_released) > 0",
            name="fields_released_valid",
        ),
        CheckConstraint("postcode ~ '^[0-9]{4}$'", name="postcode_format"),
        CheckConstraint(
            "withdrawn_at IS NULL OR withdrawn_by IS NOT NULL", name="withdrawn_has_actor"
        ),
        Index("ix_referral_consent_project", "organisation_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    consent_text_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_text_version.id", ondelete="RESTRICT"),
        nullable=False,
    )
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    max_providers: Mapped[int] = mapped_column(Integer, nullable=False)
    fields_released: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    # The released details as the customer entered them (only the fields released).
    contact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    suburb: Mapped[str | None] = mapped_column(String(100))
    lga: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(Text, nullable=False)
    postcode: Mapped[str] = mapped_column(String(4), nullable=False)
    timing: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(600))
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lead"
    __table_args__ = (
        UniqueConstraint("referral_consent_id", "category_id"),
        enum_check("status", LeadStatus),
        enum_check("state", AustralianState),
        enum_check("timing", Timing),
        CheckConstraint("max_claims BETWEEN 1 AND 3", name="max_claims_range"),
        CheckConstraint(
            "claimed_count >= 0 AND claimed_count <= max_claims", name="claimed_in_range"
        ),
        CheckConstraint("status = 'OPEN' OR closed_at IS NOT NULL", name="closed_has_time"),
        Index("ix_lead_status", "status", "expires_at"),
        Index("ix_lead_organisation", "organisation_id", "project_id"),
    )

    # The customer's organisation and project (the consent is that organisation's row).
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    referral_consent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("referral_consent.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("marketplace_category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    vertical: Mapped[str] = mapped_column(Text, nullable=False)
    suburb: Mapped[str | None] = mapped_column(String(100))
    lga: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(Text, nullable=False)
    postcode: Mapped[str] = mapped_column(String(4), nullable=False)
    timing: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(600))
    # Approval titles from the customer's assessment (rule output, no answers).
    requirements: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    max_claims: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # The release policy in force when the lead was made (``policy.py``).
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=LeadStatus.OPEN)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_wave_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LeadContact(Base):
    __tablename__ = "lead_contact"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), primary_key=True
    )
    contact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fields_released: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)


class LeadMatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lead_match"
    __table_args__ = (
        UniqueConstraint("lead_id", "partner_organisation_id"),
        enum_check("status", LeadMatchStatus),
        CheckConstraint(
            "status IN ('MATCHED', 'EXPIRED') OR offered_at IS NOT NULL",
            name="acted_on_was_offered",
        ),
        Index("ix_lead_match_partner", "partner_organisation_id", "status", "offered_at"),
        Index("ix_lead_match_lead", "lead_id", "rank"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    partner_organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_organisation.id", ondelete="CASCADE"),
        nullable=False,
    )
    score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    # Each ranking factor: {"factor", "points", "max", "why"} (shown to the partner and staff).
    score_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # Lower is better; ties broken fairly per lead (see ``matching.py``).
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # Paid placement. Nothing sets it yet; when something does, customers see "Sponsored".
    is_promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=LeadMatchStatus.MATCHED
    )
    offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the partner claimed or declined.
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(500))


class LeadClaim(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "lead_claim"
    __table_args__ = (
        UniqueConstraint("lead_match_id"),
        UniqueConstraint("lead_id", "partner_organisation_id"),
        CheckConstraint("fee_cents >= 0", name="fee_not_negative"),
        CheckConstraint("NOT included OR fee_cents = 0", name="included_is_free"),
        Index("ix_lead_claim_partner", "partner_organisation_id", "created_at"),
    )

    lead_match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead_match.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    partner_organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_organisation.id", ondelete="CASCADE"),
        nullable=False,
    )
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    # One of the plan's included leads this month (no fee).
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fee_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credit_ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    released_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    released_contact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Why the partner could claim: plan, allowance used, price, balance.
    entitlement_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LeadStatusEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "lead_status_event"
    __table_args__ = (
        enum_check("from_status", LeadMatchStatus, nullable=True),
        enum_check("to_status", LeadMatchStatus),
        Index("ix_lead_status_event_match", "lead_match_id", "occurred_at"),
    )

    lead_match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead_match.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LeadPrice(UUIDPrimaryKeyMixin, CreatedByMixin, Base):
    __tablename__ = "lead_price"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint("currency = 'AUD'", name="currency_aud"),
        Index(
            "uq_lead_price_active_category",
            "category_id",
            unique=True,
            postgresql_where=text("deactivated_at IS NULL"),
        ),
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("marketplace_category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="AUD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreditLedgerEntry(UUIDPrimaryKeyMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "credit_ledger_entry"
    __table_args__ = (
        # One entry per position: two writers racing for the same balance can't both commit.
        UniqueConstraint("organisation_id", "seq"),
        UniqueConstraint("organisation_id", "id"),
        enum_check("kind", CreditKind),
        CheckConstraint("delta_cents <> 0", name="delta_not_zero"),
        CheckConstraint("balance_after_cents >= 0", name="balance_not_negative"),
        CheckConstraint("seq > 0", name="seq_positive"),
    )

    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    delta_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(40))
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LeadQuote(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "lead_quote"
    __table_args__ = (
        UniqueConstraint("lead_match_id", "version"),
        enum_check("status", QuoteStatus),
        enum_check("gst", GstTreatment),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("total_cents >= 0", name="total_not_negative"),
        CheckConstraint("status = 'SENT' OR responded_at IS NOT NULL", name="answered_has_time"),
        # One quote waiting for the customer per partner and lead.
        Index(
            "uq_lead_quote_sent_match",
            "lead_match_id",
            unique=True,
            postgresql_where=text("status = 'SENT'"),
        ),
        Index("ix_lead_quote_lead", "lead_id", "created_at"),
    )

    lead_match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead_match.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    partner_organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_organisation.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=QuoteStatus.SENT)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"description", "amount_cents"}], in the partner's order.
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gst: Mapped[str] = mapped_column(Text, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    start_estimate: Mapped[str | None] = mapped_column(String(200))
    terms: Mapped[str | None] = mapped_column(Text)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # When it stopped waiting: superseded, withdrawn, accepted or declined.
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    response_note: Mapped[str | None] = mapped_column(String(500))


class LeadMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "lead_message"
    __table_args__ = (
        enum_check("sender", MessageSender),
        CheckConstraint("char_length(btrim(body)) > 0", name="body_not_blank"),
        CheckConstraint("char_length(body) <= 4000", name="body_length"),
        Index("ix_lead_message_match", "lead_match_id", "created_at"),
    )

    lead_match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead_match.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    partner_organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_organisation.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender: Mapped[str] = mapped_column(Text, nullable=False)
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # When someone on the other side first opened the conversation after it arrived.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
