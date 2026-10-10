"""Privacy and legal (Milestone 19).

* Policy acceptance: registration records agreement to the current Terms of Use and Privacy
  Policy; a signed-in user who hasn't agreed to the current versions is asked again.
* Download my data: everything held about a user's account and their personal workspace,
  as JSON (Australian Privacy Principle 12, access).
* Close my account: the sign-in, name and email are removed straight away; the personal
  workspace is deleted a few days later by the nightly job (``purge.py``, Milestone 29),
  tracked by a DELETION ``privacy_request`` so staff can keep it instead.
* Privacy requests from the contact page, worked by staff at ``/admin/privacy`` within the
  30 days the Australian Privacy Principles expect.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi import status
from sqlalchemy import LargeBinary, Table, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import EmailProvider, OutgoingEmail
from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter
from app.core.security import verify_password
from app.db.base import Base
from app.db.tenant import bind_tenant
from app.modules.audit import service as audit
from app.modules.audit.models import AuditEvent
from app.modules.audit.service import RequestMeta
from app.modules.billing.models import Subscription, SubscriptionStatus
from app.modules.identity import mfa
from app.modules.identity import service as identity
from app.modules.identity.models import (
    AppUser,
    AuthIdentity,
    AuthSession,
    OneTimeToken,
    PasswordCredential,
    UserStatus,
)
from app.modules.leads import service as leads
from app.modules.leads.models import ReferralConsent
from app.modules.notifications import preferences as notification_preferences
from app.modules.notifications.models import NotificationPreference
from app.modules.privacy import emails
from app.modules.privacy.models import (
    PolicyAcceptance,
    PrivacyRequest,
    PrivacyRequestKind,
    PrivacyRequestSource,
    PrivacyRequestStatus,
)
from app.modules.projects.models import Reminder, ReminderStatus
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation, OrganisationKind

logger = logging.getLogger(__name__)

RESPONSE_DAYS = 30
EXPORT_ROW_LIMIT = 10_000
AUDIT_EXPORT_LIMIT = 1_000
# Columns never exported: credentials, token digests and storage internals.
_HIDDEN_COLUMN = re.compile(r"(hash|secret|sealed|token|storage_key|password)")
# Subscriptions that would keep charging a closed account.
_LIVE_SUBSCRIPTION = (
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.TRIALING,
    SubscriptionStatus.PAST_DUE,
    SubscriptionStatus.UNPAID,
    SubscriptionStatus.PAUSED,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- Download my data ------------------------------------------------------------------


def _plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def _visible_columns(table: Table) -> list[Any]:
    return [
        c
        for c in table.columns
        if not isinstance(c.type, LargeBinary) and not _HIDDEN_COLUMN.search(c.name)
    ]


async def _tenant_tables(db: AsyncSession) -> list[Table]:
    """Tables protected by the tenant row-level security policy, i.e. a workspace's data."""
    names = set(
        (
            await db.execute(
                text(
                    "SELECT tablename FROM pg_policies "
                    "WHERE policyname = 'tenant_isolation' AND schemaname = current_schema()"
                )
            )
        ).scalars()
    )
    return [t for name, t in sorted(Base.metadata.tables.items()) if name in names]


async def _workspace(db: AsyncSession, organisation_id: uuid.UUID) -> dict[str, list[Any]]:
    await bind_tenant(db, organisation_id)
    out: dict[str, list[Any]] = {}
    for table in await _tenant_tables(db):
        columns = _visible_columns(table)
        rows = (
            await db.execute(
                select(*columns)
                .where(table.c.organisation_id == organisation_id)
                .limit(EXPORT_ROW_LIMIT)
            )
        ).mappings()
        found = [{k: _plain(v) for k, v in row.items()} for row in rows]
        if found:
            out[table.name] = found
    return out


async def export_data(db: AsyncSession, user: AppUser) -> dict[str, Any]:
    """Everything held about this account and its personal workspace, as plain JSON."""
    memberships = await tenancy.memberships(db, user.id)
    sessions = (
        await db.execute(
            select(AuthSession)
            .where(AuthSession.user_id == user.id)
            .order_by(AuthSession.created_at.desc())
        )
    ).scalars()
    acceptances = (
        await db.execute(
            select(PolicyAcceptance)
            .where(PolicyAcceptance.user_id == user.id)
            .order_by(PolicyAcceptance.accepted_at)
        )
    ).scalars()
    requests = (
        await db.execute(
            select(PrivacyRequest)
            .where(PrivacyRequest.user_id == user.id)
            .order_by(PrivacyRequest.created_at)
        )
    ).scalars()
    events = (
        await db.execute(
            select(AuditEvent)
            .where(AuditEvent.actor_user_id == user.id)
            .order_by(AuditEvent.seq.desc())
            .limit(AUDIT_EXPORT_LIMIT)
        )
    ).scalars()
    personal = next(
        (m.organisation for m in memberships if m.organisation.kind == OrganisationKind.PERSONAL),
        None,
    )
    data: dict[str, Any] = {
        "exported_at": utcnow().isoformat(),
        "about": (
            "Your ApprovalReady account and the records in your personal workspace. Files "
            "you uploaded are listed here; download them from their projects. Records of "
            "business, practice or partner organisations you belong to belong to that "
            "organisation: ask its administrator, or contact us."
        ),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "email_verified_at": _plain(user.email_verified_at),
            "created_at": _plain(user.created_at),
            "last_login_at": _plain(user.last_login_at),
            "locale": user.locale,
            "two_step_sign_in": await mfa.is_enabled(db, user.id),
        },
        "notification_settings": {
            category.value: channel.value
            for category, channel in (await notification_preferences.choices(db, user.id)).items()
        },
        "organisations": [
            {
                "id": str(m.organisation.id),
                "name": m.organisation.name,
                "kind": m.organisation.kind,
                "roles": list(m.role_keys),
            }
            for m in memberships
        ],
        "sign_ins": [
            {
                "started_at": _plain(s.created_at),
                "last_seen_at": _plain(s.last_seen_at),
                "ip": s.ip,
                "device": s.user_agent,
                "ended_at": _plain(s.revoked_at),
            }
            for s in sessions
        ],
        "policy_acceptances": [
            {
                "document": a.document,
                "version": a.version,
                "accepted_at": _plain(a.accepted_at),
                "ip": a.ip,
            }
            for a in acceptances
        ],
        "privacy_requests": [
            {
                "kind": r.kind,
                "status": r.status,
                "details": r.details,
                "created_at": _plain(r.created_at),
                "resolved_at": _plain(r.resolved_at),
                "resolution_note": r.resolution_note,
            }
            for r in requests
        ],
        "activity": [
            {
                "at": _plain(e.occurred_at),
                "action": e.action,
                "ip": e.ip,
                "device": e.user_agent,
            }
            for e in events
        ],
        "personal_workspace": await _workspace(db, personal.id) if personal else {},
    }
    return data


# --- Close my account ------------------------------------------------------------------


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


async def close_account(
    db: AsyncSession,
    settings: Settings,
    limiter: RateLimiter,
    user: AppUser,
    *,
    password: str,
    code: str | None,
    meta: RequestMeta,
) -> OutgoingEmail:
    """Close the account: sign-in, name and email are removed now; the personal
    workspace is deleted later (``purge.py``). Returns the confirmation email (to the
    address the account had)."""
    credential = (
        await db.execute(select(PasswordCredential).where(PasswordCredential.user_id == user.id))
    ).scalar_one_or_none()
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

    memberships = await tenancy.memberships(db, user.id)
    others = [
        m.organisation for m in memberships if m.organisation.kind != OrganisationKind.PERSONAL
    ]
    if others:
        names = ", ".join(sorted(o.name for o in others))
        raise _conflict(
            "account_has_organisations",
            f"Leave these organisations first: {names}. If you are the only administrator, "
            "make someone else an administrator first, or contact us to close the "
            "organisation.",
        )
    personal = next((m.organisation for m in memberships), None)
    if personal is not None:
        await bind_tenant(db, personal.id)
        live = (
            await db.execute(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.organisation_id == personal.id,
                    Subscription.status.in_(_LIVE_SUBSCRIPTION),
                    Subscription.cancel_at_period_end.is_(False),
                )
            )
        ).scalar_one()
        if live:
            raise _conflict(
                "subscription_active",
                "Cancel your plan under Billing first, so you aren't charged after closing.",
            )

    now = utcnow()
    old_email, old_name = user.email, user.display_name
    db.add(
        PrivacyRequest(
            user_id=user.id,
            name=old_name,
            email=old_email,
            kind=PrivacyRequestKind.DELETION,
            source=PrivacyRequestSource.ACCOUNT_CLOSED,
            details=(
                "The account was closed by its owner. Its personal workspace (projects, "
                "answers, uploaded files and reports) is deleted automatically, keeping "
                "payment records. To keep it instead, decline this request with the reason."
            ),
            due_at=now + timedelta(days=RESPONSE_DAYS),
            organisation_id=personal.id if personal is not None else None,
        )
    )
    if personal is not None:
        # Referrals still offered to partners stop now (Milestone 29).
        consents = (
            await db.execute(
                select(ReferralConsent).where(
                    ReferralConsent.organisation_id == personal.id,
                    ReferralConsent.withdrawn_at.is_(None),
                )
            )
        ).scalars()
        for consent in list(consents):
            await leads.withdraw(db, consent, actor_id=user.id, meta=meta, now=now)
        await db.execute(
            update(Reminder)
            .where(
                Reminder.organisation_id == personal.id,
                Reminder.status == ReminderStatus.SCHEDULED,
            )
            .values(status=ReminderStatus.CANCELLED)
        )
        org = await db.get(Organisation, personal.id)
        if org is not None:
            org.name = "Closed account"
            org.deleted_at = now
    for model in (PasswordCredential, AuthIdentity, OneTimeToken, NotificationPreference):
        await db.execute(delete(model).where(model.user_id == user.id))
    await mfa.remove(db, user.id)
    revoked = await identity.revoke_all_sessions(db, user.id, "account_closed")
    user.email = f"closed-{user.id}@closed.invalid"
    user.display_name = "Closed account"
    user.email_verified_at = None
    user.last_login_at = None
    user.status = UserStatus.DELETION_REQUESTED
    user.deleted_at = now
    await db.flush()
    await audit.record(
        db,
        "account.closed",
        actor_user_id=user.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details={"sessions_revoked": revoked},
    )
    return emails.account_closed(settings, old_email, old_name)


# --- Privacy requests ------------------------------------------------------------------


async def create_request(
    db: AsyncSession,
    *,
    name: str,
    email: str,
    kind: PrivacyRequestKind,
    details: str,
    meta: RequestMeta,
) -> PrivacyRequest:
    request = PrivacyRequest(
        name=name.strip(),
        email=identity.normalise_email(email),
        kind=kind,
        source=PrivacyRequestSource.CONTACT_FORM,
        details=details.strip(),
        due_at=utcnow() + timedelta(days=RESPONSE_DAYS),
    )
    db.add(request)
    await db.flush()
    await audit.record(
        db,
        "privacy.request.created",
        meta=meta,
        target_type="privacy_request",
        target_id=request.id,
        details={"kind": kind.value},
    )
    return request


async def notify_staff(
    provider: EmailProvider, settings: Settings, request: PrivacyRequest
) -> None:
    """Tell OPS_ALERT_EMAILS a request arrived. The request's own text is not emailed:
    staff read it at /admin/privacy."""
    for address in settings.ops_alert_emails:
        try:
            await provider.send(emails.request_received(settings, address, request))
        except Exception:
            logger.exception("privacy request email failed")


async def list_requests(
    db: AsyncSession, status_filter: PrivacyRequestStatus | None
) -> list[PrivacyRequest]:
    stmt = select(PrivacyRequest)
    if status_filter is not None:
        stmt = stmt.where(PrivacyRequest.status == status_filter)
    stmt = stmt.order_by(
        (PrivacyRequest.status != PrivacyRequestStatus.OPEN), PrivacyRequest.due_at
    ).limit(500)
    return list((await db.execute(stmt)).scalars())


async def resolve_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    staff_user_id: uuid.UUID,
    new_status: PrivacyRequestStatus,
    note: str,
    meta: RequestMeta,
) -> PrivacyRequest:
    request = (
        await db.execute(
            select(PrivacyRequest).where(PrivacyRequest.id == request_id).with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found", "Request not found.")
    if new_status == PrivacyRequestStatus.OPEN:
        request.resolved_at = None
        request.resolved_by = None
    else:
        request.resolved_at = utcnow()
        request.resolved_by = staff_user_id
    request.status = new_status
    request.resolution_note = note.strip() or None
    await audit.record(
        db,
        "privacy.request.updated",
        actor_user_id=staff_user_id,
        meta=meta,
        target_type="privacy_request",
        target_id=request.id,
        details={"status": new_status.value},
    )
    return request
