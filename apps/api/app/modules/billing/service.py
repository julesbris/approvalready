"""Billing: the catalogue and prices, checkout and the customer portal, entitlements.

The browser never decides what has been paid for. Checkout and the portal are Stripe's
hosted pages; this module only creates them and reads back what Stripe's signed webhooks
recorded (``webhooks.py``).
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.billing.models import (
    BillingCustomer,
    Feature,
    InvoiceReference,
    InvoiceStatus,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    Price,
    PriceInterval,
    Product,
    ProductFeature,
    ProductKind,
    Subscription,
    SubscriptionStatus,
)
from app.modules.billing.stripe import StripeClient, StripeError
from app.modules.identity.models import AppUser
from app.modules.tenancy.models import Organisation, OrganisationKind

# A plan that has fallen past due keeps working this long while Stripe retries the card.
PAST_DUE_GRACE = timedelta(days=7)
# Subscriptions that still hold (or are about to hold) a plan: one at a time per organisation.
LIVE_SUBSCRIPTION = (
    SubscriptionStatus.INCOMPLETE,
    SubscriptionStatus.TRIALING,
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.PAST_DUE,
    SubscriptionStatus.UNPAID,
    SubscriptionStatus.PAUSED,
)
STRIPE_INTERVAL = {PriceInterval.MONTH: "month", PriceInterval.YEAR: "year"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def payments_unavailable(exc: StripeError) -> ApiError:
    return ApiError(
        502, "payments_unavailable", "We couldn't reach our payment provider. Try again shortly."
    )


# --- Catalogue and prices ---------------------------------------------------------------


@dataclass(frozen=True)
class FeatureLimit:
    key: str
    description: str
    limit: int | None


@dataclass(frozen=True)
class ProductView:
    product: Product
    features: list[FeatureLimit]
    prices: list[Price]  # active prices only, unless asked for all


async def catalogue(
    db: AsyncSession, *, include_inactive: bool = False, kind: str | None = None
) -> list[ProductView]:
    query = select(Product).order_by(Product.sort_order, Product.key)
    if not include_inactive:
        query = query.where(Product.active.is_(True))
    if kind is not None:
        query = query.where(Product.kind == kind)
    products = list((await db.execute(query)).scalars())
    if not products:
        return []
    ids = [p.id for p in products]
    limits: dict[uuid.UUID, list[FeatureLimit]] = {i: [] for i in ids}
    for pf, f in await db.execute(
        select(ProductFeature, Feature)
        .join(Feature, Feature.id == ProductFeature.feature_id)
        .where(ProductFeature.product_id.in_(ids))
        .order_by(Feature.key)
    ):
        limits[pf.product_id].append(FeatureLimit(f.key, f.description, pf.limit_value))
    price_query = select(Price).where(Price.product_id.in_(ids))
    if not include_inactive:
        price_query = price_query.where(Price.active.is_(True))
    prices: dict[uuid.UUID, list[Price]] = {i: [] for i in ids}
    for price in (
        await db.execute(price_query.order_by(Price.active.desc(), Price.created_at.desc()))
    ).scalars():
        prices[price.product_id].append(price)
    return [ProductView(p, limits[p.id], prices[p.id]) for p in products]


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise not_found("Product")
    return product


async def get_price(db: AsyncSession, price_id: uuid.UUID, *, lock: bool = False) -> Price:
    query = select(Price).where(Price.id == price_id)
    if lock:
        query = query.with_for_update()
    price = (await db.execute(query)).scalar_one_or_none()
    if price is None:
        raise not_found("Price")
    return price


async def review_price(db: AsyncSession, vertical: str) -> tuple[Product, Price] | None:
    """The price of a professional review for a vertical, when one is on sale."""
    row = (
        await db.execute(
            select(Product, Price)
            .join(Price, Price.product_id == Product.id)
            .where(
                Product.key == f"review.{vertical.lower()}",
                Product.kind == ProductKind.REVIEW,
                Product.active.is_(True),
                Price.active.is_(True),
                Price.interval == PriceInterval.ONE_TIME,
            )
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None


def _check_interval(product: Product, interval: PriceInterval) -> None:
    recurring = product.kind in (ProductKind.SAAS, ProductKind.PARTNER_PLAN)
    if recurring and interval == PriceInterval.ONE_TIME:
        raise ApiError(422, "interval_required", "A plan is charged monthly or yearly.")
    if not recurring and interval != PriceInterval.ONE_TIME:
        raise ApiError(422, "one_time_only", "This product is charged once, not monthly.")


async def create_price(
    db: AsyncSession,
    product: Product,
    *,
    amount_cents: int,
    currency: str,
    interval: PriceInterval,
    stripe_price_id: str | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Price:
    """Put a product on sale at a price. The price it replaces (same product and interval)
    stops being offered; payments already made keep pointing at it."""
    if not product.active:
        raise ApiError(409, "product_inactive", "This product is no longer in the catalogue.")
    _check_interval(product, interval)
    replaced = (
        await db.execute(
            select(Price)
            .where(
                Price.product_id == product.id,
                Price.interval == interval,
                Price.active.is_(True),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if replaced is not None:
        replaced.active = False
        replaced.deactivated_at = utcnow()
        await db.flush()
    price = Price(
        product_id=product.id,
        amount_cents=amount_cents,
        currency=currency,
        interval=interval,
        stripe_price_id=stripe_price_id,
        active=True,
        created_by=actor_id,
    )
    db.add(price)
    await db.flush()
    await audit.record(
        db,
        "billing.price_created",
        actor_user_id=actor_id,
        target_type="price",
        target_id=price.id,
        meta=meta,
        details={
            "product": product.key,
            "amount_cents": amount_cents,
            "currency": currency,
            "interval": str(interval),
        }
        | ({"replaced": str(replaced.id)} if replaced else {}),
    )
    return price


async def deactivate_price(
    db: AsyncSession, price: Price, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    if not price.active:
        return
    price.active = False
    price.deactivated_at = utcnow()
    await db.flush()
    await audit.record(
        db,
        "billing.price_deactivated",
        actor_user_id=actor_id,
        target_type="price",
        target_id=price.id,
        meta=meta,
    )


# --- Entitlements -----------------------------------------------------------------------


@dataclass(frozen=True)
class Allowance:
    feature: str
    description: str
    limit: int | None  # None: unlimited
    enforced: bool  # False while no plan that lifts the limit is on sale
    plan: str | None  # the product it comes from, None for the free allowance


def subscription_counts(sub: Subscription, now: datetime) -> bool:
    """Whether a subscription gives its plan right now. A past-due plan keeps working for a
    grace period while Stripe retries the payment."""
    if sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING):
        return True
    return (
        sub.status == SubscriptionStatus.PAST_DUE
        and sub.past_due_since is not None
        and now < sub.past_due_since + PAST_DUE_GRACE
    )


async def _limit_on_sale(db: AsyncSession, feature_id: uuid.UUID) -> bool:
    """A limit only applies while customers can buy their way past it."""
    found = (
        await db.execute(
            select(Price.id)
            .join(Product, Product.id == Price.product_id)
            .join(ProductFeature, ProductFeature.product_id == Product.id)
            .where(
                ProductFeature.feature_id == feature_id,
                Product.active.is_(True),
                Price.active.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return found is not None


async def allowance(db: AsyncSession, organisation_id: uuid.UUID, key: str) -> Allowance:
    """What the organisation may use of a feature: the best of its current plans, else the
    free allowance. Needs the organisation bound (its subscriptions are tenant rows)."""
    feature = (await db.execute(select(Feature).where(Feature.key == key))).scalar_one_or_none()
    if feature is None or not feature.active:
        return Allowance(key, feature.description if feature else key, None, False, None)
    now = utcnow()
    plans: list[tuple[int | None, str]] = [
        (pf.limit_value, product.name)
        for sub, pf, product in await db.execute(
            select(Subscription, ProductFeature, Product)
            .join(ProductFeature, ProductFeature.product_id == Subscription.product_id)
            .join(Product, Product.id == Subscription.product_id)
            .where(
                Subscription.organisation_id == organisation_id,
                ProductFeature.feature_id == feature.id,
            )
        )
        if subscription_counts(sub, now)
    ]
    enforced = await _limit_on_sale(db, feature.id)
    limit, plan = feature.default_limit, None
    for value, name in plans:
        if limit is None:
            break
        if value is None or value > limit:
            limit, plan = value, name
    return Allowance(key, feature.description, limit, enforced, plan)


async def require_allowance(
    db: AsyncSession, organisation_id: uuid.UUID, key: str, *, in_use: int
) -> None:
    """Refuse to add one more of something when the organisation's plan is used up."""
    a = await allowance(db, organisation_id, key)
    if a.enforced and a.limit is not None and in_use >= a.limit:
        raise ApiError(
            402,
            "plan_limit",
            f"Your plan includes {a.limit} {a.description.lower()}. "
            "Upgrade your plan in Billing to add more.",
        )


# --- Customers, checkout and the portal --------------------------------------------------


async def get_customer(db: AsyncSession, organisation_id: uuid.UUID) -> BillingCustomer | None:
    return (
        await db.execute(
            select(BillingCustomer).where(BillingCustomer.organisation_id == organisation_id)
        )
    ).scalar_one_or_none()


async def ensure_customer(
    db: AsyncSession, stripe: StripeClient, organisation: Organisation, user: AppUser
) -> BillingCustomer:
    """The organisation's Stripe customer, created on first checkout. Stripe's idempotency
    key makes a retried or racing creation return the same customer."""
    existing = await get_customer(db, organisation.id)
    if existing is not None:
        return existing
    try:
        customer_id = await stripe.create_customer(
            name=organisation.name,
            email=str(user.email),
            metadata={"organisation_id": str(organisation.id)},
            idempotency_key=f"customer-{organisation.id}",
        )
    except StripeError as exc:
        raise payments_unavailable(exc) from exc
    try:
        async with db.begin_nested():
            row = BillingCustomer(
                organisation_id=organisation.id,
                stripe_customer_id=customer_id,
                created_by=user.id,
            )
            db.add(row)
    except IntegrityError:
        row = await get_customer(db, organisation.id)  # type: ignore[assignment]
        assert row is not None
    return row


def _price_line(product: Product, price: Price) -> dict[str, object]:
    if price.stripe_price_id:
        return {"price": price.stripe_price_id, "quantity": 1}
    data: dict[str, object] = {
        "currency": price.currency.lower(),
        "unit_amount": price.amount_cents,
        "product_data": {"name": product.name, "metadata": {"product": product.key}},
    }
    if price.interval != PriceInterval.ONE_TIME:
        data["recurring"] = {"interval": STRIPE_INTERVAL[PriceInterval(price.interval)]}
    return {"price_data": data, "quantity": 1}


async def checkout_for_payment(
    db: AsyncSession,
    stripe: StripeClient,
    *,
    organisation: Organisation,
    user: AppUser,
    payment: Payment,
    success_url: str,
    cancel_url: str,
) -> str:
    """A Stripe Checkout page for a pending payment. Asking again replaces the earlier page
    (which is expired at Stripe, so only one can be paid)."""
    if payment.status != PaymentStatus.PENDING:
        raise ApiError(409, "payment_not_pending", "This has already been paid or cancelled.")
    product = await get_product(db, payment.product_id)
    price = await get_price(db, payment.price_id)
    customer = await ensure_customer(db, stripe, organisation, user)
    metadata = {
        "organisation_id": str(organisation.id),
        "payment_id": str(payment.id),
        "purpose": payment.purpose,
    }
    previous = payment.stripe_checkout_session_id
    try:
        session = await stripe.create_checkout_session(
            {
                "mode": "payment",
                "customer": customer.stripe_customer_id,
                "client_reference_id": str(payment.id),
                "line_items": [_price_line(product, price)],
                "metadata": metadata,
                "payment_intent_data": {"metadata": metadata},
                "invoice_creation": {"enabled": True},
                "success_url": success_url,
                "cancel_url": cancel_url,
            },
            idempotency_key=f"checkout-{payment.id}-{uuid.uuid4()}",
        )
    except StripeError as exc:
        raise payments_unavailable(exc) from exc
    payment.stripe_checkout_session_id = session.id
    await db.flush()
    if previous:
        await close_checkout(stripe, previous)
    return session.url


async def start_payment(
    db: AsyncSession,
    *,
    organisation_id: uuid.UUID,
    purpose: PaymentPurpose,
    product: Product,
    price: Price,
    subject_type: str | None,
    subject_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> Payment:
    payment = Payment(
        organisation_id=organisation_id,
        purpose=purpose,
        product_id=product.id,
        price_id=price.id,
        amount_cents=price.amount_cents,
        currency=price.currency,
        subject_type=subject_type,
        subject_id=subject_id,
        status=PaymentStatus.PENDING,
        created_by=actor_id,
    )
    db.add(payment)
    await db.flush()
    return payment


async def get_payment(
    db: AsyncSession, organisation_id: uuid.UUID, payment_id: uuid.UUID, *, lock: bool = False
) -> Payment:
    query = select(Payment).where(
        Payment.organisation_id == organisation_id, Payment.id == payment_id
    )
    if lock:
        query = query.with_for_update()
    payment = (await db.execute(query)).scalar_one_or_none()
    if payment is None:
        raise not_found("Payment")
    return payment


async def cancel_payment(db: AsyncSession, payment: Payment) -> None:
    """What the payment was for was cancelled before it was paid. Close its checkout page
    with ``close_checkout`` after committing."""
    if payment.status != PaymentStatus.PENDING:
        return
    payment.status = PaymentStatus.CANCELLED
    await db.flush()


async def close_checkout(stripe: StripeClient, session_id: str) -> None:
    """Best effort: a page already paid or expired can't be closed, and a payment made on it
    anyway is recorded and flagged for a refund."""
    with contextlib.suppress(StripeError):
        await stripe.expire_checkout_session(session_id)


async def live_subscription(db: AsyncSession, organisation_id: uuid.UUID) -> Subscription | None:
    return (
        await db.execute(
            select(Subscription)
            .where(
                Subscription.organisation_id == organisation_id,
                Subscription.status.in_(LIVE_SUBSCRIPTION),
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def plan_kind(organisation: Organisation) -> ProductKind:
    """Partner organisations buy partner plans; everyone else customer plans."""
    if organisation.kind == OrganisationKind.PARTNER:
        return ProductKind.PARTNER_PLAN
    return ProductKind.SAAS


def grace_ends_at(sub: Subscription) -> datetime | None:
    """When a past-due plan stops working if the card isn't updated."""
    if sub.status != SubscriptionStatus.PAST_DUE or sub.past_due_since is None:
        return None
    return sub.past_due_since + PAST_DUE_GRACE


async def checkout_for_plan(
    db: AsyncSession,
    stripe: StripeClient,
    *,
    organisation: Organisation,
    user: AppUser,
    price: Price,
    success_url: str,
    cancel_url: str,
    meta: RequestMeta | None,
) -> str:
    product = await get_product(db, price.product_id)
    if not price.active or not product.active or product.kind != plan_kind(organisation):
        raise ApiError(409, "price_unavailable", "This plan is not on sale.")
    if await live_subscription(db, organisation.id) is not None:
        raise ApiError(
            409,
            "plan_exists",
            "You already have a plan. Manage or cancel it with the Manage billing button.",
        )
    customer = await ensure_customer(db, stripe, organisation, user)
    metadata = {
        "organisation_id": str(organisation.id),
        "product_id": str(product.id),
        "price_id": str(price.id),
    }
    try:
        session = await stripe.create_checkout_session(
            {
                "mode": "subscription",
                "customer": customer.stripe_customer_id,
                "client_reference_id": str(organisation.id),
                "line_items": [_price_line(product, price)],
                "metadata": metadata,
                "subscription_data": {"metadata": metadata},
                "success_url": success_url,
                "cancel_url": cancel_url,
            },
            idempotency_key=f"plan-{organisation.id}-{uuid.uuid4()}",
        )
    except StripeError as exc:
        raise payments_unavailable(exc) from exc
    await audit.record(
        db,
        "billing.checkout_started",
        actor_user_id=user.id,
        organisation_id=organisation.id,
        target_type="price",
        target_id=price.id,
        meta=meta,
        details={"product": product.key},
    )
    return session.url


async def portal_url(
    db: AsyncSession, stripe: StripeClient, organisation_id: uuid.UUID, return_url: str
) -> str:
    customer = await get_customer(db, organisation_id)
    if customer is None:
        raise ApiError(409, "no_billing_account", "There's nothing to manage yet.")
    try:
        return await stripe.create_portal_session(
            customer=customer.stripe_customer_id, return_url=return_url
        )
    except StripeError as exc:
        raise payments_unavailable(exc) from exc


# --- The organisation's billing page -----------------------------------------------------


@dataclass(frozen=True)
class Overview:
    has_customer: bool
    subscriptions: list[tuple[Subscription, Product, Price]]
    payments: list[tuple[Payment, Product]]
    invoices: list[InvoiceReference]


async def overview(db: AsyncSession, organisation_id: uuid.UUID) -> Overview:
    subs = [
        (s, p, pr)
        for s, p, pr in await db.execute(
            select(Subscription, Product, Price)
            .join(Product, Product.id == Subscription.product_id)
            .join(Price, Price.id == Subscription.price_id)
            .where(Subscription.organisation_id == organisation_id)
            .order_by(Subscription.created_at.desc())
            .limit(20)
        )
    ]
    payments = [
        (pay, p)
        for pay, p in await db.execute(
            select(Payment, Product)
            .join(Product, Product.id == Payment.product_id)
            .where(Payment.organisation_id == organisation_id)
            .order_by(Payment.created_at.desc())
            .limit(50)
        )
    ]
    invoices = list(
        (
            await db.execute(
                select(InvoiceReference)
                .where(
                    InvoiceReference.organisation_id == organisation_id,
                    InvoiceReference.status != InvoiceStatus.DRAFT,
                )
                .order_by(InvoiceReference.issued_at.desc())
                .limit(50)
            )
        ).scalars()
    )
    return Overview(
        has_customer=await get_customer(db, organisation_id) is not None,
        subscriptions=subs,
        payments=payments,
        invoices=invoices,
    )


async def customer_organisation(db: AsyncSession, stripe_customer_id: str) -> uuid.UUID | None:
    """Which organisation a Stripe customer belongs to (through a definer function: the
    webhook has no tenant bound yet)."""
    value = (
        await db.execute(
            text("SELECT billing_customer_organisation(:customer)"),
            {"customer": stripe_customer_id},
        )
    ).scalar_one_or_none()
    return uuid.UUID(str(value)) if value else None
