"""Change of email address (Milestone 28).

A signed-in user asks for a new address with their password (and a two-step code when that
is on). A link goes to the new address and a notice to the old one; nothing changes until
the link is opened. Opening it moves the account to the new address, marks it confirmed,
cancels links still waiting in the old inbox and tells the old address.

Enumeration resistance as for registration: when the new address already belongs to an
account, the request looks the same to the requester (the change waits for a link that
never comes) and the new address is told an account already uses it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import OutgoingEmail
from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter, subject_digest
from app.core.security import verify_password
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity import emails, mfa
from app.modules.identity.models import AppUser, OneTimeToken, PasswordCredential, TokenPurpose
from app.modules.identity.service import (
    consume_token_row,
    issue_token,
    normalise_email,
    utcnow,
)


@dataclass(frozen=True)
class Pending:
    new_email: str
    expires_at: datetime


async def pending(db: AsyncSession, user_id: uuid.UUID) -> Pending | None:
    """The change waiting for its link to be opened, if any (only the newest link works)."""
    row = (
        await db.execute(
            select(OneTimeToken)
            .where(
                OneTimeToken.user_id == user_id,
                OneTimeToken.purpose == TokenPurpose.EMAIL_CHANGE,
                OneTimeToken.used_at.is_(None),
                OneTimeToken.expires_at > utcnow(),
            )
            .order_by(OneTimeToken.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or row.new_email is None:
        return None
    return Pending(new_email=str(row.new_email), expires_at=row.expires_at)


async def _address_in_use(db: AsyncSession, email: str, *, other_than: uuid.UUID) -> bool:
    # Any row, closed or not: the address is unique across the table.
    found = await db.scalar(
        select(AppUser.id).where(AppUser.email == email, AppUser.id != other_than).limit(1)
    )
    return found is not None


async def request_change(
    db: AsyncSession,
    settings: Settings,
    limiter: RateLimiter,
    user: AppUser,
    *,
    new_email: str,
    password: str,
    code: str | None,
    meta: RequestMeta,
) -> list[OutgoingEmail]:
    """Start a change. Returns the emails to send: the link (or "already in use") to the
    new address, then the notice to the current one."""
    new_email = normalise_email(new_email)
    if new_email == normalise_email(user.email):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "same_email",
            "That is already your email address.",
        )
    credential = await db.scalar(
        select(PasswordCredential).where(PasswordCredential.user_id == user.id)
    )
    if not verify_password(credential.password_hash if credential else None, password):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_credentials", "Your password is incorrect."
        )
    if await mfa.is_enabled(db, user.id):
        if not code:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "mfa_code_required",
                "Enter a code from your authenticator app (or a recovery code).",
            )
        await mfa.check_code(db, settings, limiter, user, code, meta)

    token = await issue_token(
        db,
        user.id,
        TokenPurpose.EMAIL_CHANGE,
        timedelta(hours=settings.email_verification_ttl_hours),
        new_email=new_email,
    )
    await audit.record(
        db,
        "auth.email_change.requested",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details={"new_email_digest": subject_digest(new_email)},
    )
    if await _address_in_use(db, new_email, other_than=user.id):
        to_new = emails.email_change_address_taken(settings, new_email)
    else:
        to_new = emails.email_change_confirm(
            settings, new_email, user.display_name, token, user.email
        )
    return [
        to_new,
        emails.email_change_requested(settings, user.email, user.display_name, new_email),
    ]


async def cancel(db: AsyncSession, user: AppUser, meta: RequestMeta) -> bool:
    """Cancel the waiting change: its link stops working. False when nothing was waiting."""
    result = await db.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == user.id,
            OneTimeToken.purpose == TokenPurpose.EMAIL_CHANGE,
            OneTimeToken.used_at.is_(None),
        )
        .values(used_at=utcnow())
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        return False
    await audit.record(
        db,
        "auth.email_change.cancelled",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
    )
    return True


async def confirm(
    db: AsyncSession, settings: Settings, token: str, meta: RequestMeta
) -> OutgoingEmail:
    """Open the link: move the account to the new address. Returns the notice for the old
    address."""
    row, user = await consume_token_row(db, token, TokenPurpose.EMAIL_CHANGE)
    new_email = str(row.new_email)
    if await _address_in_use(db, new_email, other_than=user.id):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "email_in_use",
            "Another account already uses this address, so your email address was not changed.",
        )
    old_email = str(user.email)
    now = utcnow()
    user.email = new_email
    user.email_verified_at = now
    # Links still waiting in the old inbox (password reset, confirmation) stop working.
    await db.execute(
        update(OneTimeToken)
        .where(OneTimeToken.user_id == user.id, OneTimeToken.used_at.is_(None))
        .values(used_at=now)
    )
    await db.flush()
    await audit.record(
        db,
        "auth.email_changed",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details={
            "old_email_digest": subject_digest(old_email),
            "new_email_digest": subject_digest(new_email),
        },
    )
    return emails.email_changed(settings, old_email, user.display_name, new_email)
