"""Registration, email verification, login, sessions and password management.

Enumeration resistance: registration, verification resend and password-reset requests
return the same response whether or not the address is registered. The only place an
account's existence becomes visible is after a correct password (e.g. "email not verified").
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.breach import BreachChecker
from app.core.config import Settings
from app.core.email import EmailProvider, OutgoingEmail
from app.core.errors import ApiError, rate_limited
from app.core.ratelimit import Limit, RateLimiter, subject_digest
from app.core.security import (
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    verify_password,
)
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity import emails
from app.modules.identity.models import (
    AppUser,
    AuthSession,
    OneTimeToken,
    PasswordCredential,
    TokenPurpose,
    UserStatus,
)
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import OrganisationKind

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def validate_password(settings: Settings, password: str, email: str) -> None:
    problem = None
    if len(password) < settings.password_min_length:
        problem = f"Use at least {settings.password_min_length} characters."
    elif len(password) > 256:
        problem = "Use at most 256 characters."
    elif password.strip().lower() == email.strip().lower():
        problem = "Don't use your email address as your password."
    if problem:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, "weak_password", problem)


async def ensure_not_breached(breach: BreachChecker | None, password: str) -> None:
    """Refuse passwords that appear in known data breaches (Have I Been Pwned)."""
    if breach is None:
        return
    seen = await breach.times_seen(password)
    if seen:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "breached_password",
            "This password has appeared in a data breach, so attackers try it first. "
            "Choose a different one.",
        )


async def send_email(provider: EmailProvider, message: OutgoingEmail) -> None:
    """Send after the transaction commits. Failures are logged, never shown to the user
    (which would also reveal whether an address is registered)."""
    try:
        await provider.send(message)
    except Exception:
        logger.exception("email send failed", extra={"kind": message.kind})


# --- Throttling ------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthLimits:
    login_account: Limit
    login_ip: Limit
    requests_ip: Limit
    emails_address: Limit

    @classmethod
    def from_settings(cls, s: Settings) -> AuthLimits:
        return cls(
            login_account=Limit(
                "login-acct", s.login_max_failures_per_account, s.login_window_seconds
            ),
            login_ip=Limit("login-ip", s.login_max_failures_per_ip, s.login_window_seconds),
            requests_ip=Limit("auth-ip", s.auth_requests_per_ip_per_minute, 60),
            emails_address=Limit("auth-mail", s.auth_emails_per_address_per_hour, 3600),
        )


async def guard_request_rate(limiter: RateLimiter, limits: AuthLimits, ip: str | None) -> None:
    subject = ip or "unknown"
    if await limiter.hit(limits.requests_ip, subject) > limits.requests_ip.max_hits:
        raise rate_limited(await limiter.retry_after(limits.requests_ip, subject))


async def may_email(limiter: RateLimiter, limits: AuthLimits, kind: str, email: str) -> bool:
    """Caps emails of one kind per address, so the API can't be used to mail-bomb someone."""
    subject = f"{kind}:{subject_digest(email)}"
    return await limiter.hit(limits.emails_address, subject) <= limits.emails_address.max_hits


# --- One-time tokens -------------------------------------------------------------------


async def issue_token(
    db: AsyncSession, user_id: uuid.UUID, purpose: TokenPurpose, ttl: timedelta
) -> str:
    now = utcnow()
    # Only the newest link of each kind works.
    await db.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == user_id,
            OneTimeToken.purpose == purpose,
            OneTimeToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    token = new_token()
    db.add(
        OneTimeToken(
            user_id=user_id, purpose=purpose, token_hash=hash_token(token), expires_at=now + ttl
        )
    )
    await db.flush()
    return token


async def consume_token(db: AsyncSession, token: str, purpose: TokenPurpose) -> AppUser:
    row = (
        await db.execute(
            select(OneTimeToken)
            .where(OneTimeToken.token_hash == hash_token(token), OneTimeToken.purpose == purpose)
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = utcnow()
    user = await db.get(AppUser, row.user_id) if row else None
    if row is None or row.used_at is not None or row.expires_at <= now or user is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "invalid_token",
            "This link is invalid, expired or already used. Request a new one.",
        )
    if user.deleted_at is not None or user.status != UserStatus.ACTIVE:
        raise ApiError(status.HTTP_403_FORBIDDEN, "account_unavailable", "Account unavailable.")
    row.used_at = now
    return user


# --- Registration and verification -----------------------------------------------------


async def get_user_by_email(db: AsyncSession, email: str) -> AppUser | None:
    return (
        await db.execute(
            select(AppUser).where(
                AppUser.email == normalise_email(email), AppUser.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()


async def register(
    db: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    display_name: str,
    meta: RequestMeta,
    breach: BreachChecker | None = None,
) -> OutgoingEmail:
    """Create the user and their PERSONAL organisation. Returns the email to send."""
    email = normalise_email(email)
    validate_password(settings, password, email)
    await ensure_not_breached(breach, password)
    existing = await get_user_by_email(db, email)
    if existing is not None:
        await audit.record(
            db,
            "auth.register.duplicate",
            actor_user_id=existing.id,
            meta=meta,
            target_type="app_user",
            target_id=existing.id,
        )
        return emails.already_registered(settings, email)

    user = AppUser(email=email, display_name=display_name.strip())
    db.add(user)
    await db.flush()
    db.add(PasswordCredential(user_id=user.id, password_hash=hash_password(password)))
    await tenancy.create_organisation(
        db, creator=user, kind=OrganisationKind.PERSONAL, name=user.display_name, meta=meta
    )
    token = await issue_token(
        db,
        user.id,
        TokenPurpose.EMAIL_VERIFY,
        timedelta(hours=settings.email_verification_ttl_hours),
    )
    await audit.record(
        db,
        "auth.registered",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
    )
    return emails.verify_email(settings, email, user.display_name, token)


async def resend_verification(
    db: AsyncSession, settings: Settings, email: str
) -> OutgoingEmail | None:
    user = await get_user_by_email(db, email)
    if user is None or user.email_verified_at is not None or user.status != UserStatus.ACTIVE:
        return None
    token = await issue_token(
        db,
        user.id,
        TokenPurpose.EMAIL_VERIFY,
        timedelta(hours=settings.email_verification_ttl_hours),
    )
    return emails.verify_email(settings, user.email, user.display_name, token)


async def verify_email(db: AsyncSession, token: str, meta: RequestMeta) -> AppUser:
    user = await consume_token(db, token, TokenPurpose.EMAIL_VERIFY)
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
        await audit.record(
            db,
            "auth.email_verified",
            actor_user_id=user.id,
            meta=meta,
            target_type="app_user",
            target_id=user.id,
        )
    return user


# --- Login -----------------------------------------------------------------------------


async def authenticate(
    db: AsyncSession,
    limiter: RateLimiter,
    limits: AuthLimits,
    *,
    email: str,
    password: str,
    meta: RequestMeta,
) -> AppUser:
    email = normalise_email(email)
    account_key = subject_digest(email)
    ip_key = meta.ip or "unknown"
    for limit, key in ((limits.login_account, account_key), (limits.login_ip, ip_key)):
        if await limiter.exceeded(limit, key):
            raise rate_limited(await limiter.retry_after(limit, key))

    user = await get_user_by_email(db, email)
    credential = (
        (
            await db.execute(
                select(PasswordCredential).where(PasswordCredential.user_id == user.id)
            )
        ).scalar_one_or_none()
        if user
        else None
    )
    # Always runs Argon2 (against a dummy hash for unknown users): constant-ish timing.
    ok = verify_password(credential.password_hash if credential else None, password)

    if not ok or user is None or credential is None:
        await limiter.hit(limits.login_account, account_key)
        await limiter.hit(limits.login_ip, ip_key)
        await audit.record(
            db,
            "auth.login.failed",
            actor_user_id=user.id if user else None,
            meta=meta,
            details={"email_digest": account_key},
        )
        await db.commit()
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "Email or password is incorrect."
        )
    if user.status != UserStatus.ACTIVE:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "account_unavailable",
            "This account is not available. Contact support.",
        )
    if user.email_verified_at is None:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "email_not_verified",
            "Confirm your email address first. We can send you a new link.",
        )
    await limiter.reset(limits.login_account, account_key)
    if password_needs_rehash(credential.password_hash):
        credential.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    return user


# --- Sessions --------------------------------------------------------------------------


@dataclass
class IssuedSession:
    session: AuthSession
    token: str


async def create_session(
    db: AsyncSession,
    settings: Settings,
    user: AppUser,
    meta: RequestMeta,
    *,
    mfa_method: str | None = None,
) -> IssuedSession:
    now = utcnow()
    token = new_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        active_organisation_id=await tenancy.personal_organisation_id(db, user.id),
        ip=meta.ip,
        user_agent=meta.user_agent[:512] if meta.user_agent else None,
        last_seen_at=now,
        rotated_at=now,
        idle_expires_at=now + timedelta(minutes=settings.session_idle_minutes),
        expires_at=now + timedelta(days=settings.session_absolute_days),
        mfa_verified_at=now if mfa_method else None,
    )
    db.add(session)
    await db.flush()
    await audit.record(
        db,
        "auth.login.succeeded",
        actor_user_id=user.id,
        meta=meta,
        target_type="auth_session",
        target_id=session.id,
        details={"mfa": mfa_method} if mfa_method else None,
    )
    return IssuedSession(session, token)


async def resolve_session(db: AsyncSession, token: str) -> tuple[AuthSession, AppUser] | None:
    now = utcnow()
    digest = hash_token(token)
    row = (
        await db.execute(
            select(AuthSession, AppUser)
            .join(AppUser, AppUser.id == AuthSession.user_id)
            .where(
                or_(
                    AuthSession.token_hash == digest,
                    (AuthSession.previous_token_hash == digest)
                    & (AuthSession.previous_token_valid_until > now),
                ),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
                AuthSession.idle_expires_at > now,
                AppUser.deleted_at.is_(None),
                AppUser.status == UserStatus.ACTIVE,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    session, user = row
    return session, user


async def touch_session(db: AsyncSession, settings: Settings, session: AuthSession) -> str | None:
    """Slide the idle timeout and rotate the token when due. Returns a new token if rotated."""
    now = utcnow()
    new: str | None = None
    if now - session.rotated_at >= timedelta(minutes=settings.session_rotation_minutes):
        new = rotate_session(settings, session)
    # Write at most once a minute per session to keep reads cheap.
    if new is not None or now - session.last_seen_at >= timedelta(seconds=60):
        session.last_seen_at = now
        session.idle_expires_at = min(
            now + timedelta(minutes=settings.session_idle_minutes), session.expires_at
        )
        await db.flush()
    return new


def rotate_session(settings: Settings, session: AuthSession) -> str:
    """Replace the session token. The old one keeps working for a short grace period so
    concurrent requests that still carry it don't fail."""
    now = utcnow()
    token = new_token()
    session.previous_token_hash = session.token_hash
    session.previous_token_valid_until = now + timedelta(
        seconds=settings.session_rotation_grace_seconds
    )
    session.token_hash = hash_token(token)
    session.rotated_at = now
    return token


def rotate_session_strict(session: AuthSession) -> str:
    """Rotation on a privilege change: the old token stops working immediately."""
    token = new_token()
    session.previous_token_hash = None
    session.previous_token_valid_until = None
    session.token_hash = hash_token(token)
    session.rotated_at = utcnow()
    return token


async def revoke_session(
    db: AsyncSession, session: AuthSession, reason: str, meta: RequestMeta
) -> None:
    session.revoked_at = utcnow()
    session.revoked_reason = reason
    await audit.record(
        db,
        "auth.logout",
        actor_user_id=session.user_id,
        meta=meta,
        target_type="auth_session",
        target_id=session.id,
        details={"reason": reason},
    )


async def revoke_all_sessions(
    db: AsyncSession, user_id: uuid.UUID, reason: str, *, except_id: uuid.UUID | None = None
) -> int:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason)
    )
    if except_id is not None:
        stmt = stmt.where(AuthSession.id != except_id)
    result = await db.execute(stmt)
    return int(result.rowcount)  # type: ignore[attr-defined]


async def switch_organisation(
    db: AsyncSession, session: AuthSession, organisation_id: uuid.UUID, meta: RequestMeta
) -> str:
    if await tenancy.membership(db, session.user_id, organisation_id) is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found", "Organisation not found.")
    previous = session.active_organisation_id
    session.active_organisation_id = organisation_id
    token = rotate_session_strict(session)
    await audit.record(
        db,
        "auth.session.organisation_switched",
        actor_user_id=session.user_id,
        organisation_id=organisation_id,
        meta=meta,
        target_type="auth_session",
        target_id=session.id,
        details={"from": str(previous) if previous else None},
    )
    return token


# --- Passwords -------------------------------------------------------------------------


async def request_password_reset(
    db: AsyncSession, settings: Settings, email: str, meta: RequestMeta
) -> OutgoingEmail | None:
    user = await get_user_by_email(db, email)
    if user is None or user.status != UserStatus.ACTIVE:
        return None
    token = await issue_token(
        db,
        user.id,
        TokenPurpose.PASSWORD_RESET,
        timedelta(minutes=settings.password_reset_ttl_minutes),
    )
    await audit.record(
        db,
        "auth.password_reset.requested",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
    )
    return emails.password_reset(settings, user.email, user.display_name, token)


async def _set_password(db: AsyncSession, user: AppUser, password: str) -> None:
    credential = (
        await db.execute(select(PasswordCredential).where(PasswordCredential.user_id == user.id))
    ).scalar_one_or_none()
    if credential is None:
        db.add(PasswordCredential(user_id=user.id, password_hash=hash_password(password)))
    else:
        credential.password_hash = hash_password(password)
        credential.password_changed_at = utcnow()


async def confirm_password_reset(
    db: AsyncSession,
    settings: Settings,
    token: str,
    password: str,
    meta: RequestMeta,
    breach: BreachChecker | None = None,
) -> OutgoingEmail:
    user = await consume_token(db, token, TokenPurpose.PASSWORD_RESET)
    validate_password(settings, password, user.email)
    await ensure_not_breached(breach, password)
    await _set_password(db, user, password)
    if user.email_verified_at is None:  # the link reached this inbox
        user.email_verified_at = utcnow()
    revoked = await revoke_all_sessions(db, user.id, "password_reset")
    await audit.record(
        db,
        "auth.password_reset.completed",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details={"sessions_revoked": revoked},
    )
    return emails.password_changed(settings, user.email, user.display_name)


async def change_password(
    db: AsyncSession,
    settings: Settings,
    user: AppUser,
    session: AuthSession,
    *,
    current_password: str,
    new_password: str,
    meta: RequestMeta,
    breach: BreachChecker | None = None,
) -> tuple[str, OutgoingEmail]:
    credential = (
        await db.execute(select(PasswordCredential).where(PasswordCredential.user_id == user.id))
    ).scalar_one_or_none()
    if not verify_password(credential.password_hash if credential else None, current_password):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_credentials", "Current password is incorrect."
        )
    validate_password(settings, new_password, user.email)
    await ensure_not_breached(breach, new_password)
    await _set_password(db, user, new_password)
    revoked = await revoke_all_sessions(db, user.id, "password_changed", except_id=session.id)
    token = rotate_session_strict(session)
    await audit.record(
        db,
        "auth.password.changed",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details={"sessions_revoked": revoked},
    )
    return token, emails.password_changed(settings, user.email, user.display_name)
