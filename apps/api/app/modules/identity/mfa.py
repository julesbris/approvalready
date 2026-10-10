"""Two-step sign-in (Milestone 18): authenticator apps (TOTP) and recovery codes.

Sign-in with two-step sign-in on is two requests. ``POST /v1/auth/login`` checks the
password and, instead of a session, opens a short-lived *challenge* (an opaque token in an
HttpOnly cookie, its digest in Redis with the user id and an attempt count).
``POST /v1/auth/login/mfa`` then takes a code and only then creates the session, marked
``mfa_verified_at``. Platform staff routes require such a session (``staff_mfa_satisfied``).

Wrong codes count against the account (``mfa-acct``, like failed passwords) and against
the challenge (at most ``CHALLENGE_MAX_ATTEMPTS``, then the password is needed again).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from fastapi import status
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import totp
from app.core.config import Settings
from app.core.crypto import SealedValueError, seal, unseal
from app.core.email import OutgoingEmail
from app.core.errors import ApiError, rate_limited
from app.core.ratelimit import Limit, RateLimiter
from app.core.security import hash_token, new_token, verify_password
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity import emails
from app.modules.identity.models import (
    AppUser,
    AuthSession,
    MfaRecoveryCode,
    MfaTotp,
    PasswordCredential,
)

SEAL_PURPOSE = "mfa-totp"
RECOVERY_CODE_COUNT = 10
CHALLENGE_PREFIX = "mfa:challenge:"
CHALLENGE_MAX_ATTEMPTS = 5
_RECOVERY_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # no 0/o, 1/l: easy to copy by hand


def utcnow() -> datetime:
    return datetime.now(UTC)


def _secret_key(settings: Settings) -> str:
    return settings.secret_key.get_secret_value()


def failure_limit(settings: Settings) -> Limit:
    return Limit("mfa-acct", settings.mfa_max_failures_per_account, settings.login_window_seconds)


def invalid_code() -> ApiError:
    return ApiError(
        status.HTTP_400_BAD_REQUEST,
        "invalid_code",
        "That code didn't work. Check your authenticator app and try again.",
    )


# --- Recovery codes --------------------------------------------------------------------


def new_recovery_code() -> str:
    """16 characters (80 bits) shown as four groups: ``abcd-efgh-jkmn-pqrs``."""
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(16))
    return "-".join(raw[i : i + 4] for i in range(0, 16, 4))


def _recovery_digest(code: str) -> bytes:
    normalised = "".join(ch for ch in code.lower() if ch.isalnum())
    return hashlib.sha256(b"mfa-recovery:" + normalised.encode()).digest()


async def _replace_recovery_codes(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
    codes = [new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    db.add_all(MfaRecoveryCode(user_id=user_id, code_hash=_recovery_digest(c)) for c in codes)
    await db.flush()
    return codes


async def recovery_codes_left(db: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(MfaRecoveryCode)
                .where(MfaRecoveryCode.user_id == user_id, MfaRecoveryCode.used_at.is_(None))
            )
        ).scalar_one()
    )


# --- State -----------------------------------------------------------------------------


async def get_totp(db: AsyncSession, user_id: uuid.UUID, *, lock: bool = False) -> MfaTotp | None:
    stmt = select(MfaTotp).where(MfaTotp.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def is_enabled(db: AsyncSession, user_id: uuid.UUID) -> bool:
    row = await get_totp(db, user_id)
    return row is not None and row.confirmed_at is not None


async def staff_mfa_satisfied(
    db: AsyncSession, settings: Settings, user_id: uuid.UUID, session: AuthSession
) -> bool:
    """Platform staff routes: the user has two-step sign-in on and this session passed it."""
    if not settings.staff_mfa_required:
        return True
    return session.mfa_verified_at is not None and await is_enabled(db, user_id)


def _secret_of(settings: Settings, row: MfaTotp) -> str:
    try:
        return unseal(_secret_key(settings), SEAL_PURPOSE, row.secret_sealed).decode()
    except SealedValueError as exc:
        # SECRET_KEY changed since the app was set up: only a reset helps.
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "mfa_unreadable",
            "Two-step sign-in can't be checked for this account. Contact support to reset it.",
        ) from exc


async def _password_ok(db: AsyncSession, user_id: uuid.UUID, password: str) -> bool:
    credential = (
        await db.execute(select(PasswordCredential).where(PasswordCredential.user_id == user_id))
    ).scalar_one_or_none()
    return verify_password(credential.password_hash if credential else None, password)


# --- Checking a code -------------------------------------------------------------------


@dataclass(frozen=True)
class CodeCheck:
    method: str  # "totp" or "recovery"
    recovery_codes_left: int | None = None


async def _match_code(
    db: AsyncSession, settings: Settings, user_id: uuid.UUID, code: str
) -> CodeCheck | None:
    row = await get_totp(db, user_id, lock=True)
    if row is None or row.confirmed_at is None:
        return None
    normalised = totp.normalise_code(code)
    if normalised.isdigit():
        secret = _secret_of(settings, row)
        step = totp.matching_step(secret, normalised, after_step=row.last_used_step)
        if step is None:
            return None
        row.last_used_step = step
        return CodeCheck("totp")
    recovery = (
        await db.execute(
            select(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.user_id == user_id,
                MfaRecoveryCode.code_hash == _recovery_digest(code),
                MfaRecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if recovery is None:
        return None
    recovery.used_at = utcnow()
    await db.flush()
    return CodeCheck("recovery", await recovery_codes_left(db, user_id))


async def check_code(
    db: AsyncSession,
    settings: Settings,
    limiter: RateLimiter,
    user: AppUser,
    code: str,
    meta: RequestMeta,
) -> CodeCheck:
    """An authenticator or recovery code for ``user``. Wrong codes are counted and audited
    (committed before the error, like failed passwords)."""
    limit = failure_limit(settings)
    subject = str(user.id)
    if await limiter.exceeded(limit, subject):
        raise rate_limited(await limiter.retry_after(limit, subject))
    found = await _match_code(db, settings, user.id, code)
    if found is None:
        await limiter.hit(limit, subject)
        await audit.record(
            db,
            "auth.mfa.failed",
            actor_user_id=user.id,
            meta=meta,
            target_type="app_user",
            target_id=user.id,
        )
        await db.commit()
        raise invalid_code()
    await limiter.reset(limit, subject)
    return found


def recovery_email(settings: Settings, user: AppUser, check: CodeCheck) -> OutgoingEmail | None:
    if check.method != "recovery":
        return None
    return emails.mfa_recovery_code_used(
        settings, user.email, user.display_name, check.recovery_codes_left or 0
    )


# --- Setting up, turning off -----------------------------------------------------------


@dataclass(frozen=True)
class Setup:
    secret: str
    otpauth_uri: str
    qr_svg: str


async def begin_setup(
    db: AsyncSession, settings: Settings, user: AppUser, password: str, meta: RequestMeta
) -> Setup:
    """A new secret for the user's authenticator app (needs the password). Replaces an
    earlier unfinished setup; refused while two-step sign-in is on."""
    if not await _password_ok(db, user.id, password):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_credentials", "Your password is incorrect."
        )
    row = await get_totp(db, user.id, lock=True)
    if row is not None and row.confirmed_at is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "mfa_already_enabled",
            "Two-step sign-in is already on. Turn it off first to use a different app.",
        )
    secret = totp.new_secret()
    sealed = seal(_secret_key(settings), SEAL_PURPOSE, secret.encode())
    if row is None:
        db.add(MfaTotp(user_id=user.id, secret_sealed=sealed))
    else:
        row.secret_sealed = sealed
        row.last_used_step = None
    await audit.record(
        db,
        "auth.mfa.setup_started",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
    )
    uri = totp.provisioning_uri(secret, user.email, settings.mfa_issuer)
    return Setup(secret=secret, otpauth_uri=uri, qr_svg=totp.qr_svg(uri))


async def confirm_setup(
    db: AsyncSession,
    settings: Settings,
    limiter: RateLimiter,
    user: AppUser,
    session: AuthSession,
    code: str,
    meta: RequestMeta,
) -> tuple[str, list[str], OutgoingEmail]:
    """Turn two-step sign-in on with the first code from the app. Returns this session's new
    token (rotated: a privilege change), the recovery codes (shown once) and the notice
    email. Other sessions are signed out: they never passed the second step."""
    row = await get_totp(db, user.id, lock=True)
    if row is None or row.confirmed_at is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "mfa_setup_missing",
            "Start setting up two-step sign-in again.",
        )
    limit = failure_limit(settings)
    subject = str(user.id)
    if await limiter.exceeded(limit, subject):
        raise rate_limited(await limiter.retry_after(limit, subject))
    step = totp.matching_step(_secret_of(settings, row), code)
    if step is None:
        await limiter.hit(limit, subject)
        raise invalid_code()
    await limiter.reset(limit, subject)
    now = utcnow()
    row.confirmed_at = now
    row.last_used_step = step
    codes = await _replace_recovery_codes(db, user.id)
    session.mfa_verified_at = now
    from app.modules.identity import service as identity

    revoked = await identity.revoke_all_sessions(db, user.id, "mfa_enabled", except_id=session.id)
    token = identity.rotate_session_strict(session)
    await audit.record(
        db,
        "auth.mfa.enabled",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details={"sessions_revoked": revoked},
    )
    return token, codes, emails.mfa_enabled(settings, user.email, user.display_name)


async def disable(
    db: AsyncSession,
    settings: Settings,
    limiter: RateLimiter,
    user: AppUser,
    *,
    password: str,
    code: str,
    meta: RequestMeta,
) -> OutgoingEmail:
    """Turn two-step sign-in off: needs the password and a current code (or a recovery
    code), so a borrowed signed-in browser alone can't do it."""
    if not await is_enabled(db, user.id):
        raise ApiError(status.HTTP_409_CONFLICT, "mfa_not_enabled", "Two-step sign-in is off.")
    if not await _password_ok(db, user.id, password):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "invalid_credentials", "Your password is incorrect."
        )
    await check_code(db, settings, limiter, user, code, meta)
    await _remove(db, user.id)
    await audit.record(
        db,
        "auth.mfa.disabled",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
    )
    return emails.mfa_disabled(settings, user.email, user.display_name)


async def _remove(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
    await db.execute(delete(MfaTotp).where(MfaTotp.user_id == user_id))


async def regenerate_recovery_codes(
    db: AsyncSession,
    settings: Settings,
    limiter: RateLimiter,
    user: AppUser,
    code: str,
    meta: RequestMeta,
) -> list[str]:
    """New recovery codes (the old ones stop working); needs a current code."""
    if not await is_enabled(db, user.id):
        raise ApiError(status.HTTP_409_CONFLICT, "mfa_not_enabled", "Two-step sign-in is off.")
    await check_code(db, settings, limiter, user, code, meta)
    codes = await _replace_recovery_codes(db, user.id)
    await audit.record(
        db,
        "auth.mfa.recovery_codes_regenerated",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
    )
    return codes


async def reset_for_user(db: AsyncSession, user: AppUser, meta: RequestMeta) -> bool:
    """Operator reset (lost phone and codes): remove two-step sign-in and sign the user out
    everywhere. Returns whether anything was removed."""
    from app.modules.identity import service as identity

    had = await get_totp(db, user.id) is not None
    await _remove(db, user.id)
    revoked = await identity.revoke_all_sessions(db, user.id, "mfa_reset")
    await audit.record(
        db,
        "auth.mfa.reset",
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details={"sessions_revoked": revoked, "had_mfa": had},
    )
    return had


# --- The sign-in challenge -------------------------------------------------------------


def _challenge_key(token: str) -> str:
    return CHALLENGE_PREFIX + base64.urlsafe_b64encode(hash_token(token)).decode()


async def start_challenge(redis: Redis, settings: Settings, user_id: uuid.UUID) -> str:
    token = new_token()
    key = _challenge_key(token)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(key, mapping={"user": str(user_id), "attempts": 0})
        pipe.expire(key, settings.mfa_challenge_seconds)
        await pipe.execute()
    return token


async def challenge_attempt(redis: Redis, token: str) -> uuid.UUID | None:
    """Count one attempt on the challenge and return its user, or None if the challenge
    is unknown, expired or out of attempts (then it is closed)."""
    key = _challenge_key(token)
    user = await cast(Awaitable[str | None], redis.hget(key, "user"))
    if user is None:
        return None
    attempts = await cast(Awaitable[int], redis.hincrby(key, "attempts", 1))
    if attempts > CHALLENGE_MAX_ATTEMPTS:
        await redis.delete(key)
        return None
    return uuid.UUID(user)


async def end_challenge(redis: Redis, token: str) -> None:
    await redis.delete(_challenge_key(token))
