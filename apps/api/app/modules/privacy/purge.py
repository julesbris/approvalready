"""Deleting a closed account's personal workspace (Milestone 29).

Closing an account (``service.close_account``) removes the sign-in, name and email at once
and opens a DELETION privacy request for the personal workspace. The Privacy Policy
promises the workspace's projects, answers and files are deleted within 30 days, so:

* every night the worker deletes the workspaces of accounts closed more than
  ``PRIVACY_PURGE_AFTER_DAYS`` ago (default 7) whose request is still open;
* staff can delete one sooner from ``/admin/privacy``, or keep it (a legal hold, a dispute)
  by declining the request with a reason; the nightly job skips requests that aren't open.

What goes: every workspace table (the ``tenant_isolation`` row-level security policy marks
them) except payment records, plus the uploaded and generated files and the account's old
sign-in records (IP addresses). What stays: payments, subscriptions, invoices, refunds and
credit (tax law), the security log, the policy agreements, the privacy request itself, and
referrals partners received, detached from the project and without the customer's contact
snapshot or summary (records of a business stay with that business).

The rows are removed by the ``purge_closed_workspace`` database function (migration 0029):
the application role can't delete most of these tables itself, and the function refuses
anything but a closed personal workspace.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiError
from app.db.base import Base
from app.db.tenant import bind_tenant
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.documents.models import GeneratedDocument, UploadedDocument
from app.modules.documents.storage import ObjectStorage
from app.modules.identity.models import AuthSession
from app.modules.leads import service as leads
from app.modules.leads.models import ReferralConsent
from app.modules.privacy.models import (
    PrivacyRequest,
    PrivacyRequestKind,
    PrivacyRequestSource,
    PrivacyRequestStatus,
)

logger = logging.getLogger(__name__)

# Kept for tax law. The database function refuses these too (migration 0029).
KEPT_TABLES = frozenset(
    {
        "billing_customer",
        "payment",
        "subscription",
        "invoice_reference",
        "refund",
        "credit_ledger_entry",
    }
)

# How the summary on the request names what was deleted.
_LABELS = {
    "project": "project",
    "question_response": "answer",
    "uploaded_document": "uploaded file",
    "generated_document": "report",
    "property": "property",
    "vessel": "vessel",
    "business_profile": "business profile",
    "notification": "notification",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PurgeResult:
    request_id: uuid.UUID
    rows: dict[str, int]
    files: int

    @property
    def total(self) -> int:
        return sum(self.rows.values())


async def workspace_tables(db: AsyncSession) -> list[str]:
    """Workspace tables to empty, children before parents (so foreign keys without a
    cascade are satisfied), without the kept payment records."""
    tenant = set(
        (
            await db.execute(
                text(
                    "SELECT tablename FROM pg_policies "
                    "WHERE policyname = 'tenant_isolation' AND schemaname = current_schema()"
                )
            )
        ).scalars()
    )
    return [
        t.name
        for t in reversed(Base.metadata.sorted_tables)
        if t.name in tenant and t.name not in KEPT_TABLES
    ]


def deletes_on(request: PrivacyRequest, after_days: int) -> datetime | None:
    """When the nightly job will delete this request's workspace, if it will."""
    if (
        request.source != PrivacyRequestSource.ACCOUNT_CLOSED
        or request.kind != PrivacyRequestKind.DELETION
        or request.status != PrivacyRequestStatus.OPEN
        or request.organisation_id is None
        or request.purged_at is not None
    ):
        return None
    return request.created_at + timedelta(days=after_days)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary(rows: dict[str, int], files: int, *, automatic: bool) -> str:
    named = [_plural(rows[t], label) for t, label in _LABELS.items() if rows.get(t)]
    others = sum(n for t, n in rows.items() if t not in _LABELS)
    if others:
        named.append(_plural(others, "other record"))
    what = ", ".join(named) if named else "nothing was left in it"
    how = "automatically" if automatic else "by staff"
    return (
        f"Personal workspace deleted {how}: {what}; {_plural(files, 'stored file')} removed. "
        "Payment records, the security log and referrals partners received are kept."
    )


def _refuse(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


async def purge_workspace(
    db: AsyncSession,
    storage: ObjectStorage,
    request_id: uuid.UUID,
    *,
    staff_user_id: uuid.UUID | None,
    meta: RequestMeta | None = None,
    now: datetime | None = None,
) -> PurgeResult:
    """Delete the workspace of a closed account's open deletion request. The caller
    commits. Files are removed first: if that fails nothing is committed and the next run
    tries again (removing a file that is already gone is fine)."""
    now = now or utcnow()
    request = (
        await db.execute(
            select(PrivacyRequest).where(PrivacyRequest.id == request_id).with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found", "Request not found.")
    if request.organisation_id is None or request.source != PrivacyRequestSource.ACCOUNT_CLOSED:
        raise _refuse(
            "no_workspace",
            "This request isn't about a closed account's workspace. Handle it by hand.",
        )
    if request.purged_at is not None:
        raise _refuse("already_deleted", "This workspace has already been deleted.")
    if request.status != PrivacyRequestStatus.OPEN:
        raise _refuse(
            "request_not_open",
            "Reopen the request before deleting the workspace.",
        )
    org_id = request.organisation_id
    await bind_tenant(db, org_id)

    # Stop any referral still offered to partners (closing does this too, since Milestone
    # 29; accounts closed before then may still have some).
    consents = (
        await db.execute(
            select(ReferralConsent).where(
                ReferralConsent.organisation_id == org_id,
                ReferralConsent.withdrawn_at.is_(None),
            )
        )
    ).scalars()
    for consent in list(consents):
        await leads.withdraw(db, consent, actor_id=consent.user_id, meta=None, now=now)

    keys: set[str] = set()
    for model in (UploadedDocument, GeneratedDocument):
        keys.update(
            k
            for k in (
                await db.execute(select(model.storage_key).where(model.organisation_id == org_id))
            ).scalars()
            if k
        )
    for key in sorted(keys):
        await storage.delete(key)

    tables = await workspace_tables(db)
    raw: dict[str, Any] = (
        await db.execute(
            text("SELECT purge_closed_workspace(:org, :tables)"),
            {"org": org_id, "tables": tables},
        )
    ).scalar_one()
    rows = {name: int(n) for name, n in raw.items()}
    if request.user_id is not None:
        await db.execute(delete(AuthSession).where(AuthSession.user_id == request.user_id))

    request.purged_at = now
    request.status = PrivacyRequestStatus.DONE
    request.resolved_at = now
    request.resolved_by = staff_user_id
    request.resolution_note = summary(rows, len(keys), automatic=staff_user_id is None)
    await audit.record(
        db,
        "privacy.workspace.deleted",
        actor_user_id=staff_user_id,
        meta=meta,
        target_type="privacy_request",
        target_id=request.id,
        details={"organisation_id": str(org_id), "rows": rows, "files": len(keys)},
    )
    return PurgeResult(request.id, rows, len(keys))


async def due_requests(db: AsyncSession, now: datetime, after_days: int) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(PrivacyRequest.id)
                .where(
                    PrivacyRequest.source == PrivacyRequestSource.ACCOUNT_CLOSED,
                    PrivacyRequest.kind == PrivacyRequestKind.DELETION,
                    PrivacyRequest.status == PrivacyRequestStatus.OPEN,
                    PrivacyRequest.organisation_id.is_not(None),
                    PrivacyRequest.purged_at.is_(None),
                    PrivacyRequest.created_at <= now - timedelta(days=after_days),
                )
                .order_by(PrivacyRequest.created_at)
                .limit(200)
            )
        ).scalars()
    )


async def run_due(
    factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    after_days: int,
    now: datetime | None = None,
) -> list[PurgeResult]:
    """The nightly job: delete every workspace that is due, each in its own transaction.
    One that fails is logged and retried the next night (the privacy operations check
    turns red if a request passes its 30-day answer date)."""
    now = now or utcnow()
    async with factory() as db:
        due = await due_requests(db, now, after_days)
    done = []
    for request_id in due:
        async with factory() as db:
            try:
                result = await purge_workspace(db, storage, request_id, staff_user_id=None, now=now)
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("deleting a closed workspace failed", extra={"id": request_id})
                continue
        done.append(result)
        logger.info(
            "closed workspace deleted",
            extra={"request_id": str(request_id), "rows": result.total, "files": result.files},
        )
    return done
