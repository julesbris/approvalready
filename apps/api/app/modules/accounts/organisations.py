"""Suspending and restoring a business workspace from Admin > Accounts.

A suspended organisation drops out of every member's organisation menu and its pages and
API stop working for them (memberships only count while the organisation is active), and
its keep-going reminders stop. Nothing is deleted; restoring brings it all back.

Rules:

* Needs ``platform.users.manage`` (ADMIN and SUPERADMIN) and a reason, kept in the audit log.
* Business and professional practice workspaces only. Personal workspaces go with their
  account (suspend the account instead), partner accounts have their own suspension in
  Admin > Partners, and the platform organisation is never suspended.
* The organisation must be one the account on the page belongs to (the page it is done from).
* Every active member is emailed.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import OutgoingEmail
from app.core.errors import ApiError, forbidden, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity.models import AppUser
from app.modules.tenancy.models import (
    MemberStatus,
    Organisation,
    OrganisationKind,
    OrganisationMember,
    OrganisationStatus,
)
from app.modules.tenancy.rbac import Perm

SUSPENDABLE_KINDS = frozenset({OrganisationKind.BUSINESS, OrganisationKind.PROFESSIONAL_PRACTICE})


def may_suspend(permissions: frozenset[str], kind: str) -> bool:
    return Perm.PLATFORM_USERS_MANAGE in permissions and kind in SUSPENDABLE_KINDS


def _email(settings: Settings, to: str, name: str, org: str, suspended: bool) -> OutgoingEmail:
    site = settings.web_base_url.rstrip("/")
    if suspended:
        return OutgoingEmail(
            to=to,
            kind="admin.organisation_suspended",
            subject=f"{org} is suspended on ApprovalReady",
            text=(
                f"Hi {name},\n\nWe've suspended the {org} workspace on ApprovalReady, so you "
                "can't open it for now. Nothing in it has been deleted, and your own account "
                "still works.\n\nReply to this email if you'd like to know why or think this "
                "is a mistake."
            ),
        )
    return OutgoingEmail(
        to=to,
        kind="admin.organisation_restored",
        subject=f"{org} is open again on ApprovalReady",
        text=(
            f"Hi {name},\n\nThe {org} workspace is open again. Choose it in the organisation "
            f"menu at the top of the page after you sign in at {site}/login"
        ),
    )


async def set_status(
    db: AsyncSession,
    settings: Settings,
    permissions: frozenset[str],
    staff_id: uuid.UUID,
    user_id: uuid.UUID,
    organisation_id: uuid.UUID,
    new_status: Literal["SUSPENDED", "ACTIVE"],
    reason: str,
    meta: RequestMeta,
) -> tuple[str, list[OutgoingEmail]]:
    if Perm.PLATFORM_USERS_MANAGE not in permissions:
        raise forbidden()
    org = (
        await db.execute(
            select(Organisation).where(Organisation.id == organisation_id).with_for_update()
        )
    ).scalar_one_or_none()
    member_of = (
        await db.execute(
            select(OrganisationMember.id).where(
                OrganisationMember.organisation_id == organisation_id,
                OrganisationMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if org is None or org.deleted_at is not None or member_of is None:
        raise not_found("Organisation")
    if org.kind not in SUSPENDABLE_KINDS:
        hint = (
            "Suspend partner accounts from Admin > Partners."
            if org.kind == OrganisationKind.PARTNER
            else "Only business workspaces can be suspended here."
        )
        raise ApiError(status.HTTP_409_CONFLICT, "not_suspendable", hint)
    if org.status == new_status:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "same_status",
            "It's already like that. Reload the page.",
        )
    reason = reason.strip()
    if new_status == OrganisationStatus.SUSPENDED and not reason:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "reason_required",
            "Say why (it is kept in the audit log).",
            fields={"reason": "Required."},
        )
    before = org.status
    org.status = new_status
    suspended = new_status == OrganisationStatus.SUSPENDED
    await audit.record(
        db,
        "org.suspended" if suspended else "org.restored",
        actor_user_id=staff_id,
        organisation_id=org.id,
        meta=meta,
        target_type="organisation",
        target_id=org.id,
        details={"before": before, "reason": reason, "via": "admin", "from_user": str(user_id)},
    )
    members = (
        await db.execute(
            select(AppUser.email, AppUser.display_name)
            .join(OrganisationMember, OrganisationMember.user_id == AppUser.id)
            .where(
                OrganisationMember.organisation_id == org.id,
                OrganisationMember.status == MemberStatus.ACTIVE,
                AppUser.deleted_at.is_(None),
            )
        )
    ).all()
    await db.flush()
    emails = [_email(settings, email, name, org.name, suspended) for email, name in members]
    word = "Suspended" if suspended else "Restored"
    return f"{word} {org.name}. {len(emails)} member(s) emailed.", emails
