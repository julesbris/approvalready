"""Staff view of people's accounts (Milestone 27): find an account, see its organisations,
sign-in state and recent activity, and do the support jobs that used to need a server
command (resend the verification email, send a password reset link, sign out everywhere,
reset two-step sign-in, suspend and restore).

Rules:

* Reading needs ``platform.users.read`` (every platform role); changing needs
  ``platform.users.manage`` (ADMIN and SUPERADMIN).
* Nobody acts on their own account here (the Account page is for that).
* Accounts that hold a platform role can only be changed by someone who can grant platform
  roles (SUPERADMIN), so an administrator can't lock out a super administrator.
* Every change, and every staff view of an account, is in the audit log with who did it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import OutgoingEmail
from app.core.errors import ApiError, forbidden, not_found
from app.core.ratelimit import RateLimiter
from app.modules.accounts.schemas import (
    AccountDetail,
    AccountEvent,
    AccountMembership,
    AccountSession,
    AccountSummary,
)
from app.modules.audit import service as audit
from app.modules.audit.models import AuditEvent
from app.modules.audit.service import RequestMeta
from app.modules.identity import emails, mfa
from app.modules.identity import service as identity
from app.modules.identity.models import (
    AppUser,
    AuthSession,
    MfaTotp,
    PasswordCredential,
    TokenPurpose,
    UserStatus,
)
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import (
    MemberRole,
    MemberStatus,
    Organisation,
    OrganisationKind,
    OrganisationMember,
    Role,
)
from app.modules.tenancy.rbac import Perm, RoleKey

SEARCH_LIMIT = 50
EVENTS_LIMIT = 40
# One "viewed" audit row per staff member and account in this window, not one per page load.
VIEW_AUDIT_WINDOW = timedelta(minutes=30)
VIEWED_ACTION = "admin.account.viewed"

PLATFORM_ROLE_RANK: dict[str, int] = {RoleKey.STAFF: 1, RoleKey.ADMIN: 2, RoleKey.SUPERADMIN: 3}

# Actions that need a reason, kept in the audit log.
NEEDS_REASON = frozenset({"reset_two_step", "suspend"})


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Staff:
    user_id: uuid.UUID
    permissions: frozenset[str]


# --- Reading ---------------------------------------------------------------------------


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _platform_members() -> Select[uuid.UUID]:
    return (
        select(OrganisationMember.user_id)
        .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
        .join(MemberRole, MemberRole.organisation_member_id == OrganisationMember.id)
        .where(
            Organisation.kind == OrganisationKind.PLATFORM_ADMIN,
            Organisation.deleted_at.is_(None),
            OrganisationMember.status == MemberStatus.ACTIVE,
        )
    )


async def search(db: AsyncSession, query: str, status_filter: str | None) -> list[AccountSummary]:
    """Newest accounts first, matching the email, name, a business name or ABN, or an exact
    account id. An empty query lists the newest accounts."""
    stmt = select(AppUser)
    q = query.strip()
    if q:
        conditions: list[ColumnElement[bool]] = [
            AppUser.email.ilike(_like(q), escape="\\"),
            AppUser.display_name.ilike(_like(q), escape="\\"),
        ]
        org_match: list[ColumnElement[bool]] = [Organisation.name.ilike(_like(q), escape="\\")]
        digits = q.replace(" ", "")
        if digits.isdigit() and len(digits) == 11:
            org_match.append(Organisation.abn == digits)
        conditions.append(
            AppUser.id.in_(
                select(OrganisationMember.user_id)
                .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
                .where(
                    Organisation.kind != OrganisationKind.PERSONAL,
                    Organisation.deleted_at.is_(None),
                    or_(*org_match),
                )
            )
        )
        with suppress(ValueError):
            conditions.append(AppUser.id == uuid.UUID(q))
        stmt = stmt.where(or_(*conditions))
    if status_filter == "ACTIVE":
        stmt = stmt.where(
            AppUser.status == UserStatus.ACTIVE,
            AppUser.deleted_at.is_(None),
            AppUser.email_verified_at.is_not(None),
        )
    elif status_filter == "SUSPENDED":
        stmt = stmt.where(
            AppUser.status.in_([UserStatus.SUSPENDED, UserStatus.LOCKED]),
            AppUser.deleted_at.is_(None),
        )
    elif status_filter == "UNVERIFIED":
        stmt = stmt.where(AppUser.email_verified_at.is_(None), AppUser.deleted_at.is_(None))
    elif status_filter == "CLOSED":
        stmt = stmt.where(AppUser.deleted_at.is_not(None))
    elif status_filter == "STAFF":
        stmt = stmt.where(AppUser.id.in_(_platform_members()))
    users = list(
        (
            await db.execute(
                stmt.order_by(AppUser.created_at.desc(), AppUser.id).limit(SEARCH_LIMIT)
            )
        ).scalars()
    )
    return await _summaries(db, users)


async def _platform_roles(db: AsyncSession, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = await db.execute(
        select(OrganisationMember.user_id, Role.key)
        .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
        .join(MemberRole, MemberRole.organisation_member_id == OrganisationMember.id)
        .join(Role, Role.id == MemberRole.role_id)
        .where(
            Organisation.kind == OrganisationKind.PLATFORM_ADMIN,
            Organisation.deleted_at.is_(None),
            OrganisationMember.status == MemberStatus.ACTIVE,
            OrganisationMember.user_id.in_(list(user_ids)),
        )
    )
    best: dict[uuid.UUID, str] = {}
    for user_id, key in rows.all():
        rank = PLATFORM_ROLE_RANK.get(key, 0)
        if rank > PLATFORM_ROLE_RANK.get(best.get(user_id, ""), 0):
            best[user_id] = key
    return best


async def _summaries(db: AsyncSession, users: list[AppUser]) -> list[AccountSummary]:
    if not users:
        return []
    ids = [u.id for u in users]
    with_mfa = set(
        (
            await db.execute(
                select(MfaTotp.user_id).where(
                    MfaTotp.user_id.in_(ids), MfaTotp.confirmed_at.is_not(None)
                )
            )
        ).scalars()
    )
    org_counts = dict(
        (
            await db.execute(
                select(OrganisationMember.user_id, func.count())
                .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
                .where(
                    OrganisationMember.user_id.in_(ids),
                    OrganisationMember.status == MemberStatus.ACTIVE,
                    Organisation.deleted_at.is_(None),
                    Organisation.kind != OrganisationKind.PLATFORM_ADMIN,
                )
                .group_by(OrganisationMember.user_id)
            )
        ).all()
    )
    roles = await _platform_roles(db, ids)
    return [
        AccountSummary(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            status=u.status,
            email_verified=u.email_verified_at is not None,
            mfa_enabled=u.id in with_mfa,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
            closed=u.deleted_at is not None,
            platform_role=roles.get(u.id),
            organisations=int(org_counts.get(u.id, 0)),
        )
        for u in users
    ]


async def _memberships(db: AsyncSession, user_id: uuid.UUID) -> list[AccountMembership]:
    rows = (
        await db.execute(
            select(Organisation, OrganisationMember)
            .join(OrganisationMember, OrganisationMember.organisation_id == Organisation.id)
            .where(OrganisationMember.user_id == user_id, Organisation.deleted_at.is_(None))
            .order_by(
                OrganisationMember.status != MemberStatus.ACTIVE,
                Organisation.kind != OrganisationKind.PERSONAL,
                Organisation.name,
            )
        )
    ).all()
    return [
        AccountMembership(
            organisation_id=org.id,
            name=org.name,
            kind=org.kind,
            organisation_status=org.status,
            abn=org.abn,
            member_status=member.status,
            roles=list(await tenancy.member_role_keys(db, member.id)),
            joined_at=member.created_at,
        )
        for org, member in rows
    ]


def _live_sessions(user_id: uuid.UUID) -> Select[AuthSession]:
    now = utcnow()
    return select(AuthSession).where(
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > now,
        AuthSession.idle_expires_at > now,
    )


async def _events(db: AsyncSession, user: AppUser) -> list[AccountEvent]:
    rows = list(
        (
            await db.execute(
                select(AuditEvent)
                .where(
                    or_(
                        AuditEvent.actor_user_id == user.id,
                        and_(
                            AuditEvent.target_type == "app_user",
                            AuditEvent.target_id == str(user.id),
                        ),
                    ),
                    AuditEvent.action != VIEWED_ACTION,
                )
                .order_by(AuditEvent.seq.desc())
                .limit(EVENTS_LIMIT)
            )
        ).scalars()
    )
    others = {e.actor_user_id for e in rows if e.actor_user_id not in (None, user.id)}
    emails_by_id: dict[uuid.UUID, str] = {}
    if others:
        emails_by_id = dict(
            (
                await db.execute(select(AppUser.id, AppUser.email).where(AppUser.id.in_(others)))
            ).all()
        )
    return [
        AccountEvent(
            seq=e.seq,
            occurred_at=e.occurred_at,
            action=e.action,
            by="system"
            if e.actor_user_id is None
            else "self"
            if e.actor_user_id == user.id
            else "other",
            actor_email=emails_by_id.get(e.actor_user_id) if e.actor_user_id else None,
            ip=e.ip,
            details=e.details,
        )
        for e in rows
    ]


def allowed_actions(
    staff: Staff,
    user: AppUser,
    *,
    platform_role: str | None,
    has_two_step: bool,
    live_sessions: int,
) -> list[str]:
    """What ``staff`` may do to ``user`` now, in display order."""
    if (
        user.id == staff.user_id
        or user.deleted_at is not None
        or Perm.PLATFORM_USERS_MANAGE not in staff.permissions
        or (platform_role and Perm.PLATFORM_ROLES_MANAGE not in staff.permissions)
    ):
        return []
    active = user.status == UserStatus.ACTIVE
    actions = []
    if active and user.email_verified_at is None:
        actions.append("resend_verification")
    if active:
        actions.append("send_password_reset")
    if live_sessions:
        actions.append("sign_out_everywhere")
    if has_two_step:
        actions.append("reset_two_step")
    if active:
        actions.append("suspend")
    if user.status in (UserStatus.SUSPENDED, UserStatus.LOCKED):
        actions.append("restore")
    return actions


async def _load(db: AsyncSession, user_id: uuid.UUID, *, lock: bool = False) -> AppUser:
    stmt = select(AppUser).where(AppUser.id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise not_found("Account")
    return user


async def detail(db: AsyncSession, staff: Staff, user_id: uuid.UUID) -> AccountDetail:
    user = await _load(db, user_id)
    (summary,) = await _summaries(db, [user])
    credential = (
        await db.execute(select(PasswordCredential).where(PasswordCredential.user_id == user.id))
    ).scalar_one_or_none()
    sessions = list(
        (await db.execute(_live_sessions(user.id).order_by(AuthSession.last_seen_at.desc())))
        .scalars()
        .all()
    )
    has_two_step = await mfa.get_totp(db, user.id) is not None
    return AccountDetail(
        **summary.model_dump(),
        password_set=credential is not None,
        password_changed_at=credential.password_changed_at if credential else None,
        recovery_codes_left=await mfa.recovery_codes_left(db, user.id) if has_two_step else 0,
        memberships=await _memberships(db, user.id),
        sessions=[
            AccountSession(
                id=s.id,
                surface=s.surface,
                ip=s.ip,
                user_agent=s.user_agent,
                created_at=s.created_at,
                last_seen_at=s.last_seen_at,
                expires_at=s.expires_at,
            )
            for s in sessions
        ],
        events=await _events(db, user),
        allowed_actions=allowed_actions(
            staff,
            user,
            platform_role=summary.platform_role,
            has_two_step=has_two_step,
            live_sessions=len(sessions),
        ),
    )


async def record_view(
    db: AsyncSession, staff: Staff, user_id: uuid.UUID, meta: RequestMeta
) -> None:
    """Audit that a staff member opened this account (at most once per window)."""
    recent = (
        await db.execute(
            select(AuditEvent.id)
            .where(
                AuditEvent.action == VIEWED_ACTION,
                AuditEvent.actor_user_id == staff.user_id,
                AuditEvent.target_id == str(user_id),
                AuditEvent.occurred_at > utcnow() - VIEW_AUDIT_WINDOW,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if recent is None:
        await audit.record(
            db,
            VIEWED_ACTION,
            actor_user_id=staff.user_id,
            meta=meta,
            target_type="app_user",
            target_id=user_id,
        )


# --- Support actions -------------------------------------------------------------------


@dataclass(frozen=True)
class ActionResult:
    message: str
    email: OutgoingEmail | None = None


async def perform(
    db: AsyncSession,
    settings: Settings,
    limiter: RateLimiter,
    staff: Staff,
    user_id: uuid.UUID,
    action: str,
    reason: str,
    meta: RequestMeta,
) -> ActionResult:
    user = await _load(db, user_id, lock=True)
    if user.id == staff.user_id:
        raise forbidden("Use your own Account page to change your own account.")
    platform_role = (await _platform_roles(db, [user.id])).get(user.id)
    if platform_role and Perm.PLATFORM_ROLES_MANAGE not in staff.permissions:
        raise forbidden("Only a super administrator can change a staff member's account.")
    reason = reason.strip()
    if action in NEEDS_REASON and not reason:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "reason_required",
            "Say why (for example how you confirmed who you were talking to).",
            fields={"reason": "Required."},
        )
    live = int(
        (
            await db.execute(select(func.count()).select_from(_live_sessions(user.id).subquery()))
        ).scalar_one()
    )
    possible = allowed_actions(
        staff,
        user,
        platform_role=platform_role,
        has_two_step=await mfa.get_totp(db, user.id) is not None,
        live_sessions=live,
    )
    if action not in possible:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "action_not_available",
            "That can't be done to this account in its current state. Reload the page.",
        )

    details: dict[str, object] = {"via": "admin"}
    if reason:
        details["reason"] = reason
    result: ActionResult
    if action == "resend_verification":
        token = await identity.issue_token(
            db,
            user.id,
            TokenPurpose.EMAIL_VERIFY,
            timedelta(hours=settings.email_verification_ttl_hours),
        )
        result = ActionResult(
            f"A new verification link is on its way to {user.email}.",
            emails.verify_email(settings, user.email, user.display_name, token),
        )
        audit_action = "admin.account.verification_resent"
    elif action == "send_password_reset":
        token = await identity.issue_token(
            db,
            user.id,
            TokenPurpose.PASSWORD_RESET,
            timedelta(minutes=settings.password_reset_ttl_minutes),
        )
        result = ActionResult(
            f"A password reset link is on its way to {user.email}. It works for "
            f"{settings.password_reset_ttl_minutes} minutes.",
            emails.password_reset(settings, user.email, user.display_name, token),
        )
        audit_action = "admin.account.password_reset_sent"
    elif action == "sign_out_everywhere":
        details["sessions_revoked"] = await identity.revoke_all_sessions(
            db, user.id, "staff_sign_out"
        )
        result = ActionResult("Signed out on every device.")
        audit_action = "admin.account.signed_out"
    elif action == "reset_two_step":
        await mfa.remove(db, user.id)
        details["sessions_revoked"] = await identity.revoke_all_sessions(db, user.id, "mfa_reset")
        result = ActionResult(
            "Two-step sign-in is off and they are signed out everywhere. They can sign in with "
            "their password and set it up again from Account.",
            emails.mfa_disabled(settings, user.email, user.display_name),
        )
        audit_action = "auth.mfa.reset"
    elif action == "suspend":
        user.status = UserStatus.SUSPENDED
        details["sessions_revoked"] = await identity.revoke_all_sessions(
            db, user.id, "account_suspended"
        )
        result = ActionResult(
            "Suspended. They are signed out and can't sign in, reset their password or use "
            "links already sent until the account is restored."
        )
        audit_action = "admin.account.suspended"
    else:  # restore
        details["previous_status"] = user.status
        user.status = UserStatus.ACTIVE
        result = ActionResult("Restored. They can sign in again.")
        audit_action = "admin.account.restored"

    if result.email is not None:
        limits = identity.AuthLimits.from_settings(settings)
        if not await identity.may_email(limiter, limits, result.email.kind, result.email.to):
            raise ApiError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "email_limit",
                "That address has had too many of these emails in the last hour. Try later.",
            )
    await audit.record(
        db,
        audit_action,
        actor_user_id=staff.user_id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details=details,
    )
    await db.flush()
    return result
