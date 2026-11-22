"""Staff notes on an account, logged calls, and emailing the person from Admin > Accounts.

Rules:

* Every platform role (``platform.users.read``) may add notes, log calls and email a person,
  because that is everyday support work; deleting someone else's note needs
  ``platform.users.manage``. Nobody does any of it on their own account, or on a closed one.
* Emails go through the normal outbox from the team address, so replies come back to the
  team inbox, and are capped per address like every other email.
* The audit log records that a note was written or an email sent (and which project it was
  about), never what it said: the words live only here and go when the account is closed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from fastapi import status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import OutgoingEmail
from app.core.errors import ApiError, forbidden, not_found
from app.core.ratelimit import RateLimiter
from app.modules.accounts.models import NoteKind, StaffNote
from app.modules.accounts.schemas import StaffEmailIn, StaffNoteIn, StaffNoteOut
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity import service as identity
from app.modules.identity.models import AppUser
from app.modules.tenancy.rbac import Perm

NOTES_LIMIT = 100
EMAIL_KIND = "support.message"


def may_contact(permissions: frozenset[str], staff_id: uuid.UUID, user: AppUser) -> bool:
    return (
        Perm.PLATFORM_USERS_READ in permissions and user.id != staff_id and user.deleted_at is None
    )


def _may_delete(permissions: frozenset[str], staff_id: uuid.UUID, note: StaffNote) -> bool:
    return note.author_user_id == staff_id or Perm.PLATFORM_USERS_MANAGE in permissions


async def list_for(
    db: AsyncSession, permissions: frozenset[str], staff_id: uuid.UUID, user_id: uuid.UUID
) -> list[StaffNoteOut]:
    rows = list(
        (
            await db.execute(
                select(StaffNote, AppUser.display_name)
                .outerjoin(AppUser, AppUser.id == StaffNote.author_user_id)
                .where(StaffNote.user_id == user_id)
                .order_by(StaffNote.created_at.desc(), StaffNote.id.desc())
                .limit(NOTES_LIMIT)
            )
        ).all()
    )
    return [
        StaffNoteOut(
            id=note.id,
            kind=note.kind,
            subject=note.subject,
            body=note.body,
            project_reference=note.project_reference,
            created_at=note.created_at,
            author_name=author,
            can_delete=_may_delete(permissions, staff_id, note),
        )
        for note, author in rows
    ]


async def last_contacted(
    db: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    """When staff last called or emailed each person (for Stuck projects)."""
    ids = list(user_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(StaffNote.user_id, func.max(StaffNote.created_at))
        .where(
            StaffNote.user_id.in_(ids),
            StaffNote.kind.in_([NoteKind.CALL, NoteKind.EMAIL]),
        )
        .group_by(StaffNote.user_id)
    )
    return {user_id: at for user_id, at in rows.all()}


async def _contactable(
    db: AsyncSession, permissions: frozenset[str], staff_id: uuid.UUID, user_id: uuid.UUID
) -> AppUser:
    user = await db.get(AppUser, user_id)
    if user is None:
        raise not_found("Account")
    if user.id == staff_id:
        raise forbidden("Notes are for other people's accounts.")
    if not may_contact(permissions, staff_id, user):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "account_closed",
            "This account is closed, so notes and emails are off.",
        )
    return user


def _reference(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


async def add(
    db: AsyncSession,
    permissions: frozenset[str],
    staff_id: uuid.UUID,
    user_id: uuid.UUID,
    body: StaffNoteIn,
    meta: RequestMeta,
) -> str:
    await _contactable(db, permissions, staff_id, user_id)
    text = body.body.strip()
    if not text:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "note_empty",
            "Write the note first.",
            fields={"body": "Required."},
        )
    note = StaffNote(
        user_id=user_id,
        author_user_id=staff_id,
        kind=body.kind,
        body=text,
        project_reference=_reference(body.project_reference),
    )
    db.add(note)
    await db.flush()
    await audit.record(
        db,
        "admin.account.call_logged" if body.kind == NoteKind.CALL else "admin.account.note_added",
        actor_user_id=staff_id,
        meta=meta,
        target_type="app_user",
        target_id=user_id,
        details={"note_id": str(note.id), "project": note.project_reference},
    )
    return "Call logged." if body.kind == NoteKind.CALL else "Note saved."


async def remove(
    db: AsyncSession,
    permissions: frozenset[str],
    staff_id: uuid.UUID,
    user_id: uuid.UUID,
    note_id: uuid.UUID,
    meta: RequestMeta,
) -> str:
    note = await db.get(StaffNote, note_id)
    if note is None or note.user_id != user_id:
        raise not_found("Note")
    if not _may_delete(permissions, staff_id, note):
        raise forbidden("Only the person who wrote it or an administrator can delete a note.")
    kind = note.kind
    await db.delete(note)
    await audit.record(
        db,
        "admin.account.note_deleted",
        actor_user_id=staff_id,
        meta=meta,
        target_type="app_user",
        target_id=user_id,
        details={"note_id": str(note_id), "kind": kind},
    )
    await db.flush()
    return "Deleted."


def support_email(
    settings: Settings,
    to: str,
    name: str,
    subject: str,
    message: str,
    staff_name: str,
    project_reference: str | None,
) -> OutgoingEmail:
    about = f"About your project {project_reference}.\n\n" if project_reference else ""
    site = settings.web_base_url.rstrip("/")
    signature = staff_name.split()[0] if staff_name.strip() else "The ApprovalReady team"
    return OutgoingEmail(
        to=to,
        kind=EMAIL_KIND,
        subject=subject,
        text=(
            f"Hi {name},\n\n{about}{message}\n\n{signature}\nApprovalReady\n\n"
            f"Reply to this email to get back to us, or sign in at {site}."
        ),
    )


async def contact(
    db: AsyncSession,
    settings: Settings,
    limiter: RateLimiter,
    permissions: frozenset[str],
    staff_id: uuid.UUID,
    user_id: uuid.UUID,
    body: StaffEmailIn,
    meta: RequestMeta,
) -> tuple[str, OutgoingEmail]:
    user = await _contactable(db, permissions, staff_id, user_id)
    subject = " ".join(body.subject.split())
    message = body.message.strip()
    if not subject or not message:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "email_empty",
            "Add a subject and a message.",
            fields={
                **({"subject": "Required."} if not subject else {}),
                **({"message": "Required."} if not message else {}),
            },
        )
    staff = await db.get(AppUser, staff_id)
    reference = _reference(body.project_reference)
    email = support_email(
        settings,
        user.email,
        user.display_name,
        subject,
        message,
        staff.display_name if staff else "",
        reference,
    )
    limits = identity.AuthLimits.from_settings(settings)
    if not await identity.may_email(limiter, limits, EMAIL_KIND, user.email):
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "email_limit",
            "That address has had too many emails in the last hour. Try later.",
        )
    note = StaffNote(
        user_id=user.id,
        author_user_id=staff_id,
        kind=NoteKind.EMAIL,
        subject=subject,
        body=message,
        project_reference=reference,
    )
    db.add(note)
    await db.flush()
    await audit.record(
        db,
        "admin.account.emailed",
        actor_user_id=staff_id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details={"note_id": str(note.id), "project": reference},
    )
    return f"Email on its way to {user.email}. A copy is saved below.", email


async def forget(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete everything staff wrote about a person (their account is being closed)."""
    await db.execute(delete(StaffNote).where(StaffNote.user_id == user_id))
