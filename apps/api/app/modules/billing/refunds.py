"""Refunds (Milestone 22): give money back on a one-off payment through Stripe.

A refund is recorded first (``refund`` row, ``PENDING``) in the same transaction as whatever
caused it, then sent to Stripe after that commits: by the worker (``billing.send_refund``),
or straight away with ``JOBS_MODE=inline``. The row id is Stripe's idempotency key, so a
retry after a lost answer never refunds twice. Refunds still pending after a while are
picked up again by the worker's sweep (``pending_refunds()``).

When refunds happen:

* the customer cancels a paid review before the reviewer starts work (``REVIEW_CANCELLED``,
  the whole amount; see ``review.service.cancel``);
* a review is paid for on a checkout page left open after it was cancelled
  (``PAID_AFTER_CANCEL``, the whole amount; see ``review.service.payment_received``);
* staff with ``billing.refund`` refund part or all of a paid review, with a note
  (``STAFF``), for example when the reviewer had already started.

``payment.refunded_cents`` is what Stripe has accepted to refund so far: refunds sent from
here add to it, and ``charge.refunded`` webhooks (which also cover refunds made in the
Stripe dashboard) set it to Stripe's total.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.tenant import bind_tenant
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.billing.models import (
    Payment,
    PaymentStatus,
    Refund,
    RefundReason,
    RefundStatus,
)
from app.modules.billing.stripe import StripeClient, StripeError

log = logging.getLogger(__name__)

# Payments money can still be given back on.
REFUNDABLE_PAYMENTS = (PaymentStatus.PAID, PaymentStatus.PARTIALLY_REFUNDED)
# Stripe's refund statuses.
STRIPE_STATUS = {
    "succeeded": RefundStatus.SUCCEEDED,
    "pending": RefundStatus.SUBMITTED,
    "requires_action": RefundStatus.SUBMITTED,
    "failed": RefundStatus.FAILED,
    "canceled": RefundStatus.FAILED,
}
# Where new refunds are noted on the session until the caller has committed and sends them.
_NEW = "billing.new_refunds"


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


def apply_refunded(payment: Payment, refunded_cents: int) -> bool:
    """Record Stripe's running total of refunds on the payment. Never goes down (events can
    arrive out of order). Returns whether anything changed."""
    refunded = min(refunded_cents, payment.amount_cents)
    if refunded <= payment.refunded_cents:
        return False
    payment.refunded_cents = refunded
    payment.status = (
        PaymentStatus.REFUNDED
        if refunded >= payment.amount_cents
        else PaymentStatus.PARTIALLY_REFUNDED
    )
    return True


async def for_payment(db: AsyncSession, payment_id: uuid.UUID) -> list[Refund]:
    return list(
        (
            await db.execute(
                select(Refund)
                .where(Refund.payment_id == payment_id)
                .order_by(Refund.created_at, Refund.id)
            )
        ).scalars()
    )


async def refundable_cents(db: AsyncSession, payment: Payment) -> int:
    """What is left to give back: the amount, less what Stripe has refunded and what is
    still waiting to be sent."""
    if payment.status not in REFUNDABLE_PAYMENTS or not payment.stripe_payment_intent_id:
        return 0
    waiting = (
        await db.execute(
            select(func.coalesce(func.sum(Refund.amount_cents), 0)).where(
                Refund.organisation_id == payment.organisation_id,
                Refund.payment_id == payment.id,
                Refund.status == RefundStatus.PENDING,
            )
        )
    ).scalar_one()
    return max(0, payment.amount_cents - payment.refunded_cents - int(waiting))


async def request(
    db: AsyncSession,
    payment: Payment,
    *,
    reason: RefundReason,
    amount_cents: int | None = None,
    note: str | None = None,
    actor_id: uuid.UUID | None,
    meta: RequestMeta | None,
) -> Refund:
    """Record a refund of ``amount_cents`` (everything left when None). The payment must be
    locked by the caller. Send it with ``send`` once the transaction has committed."""
    left = await refundable_cents(db, payment)
    if left <= 0:
        raise _conflict("nothing_to_refund", "There is nothing left to refund on this payment.")
    amount = left if amount_cents is None else amount_cents
    if amount <= 0 or amount > left:
        raise _conflict(
            "refund_too_large",
            f"At most {left / 100:.2f} {payment.currency} can be refunded on this payment.",
        )
    if reason == RefundReason.STAFF and not (note and note.strip()):
        raise ApiError(422, "note_required", "Say why this refund is being made.")
    refund = Refund(
        organisation_id=payment.organisation_id,
        payment_id=payment.id,
        amount_cents=amount,
        currency=payment.currency,
        reason=reason,
        note=note.strip() if note else None,
        status=RefundStatus.PENDING,
        created_by=actor_id,
    )
    db.add(refund)
    await db.flush()
    db.info.setdefault(_NEW, []).append((payment.organisation_id, refund.id))
    await audit.record(
        db,
        "billing.refund_requested",
        actor_user_id=actor_id,
        organisation_id=payment.organisation_id,
        target_type="refund",
        target_id=refund.id,
        meta=meta,
        details={"payment_id": str(payment.id), "amount_cents": amount, "reason": reason},
    )
    return refund


def take_new(db: AsyncSession) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(organisation, refund) pairs recorded on this session since last asked: call after
    committing, to send them."""
    new: list[tuple[uuid.UUID, uuid.UUID]] = db.info.pop(_NEW, [])
    return new


@dataclass(frozen=True)
class Sent:
    """What happened to a refund that was sent (or tried)."""

    refund: Refund
    payment: Payment
    status: str


def _permanent(exc: StripeError) -> bool:
    """Stripe refused the refund itself (already refunded, disputed, too old): trying again
    won't help. Rate limits, outages and lost connections are worth retrying."""
    return exc.status is not None and 400 <= exc.status < 500 and exc.status not in (409, 429)


async def send(
    db: AsyncSession,
    stripe: StripeClient,
    organisation_id: uuid.UUID,
    refund_id: uuid.UUID,
    *,
    final_attempt: bool,
) -> Sent | None:
    """Send a pending refund to Stripe and record the answer. Commits. Returns None when
    there was nothing to send (already sent, or not found)."""
    await bind_tenant(db, organisation_id)
    refund = (
        await db.execute(
            select(Refund)
            .where(Refund.organisation_id == organisation_id, Refund.id == refund_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if refund is None or refund.status != RefundStatus.PENDING:
        await db.commit()
        return None
    payment = (
        await db.execute(
            select(Payment)
            .where(Payment.organisation_id == organisation_id, Payment.id == refund.payment_id)
            .with_for_update()
        )
    ).scalar_one()
    refund.attempts += 1
    intent = payment.stripe_payment_intent_id
    try:
        if not intent:
            raise StripeError("The payment has no Stripe payment to refund.", 400)
        answer = await stripe.create_refund(
            payment_intent=intent,
            amount_cents=refund.amount_cents,
            metadata={
                "refund_id": str(refund.id),
                "payment_id": str(payment.id),
                "organisation_id": str(organisation_id),
            },
            idempotency_key=f"refund-{refund.id}",
        )
    except StripeError as exc:
        refund.error = str(exc)[:500]
        if _permanent(exc) or final_attempt:
            refund.status = RefundStatus.FAILED
            await audit.record(
                db,
                "billing.refund_failed",
                organisation_id=organisation_id,
                target_type="refund",
                target_id=refund.id,
                details={"payment_id": str(payment.id), "error": refund.error},
            )
        await db.commit()
        log.warning(
            "refund not sent",
            extra={"refund_id": str(refund.id), "status": refund.status, "error": refund.error},
        )
        return Sent(refund, payment, refund.status)
    refund.stripe_refund_id = answer.id
    refund.status = STRIPE_STATUS.get(answer.status, RefundStatus.SUBMITTED)
    refund.error = None
    refund.sent_at = datetime.now(UTC)
    if refund.status != RefundStatus.FAILED:
        apply_refunded(payment, payment.refunded_cents + refund.amount_cents)
    await audit.record(
        db,
        "billing.refund_sent" if refund.status != RefundStatus.FAILED else "billing.refund_failed",
        organisation_id=organisation_id,
        target_type="refund",
        target_id=refund.id,
        details={
            "payment_id": str(payment.id),
            "amount_cents": refund.amount_cents,
            "stripe_refund_id": answer.id,
            "stripe_status": answer.status,
        },
    )
    await db.commit()
    return Sent(refund, payment, refund.status)


async def pending(db: AsyncSession, older_than_minutes: int) -> list[tuple[str, str]]:
    """(organisation, refund) ids of refunds still waiting to be sent (the worker's sweep)."""
    rows = await db.execute(
        text("SELECT organisation_id, id FROM pending_refunds(:age)"),
        {"age": f"{older_than_minutes} minutes"},
    )
    return [(str(r[0]), str(r[1])) for r in rows]
