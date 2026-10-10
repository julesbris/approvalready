"""Billing routes.

* ``/v1/organisations/{id}/billing...``: the organisation's plan, allowances, payments and
  invoices; Stripe Checkout for a plan and the Stripe customer portal (``billing.manage``).
  The catalogue (what is on sale, for price labels) needs only ``org.read``.
* ``/v1/billing/stripe/webhook``: Stripe's signed webhooks. No session: the signature is
  the authentication.
* ``/v1/admin/billing/...``: staff set prices and follow webhook processing
  (``billing.configure``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    DbDep,
    MetaDep,
    OrgContext,
    ResourcesDep,
    SettingsDep,
    require_org_permission,
    require_platform_permission,
)
from app.core.config import Settings
from app.core.errors import ApiError, not_found
from app.modules.billing import service, webhooks
from app.modules.billing.models import (
    EventStatus,
    InvoiceReference,
    Payment,
    Price,
    Product,
    ProductKind,
    StripeEvent,
    Subscription,
)
from app.modules.billing.schemas import (
    AllowanceOut,
    BillingOut,
    BillingStatusOut,
    CatalogueOut,
    FeatureLimitOut,
    InvoiceOut,
    PaymentOut,
    PlanCheckoutIn,
    PriceIn,
    PriceOut,
    ProductOut,
    RedirectOut,
    StripeEventOut,
    SubscriptionOut,
)
from app.modules.billing.stripe import SignatureError, StripeClient, verify_webhook
from app.modules.tenancy.rbac import Perm

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["billing"])
webhook_router = APIRouter(prefix="/v1/billing", tags=["billing"])
admin_router = APIRouter(prefix="/v1/admin/billing", tags=["admin: billing"])

WEBHOOK_PATH = "/v1/billing/stripe/webhook"

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_READ))]
Manage = Annotated[OrgContext, Depends(require_org_permission(Perm.BILLING_MANAGE))]
Staff = Annotated[OrgContext, Depends(require_platform_permission(Perm.BILLING_CONFIGURE))]


def get_stripe(request: Request) -> StripeClient | None:
    """The Stripe client, or None while payments are switched off."""
    client: StripeClient | None = getattr(request.app.state, "stripe", None)
    return client


StripeDep = Annotated[StripeClient | None, Depends(get_stripe)]


def _require(stripe: StripeClient | None) -> StripeClient:
    if stripe is None:
        raise ApiError(409, "payments_disabled", "Payments are switched off on this server.")
    return stripe


def test_mode(settings: Settings) -> bool:
    key = settings.stripe_secret_key
    return key is not None and key.get_secret_value().startswith(("sk_test_", "rk_test_"))


# How much of each limited feature an organisation uses now.
UsageFn = Callable[[AsyncSession, uuid.UUID], Awaitable[int]]


def _usage() -> dict[str, UsageFn]:
    from app.modules.rentals import service as rentals

    return {rentals.RENTAL_FEATURE: rentals.rentals_in_use}


# --- Output ------------------------------------------------------------------------------


def price_out(p: Price) -> PriceOut:
    return PriceOut.model_validate(p, from_attributes=True)


def product_out(v: service.ProductView) -> ProductOut:
    return ProductOut(
        id=v.product.id,
        key=v.product.key,
        kind=v.product.kind,
        vertical=v.product.vertical,
        name=v.product.name,
        description=v.product.description,
        active=v.product.active,
        features=[
            FeatureLimitOut(key=f.key, description=f.description, limit=f.limit) for f in v.features
        ],
        prices=[price_out(p) for p in v.prices],
    )


def subscription_out(s: Subscription, product: Product, price: Price) -> SubscriptionOut:
    return SubscriptionOut(
        id=s.id,
        product_key=product.key,
        product_name=product.name,
        status=s.status,
        amount_cents=price.amount_cents,
        currency=price.currency,
        interval=price.interval,
        current_period_end=s.current_period_end,
        cancel_at_period_end=s.cancel_at_period_end,
        canceled_at=s.canceled_at,
        past_due_since=s.past_due_since,
        gives_plan=service.subscription_counts(s, service.utcnow()),
    )


def payment_out(p: Payment, product: Product) -> PaymentOut:
    return PaymentOut(
        id=p.id,
        purpose=p.purpose,
        product_name=product.name,
        amount_cents=p.amount_cents,
        currency=p.currency,
        status=p.status,
        refunded_cents=p.refunded_cents,
        subject_type=p.subject_type,
        subject_id=p.subject_id,
        created_at=p.created_at,
        paid_at=p.paid_at,
    )


def invoice_out(i: InvoiceReference) -> InvoiceOut:
    return InvoiceOut.model_validate(i, from_attributes=True)


def event_out(e: StripeEvent) -> StripeEventOut:
    return StripeEventOut.model_validate(e, from_attributes=True)


def _on_sale(views: list[service.ProductView]) -> list[ProductOut]:
    return [product_out(v) for v in views if v.prices]


# --- Customer ----------------------------------------------------------------------------


@router.get("/billing/catalogue", response_model=CatalogueOut)
async def catalogue(ctx: Read, db: DbDep, settings: SettingsDep) -> CatalogueOut:
    """What is on sale and at what price (nothing while payments are switched off)."""
    if not settings.payments_enabled:
        return CatalogueOut(enabled=False, products=[])
    return CatalogueOut(enabled=True, products=_on_sale(await service.catalogue(db)))


@router.get("/billing", response_model=BillingOut)
async def billing_overview(ctx: Manage, db: DbDep, settings: SettingsDep) -> BillingOut:
    """The organisation's plan, what it allows, and its payments and invoices."""
    org_id = ctx.organisation.id
    view = await service.overview(db, org_id)
    allowances = []
    for key, used in _usage().items():
        a = await service.allowance(db, org_id, key)
        allowances.append(
            AllowanceOut(
                feature=a.feature,
                description=a.description,
                limit=a.limit,
                in_use=await used(db, org_id),
                enforced=a.enforced,
                plan=a.plan,
            )
        )
    plans = (
        _on_sale(await service.catalogue(db, kind=ProductKind.SAAS))
        if settings.payments_enabled
        else []
    )
    return BillingOut(
        enabled=settings.payments_enabled,
        test_mode=test_mode(settings),
        has_billing_account=view.has_customer,
        plans=plans,
        subscriptions=[subscription_out(*row) for row in view.subscriptions],
        allowances=allowances,
        payments=[payment_out(*row) for row in view.payments],
        invoices=[invoice_out(i) for i in view.invoices],
    )


@router.post("/billing/checkout", response_model=RedirectOut)
async def plan_checkout(
    body: PlanCheckoutIn,
    ctx: Manage,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
    stripe: StripeDep,
) -> RedirectOut:
    """A Stripe Checkout page to start a plan. The plan starts when Stripe confirms it."""
    client = _require(stripe)
    price = await service.get_price(db, body.price_id)
    back = f"{settings.web_base_url}/account/organisations/{ctx.organisation.id}/billing"
    url = await service.checkout_for_plan(
        db,
        client,
        organisation=ctx.organisation,
        user=ctx.auth.user,
        price=price,
        success_url=f"{back}?checkout=done",
        cancel_url=f"{back}?checkout=cancelled",
        meta=meta,
    )
    await db.commit()
    return RedirectOut(url=url)


@router.post("/billing/portal", response_model=RedirectOut)
async def billing_portal(
    ctx: Manage, db: DbDep, settings: SettingsDep, stripe: StripeDep
) -> RedirectOut:
    """Stripe's customer portal: change the card, download invoices, cancel the plan."""
    client = _require(stripe)
    url = await service.portal_url(
        db,
        client,
        ctx.organisation.id,
        f"{settings.web_base_url}/account/organisations/{ctx.organisation.id}/billing",
    )
    await db.commit()
    return RedirectOut(url=url)


# --- Webhook -----------------------------------------------------------------------------


@webhook_router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request, db: DbDep, settings: SettingsDep, resources: ResourcesDep
) -> dict[str, bool]:
    secret = settings.stripe_webhook_secret
    if not settings.payments_enabled or secret is None:
        raise ApiError(404, "not_found", "Not found.")
    payload = await request.body()
    try:
        event = verify_webhook(
            payload,
            request.headers.get("stripe-signature"),
            secret.get_secret_value(),
            tolerance=settings.stripe_webhook_tolerance_seconds,
        )
    except SignatureError as exc:
        log.warning("stripe webhook rejected: %s", exc)
        raise ApiError(400, "bad_signature", "Signature check failed.") from exc
    row, created = await webhooks.record_event(db, event)
    await db.commit()
    if created or row.status == EventStatus.RECEIVED:
        try:
            await resources.jobs.billing_event(row.id)
        except Exception:
            log.exception("could not queue stripe event")  # the sweep picks it up
    return {"received": True}


# --- Staff -------------------------------------------------------------------------------


@admin_router.get("/status", response_model=BillingStatusOut)
async def billing_status(ctx: Staff, settings: SettingsDep) -> BillingStatusOut:
    return BillingStatusOut(
        enabled=settings.payments_enabled,
        test_mode=test_mode(settings),
        webhook_path=WEBHOOK_PATH,
        webhook_events=webhooks.SUBSCRIBED_EVENTS,
    )


@admin_router.get("/products", response_model=list[ProductOut])
async def admin_products(ctx: Staff, db: DbDep) -> list[ProductOut]:
    """Every product in the catalogue with its current and past prices."""
    return [product_out(v) for v in await service.catalogue(db, include_inactive=True)]


async def _product_view(db: DbDep, product_id: uuid.UUID) -> ProductOut:
    db.expire_all()
    for v in await service.catalogue(db, include_inactive=True):
        if v.product.id == product_id:
            return product_out(v)
    raise not_found("Product")


@admin_router.post("/products/{product_id}/prices", response_model=ProductOut, status_code=201)
async def add_price(
    product_id: uuid.UUID,
    body: PriceIn,
    ctx: Staff,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
) -> ProductOut:
    """Put a product on sale. A new price replaces the current one for the same interval."""
    if not settings.payments_enabled:
        raise ApiError(
            409,
            "payments_disabled",
            "Switch payments on (PAYMENTS_PROVIDER=stripe) before setting prices.",
        )
    product = await service.get_product(db, product_id)
    await service.create_price(
        db,
        product,
        amount_cents=body.amount_cents,
        currency=body.currency,
        interval=body.interval,
        stripe_price_id=body.stripe_price_id,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _product_view(db, product_id)


@admin_router.post("/prices/{price_id}/deactivate", response_model=ProductOut)
async def deactivate_price(price_id: uuid.UUID, ctx: Staff, db: DbDep, meta: MetaDep) -> ProductOut:
    """Take a price off sale. Payments and plans already on it are not affected."""
    price = await service.get_price(db, price_id, lock=True)
    await service.deactivate_price(db, price, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await _product_view(db, price.product_id)


@admin_router.get("/events", response_model=list[StripeEventOut])
async def list_events(
    ctx: Staff,
    db: DbDep,
    status: Annotated[EventStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[StripeEventOut]:
    """Recent webhook events and how they were processed (no payloads)."""
    query = select(StripeEvent).order_by(StripeEvent.received_at.desc()).limit(limit)
    if status is not None:
        query = query.where(StripeEvent.status == status)
    return [event_out(e) for e in (await db.execute(query)).scalars()]


@admin_router.post("/events/{event_id}/retry", response_model=StripeEventOut)
async def retry_event(
    event_id: uuid.UUID, ctx: Staff, db: DbDep, resources: ResourcesDep
) -> StripeEventOut:
    event = (
        await db.execute(select(StripeEvent).where(StripeEvent.id == event_id).with_for_update())
    ).scalar_one_or_none()
    if event is None:
        raise not_found("Event")
    if event.status != EventStatus.FAILED:
        raise ApiError(409, "not_failed", "Only failed events can be retried.")
    await webhooks.retry_event(db, event)
    await db.commit()
    await resources.jobs.billing_event(event.id)
    db.expire_all()
    fresh = (await db.execute(select(StripeEvent).where(StripeEvent.id == event_id))).scalar_one()
    return event_out(fresh)
