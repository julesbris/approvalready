"""Regulatory sources: capture with provenance, snapshots and the verification workflow.

Verification workflow for a reference (``source_review_event`` records every step)::

    UNVERIFIED ─VERIFY─▶ VERIFIED ─REOPEN─▶ UNVERIFIED
        │                  │  ▲
        │               DISPUTE│VERIFY
        ├──DISPUTE──▶ DISPUTED ┘
        └──SUPERSEDE─▶ SUPERSEDED (final; also from VERIFIED and DISPUTED)

Verifying checks the extract against the document's latest snapshot, so a document needs a
snapshot before any of its references can be verified, and the reference remembers which
snapshot it was checked against. Editing a reference's citation or text undoes its
verification. Every change is in the audit log as well.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.regulatory.models import (
    ReviewAction,
    SourceDocument,
    SourceOrganisation,
    SourceReference,
    SourceReviewEvent,
    SourceSnapshot,
    VerificationStatus,
)

V = VerificationStatus
DEFAULT_REVIEW_INTERVAL = timedelta(days=365)

# Review action → (statuses it may be taken from, status it leads to).
REVIEW_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "VERIFY": (frozenset({V.UNVERIFIED, V.VERIFIED, V.DISPUTED}), V.VERIFIED),
    "DISPUTE": (frozenset({V.UNVERIFIED, V.VERIFIED}), V.DISPUTED),
    "SUPERSEDE": (frozenset({V.UNVERIFIED, V.VERIFIED, V.DISPUTED}), V.SUPERSEDED),
    "REOPEN": (frozenset({V.VERIFIED, V.DISPUTED}), V.UNVERIFIED),
}
_ACTION_EVENTS = {
    "VERIFY": ReviewAction.VERIFIED,
    "DISPUTE": ReviewAction.DISPUTED,
    "SUPERSEDE": ReviewAction.SUPERSEDED,
    "REOPEN": ReviewAction.REOPENED,
}
CITATION_FIELDS = ("section", "clause", "page", "extracted_text", "interpretation")


def utcnow() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return utcnow().date()


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


def _invalid(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


async def _audit(
    db: AsyncSession,
    action: str,
    *,
    actor_id: uuid.UUID,
    platform_org_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    meta: RequestMeta | None,
    details: dict[str, Any] | None = None,
) -> None:
    await audit.record(
        db,
        action,
        actor_user_id=actor_id,
        organisation_id=platform_org_id,
        target_type=target_type,
        target_id=target_id,
        meta=meta,
        details=details,
    )


@dataclass(frozen=True)
class Actor:
    """Who is acting, from which (platform) organisation, for the audit log."""

    user_id: uuid.UUID
    organisation_id: uuid.UUID
    meta: RequestMeta | None


# --- Organisations ---------------------------------------------------------------------


async def list_organisations(db: AsyncSession) -> list[SourceOrganisation]:
    return list(
        (await db.execute(select(SourceOrganisation).order_by(SourceOrganisation.name))).scalars()
    )


async def get_organisation(db: AsyncSession, organisation_id: uuid.UUID) -> SourceOrganisation:
    found = await db.get(SourceOrganisation, organisation_id)
    if found is None:
        raise not_found("Source organisation")
    return found


async def _name_taken(db: AsyncSession, name: str, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(SourceOrganisation.id).where(func.lower(SourceOrganisation.name) == name.lower())
    if exclude is not None:
        stmt = stmt.where(SourceOrganisation.id != exclude)
    return (await db.execute(stmt)).first() is not None


async def create_organisation(
    db: AsyncSession, data: dict[str, Any], actor: Actor
) -> SourceOrganisation:
    if await _name_taken(db, data["name"]):
        raise _conflict("name_taken", "A source organisation with that name already exists.")
    org = SourceOrganisation(created_by=actor.user_id, **data)
    db.add(org)
    await db.flush()
    await _audit(
        db,
        "source.organisation_created",
        actor_id=actor.user_id,
        platform_org_id=actor.organisation_id,
        target_type="source_organisation",
        target_id=org.id,
        meta=actor.meta,
        details={"name": org.name},
    )
    return org


async def update_organisation(
    db: AsyncSession, org: SourceOrganisation, changes: dict[str, Any], actor: Actor
) -> SourceOrganisation:
    changes = {k: v for k, v in changes.items() if v is not None or k == "website"}
    if "name" in changes and await _name_taken(db, changes["name"], exclude=org.id):
        raise _conflict("name_taken", "A source organisation with that name already exists.")
    applied = sorted(k for k, v in changes.items() if getattr(org, k) != v)
    for key in applied:
        setattr(org, key, changes[key])
    if applied:
        await db.flush()
        await _audit(
            db,
            "source.organisation_updated",
            actor_id=actor.user_id,
            platform_org_id=actor.organisation_id,
            target_type="source_organisation",
            target_id=org.id,
            meta=actor.meta,
            details={"fields": applied},
        )
    return org


# --- Documents -------------------------------------------------------------------------


async def list_documents(
    db: AsyncSession, source_organisation_id: uuid.UUID | None = None
) -> list[tuple[SourceDocument, SourceOrganisation]]:
    stmt = select(SourceDocument, SourceOrganisation).join(
        SourceOrganisation, SourceOrganisation.id == SourceDocument.source_organisation_id
    )
    if source_organisation_id is not None:
        stmt = stmt.where(SourceDocument.source_organisation_id == source_organisation_id)
    rows = await db.execute(stmt.order_by(SourceOrganisation.name, SourceDocument.title))
    return [(d, o) for d, o in rows.all()]


async def get_document(
    db: AsyncSession, document_id: uuid.UUID
) -> tuple[SourceDocument, SourceOrganisation]:
    row = (
        await db.execute(
            select(SourceDocument, SourceOrganisation)
            .join(
                SourceOrganisation, SourceOrganisation.id == SourceDocument.source_organisation_id
            )
            .where(SourceDocument.id == document_id)
        )
    ).one_or_none()
    if row is None:
        raise not_found("Source document")
    return row[0], row[1]


def _check_dates(effective_from: date | None, effective_to: date | None) -> None:
    if effective_from and effective_to and effective_to <= effective_from:
        raise _invalid("invalid_dates", "The end date must be after the start date.")


async def _check_supersedes(
    db: AsyncSession, supersedes_id: uuid.UUID | None, self_id: uuid.UUID | None = None
) -> None:
    if supersedes_id is None:
        return
    if supersedes_id == self_id or await db.get(SourceDocument, supersedes_id) is None:
        raise _invalid("invalid_supersedes", "Choose another existing document to supersede.")


async def create_document(db: AsyncSession, data: dict[str, Any], actor: Actor) -> SourceDocument:
    await get_organisation(db, data["source_organisation_id"])
    _check_dates(data.get("effective_from"), data.get("effective_to"))
    await _check_supersedes(db, data.get("supersedes_id"))
    document = SourceDocument(created_by=actor.user_id, **data)
    db.add(document)
    await db.flush()
    await _audit(
        db,
        "source.document_created",
        actor_id=actor.user_id,
        platform_org_id=actor.organisation_id,
        target_type="source_document",
        target_id=document.id,
        meta=actor.meta,
        details={"title": document.title, "url": document.url},
    )
    return document


async def update_document(
    db: AsyncSession, document: SourceDocument, changes: dict[str, Any], actor: Actor
) -> SourceDocument:
    nullable = {"version_label", "effective_from", "effective_to", "licence", "supersedes_id"}
    changes = {k: v for k, v in changes.items() if v is not None or k in nullable}
    _check_dates(
        changes.get("effective_from", document.effective_from),
        changes.get("effective_to", document.effective_to),
    )
    if "supersedes_id" in changes:
        await _check_supersedes(db, changes["supersedes_id"], document.id)
    applied = sorted(k for k, v in changes.items() if getattr(document, k) != v)
    for key in applied:
        setattr(document, key, changes[key])
    if applied:
        await db.flush()
        await _audit(
            db,
            "source.document_updated",
            actor_id=actor.user_id,
            platform_org_id=actor.organisation_id,
            target_type="source_document",
            target_id=document.id,
            meta=actor.meta,
            details={"fields": applied},
        )
    return document


async def reference_counts(
    db: AsyncSession, document_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    counts: dict[uuid.UUID, dict[str, int]] = {d: {} for d in document_ids}
    rows = await db.execute(
        select(
            SourceReference.source_document_id,
            SourceReference.verification_status,
            func.count(SourceReference.id),
        )
        .where(SourceReference.source_document_id.in_(document_ids))
        .group_by(SourceReference.source_document_id, SourceReference.verification_status)
    )
    for document_id, verification_status, count in rows.all():
        counts[document_id][verification_status] = count
    return counts


# --- Snapshots -------------------------------------------------------------------------


def content_hash(text: str) -> bytes:
    return hashlib.sha256(text.encode()).digest()


async def latest_snapshots(
    db: AsyncSession, document_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, SourceSnapshot]:
    if not document_ids:
        return {}
    rows = (
        await db.execute(
            select(SourceSnapshot)
            .where(SourceSnapshot.source_document_id.in_(document_ids))
            .ext(distinct_on(SourceSnapshot.source_document_id))
            .order_by(
                SourceSnapshot.source_document_id,
                SourceSnapshot.captured_at.desc(),
                SourceSnapshot.id.desc(),
            )
        )
    ).scalars()
    return {s.source_document_id: s for s in rows}


async def list_snapshots(db: AsyncSession, document: SourceDocument) -> list[SourceSnapshot]:
    return list(
        (
            await db.execute(
                select(SourceSnapshot)
                .where(SourceSnapshot.source_document_id == document.id)
                .order_by(SourceSnapshot.captured_at.desc(), SourceSnapshot.id.desc())
            )
        ).scalars()
    )


async def get_snapshot(
    db: AsyncSession, document: SourceDocument, snapshot_id: uuid.UUID
) -> SourceSnapshot:
    found = await db.get(SourceSnapshot, snapshot_id)
    if found is None or found.source_document_id != document.id:
        raise not_found("Snapshot")
    return found


async def capture_snapshot(
    db: AsyncSession,
    document: SourceDocument,
    content_text: str,
    retrieved_at: datetime,
    actor: Actor,
) -> tuple[SourceSnapshot, bool]:
    """Store what the document says now. Returns the snapshot and whether it differs from
    the previous one. Capturing unchanged content again stores nothing new."""
    if retrieved_at.tzinfo is None:
        raise _invalid("timezone_required", "Include a time zone with the retrieval time.")
    if retrieved_at > utcnow() + timedelta(minutes=5):
        raise _invalid("in_the_future", "The retrieval time can't be in the future.")
    digest = content_hash(content_text)
    previous = (await latest_snapshots(db, [document.id])).get(document.id)
    if previous is not None and previous.content_hash == digest:
        return previous, False
    snapshot = SourceSnapshot(
        source_document_id=document.id,
        retrieved_at=retrieved_at,
        content_text=content_text,
        content_hash=digest,
        captured_by=actor.user_id,
    )
    db.add(snapshot)
    await db.flush()
    await db.refresh(snapshot)
    await _audit(
        db,
        "source.snapshot_captured",
        actor_id=actor.user_id,
        platform_org_id=actor.organisation_id,
        target_type="source_document",
        target_id=document.id,
        meta=actor.meta,
        details={
            "snapshot_id": str(snapshot.id),
            "content_hash": digest.hex(),
            "changed": previous is not None,
        },
    )
    return snapshot, True


# --- References ------------------------------------------------------------------------


def citation(ref: SourceReference, document: SourceDocument) -> str:
    parts = [p for p in (ref.section, ref.clause and f"cl. {ref.clause}") if p]
    if ref.page:
        parts.append(f"p. {ref.page}")
    return f"{document.title}{', ' + ', '.join(parts) if parts else ''}"


def attention(
    ref: SourceReference, document: SourceDocument, latest_snapshot_id: uuid.UUID | None, on: date
) -> list[str]:
    """Plain-language reasons a reviewer should look at this reference now."""
    found: list[str] = []
    if ref.verification_status == V.UNVERIFIED:
        found.append("Not verified yet.")
    if ref.verification_status == V.DISPUTED:
        found.append("Disputed.")
    if ref.verification_status == V.VERIFIED:
        if ref.next_review_due is not None and ref.next_review_due < on:
            found.append("Overdue for review.")
        if latest_snapshot_id is not None and latest_snapshot_id != ref.verified_snapshot_id:
            found.append("The document has changed since this was verified.")
    if document.effective_to is not None and document.effective_to <= on:
        found.append("The document is no longer in force.")
    return found


def allowed_actions(ref: SourceReference) -> list[str]:
    return [
        a for a, (sources, _) in REVIEW_TRANSITIONS.items() if ref.verification_status in sources
    ]


@dataclass(frozen=True)
class ReferenceView:
    reference: SourceReference
    document: SourceDocument
    organisation: SourceOrganisation
    latest_snapshot_id: uuid.UUID | None
    rule_versions: int


async def _views(
    db: AsyncSession, rows: Sequence[tuple[SourceReference, SourceDocument, SourceOrganisation]]
) -> list[ReferenceView]:
    from app.modules.rules.models import RuleSource  # rules depend on sources, not vice versa

    snapshots = await latest_snapshots(db, list({d.id for _, d, _ in rows}))
    ids = [r.id for r, _, _ in rows]
    usage: dict[uuid.UUID, int] = {}
    if ids:
        usage = {
            ref_id: count
            for ref_id, count in (
                await db.execute(
                    select(RuleSource.source_reference_id, func.count(RuleSource.id))
                    .where(RuleSource.source_reference_id.in_(ids))
                    .group_by(RuleSource.source_reference_id)
                )
            ).all()
        }
    return [
        ReferenceView(
            reference=r,
            document=d,
            organisation=o,
            latest_snapshot_id=snapshots[d.id].id if d.id in snapshots else None,
            rule_versions=usage.get(r.id, 0),
        )
        for r, d, o in rows
    ]


def _reference_query() -> Any:
    return (
        select(SourceReference, SourceDocument, SourceOrganisation)
        .join(SourceDocument, SourceDocument.id == SourceReference.source_document_id)
        .join(SourceOrganisation, SourceOrganisation.id == SourceDocument.source_organisation_id)
    )


async def list_references(
    db: AsyncSession,
    *,
    document_id: uuid.UUID | None = None,
    verification_status: str | None = None,
    needs_attention: bool = False,
    ids: Sequence[uuid.UUID] | None = None,
) -> list[ReferenceView]:
    stmt = _reference_query()
    if document_id is not None:
        stmt = stmt.where(SourceReference.source_document_id == document_id)
    if verification_status is not None:
        stmt = stmt.where(SourceReference.verification_status == verification_status)
    if ids is not None:
        stmt = stmt.where(SourceReference.id.in_(list(ids)))
    rows = (
        await db.execute(
            stmt.order_by(SourceDocument.title, SourceReference.section, SourceReference.created_at)
        )
    ).all()
    views = await _views(db, [(r, d, o) for r, d, o in rows])
    if needs_attention:
        on = today()
        views = [v for v in views if attention(v.reference, v.document, v.latest_snapshot_id, on)]
    return views


async def get_reference(db: AsyncSession, reference_id: uuid.UUID) -> ReferenceView:
    row = (
        await db.execute(_reference_query().where(SourceReference.id == reference_id))
    ).one_or_none()
    if row is None:
        raise not_found("Source reference")
    return (await _views(db, [(row[0], row[1], row[2])]))[0]


async def _event(
    db: AsyncSession,
    ref: SourceReference,
    action: ReviewAction,
    previous: str | None,
    *,
    actor_id: uuid.UUID,
    notes: str | None = None,
) -> None:
    db.add(
        SourceReviewEvent(
            source_reference_id=ref.id,
            action=action,
            from_status=previous,
            to_status=ref.verification_status,
            reviewer_id=actor_id,
            notes=notes,
        )
    )
    await db.flush()


async def create_reference(
    db: AsyncSession, document: SourceDocument, data: dict[str, Any], actor: Actor
) -> SourceReference:
    ref = SourceReference(source_document_id=document.id, created_by=actor.user_id, **data)
    db.add(ref)
    await db.flush()
    await _event(db, ref, ReviewAction.CREATED, None, actor_id=actor.user_id)
    await _audit(
        db,
        "source.reference_created",
        actor_id=actor.user_id,
        platform_org_id=actor.organisation_id,
        target_type="source_reference",
        target_id=ref.id,
        meta=actor.meta,
        details={"source_document_id": str(document.id)},
    )
    return ref


async def update_reference(
    db: AsyncSession, ref: SourceReference, changes: dict[str, Any], actor: Actor
) -> SourceReference:
    if ref.verification_status == V.SUPERSEDED:
        raise _conflict("superseded", "A superseded reference can't be changed. Add a new one.")
    nullable = {"section", "clause", "page", "interpretation"}
    changes = {k: v for k, v in changes.items() if v is not None or k in nullable}
    applied = sorted(k for k, v in changes.items() if getattr(ref, k) != v)
    if not applied:
        return ref
    for key in applied:
        setattr(ref, key, changes[key])
    previous = ref.verification_status
    if previous != V.UNVERIFIED:
        # What was verified is no longer what is stored.
        ref.verification_status = V.UNVERIFIED
        ref.verified_at = None
        ref.verified_by = None
        ref.verified_snapshot_id = None
    await db.flush()
    await _event(db, ref, ReviewAction.EDITED, previous, actor_id=actor.user_id)
    await _audit(
        db,
        "source.reference_updated",
        actor_id=actor.user_id,
        platform_org_id=actor.organisation_id,
        target_type="source_reference",
        target_id=ref.id,
        meta=actor.meta,
        details={"fields": applied, "from_status": previous, "to_status": ref.verification_status},
    )
    return ref


async def review_reference(
    db: AsyncSession,
    view: ReferenceView,
    action: str,
    *,
    notes: str | None,
    next_review_due: date | None,
    actor: Actor,
) -> SourceReference:
    ref = view.reference
    allowed_from, target = REVIEW_TRANSITIONS[action]
    if ref.verification_status not in allowed_from:
        raise _conflict(
            "invalid_review",
            f"A reference that is {ref.verification_status.lower()} can't be "
            f"{_ACTION_EVENTS[action].lower()}.",
        )
    if action in ("DISPUTE", "SUPERSEDE") and not notes:
        raise _invalid("notes_required", "Explain why in the notes.")
    if action != "VERIFY" and next_review_due is not None:
        raise _invalid("review_date_not_allowed", "Only verification sets a review date.")
    now = utcnow()
    previous = ref.verification_status
    if action == "VERIFY":
        if view.latest_snapshot_id is None:
            raise _conflict(
                "snapshot_required",
                "Capture a snapshot of the document before verifying its references.",
            )
        due = next_review_due or (now + DEFAULT_REVIEW_INTERVAL).date()
        if due <= now.date():
            raise _invalid("invalid_review_date", "The next review date must be in the future.")
        ref.verified_by = actor.user_id
        ref.verified_at = now
        ref.verified_snapshot_id = view.latest_snapshot_id
        ref.next_review_due = due
    elif target != V.VERIFIED:
        ref.verified_by = None
        ref.verified_at = None
        ref.verified_snapshot_id = None
    ref.verification_status = target
    ref.last_reviewed_at = now
    await db.flush()
    await _event(db, ref, _ACTION_EVENTS[action], previous, actor_id=actor.user_id, notes=notes)
    await _audit(
        db,
        "source.reference_reviewed",
        actor_id=actor.user_id,
        platform_org_id=actor.organisation_id,
        target_type="source_reference",
        target_id=ref.id,
        meta=actor.meta,
        details={"action": action, "from_status": previous, "to_status": target},
    )
    return ref


async def review_events(db: AsyncSession, ref: SourceReference) -> list[SourceReviewEvent]:
    return list(
        (
            await db.execute(
                select(SourceReviewEvent)
                .where(SourceReviewEvent.source_reference_id == ref.id)
                .order_by(SourceReviewEvent.occurred_at, SourceReviewEvent.id)
            )
        ).scalars()
    )
