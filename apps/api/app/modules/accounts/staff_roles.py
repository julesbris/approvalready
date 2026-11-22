"""Giving and taking away staff roles from Admin > Accounts (instead of a server command).

Rules:

* Only someone who can grant platform roles (``platform.roles.manage``, SUPERADMIN) may do
  it, never to their own account, so there is always at least one super administrator.
* Only active accounts with a confirmed email address can be given a role; closed accounts
  can't. A reason is required and kept in the audit log.
* Taking every role away removes the person from the platform organisation; their staff
  pages stop working on their next click (permissions are read on every request).
* The person is emailed when they are given a role, with how to reach the staff pages.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import OutgoingEmail
from app.core.errors import ApiError, forbidden, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity.models import AppUser, AuthSession, UserStatus
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import (
    MemberRole,
    MemberStatus,
    Organisation,
    OrganisationKind,
    OrganisationMember,
)
from app.modules.tenancy.rbac import Perm, RoleKey

PlatformRole = Literal["STAFF", "ADMIN", "SUPERADMIN"]
ROLE_NAMES: dict[str, str] = {
    RoleKey.STAFF: "Staff",
    RoleKey.ADMIN: "Platform administrator",
    RoleKey.SUPERADMIN: "Super administrator",
}


def may_change(permissions: frozenset[str], staff_id: uuid.UUID, user: AppUser) -> bool:
    return (
        Perm.PLATFORM_ROLES_MANAGE in permissions
        and user.id != staff_id
        and user.deleted_at is None
    )


def role_granted_email(
    settings: Settings, to: str, name: str, role: str, org_name: str
) -> OutgoingEmail:
    site = settings.web_base_url.rstrip("/")
    two_step = (
        "1. Turn on two-step sign-in under Account (staff pages need it), then sign in again.\n"
        if settings.staff_mfa_required
        else ""
    )
    step = 2 if two_step else 1
    return OutgoingEmail(
        to=to,
        kind="admin.staff_role_granted",
        subject=f"You now have {ROLE_NAMES.get(role, role)} access to ApprovalReady",
        text=(
            f"Hi {name},\n\nYou've been given the {ROLE_NAMES.get(role, role)} role, so you can "
            "use the staff pages.\n\nTo get there:\n"
            f"{two_step}"
            f"{step}. Choose {org_name} in the organisation menu at the top of the page.\n"
            f"{step + 1}. Open Admin.\n\nSign in at {site}/login\n\n"
            "If you weren't expecting this, reply to this email."
        ),
    )


async def set_role(
    db: AsyncSession,
    settings: Settings,
    permissions: frozenset[str],
    staff_id: uuid.UUID,
    organisation: Organisation,
    user_id: uuid.UUID,
    role: PlatformRole | None,
    reason: str,
    meta: RequestMeta,
) -> tuple[str, OutgoingEmail | None]:
    """Give ``user_id`` exactly ``role`` in the platform organisation, or none."""
    if Perm.PLATFORM_ROLES_MANAGE not in permissions:
        raise forbidden("Only a super administrator can change staff roles.")
    if organisation.kind != OrganisationKind.PLATFORM_ADMIN:
        raise forbidden()
    user = (
        await db.execute(select(AppUser).where(AppUser.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise not_found("Account")
    if user.id == staff_id:
        raise forbidden("You can't change your own staff role. Ask another super administrator.")
    if user.deleted_at is not None:
        raise ApiError(status.HTTP_409_CONFLICT, "account_closed", "This account is closed.")
    reason = reason.strip()
    if not reason:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "reason_required",
            "Say why (it is kept in the audit log).",
            fields={"reason": "Required."},
        )
    member = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.organisation_id == organisation.id,
                OrganisationMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    active = member is not None and member.status == MemberStatus.ACTIVE
    before = list(await tenancy.member_role_keys(db, member.id)) if member and active else []

    if role is None:
        if not active or member is None:
            raise ApiError(
                status.HTTP_409_CONFLICT, "no_staff_role", "This account has no staff role."
            )
        member.status = MemberStatus.REMOVED
        await db.execute(delete(MemberRole).where(MemberRole.organisation_member_id == member.id))
        # Their open sessions drop back to their own workspace.
        await db.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.active_organisation_id == organisation.id,
            )
            .values(active_organisation_id=None)
        )
        action, message, email = "platform.role_removed", "Staff access removed.", None
    else:
        if user.status != UserStatus.ACTIVE or user.email_verified_at is None:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "account_not_ready",
                "Only an active account with a confirmed email address can be given a role.",
            )
        if before == [role]:
            raise ApiError(
                status.HTTP_409_CONFLICT, "same_role", "They already have exactly that role."
            )
        if member is None:
            member = OrganisationMember(organisation_id=organisation.id, user_id=user.id)
            db.add(member)
            await db.flush()
        member.status = MemberStatus.ACTIVE
        await db.execute(delete(MemberRole).where(MemberRole.organisation_member_id == member.id))
        roles = await tenancy.roles_by_key(db, [role])
        db.add(
            MemberRole(
                organisation_member_id=member.id, role_id=roles[role].id, granted_by=staff_id
            )
        )
        action = "platform.role_granted"
        message = f"{user.display_name} is now {ROLE_NAMES[RoleKey(role)]}. They've been emailed."
        email = role_granted_email(settings, user.email, user.display_name, role, organisation.name)
    await db.flush()
    await audit.record(
        db,
        action,
        actor_user_id=staff_id,
        organisation_id=organisation.id,
        meta=meta,
        target_type="app_user",
        target_id=user.id,
        details={
            "before": before,
            "after": [role] if role else [],
            "reason": reason,
            "via": "admin",
        },
    )
    return message, email
