from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.billing.models import (
    EventStatus,
    InvoiceStatus,
    PaymentPurpose,
    PaymentStatus,
    PriceInterval,
    ProductKind,
    SubscriptionStatus,
)
from app.modules.projects.models import Vertical


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceOut(BaseModel):
    id: uuid.UUID
    amount_cents: int
    currency: str
    interval: PriceInterval
    active: bool
    stripe_price_id: str | None = None
    created_at: datetime
    deactivated_at: datetime | None = None


class FeatureLimitOut(BaseModel):
    key: str
    description: str
    limit: int | None = Field(description="Null: unlimited.")


class ProductOut(BaseModel):
    id: uuid.UUID
    key: str
    kind: ProductKind
    vertical: Vertical | None
    name: str
    description: str
    active: bool
    features: list[FeatureLimitOut]
    prices: list[PriceOut] = Field(description="Prices on sale (staff also see past prices).")


class CatalogueOut(BaseModel):
    enabled: bool = Field(description="Whether anything can be bought on this server.")
    products: list[ProductOut] = Field(description="Products with a price on sale.")


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    product_key: str
    product_name: str
    status: SubscriptionStatus
    amount_cents: int
    currency: str
    interval: PriceInterval
    current_period_end: datetime | None
    cancel_at_period_end: bool
    canceled_at: datetime | None
    past_due_since: datetime | None
    grace_ends_at: datetime | None = Field(
        description="Payment overdue: when the plan stops working if the card isn't updated."
    )
    gives_plan: bool = Field(description="Whether the plan's limits apply right now.")


class AllowanceOut(BaseModel):
    feature: str
    description: str
    limit: int | None = Field(description="Null: unlimited.")
    in_use: int
    enforced: bool = Field(description="Limits apply only once a plan that lifts them is on sale.")
    plan: str | None = Field(description="The plan it comes from; null for the free allowance.")


class PaymentOut(BaseModel):
    id: uuid.UUID
    purpose: PaymentPurpose
    product_name: str
    amount_cents: int
    currency: str
    status: PaymentStatus
    refunded_cents: int
    subject_type: str | None
    subject_id: uuid.UUID | None
    created_at: datetime
    paid_at: datetime | None


class InvoiceOut(BaseModel):
    id: uuid.UUID
    number: str | None
    status: InvoiceStatus
    amount_due_cents: int
    amount_paid_cents: int
    currency: str
    hosted_invoice_url: str | None
    invoice_pdf_url: str | None
    issued_at: datetime


class BillingOut(BaseModel):
    enabled: bool
    test_mode: bool = Field(description="Stripe test keys: no real money moves.")
    has_billing_account: bool
    plans: list[ProductOut] = Field(description="Plans on sale.")
    subscriptions: list[SubscriptionOut]
    allowances: list[AllowanceOut]
    payments: list[PaymentOut]
    invoices: list[InvoiceOut]


class PlanCheckoutIn(_In):
    price_id: uuid.UUID


class RedirectOut(BaseModel):
    url: str = Field(description="A Stripe page: send the browser there.")


# --- Staff ------------------------------------------------------------------------------

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
StripePriceId = Annotated[str, StringConstraints(pattern=r"^price_[A-Za-z0-9]{6,200}$")]


class PriceIn(_In):
    amount_cents: int = Field(gt=0, le=100_000_000, description="Including GST.")
    currency: Currency = "AUD"
    interval: PriceInterval
    stripe_price_id: StripePriceId | None = Field(
        default=None,
        description="Optional: a price made in the Stripe dashboard (same amount and interval).",
    )


class BillingStatusOut(BaseModel):
    enabled: bool
    test_mode: bool
    webhook_path: str
    webhook_events: list[str] = Field(description="Event types to send to the webhook.")


class StripeEventOut(BaseModel):
    id: uuid.UUID
    stripe_event_id: str
    type: str
    livemode: bool
    status: EventStatus
    attempts: int
    error: str | None
    organisation_id: uuid.UUID | None
    stripe_created_at: datetime
    received_at: datetime
    processed_at: datetime | None
