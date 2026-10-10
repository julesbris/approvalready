"""Billing (Milestone 13): the catalogue, prices, Stripe customers, payments,
subscriptions, invoices and the webhook event store.

* ``product``, ``feature``, ``product_feature``: platform data from the reviewed
  ``catalogue.json`` (synced on migrate). What a product is and which limits it lifts is
  code-reviewed; what it costs is not.
* ``price``: platform data that staff add at ``/admin/billing``. No price is ever written in
  code. A price's amount, currency and interval never change (trigger): a new amount is a
  new price, so a payment always points at what was actually charged.
* ``billing_customer``, ``payment``, ``subscription``, ``invoice_reference`` (tenant): the
  organisation's side, written only by the server. Payment and subscription state comes
  from verified Stripe webhooks, never from the browser. No card data is stored, ever.
* ``stripe_event`` (platform): every verified webhook, once (unique event id), with how it
  was processed. Replays and duplicates are recognised by the event id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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

from app.db.base import (
    Base,
    CreatedByMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
)
from app.modules.projects.models import Vertical


class ProductKind(StrEnum):
    ONE_OFF = "ONE_OFF"  # a one-off purchase (a report, a pack)
    SAAS = "SAAS"  # a customer subscription plan (e.g. RentReady Manage)
    REVIEW = "REVIEW"  # a professional review of one assessment
    PARTNER_PLAN = "PARTNER_PLAN"  # Milestone 14
    LEAD = "LEAD"  # Milestone 15
    CREDIT_PACK = "CREDIT_PACK"  # Milestone 15


class PriceInterval(StrEnum):
    ONE_TIME = "ONE_TIME"
    MONTH = "MONTH"
    YEAR = "YEAR"


class PaymentPurpose(StrEnum):
    REVIEW = "REVIEW"
    PRODUCT = "PRODUCT"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"  # waiting for the customer to pay at Stripe
    PAID = "PAID"
    FAILED = "FAILED"  # a delayed payment method (e.g. BECS direct debit) failed
    CANCELLED = "CANCELLED"  # what it paid for was cancelled before payment
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class SubscriptionStatus(StrEnum):
    """Stripe's subscription statuses, upper-cased."""

    INCOMPLETE = "INCOMPLETE"
    INCOMPLETE_EXPIRED = "INCOMPLETE_EXPIRED"
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"
    UNPAID = "UNPAID"
    PAUSED = "PAUSED"


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"
    UNCOLLECTIBLE = "UNCOLLECTIBLE"


class EventStatus(StrEnum):
    RECEIVED = "RECEIVED"  # stored, waiting for the worker
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"  # a type we don't act on, or nothing of ours
    FAILED = "FAILED"  # retried by the worker; staff can retry from /admin/billing


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("key"),
        enum_check("kind", ProductKind),
        enum_check("vertical", Vertical, nullable=True),
    )

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    vertical: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class Feature(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A limit a plan can lift (e.g. ``rent.properties.max``)."""

    __tablename__ = "feature"
    __table_args__ = (
        UniqueConstraint("key"),
        CheckConstraint("default_limit IS NULL OR default_limit >= 0", name="limit_not_negative"),
    )

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    # What an organisation without a plan that includes the feature gets. Null: no limit.
    default_limit: Mapped[int | None] = mapped_column(Integer)
    # An inactive feature (removed from the catalogue) limits nothing.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class ProductFeature(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_feature"
    __table_args__ = (
        UniqueConstraint("product_id", "feature_id"),
        CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="limit_not_negative"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    feature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feature.id", ondelete="CASCADE"), nullable=False
    )
    # Null: unlimited.
    limit_value: Mapped[int | None] = mapped_column(Integer)


class Price(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "price"
    __table_args__ = (
        enum_check("interval", PriceInterval),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_code"),
        Index("ix_price_product_id", "product_id"),
        # At most one price on sale per product and interval.
        Index(
            "uq_price_one_active",
            "product_id",
            "interval",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product.id", ondelete="RESTRICT"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="AUD")
    interval: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional: a price made in the Stripe dashboard. Without one, checkout sends the amount.
    stripe_price_id: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingCustomer(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """The organisation's Stripe customer (one per organisation)."""

    __tablename__ = "billing_customer"
    __table_args__ = (UniqueConstraint("organisation_id"), UniqueConstraint("stripe_customer_id"))

    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """A one-off charge: what it is for, what it costs, and where it stands at Stripe."""

    __tablename__ = "payment"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        enum_check("purpose", PaymentPurpose),
        enum_check("status", PaymentStatus),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint(
            "refunded_cents >= 0 AND refunded_cents <= amount_cents", name="refund_in_range"
        ),
        CheckConstraint("status <> 'PAID' OR paid_at IS NOT NULL", name="paid_has_time"),
        Index("ix_payment_subject_id", "subject_id"),
        Index("ix_payment_stripe_payment_intent_id", "stripe_payment_intent_id"),
    )

    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product.id", ondelete="RESTRICT"), nullable=False
    )
    price_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price.id", ondelete="RESTRICT"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # What it pays for, e.g. a review request.
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=PaymentStatus.PENDING)
    # The latest checkout session made for it (a new one replaces an abandoned one).
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255))
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255))
    refunded_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """The organisation's plan, mirrored from Stripe (webhooks only)."""

    __tablename__ = "subscription"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("stripe_subscription_id"),
        enum_check("status", SubscriptionStatus),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product.id", ondelete="RESTRICT"), nullable=False
    )
    price_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price.id", ondelete="RESTRICT"), nullable=False
    )
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    past_due_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When Stripe created the event last applied: older events arriving late are skipped.
    stripe_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvoiceReference(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A Stripe invoice's number, amounts, status and links. Stripe keeps the invoice."""

    __tablename__ = "invoice_reference"
    __table_args__ = (
        UniqueConstraint("stripe_invoice_id"),
        enum_check("status", InvoiceStatus),
        Index("ix_invoice_reference_issued_at", "organisation_id", "issued_at"),
    )

    stripe_invoice_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    number: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    amount_due_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_paid_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    hosted_invoice_url: Mapped[str | None] = mapped_column(String(2000))
    invoice_pdf_url: Mapped[str | None] = mapped_column(String(2000))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stripe_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StripeEvent(UUIDPrimaryKeyMixin, Base):
    """A verified webhook, stored once. The event itself never changes (trigger); only how
    far processing got does."""

    __tablename__ = "stripe_event"
    __table_args__ = (
        UniqueConstraint("stripe_event_id"),
        enum_check("status", EventStatus),
        Index("ix_stripe_event_received_at", "received_at"),
        Index("ix_stripe_event_status", "status", "received_at"),
    )

    stripe_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stripe_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisation.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=EventStatus.RECEIVED)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
