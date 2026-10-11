"""The guides email list: who is on it, joining, leaving, and the emails it sends.

The Spam Act 2003 needs consent, a clear sender and a working unsubscribe in every message:

* Joining from the public form sends a confirmation email first; only a person who clicks
  "Confirm" is sent guides (double opt-in, so nobody can sign someone else up). Joining from
  their account needs no confirmation: the address is already verified.
* Every guide email carries the person's own unsubscribe link, in the text and as a
  one-click ``List-Unsubscribe`` header (RFC 8058). Leaving takes effect at once.
* Unconfirmed sign-ups are deleted after ``PENDING_DAYS`` days.

Links are signed with ``SECRET_KEY`` (HMAC of the subscriber and the purpose), so they need
nothing stored and can't be guessed or reused for another subscriber.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import OutgoingEmail
from app.modules.identity.models import AppUser
from app.modules.marketing.models import (
    NewsletterSubscriber,
    SubscriberSource,
    SubscriberStatus,
)

PAGE = "/newsletter"
ONE_CLICK_PATH = "/api/v1/marketing/unsubscribe"
PENDING_DAYS = 30
# A second confirmation email to the same address waits this long (stops the form being
# used to flood someone's inbox).
RESEND_AFTER = timedelta(minutes=15)
CONFIRM = "confirm"
UNSUBSCRIBE = "unsubscribe"
_SIG_BYTES = 18

SENDER_LINE = "ApprovalReady (approvalready.au) sends these guides to people who asked for them."


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalise(email: str) -> str:
    return email.strip().lower()


# --- Signed links ------------------------------------------------------------------------


def _sign(settings: Settings, purpose: str, payload: str) -> str:
    key = settings.secret_key.get_secret_value().encode()
    mac = hmac.new(key, f"newsletter:{purpose}:{payload}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:_SIG_BYTES]).rstrip(b"=").decode()


def token(settings: Settings, purpose: str, subscriber_id: uuid.UUID) -> str:
    return f"{subscriber_id.hex}.{_sign(settings, purpose, subscriber_id.hex)}"


def read_token(settings: Settings, purpose: str, value: str) -> uuid.UUID | None:
    parts = value.split(".")
    if len(parts) != 2:
        return None
    payload, signature = parts
    if not hmac.compare_digest(signature.encode(), _sign(settings, purpose, payload).encode()):
        return None
    try:
        return uuid.UUID(hex=payload)
    except ValueError:
        return None


def links(settings: Settings, subscriber_id: uuid.UUID) -> tuple[str, str]:
    """(unsubscribe page, one-click URL mail providers post to)."""
    base = settings.web_base_url.rstrip("/")
    t = token(settings, UNSUBSCRIBE, subscriber_id)
    return f"{base}{PAGE}?unsubscribe={t}", f"{base}{ONE_CLICK_PATH}?token={t}"


# --- Joining and leaving -----------------------------------------------------------------


async def by_email(db: AsyncSession, email: str) -> NewsletterSubscriber | None:
    return (
        await db.execute(
            select(NewsletterSubscriber).where(NewsletterSubscriber.email == normalise(email))
        )
    ).scalar_one_or_none()


async def by_user(db: AsyncSession, user_id: uuid.UUID) -> NewsletterSubscriber | None:
    return (
        await db.execute(
            select(NewsletterSubscriber).where(NewsletterSubscriber.user_id == user_id)
        )
    ).scalar_one_or_none()


async def sign_up(
    db: AsyncSession, email: str, now: datetime | None = None
) -> NewsletterSubscriber | None:
    """Someone typed an address into the form. Returns the subscriber to send a confirmation
    to, or ``None`` when nothing should be sent (already on the list, or one was just sent).
    The form's answer is the same either way, so it never says who is on the list."""
    now = now or utcnow()
    row = await by_email(db, email)
    if row is None:
        row = NewsletterSubscriber(
            email=normalise(email),
            status=SubscriberStatus.PENDING,
            source=SubscriberSource.FORM,
        )
        db.add(row)
    elif row.status == SubscriberStatus.SUBSCRIBED or (
        row.status == SubscriberStatus.PENDING
        and row.confirm_sent_at is not None
        and now - row.confirm_sent_at < RESEND_AFTER
    ):
        return None
    else:
        row.status = SubscriberStatus.PENDING
        row.source = SubscriberSource.FORM
    row.confirm_sent_at = now
    await db.flush()
    return row


async def confirm(
    db: AsyncSession, subscriber_id: uuid.UUID, now: datetime | None = None
) -> NewsletterSubscriber | None:
    row = await db.get(NewsletterSubscriber, subscriber_id)
    if row is None:
        return None
    if row.status == SubscriberStatus.PENDING:
        row.status = SubscriberStatus.SUBSCRIBED
        row.subscribed_at = now or utcnow()
        row.unsubscribed_at = None
        await db.flush()
    return row


async def unsubscribe(
    db: AsyncSession, row: NewsletterSubscriber, now: datetime | None = None
) -> None:
    if row.status != SubscriberStatus.UNSUBSCRIBED:
        row.status = SubscriberStatus.UNSUBSCRIBED
        row.unsubscribed_at = now or utcnow()
        await db.flush()


async def set_for_account(
    db: AsyncSession, user: AppUser, subscribed: bool, now: datetime | None = None
) -> NewsletterSubscriber | None:
    """Tick or untick "Send me new guides" in the account. The account's address is verified,
    so no confirmation email is needed."""
    now = now or utcnow()
    row = await by_user(db, user.id) or await by_email(db, user.email)
    if not subscribed:
        if row is not None:
            await unsubscribe(db, row, now)
        return row
    if row is None:
        row = NewsletterSubscriber(email=normalise(user.email), source=SubscriberSource.ACCOUNT)
        db.add(row)
    # The address stays as first given; sending uses the account's current one.
    row.user_id = user.id
    if row.status != SubscriberStatus.SUBSCRIBED:
        row.status = SubscriberStatus.SUBSCRIBED
        row.source = SubscriberSource.ACCOUNT
        row.subscribed_at = now
        row.unsubscribed_at = None
    await db.flush()
    return row


async def is_subscribed(db: AsyncSession, user: AppUser) -> bool:
    row = await by_user(db, user.id) or await by_email(db, user.email)
    return row is not None and row.status == SubscriberStatus.SUBSCRIBED


async def export(db: AsyncSession, user: AppUser) -> dict[str, str | None] | None:
    """The person's place on the guides list, for their data export."""
    row = await by_user(db, user.id) or await by_email(db, user.email)
    if row is None:
        return None
    return {
        "email": row.email,
        "status": row.status,
        "joined_from": row.source,
        "subscribed_at": row.subscribed_at.isoformat() if row.subscribed_at else None,
        "unsubscribed_at": row.unsubscribed_at.isoformat() if row.unsubscribed_at else None,
    }


async def forget_account(db: AsyncSession, user_id: uuid.UUID, email: str) -> None:
    """Closing an account takes it off the list: its row, and any sign-up from its address,
    are deleted."""
    await db.execute(
        delete(NewsletterSubscriber).where(
            or_(
                NewsletterSubscriber.user_id == user_id,
                NewsletterSubscriber.email == normalise(email),
            )
        )
    )


async def purge_unconfirmed(db: AsyncSession, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - timedelta(days=PENDING_DAYS)
    result = await db.execute(
        delete(NewsletterSubscriber).where(
            NewsletterSubscriber.status == SubscriberStatus.PENDING,
            NewsletterSubscriber.updated_at < cutoff,
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def counts(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(
            select(NewsletterSubscriber.status, func.count()).group_by(NewsletterSubscriber.status)
        )
    ).all()
    found = {status: int(n) for status, n in rows}
    return {s.value: found.get(s.value, 0) for s in SubscriberStatus}


async def recipients(
    db: AsyncSession, after: uuid.UUID | None, limit: int
) -> list[tuple[uuid.UUID, str]]:
    """Subscribers in id order after ``after``, with the address to send to: the account's
    current address for people who joined from their account."""
    address = func.coalesce(AppUser.email, NewsletterSubscriber.email)
    stmt = (
        select(NewsletterSubscriber.id, address)
        .outerjoin(AppUser, AppUser.id == NewsletterSubscriber.user_id)
        .where(
            NewsletterSubscriber.status == SubscriberStatus.SUBSCRIBED,
            AppUser.deleted_at.is_(None),
        )
        .order_by(NewsletterSubscriber.id)
        .limit(limit)
    )
    if after is not None:
        stmt = stmt.where(NewsletterSubscriber.id > after)
    return [(sid, email) for sid, email in (await db.execute(stmt)).all()]


# --- Emails ------------------------------------------------------------------------------


def confirm_email(settings: Settings, row: NewsletterSubscriber) -> OutgoingEmail:
    base = settings.web_base_url.rstrip("/")
    link = f"{base}{PAGE}?confirm={token(settings, CONFIRM, row.id)}"
    text = (
        "Hi,\n\n"
        "Someone (we hope you) asked for ApprovalReady's step-by-step approval guides to be "
        "sent to this address.\n\n"
        f"Confirm you'd like them: {link}\n\n"
        "If this wasn't you, ignore this email: you won't hear from us again, and we delete "
        f"unconfirmed sign-ups after {PENDING_DAYS} days.\n\n"
        f"{SENDER_LINE}\n"
    )
    return OutgoingEmail(
        to=row.email,
        subject="Confirm your ApprovalReady guides",
        text=text,
        kind="marketing.confirm",
        links={"confirm": link},
    )


def guide_email(
    settings: Settings, to: str, subscriber_id: uuid.UUID, subject: str, body: str
) -> OutgoingEmail:
    page, one_click = links(settings, subscriber_id)
    text = f"{body.rstrip()}\n\n--\n{SENDER_LINE}\nUnsubscribe (one click, no sign-in): {page}\n"
    return OutgoingEmail(
        to=to,
        subject=subject,
        text=text,
        kind="marketing.guide",
        links={"unsubscribe": page},
        headers={
            "List-Unsubscribe": f"<{one_click}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )
