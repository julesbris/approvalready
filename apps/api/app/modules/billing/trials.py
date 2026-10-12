"""Free-trial emails for ApprovalReady Plus (``billing.trial_emails``, every 15 minutes).

* **Started.** Once Stripe says a trial began, the organisation's billing managers get an
  email with the date of the first charge, the amount, and how to cancel before then.
* **Ending soon.** ``MEMBERSHIP_TRIAL_REMINDER_DAYS`` before the first charge (7 by
  default) they get a reminder. A trial already set to cancel gets none. When the trial is
  shorter than the reminder window, the started email is the reminder.

Each email is marked sent before it goes out (with the organisation bound and the row
locked), so a job that runs twice, or late, never repeats one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.email import EmailProvider
from app.db.tenant import bind_tenant
from app.modules.billing import emails
from app.modules.billing.models import Price, Subscription, SubscriptionStatus
from app.modules.identity import service as identity
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation
from app.modules.tenancy.rbac import Perm

Factory = async_sessionmaker[AsyncSession]
BATCH = 500


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Due:
    organisation_id: uuid.UUID
    subscription_id: uuid.UUID
    trial_end: datetime


async def trials_to_email(db: AsyncSession, remind_before: timedelta, limit: int) -> list[Due]:
    rows = await db.execute(
        text("SELECT * FROM trials_to_email(:remind, :n)"), {"remind": remind_before, "n": limit}
    )
    return [Due(*row) for row in rows.all()]


async def billing_managers(db: AsyncSession, organisation_id: uuid.UUID) -> list[tuple[str, str]]:
    """(email, name) of the members who handle the organisation's billing."""
    out = []
    for m in await tenancy.list_members(db, organisation_id):
        if Perm.BILLING_MANAGE in await tenancy.permissions_of_roles(db, m.role_keys):
            out.append((str(m.user.email), m.user.display_name))
    return out


async def _email_one(
    factory: Factory, provider: EmailProvider, settings: Settings, due: Due, now: datetime
) -> bool:
    remind_before = timedelta(days=settings.membership_trial_reminder_days)
    async with factory() as db:
        await bind_tenant(db, due.organisation_id)
        sub = (
            await db.execute(
                select(Subscription)
                .where(
                    Subscription.organisation_id == due.organisation_id,
                    Subscription.id == due.subscription_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            sub is None
            or sub.status != SubscriptionStatus.TRIALING
            or sub.trial_end is None
            or sub.trial_end <= now
        ):
            await db.commit()
            return False
        reminder_due = (
            sub.trial_reminder_sent_at is None
            and not sub.cancel_at_period_end
            and sub.trial_end <= now + remind_before
        )
        if sub.trial_welcome_sent_at is None:
            kind = "started"
            sub.trial_welcome_sent_at = now
            if reminder_due:  # a short trial: the started email says when the charge comes
                sub.trial_reminder_sent_at = now
        elif reminder_due:
            kind = "ending"
            sub.trial_reminder_sent_at = now
        else:
            await db.commit()
            return False
        price = await db.get(Price, sub.price_id)
        organisation = await db.get(Organisation, sub.organisation_id)
        recipients = await billing_managers(db, sub.organisation_id)
        trial_end, cancelling = sub.trial_end, sub.cancel_at_period_end
        await db.commit()
    if price is None or organisation is None:
        return False
    make = emails.trial_started if kind == "started" else emails.trial_ending
    for to, name in recipients:
        await identity.send_email(
            provider,
            make(
                settings,
                to,
                name,
                organisation.id,
                trial_end=trial_end,
                amount_cents=price.amount_cents,
                currency=price.currency,
                interval=price.interval,
                cancelling=cancelling,
            ),
        )
    return True


async def send_trial_emails(
    factory: Factory,
    provider: EmailProvider,
    settings: Settings,
    *,
    now: datetime | None = None,
    limit: int = BATCH,
) -> int:
    """Send the trial emails that are due. Returns how many trials were emailed about."""
    now = now or utcnow()
    async with factory() as db:
        due = await trials_to_email(
            db, timedelta(days=settings.membership_trial_reminder_days), limit
        )
        await db.commit()
    sent = 0
    for d in due:
        if await _email_one(factory, provider, settings, d, now):
            sent += 1
    return sent
