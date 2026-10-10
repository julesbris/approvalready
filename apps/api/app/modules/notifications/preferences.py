"""Notification preferences and unsubscribe links (Milestone 21).

Each person picks, per category, whether they hear about it in the app and by email, in the
app only, or not at all (``NotificationChannel``). ``service.create`` applies the choice when a
notification is generated, so it holds for reminders, grant rounds, referrals and staff
alerts alike. Ops alerts and account emails (sign-in links, password and security notices,
invitations, reviews) are not optional and are never affected.

Every notification email carries an unsubscribe link for its category, in the text and as a
``List-Unsubscribe`` header with one-click ``List-Unsubscribe-Post`` (RFC 8058), as the
Spam Act 2003 and the large mailbox providers expect. The token is an HMAC of the person and
the category under ``SECRET_KEY``: it can only switch that person's emails off, so it needs
no expiry and nothing stored. Changing ``SECRET_KEY`` invalidates links already sent.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.notifications.models import (
    CATEGORY_OF,
    NotificationCategory,
    NotificationChannel,
    NotificationKind,
    NotificationPreference,
)

UNSUBSCRIBE_PAGE = "/unsubscribe"
# The web app's proxy path to ``POST /v1/auth/unsubscribe`` (mail providers post here).
ONE_CLICK_PATH = "/api/v1/auth/unsubscribe"
_SIG_BYTES = 18


def utcnow() -> datetime:
    return datetime.now(UTC)


async def choices(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[NotificationCategory, NotificationChannel]:
    """Every category with this person's channel (``ALL`` where they haven't chosen)."""
    rows = (
        await db.execute(
            select(NotificationPreference.category, NotificationPreference.channel).where(
                NotificationPreference.user_id == user_id
            )
        )
    ).all()
    chosen = {NotificationCategory(c): NotificationChannel(ch) for c, ch in rows}
    return {c: chosen.get(c, NotificationChannel.ALL) for c in NotificationCategory}


async def channel_for(
    db: AsyncSession, user_id: uuid.UUID, kind: NotificationKind
) -> NotificationChannel:
    category = CATEGORY_OF.get(kind)
    if category is None:
        return NotificationChannel.ALL
    return await channel_for_category(db, user_id, category)


async def channel_for_category(
    db: AsyncSession, user_id: uuid.UUID, category: NotificationCategory
) -> NotificationChannel:
    channel = (
        await db.execute(
            select(NotificationPreference.channel).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.category == category,
            )
        )
    ).scalar_one_or_none()
    return NotificationChannel(channel) if channel else NotificationChannel.ALL


async def choose(
    db: AsyncSession,
    user_id: uuid.UUID,
    category: NotificationCategory,
    channel: NotificationChannel,
) -> None:
    stmt = insert(NotificationPreference).values(
        user_id=user_id, category=category, channel=channel, updated_at=utcnow()
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "category"],
            set_={"channel": stmt.excluded.channel, "updated_at": stmt.excluded.updated_at},
        )
    )


async def stop_emails(
    db: AsyncSession, user_id: uuid.UUID, categories: list[NotificationCategory]
) -> None:
    """Unsubscribe: no more emails for these categories. A category already off stays off."""
    current = await choices(db, user_id)
    for category in categories:
        if current[category] == NotificationChannel.ALL:
            await choose(db, user_id, category, NotificationChannel.IN_APP)


# --- Unsubscribe tokens ----------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _sign(secret_key: str, payload: str) -> str:
    mac = hmac.new(secret_key.encode(), f"unsubscribe:{payload}".encode(), hashlib.sha256)
    return _b64(mac.digest()[:_SIG_BYTES])


def unsubscribe_token(secret_key: str, user_id: uuid.UUID, category: NotificationCategory) -> str:
    payload = f"{user_id.hex}.{category.value}"
    return f"{payload}.{_sign(secret_key, payload)}"


def read_unsubscribe_token(
    secret_key: str, token: str
) -> tuple[uuid.UUID, NotificationCategory] | None:
    """The person and category a token was made for, or ``None`` when it isn't genuine."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    user_hex, category, signature = parts
    payload = f"{user_hex}.{category}"
    if not hmac.compare_digest(signature.encode(), _sign(secret_key, payload).encode()):
        return None
    try:
        return uuid.UUID(hex=user_hex), NotificationCategory(category)
    except ValueError:
        return None


def unsubscribe_links(
    settings: Settings, user_id: uuid.UUID, category: NotificationCategory
) -> tuple[str, str]:
    """(page a person opens from the email, URL mail providers post to for one click)."""
    base = settings.web_base_url.rstrip("/")
    token = unsubscribe_token(settings.secret_key.get_secret_value(), user_id, category)
    return f"{base}{UNSUBSCRIBE_PAGE}?token={token}", f"{base}{ONE_CLICK_PATH}?token={token}"
