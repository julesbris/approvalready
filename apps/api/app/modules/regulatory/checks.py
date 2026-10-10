"""Automatic source checks (Milestone 24): read each source document from its official
address, keep a snapshot when its text changes, and tell staff what changed or couldn't be
read.

* Staff press "Check now" on a document (``check_document`` with trigger ``MANUAL``).
* Every Monday morning the worker checks every document that is in force, not superseded,
  has ``auto_check`` on and wasn't checked in the last few days (``run_weekly``), one at a
  time with a pause between them. Staff with ``source.manage`` get one notification (and
  email) listing what changed and what couldn't be read.

A changed snapshot is all it takes to put verified references back in front of a reviewer:
``attention`` already flags a reference whose document has a newer snapshot than the one it
was verified against. The app never edits or re-verifies a reference itself.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.core.config import Settings
from app.core.email import EmailProvider
from app.db.tenant import bind_tenant
from app.modules.audit.service import RequestMeta
from app.modules.notifications import service as notifications
from app.modules.notifications.models import NotificationKind
from app.modules.notifications.reminders import local_today
from app.modules.regulatory.fetch import (
    MIN_TEXT_CHARS,
    FetchRefused,
    SourceFetcher,
    readable_text,
)
from app.modules.regulatory.models import (
    MAX_SNAPSHOT_CHARS,
    CaptureMethod,
    CheckOutcome,
    CheckTrigger,
    SourceCheck,
    SourceDocument,
    SourceSnapshot,
)
from app.modules.regulatory.service import store_snapshot
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation, OrganisationKind, OrganisationMember
from app.modules.tenancy.rbac import Perm

Factory = async_sessionmaker[AsyncSession]


# A document checked more recently than this is skipped by the weekly run, so running it
# again (or by hand from the command line) doesn't read every page twice.
RECHECK_AFTER = timedelta(days=6)
# Outcomes staff are told about.
NEWS = (CheckOutcome.CHANGED, CheckOutcome.FILE_CHANGED, CheckOutcome.FAILED)
LISTED_IN_NOTICE = 10

OUTCOME_LABELS = {
    CheckOutcome.SAVED: "first reading saved",
    CheckOutcome.CHANGED: "changed",
    CheckOutcome.UNCHANGED: "unchanged",
    CheckOutcome.FILE_SEEN: "file read (capture its text by hand)",
    CheckOutcome.FILE_CHANGED: "file changed (capture its text by hand)",
    CheckOutcome.FILE_UNCHANGED: "file unchanged",
    CheckOutcome.FAILED: "couldn't be read",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


async def _last_file_hash(db: AsyncSession, document_id: uuid.UUID) -> bytes | None:
    return (
        await db.execute(
            select(SourceCheck.body_sha256)
            .where(
                SourceCheck.source_document_id == document_id,
                SourceCheck.outcome.in_(
                    (CheckOutcome.FILE_SEEN, CheckOutcome.FILE_CHANGED, CheckOutcome.FILE_UNCHANGED)
                ),
            )
            .order_by(SourceCheck.checked_at.desc(), SourceCheck.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _fetched_before(db: AsyncSession, document_id: uuid.UUID) -> bool:
    return bool(
        (
            await db.execute(
                select(
                    exists().where(
                        SourceSnapshot.source_document_id == document_id,
                        SourceSnapshot.capture_method == CaptureMethod.FETCHED,
                    )
                )
            )
        ).scalar_one()
    )


async def check_document(
    db: AsyncSession,
    fetcher: SourceFetcher,
    document: SourceDocument,
    *,
    trigger: str,
    requested_by: uuid.UUID | None,
    organisation_id: uuid.UUID | None,
    meta: RequestMeta | None = None,
) -> SourceCheck:
    """Read the document now and record what happened (the caller commits)."""
    check = SourceCheck(
        source_document_id=document.id,
        trigger=trigger,
        requested_by=requested_by,
        url=document.url,
    )
    retrieved_at = utcnow()
    try:
        fetched = await fetcher.fetch(document.url)
    except FetchRefused as exc:
        check.outcome = CheckOutcome.FAILED
        check.error = exc.message[:500]
        check.http_status = exc.http_status
    else:
        check.final_url = fetched.final_url[:2000]
        check.http_status = fetched.http_status
        check.content_type = fetched.content_type[:200] or None
        check.size_bytes = len(fetched.body)
        check.body_sha256 = fetched.sha256
        text = readable_text(fetched)
        if text is None:
            previous = await _last_file_hash(db, document.id)
            check.outcome = (
                CheckOutcome.FILE_SEEN
                if previous is None
                else CheckOutcome.FILE_UNCHANGED
                if previous == check.body_sha256
                else CheckOutcome.FILE_CHANGED
            )
        elif len(text) < MIN_TEXT_CHARS:
            check.outcome = CheckOutcome.FAILED
            check.error = "The page has no readable text (it may only work with JavaScript)."
        elif len(text) > MAX_SNAPSHOT_CHARS:
            check.outcome = CheckOutcome.FAILED
            check.error = "The page's text is too long to keep as a snapshot."
        else:
            fetched_before = await _fetched_before(db, document.id)
            snapshot, changed = await store_snapshot(
                db,
                document,
                text,
                retrieved_at,
                captured_by=requested_by,
                organisation_id=organisation_id,
                meta=meta,
                capture_method=CaptureMethod.FETCHED,
            )
            check.snapshot_id = snapshot.id
            check.outcome = (
                CheckOutcome.UNCHANGED
                if not changed
                else CheckOutcome.CHANGED
                if fetched_before
                else CheckOutcome.SAVED
            )
    db.add(check)
    await db.flush()
    await db.refresh(check)
    return check


async def list_checks(
    db: AsyncSession, document: SourceDocument, limit: int = 20
) -> list[SourceCheck]:
    return list(
        (
            await db.execute(
                select(SourceCheck)
                .where(SourceCheck.source_document_id == document.id)
                .order_by(SourceCheck.checked_at.desc(), SourceCheck.id.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def latest_checks(
    db: AsyncSession, document_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, SourceCheck]:
    if not document_ids:
        return {}
    rows = (
        await db.execute(
            select(SourceCheck)
            .where(SourceCheck.source_document_id.in_(document_ids))
            .ext(distinct_on(SourceCheck.source_document_id))
            .order_by(
                SourceCheck.source_document_id,
                SourceCheck.checked_at.desc(),
                SourceCheck.id.desc(),
            )
        )
    ).scalars()
    return {c.source_document_id: c for c in rows}


# --- Weekly run ------------------------------------------------------------------------


async def due_documents(db: AsyncSession, today: date, now: datetime) -> list[uuid.UUID]:
    """Documents the weekly run reads: checked automatically, in force, not superseded by
    another document, and not checked recently."""
    newer = aliased(SourceDocument)
    recent = select(SourceCheck.id).where(
        SourceCheck.source_document_id == SourceDocument.id,
        SourceCheck.checked_at > now - RECHECK_AFTER,
    )
    return list(
        (
            await db.execute(
                select(SourceDocument.id)
                .where(
                    SourceDocument.auto_check.is_(True),
                    (SourceDocument.effective_to.is_(None)) | (SourceDocument.effective_to > today),
                    ~exists().where(newer.supersedes_id == SourceDocument.id),
                    ~recent.exists(),
                )
                .order_by(SourceDocument.url, SourceDocument.id)
            )
        ).scalars()
    )


@dataclass
class WeeklyResult:
    checked: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    news: list[tuple[str, str, str | None]] = field(default_factory=list)  # title, outcome, error
    notified: int = 0


async def _platform_org(factory: Factory) -> uuid.UUID | None:
    async with factory() as db:
        found = (
            await db.execute(
                select(Organisation.id)
                .where(
                    Organisation.kind == OrganisationKind.PLATFORM_ADMIN,
                    Organisation.deleted_at.is_(None),
                )
                .order_by(Organisation.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        await db.commit()
    return found


def _notice(news: list[tuple[str, str, str | None]]) -> tuple[str, str]:
    changed = sum(1 for _, o, _ in news if o in (CheckOutcome.CHANGED, CheckOutcome.FILE_CHANGED))
    failed = sum(1 for _, o, _ in news if o == CheckOutcome.FAILED)
    parts = []
    if changed:
        parts.append(f"{changed} changed")
    if failed:
        parts.append(f"{failed} couldn't be read")
    title = f"Weekly source check: {' and '.join(parts)}"
    lines = [
        f"{t}: {OUTCOME_LABELS[CheckOutcome(o)]}{f' ({e})' if e else ''}"
        for t, o, e in news[:LISTED_IN_NOTICE]
    ]
    if len(news) > LISTED_IN_NOTICE:
        lines.append(f"and {len(news) - LISTED_IN_NOTICE} more.")
    lines.append(
        "Re-verify references on changed documents; capture the others by hand from their "
        "official address."
    )
    return title, "\n".join(lines)


async def _notify(
    factory: Factory,
    provider: EmailProvider,
    settings: Settings,
    org_id: uuid.UUID,
    news: list[tuple[str, str, str | None]],
    today: date,
) -> int:
    title, body = _notice(news)
    year, week, _ = today.isocalendar()
    async with factory() as db:
        await bind_tenant(db, org_id)
        members = list(
            (
                await db.execute(
                    select(OrganisationMember.user_id).where(
                        OrganisationMember.organisation_id == org_id
                    )
                )
            ).scalars()
        )
        ids: list[uuid.UUID] = []
        for user_id in members:
            m = await tenancy.membership(db, user_id, org_id)
            if m is None or Perm.SOURCE_MANAGE not in m.permissions:
                continue
            nid = await notifications.create(
                db,
                organisation_id=org_id,
                recipient_user_id=user_id,
                kind=NotificationKind.SOURCES_DUE,
                title=title,
                body=body,
                link_path="/admin/sources",
                dedupe_key=f"source_check:{year}-W{week:02d}",
            )
            if nid is not None:
                ids.append(nid)
        await db.commit()
        await notifications.send_emails(db, provider, settings, org_id, ids)
    return len(ids)


async def run_weekly(
    factory: Factory,
    provider: EmailProvider,
    settings: Settings,
    fetcher: SourceFetcher,
    *,
    now: datetime | None = None,
    today: date | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> WeeklyResult:
    now = now or utcnow()
    today = today or local_today()
    result = WeeklyResult()
    if not settings.source_checks_enabled:
        return result
    org_id = await _platform_org(factory)
    async with factory() as db:
        ids = await due_documents(db, today, now)
        await db.commit()
    for index, document_id in enumerate(ids):
        if index:
            await sleep(settings.source_fetch_delay_seconds)
        async with factory() as db:
            document = await db.get(SourceDocument, document_id)
            if document is None:
                continue
            check = await check_document(
                db,
                fetcher,
                document,
                trigger=CheckTrigger.SCHEDULED,
                requested_by=None,
                organisation_id=org_id,
            )
            title = document.title
            await db.commit()
        result.checked += 1
        result.outcomes[check.outcome] = result.outcomes.get(check.outcome, 0) + 1
        if check.outcome in NEWS:
            result.news.append((title, check.outcome, check.error))
    if result.news and org_id is not None:
        result.notified = await _notify(factory, provider, settings, org_id, result.news, today)
    return result
