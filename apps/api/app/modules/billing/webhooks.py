"""Stripe webhooks: store each verified event once, then apply it in the worker.

The endpoint only checks the signature and stores the event (``stripe_event``, unique on
Stripe's event id), so Stripe gets its 200 quickly and a redelivered or replayed event is
recognised. The worker then works out whose event it is (from the Stripe customer, which
only this server creates), binds that organisation and applies the event:

* ``checkout.session.completed`` / ``checkout.session.async_payment_succeeded``: a one-off
  payment is paid; what it paid for is released (a review goes to staff for assignment).
* ``checkout.session.async_payment_failed``: the payment failed.
* ``customer.subscription.*``: the plan's status, period and cancellation, as Stripe says.
* ``invoice.*``: the invoice's number, amounts, status and links.
* ``charge.refunded``: the payment is marked refunded (refunds are made in Stripe).

Events can arrive out of order: subscription and invoice rows remember the time of the
event last applied, and an older event is skipped.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant import bind_tenant
from app.modules.audit import service as audit
from app.modules.billing import service
from app.modules.billing.models import (
    EventStatus,
    InvoiceReference,
    InvoiceStatus,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    Price,
    StripeEvent,
    Subscription,
    SubscriptionStatus,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 8


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if value else None


def _id(value: Any) -> str | None:
    """An id that may come expanded as an object."""
    if isinstance(value, dict):
        return str(value.get("id")) if value.get("id") else None
    return str(value) if value else None


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def record_event(db: AsyncSession, event: dict[str, Any]) -> tuple[StripeEvent, bool]:
    """Store a verified event. Returns the stored row and whether it is new."""
    values = {
        "stripe_event_id": str(event["id"])[:255],
        "type": str(event.get("type") or "")[:100],
        "livemode": bool(event.get("livemode")),
        "stripe_created_at": _ts(event.get("created")) or datetime.now(UTC),
        "payload": event,
        "status": EventStatus.RECEIVED,
    }
    inserted = (
        await db.execute(
            insert(StripeEvent)
            .values(id=uuid.uuid4(), **values)
            .on_conflict_do_nothing(index_elements=["stripe_event_id"])
            .returning(StripeEvent.id)
        )
    ).scalar_one_or_none()
    row = (
        await db.execute(
            select(StripeEvent).where(StripeEvent.stripe_event_id == values["stripe_event_id"])
        )
    ).scalar_one()
    return row, inserted is not None


# --- Handlers ---------------------------------------------------------------------------

Handler = Callable[[AsyncSession, uuid.UUID, dict[str, Any], datetime], Awaitable[str]]


async def _payment_from(
    db: AsyncSession, organisation_id: uuid.UUID, obj: dict[str, Any]
) -> Payment | None:
    payment_id = _uuid((obj.get("metadata") or {}).get("payment_id"))
    if payment_id is None:
        return None
    return (
        await db.execute(
            select(Payment)
            .where(Payment.organisation_id == organisation_id, Payment.id == payment_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def mark_paid(
    db: AsyncSession, payment: Payment, *, intent: str | None, session_id: str | None
) -> None:
    previous = payment.status
    if previous == PaymentStatus.PAID:
        if (
            intent
            and payment.stripe_payment_intent_id
            and intent != payment.stripe_payment_intent_id
        ):
            # Paid twice (two checkout pages both completed): staff refund one in Stripe.
            log.warning("payment paid twice", extra={"payment_id": str(payment.id)})
            await audit.record(
                db,
                "billing.paid_twice",
                organisation_id=payment.organisation_id,
                target_type="payment",
                target_id=payment.id,
                details={"payment_intent": intent},
            )
        return
    payment.status = PaymentStatus.PAID
    payment.paid_at = datetime.now(UTC)
    payment.stripe_payment_intent_id = intent or payment.stripe_payment_intent_id
    payment.stripe_checkout_session_id = session_id or payment.stripe_checkout_session_id
    await db.flush()
    await audit.record(
        db,
        "billing.payment_paid",
        organisation_id=payment.organisation_id,
        target_type="payment",
        target_id=payment.id,
        details={"amount_cents": payment.amount_cents, "currency": payment.currency}
        | ({"was": previous} if previous != PaymentStatus.PENDING else {}),
    )
    if payment.purpose == PaymentPurpose.REVIEW and payment.subject_id is not None:
        from app.modules.review import service as reviews

        await reviews.payment_received(db, payment)
    from app.modules.leads import service as leads

    if (
        payment.purpose == PaymentPurpose.PRODUCT
        and payment.subject_type == leads.CREDIT_PACK_SUBJECT
    ):
        await leads.credits_purchased(db, payment)


async def _checkout_paid(
    db: AsyncSession, org: uuid.UUID, obj: dict[str, Any], at: datetime
) -> str:
    if obj.get("mode") != "payment":
        return EventStatus.IGNORED  # plans are applied from the subscription events
    payment = await _payment_from(db, org, obj)
    if payment is None:
        return EventStatus.IGNORED
    if obj.get("payment_status") not in ("paid", "no_payment_required"):
        return EventStatus.PROCESSED  # a delayed method (direct debit): wait for the outcome
    await mark_paid(db, payment, intent=_id(obj.get("payment_intent")), session_id=obj.get("id"))
    return EventStatus.PROCESSED


async def _checkout_failed(
    db: AsyncSession, org: uuid.UUID, obj: dict[str, Any], at: datetime
) -> str:
    payment = await _payment_from(db, org, obj)
    if payment is None or obj.get("mode") != "payment":
        return EventStatus.IGNORED
    if payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.FAILED
        await db.flush()
        await audit.record(
            db,
            "billing.payment_failed",
            organisation_id=org,
            target_type="payment",
            target_id=payment.id,
        )
    return EventStatus.PROCESSED


def _period_end(obj: dict[str, Any]) -> datetime | None:
    # Newer Stripe API versions keep the period on each item instead of the subscription.
    if obj.get("current_period_end"):
        return _ts(obj["current_period_end"])
    items = (obj.get("items") or {}).get("data") or []
    ends = [i.get("current_period_end") for i in items if i.get("current_period_end")]
    return _ts(max(ends)) if ends else None


async def _subscription(db: AsyncSession, org: uuid.UUID, obj: dict[str, Any], at: datetime) -> str:
    stripe_id = _id(obj.get("id"))
    try:
        status = SubscriptionStatus(str(obj.get("status", "")).upper())
    except ValueError:
        return EventStatus.IGNORED
    row = (
        await db.execute(
            select(Subscription)
            .where(Subscription.stripe_subscription_id == stripe_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None and row.stripe_event_at > at:
        return EventStatus.IGNORED  # an older event arriving late
    if row is None:
        price_id = _uuid((obj.get("metadata") or {}).get("price_id"))
        price = await db.get(Price, price_id) if price_id else None
        if price is None:
            return EventStatus.IGNORED  # not a plan sold through this server
        row = Subscription(
            organisation_id=org,
            product_id=price.product_id,
            price_id=price.id,
            stripe_subscription_id=stripe_id,
            status=status,
            stripe_event_at=at,
        )
        db.add(row)
        previous = None
    else:
        previous = row.status
    row.status = status
    row.current_period_end = _period_end(obj)
    row.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
    row.canceled_at = _ts(obj.get("canceled_at"))
    if status == SubscriptionStatus.PAST_DUE:
        row.past_due_since = row.past_due_since or at
    else:
        row.past_due_since = None
    row.stripe_event_at = at
    await db.flush()
    if previous != status:
        await audit.record(
            db,
            "billing.subscription_changed",
            organisation_id=org,
            target_type="subscription",
            target_id=row.id,
            details={"from": previous, "to": str(status)},
        )
    return EventStatus.PROCESSED


def _invoice_subscription(obj: dict[str, Any]) -> str | None:
    if obj.get("subscription"):
        return _id(obj["subscription"])
    parent = obj.get("parent") or {}
    return _id((parent.get("subscription_details") or {}).get("subscription"))


async def _invoice(db: AsyncSession, org: uuid.UUID, obj: dict[str, Any], at: datetime) -> str:
    try:
        status = InvoiceStatus(str(obj.get("status", "")).upper())
    except ValueError:
        return EventStatus.IGNORED
    stripe_id = _id(obj.get("id"))
    row = (
        await db.execute(
            select(InvoiceReference)
            .where(InvoiceReference.stripe_invoice_id == stripe_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None and row.stripe_event_at > at:
        return EventStatus.IGNORED
    values = {
        "stripe_subscription_id": _invoice_subscription(obj),
        "number": obj.get("number"),
        "status": status,
        "amount_due_cents": int(obj.get("amount_due") or 0),
        "amount_paid_cents": int(obj.get("amount_paid") or 0),
        "currency": str(obj.get("currency") or "aud").upper()[:3],
        "hosted_invoice_url": obj.get("hosted_invoice_url"),
        "invoice_pdf_url": obj.get("invoice_pdf"),
        "issued_at": _ts(obj.get("created")) or at,
        "stripe_event_at": at,
    }
    if row is None:
        db.add(InvoiceReference(organisation_id=org, stripe_invoice_id=stripe_id, **values))
    else:
        for k, v in values.items():
            setattr(row, k, v)
    await db.flush()
    return EventStatus.PROCESSED


async def _refunded(db: AsyncSession, org: uuid.UUID, obj: dict[str, Any], at: datetime) -> str:
    intent = _id(obj.get("payment_intent"))
    if not intent:
        return EventStatus.IGNORED
    payment = (
        await db.execute(
            select(Payment)
            .where(Payment.organisation_id == org, Payment.stripe_payment_intent_id == intent)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if payment is None:
        return EventStatus.IGNORED  # e.g. a subscription invoice's charge
    refunded = min(int(obj.get("amount_refunded") or 0), payment.amount_cents)
    if refunded <= payment.refunded_cents:
        return EventStatus.PROCESSED
    payment.refunded_cents = refunded
    payment.status = (
        PaymentStatus.REFUNDED
        if refunded >= payment.amount_cents
        else PaymentStatus.PARTIALLY_REFUNDED
    )
    await db.flush()
    await audit.record(
        db,
        "billing.payment_refunded",
        organisation_id=org,
        target_type="payment",
        target_id=payment.id,
        details={"refunded_cents": refunded},
    )
    return EventStatus.PROCESSED


HANDLERS: dict[str, Handler] = {
    "checkout.session.completed": _checkout_paid,
    "checkout.session.async_payment_succeeded": _checkout_paid,
    "checkout.session.async_payment_failed": _checkout_failed,
    "customer.subscription.created": _subscription,
    "customer.subscription.updated": _subscription,
    "customer.subscription.deleted": _subscription,
    "customer.subscription.paused": _subscription,
    "customer.subscription.resumed": _subscription,
    "invoice.created": _invoice,
    "invoice.finalized": _invoice,
    "invoice.updated": _invoice,
    "invoice.paid": _invoice,
    "invoice.payment_failed": _invoice,
    "invoice.voided": _invoice,
    "invoice.marked_uncollectible": _invoice,
    "charge.refunded": _refunded,
}
# What to select when adding the webhook endpoint in the Stripe dashboard.
SUBSCRIBED_EVENTS = sorted(HANDLERS)


class EventFailed(Exception):
    """Applying the event failed; the worker retries it."""


async def process_event(db: AsyncSession, event_id: uuid.UUID) -> str | None:
    """Apply one stored event (worker). Commits. Raises ``EventFailed`` after recording a
    failure that should be retried."""
    row = (
        await db.execute(select(StripeEvent).where(StripeEvent.id == event_id).with_for_update())
    ).scalar_one_or_none()
    if row is None or row.status in (EventStatus.PROCESSED, EventStatus.IGNORED):
        return None
    row.attempts += 1
    stored_id, attempts = row.id, row.attempts
    handler = HANDLERS.get(row.type)
    obj = (row.payload.get("data") or {}).get("object") or {}
    customer = _id(obj.get("customer"))
    org = await service.customer_organisation(db, customer) if customer else None
    if handler is None or org is None:
        row.status = EventStatus.IGNORED
        row.processed_at = datetime.now(UTC)
        row.error = None if handler is None else "Not a customer of this server."
        await db.commit()
        return str(row.status)
    try:
        await bind_tenant(db, org)
        row.organisation_id = org
        result = await handler(db, org, obj, row.stripe_created_at)
        row.status = result
        row.error = None
        row.processed_at = datetime.now(UTC)
        await db.commit()
        return result
    except Exception as exc:
        await db.rollback()
        log.exception("stripe event failed", extra={"stripe_event_id": str(stored_id)})
        failed = (
            await db.execute(select(StripeEvent).where(StripeEvent.id == stored_id))
        ).scalar_one()
        failed.status = EventStatus.FAILED
        failed.attempts = attempts
        failed.error = f"{type(exc).__name__}: {exc}"[:500]
        await db.commit()
        raise EventFailed(str(exc)) from exc


async def retry_event(db: AsyncSession, event: StripeEvent) -> None:
    """Staff: try a failed event again."""
    if event.status == EventStatus.FAILED:
        event.status = EventStatus.RECEIVED
        await db.flush()


async def events_to_requeue(db: AsyncSession, older_than_minutes: int) -> list[uuid.UUID]:
    """Events still waiting, or failed with tries left, after a while (the worker's sweep)."""
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    rows = await db.execute(
        select(StripeEvent.id)
        .where(
            StripeEvent.received_at < cutoff,
            (StripeEvent.status == EventStatus.RECEIVED)
            | ((StripeEvent.status == EventStatus.FAILED) & (StripeEvent.attempts < MAX_ATTEMPTS)),
        )
        .order_by(StripeEvent.received_at)
        .limit(200)
    )
    return list(rows.scalars())
