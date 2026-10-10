"""Organisations, memberships, roles and invitations.

Authorisation rules enforced here (callers have already checked the caller's permission
for the endpoint):

* A role can only be granted in organisation kinds it allows (also a DB trigger).
* No privilege escalation: an actor may only grant roles whose permissions are a subset
  of their own, and may only change or remove members whose permissions are a subset of
  their own.
* An organisation always keeps at least one active member able to manage members.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApiError, forbidden, not_found
from app.core.security import hash_token, new_token
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity.models import AppUser
from app.modules.tenancy.models import (
    MemberRole,
    MemberStatus,
    Organisation,
    OrganisationInvitation,
    OrganisationKind,
    OrganisationMember,
    OrganisationStatus,
    Permission,
    Role,
    role_permission,
)
from app.modules.tenancy.rbac import CREATOR_ROLES, MULTI_MEMBER_KINDS, Perm


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Membership:
    organisation: Organisation
    member: OrganisationMember
    role_keys: tuple[str, ...]
    permissions: frozenset[str]


# --- Roles and permissions -------------------------------------------------------------


async def roles_by_key(db: AsyncSession, keys: Iterable[str]) -> dict[str, Role]:
    keys = list(dict.fromkeys(keys))
    rows = (await db.execute(select(Role).where(Role.key.in_(keys)))).scalars().all()
    found = {r.key: r for r in rows}
    missing = [k for k in keys if k not in found]
    if missing:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_role", f"Unknown role: {missing[0]}"
        )
    return found


async def permissions_of_roles(db: AsyncSession, role_keys: Iterable[str]) -> frozenset[str]:
    keys = list(role_keys)
    if not keys:
        return frozenset()
    rows = await db.execute(
        select(Permission.key)
        .join(role_permission, role_permission.c.permission_id == Permission.id)
        .join(Role, Role.id == role_permission.c.role_id)
        .where(Role.key.in_(keys))
    )
    return frozenset(rows.scalars().all())


async def member_role_keys(db: AsyncSession, member_id: uuid.UUID) -> tuple[str, ...]:
    rows = await db.execute(
        select(Role.key)
        .join(MemberRole, MemberRole.role_id == Role.id)
        .where(MemberRole.organisation_member_id == member_id)
        .order_by(Role.key)
    )
    return tuple(rows.scalars().all())


async def membership(
    db: AsyncSession, user_id: uuid.UUID, organisation_id: uuid.UUID
) -> Membership | None:
    """The user's *effective* membership: active member of an active, undeleted org."""
    row = (
        await db.execute(
            select(Organisation, OrganisationMember)
            .join(OrganisationMember, OrganisationMember.organisation_id == Organisation.id)
            .where(
                Organisation.id == organisation_id,
                Organisation.deleted_at.is_(None),
                Organisation.status == OrganisationStatus.ACTIVE,
                OrganisationMember.user_id == user_id,
                OrganisationMember.status == MemberStatus.ACTIVE,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    org, member = row
    keys = await member_role_keys(db, member.id)
    return Membership(org, member, keys, await permissions_of_roles(db, keys))


async def memberships(db: AsyncSession, user_id: uuid.UUID) -> list[Membership]:
    rows = (
        await db.execute(
            select(Organisation, OrganisationMember)
            .join(OrganisationMember, OrganisationMember.organisation_id == Organisation.id)
            .where(
                Organisation.deleted_at.is_(None),
                Organisation.status == OrganisationStatus.ACTIVE,
                OrganisationMember.user_id == user_id,
                OrganisationMember.status == MemberStatus.ACTIVE,
            )
            .order_by(Organisation.kind != OrganisationKind.PERSONAL, Organisation.name)
        )
    ).all()
    result = []
    for org, member in rows:
        keys = await member_role_keys(db, member.id)
        result.append(Membership(org, member, keys, await permissions_of_roles(db, keys)))
    return result


async def personal_organisation_id(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    return (
        await db.execute(
            select(Organisation.id)
            .join(OrganisationMember, OrganisationMember.organisation_id == Organisation.id)
            .where(
                Organisation.kind == OrganisationKind.PERSONAL,
                Organisation.deleted_at.is_(None),
                OrganisationMember.user_id == user_id,
                OrganisationMember.status == MemberStatus.ACTIVE,
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _grant(
    db: AsyncSession,
    member: OrganisationMember,
    role_keys: Sequence[str],
    granted_by: uuid.UUID | None,
) -> None:
    roles = await roles_by_key(db, role_keys)
    for role in roles.values():
        db.add(MemberRole(organisation_member_id=member.id, role_id=role.id, granted_by=granted_by))
    await db.flush()


async def _check_assignable(
    db: AsyncSession, org: Organisation, role_keys: Sequence[str], actor_permissions: frozenset[str]
) -> None:
    if not role_keys:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "roles_required", "Choose at least one role."
        )
    roles = await roles_by_key(db, role_keys)
    for role in roles.values():
        if org.kind not in role.allowed_org_kinds:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "role_not_allowed",
                f"The {role.key} role cannot be used in this kind of organisation.",
            )
    if not await permissions_of_roles(db, role_keys) <= actor_permissions:
        raise forbidden("You cannot grant a role with more access than you have.")


async def _managers_remaining(db: AsyncSession, organisation_id: uuid.UUID) -> int:
    count = await db.execute(
        select(func.count(func.distinct(OrganisationMember.id)))
        .join(MemberRole, MemberRole.organisation_member_id == OrganisationMember.id)
        .join(role_permission, role_permission.c.role_id == MemberRole.role_id)
        .join(Permission, Permission.id == role_permission.c.permission_id)
        .where(
            OrganisationMember.organisation_id == organisation_id,
            OrganisationMember.status == MemberStatus.ACTIVE,
            Permission.key == Perm.ORG_MEMBERS_MANAGE,
        )
    )
    return int(count.scalar_one())


async def _require_manager_remains(db: AsyncSession, organisation_id: uuid.UUID) -> None:
    await db.flush()
    if await _managers_remaining(db, organisation_id) < 1:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "last_admin",
            "The organisation needs at least one member who can manage members.",
        )


# --- Organisations ---------------------------------------------------------------------


async def create_organisation(
    db: AsyncSession,
    *,
    creator: AppUser,
    kind: OrganisationKind,
    name: str,
    abn: str | None = None,
    meta: RequestMeta | None = None,
) -> Organisation:
    org = Organisation(kind=kind, name=name, abn=abn, created_by=creator.id)
    db.add(org)
    await db.flush()
    member = OrganisationMember(organisation_id=org.id, user_id=creator.id, created_by=creator.id)
    db.add(member)
    await db.flush()
    roles = CREATOR_ROLES[kind]
    await _grant(db, member, roles, granted_by=creator.id)
    await audit.record(
        db,
        "org.created",
        actor_user_id=creator.id,
        organisation_id=org.id,
        target_type="organisation",
        target_id=org.id,
        meta=meta,
        details={"kind": kind, "roles": list(roles)},
    )
    return org


async def update_organisation(
    db: AsyncSession,
    org: Organisation,
    *,
    actor_id: uuid.UUID,
    changes: dict[str, object],
    meta: RequestMeta | None,
) -> Organisation:
    applied = {k: v for k, v in changes.items() if getattr(org, k) != v}
    for key, value in applied.items():
        setattr(org, key, value)
    if applied:
        await db.flush()
        await audit.record(
            db,
            "org.updated",
            actor_user_id=actor_id,
            organisation_id=org.id,
            target_type="organisation",
            target_id=org.id,
            meta=meta,
            details={"fields": sorted(applied)},
        )
    return org


# --- Members ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemberView:
    member: OrganisationMember
    user: AppUser
    role_keys: tuple[str, ...]


async def list_members(db: AsyncSession, organisation_id: uuid.UUID) -> list[MemberView]:
    rows = (
        await db.execute(
            select(OrganisationMember, AppUser)
            .join(AppUser, AppUser.id == OrganisationMember.user_id)
            .where(
                OrganisationMember.organisation_id == organisation_id,
                OrganisationMember.status == MemberStatus.ACTIVE,
            )
            .order_by(AppUser.display_name)
        )
    ).all()
    return [MemberView(m, u, await member_role_keys(db, m.id)) for m, u in rows]


async def _target_member(
    db: AsyncSession, organisation_id: uuid.UUID, member_id: uuid.UUID
) -> OrganisationMember:
    member = await db.get(OrganisationMember, member_id)
    if (
        member is None
        or member.organisation_id != organisation_id
        or member.status != MemberStatus.ACTIVE
    ):
        raise not_found("Member")
    return member


async def _check_can_manage(
    db: AsyncSession, member: OrganisationMember, actor_permissions: frozenset[str]
) -> tuple[str, ...]:
    current = await member_role_keys(db, member.id)
    if not await permissions_of_roles(db, current) <= actor_permissions:
        raise forbidden("You cannot change a member who has more access than you.")
    return current


async def set_member_roles(
    db: AsyncSession,
    org: Organisation,
    member_id: uuid.UUID,
    role_keys: Sequence[str],
    *,
    actor_id: uuid.UUID,
    actor_permissions: frozenset[str],
    meta: RequestMeta | None,
) -> MemberView:
    member = await _target_member(db, org.id, member_id)
    before = await _check_can_manage(db, member, actor_permissions)
    await _check_assignable(db, org, role_keys, actor_permissions)
    await db.execute(delete(MemberRole).where(MemberRole.organisation_member_id == member.id))
    await _grant(db, member, role_keys, granted_by=actor_id)
    await _require_manager_remains(db, org.id)
    after = await member_role_keys(db, member.id)
    await audit.record(
        db,
        "org.member.roles_changed",
        actor_user_id=actor_id,
        organisation_id=org.id,
        target_type="organisation_member",
        target_id=member.id,
        meta=meta,
        details={"user_id": str(member.user_id), "before": list(before), "after": list(after)},
    )
    user = await db.get(AppUser, member.user_id)
    assert user is not None
    return MemberView(member, user, after)


async def remove_member(
    db: AsyncSession,
    org: Organisation,
    member_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    actor_permissions: frozenset[str],
    meta: RequestMeta | None,
) -> None:
    member = await _target_member(db, org.id, member_id)
    if org.kind == OrganisationKind.PERSONAL:
        raise ApiError(
            status.HTTP_409_CONFLICT, "personal_org", "You cannot leave your personal account."
        )
    if member.user_id != actor_id:
        await _check_can_manage(db, member, actor_permissions)
    member.status = MemberStatus.REMOVED
    await db.execute(delete(MemberRole).where(MemberRole.organisation_member_id == member.id))
    await _require_manager_remains(db, org.id)
    await audit.record(
        db,
        "org.member.removed",
        actor_user_id=actor_id,
        organisation_id=org.id,
        target_type="organisation_member",
        target_id=member.id,
        meta=meta,
        details={"user_id": str(member.user_id), "self": member.user_id == actor_id},
    )


# --- Invitations -----------------------------------------------------------------------


async def _check_partner_seats(
    db: AsyncSession, organisation_id: uuid.UUID, email: str, now: datetime
) -> None:
    """A partner plan limits the people in the account (members and open invitations)."""
    from app.modules.billing import service as billing
    from app.modules.partners.entitlements import MEMBERS_FEATURE, members_in_use

    invited = (
        await db.execute(
            select(func.count())
            .select_from(OrganisationInvitation)
            .where(
                OrganisationInvitation.organisation_id == organisation_id,
                OrganisationInvitation.email != email,
                OrganisationInvitation.accepted_at.is_(None),
                OrganisationInvitation.revoked_at.is_(None),
                OrganisationInvitation.expires_at > now,
            )
        )
    ).scalar_one()
    await billing.require_allowance(
        db,
        organisation_id,
        MEMBERS_FEATURE,
        in_use=await members_in_use(db, organisation_id) + int(invited),
    )


async def create_invitation(
    db: AsyncSession,
    settings: Settings,
    org: Organisation,
    *,
    email: str,
    role_keys: Sequence[str],
    actor_id: uuid.UUID,
    actor_permissions: frozenset[str],
    meta: RequestMeta | None,
) -> tuple[OrganisationInvitation, str]:
    if org.kind not in MULTI_MEMBER_KINDS:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "single_member_org",
            "Personal accounts can't have other members. Create a business organisation instead.",
        )
    await _check_assignable(db, org, role_keys, actor_permissions)
    already_member = (
        await db.execute(
            select(OrganisationMember.id)
            .join(AppUser, AppUser.id == OrganisationMember.user_id)
            .where(
                OrganisationMember.organisation_id == org.id,
                OrganisationMember.status == MemberStatus.ACTIVE,
                AppUser.email == email,
            )
        )
    ).scalar_one_or_none()
    if already_member is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT, "already_member", "That person is already a member."
        )
    now = utcnow()
    if org.kind == OrganisationKind.PARTNER:
        await _check_partner_seats(db, org.id, email, now)
    # Re-inviting replaces any open invitation for the same address.
    open_invites = (
        (
            await db.execute(
                select(OrganisationInvitation).where(
                    OrganisationInvitation.organisation_id == org.id,
                    OrganisationInvitation.email == email,
                    OrganisationInvitation.accepted_at.is_(None),
                    OrganisationInvitation.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for old in open_invites:
        old.revoked_at = now
    await db.flush()
    token = new_token()
    invitation = OrganisationInvitation(
        organisation_id=org.id,
        email=email,
        role_keys=list(dict.fromkeys(role_keys)),
        token_hash=hash_token(token),
        expires_at=now + timedelta(days=settings.invitation_ttl_days),
        created_by=actor_id,
    )
    db.add(invitation)
    await db.flush()
    await audit.record(
        db,
        "org.invitation.created",
        actor_user_id=actor_id,
        organisation_id=org.id,
        target_type="organisation_invitation",
        target_id=invitation.id,
        meta=meta,
        details={"roles": invitation.role_keys, "replaced": len(open_invites)},
    )
    return invitation, token


async def list_open_invitations(
    db: AsyncSession, organisation_id: uuid.UUID
) -> Sequence[OrganisationInvitation]:
    return (
        (
            await db.execute(
                select(OrganisationInvitation)
                .where(
                    OrganisationInvitation.organisation_id == organisation_id,
                    OrganisationInvitation.accepted_at.is_(None),
                    OrganisationInvitation.revoked_at.is_(None),
                    OrganisationInvitation.expires_at > utcnow(),
                )
                .order_by(OrganisationInvitation.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def revoke_invitation(
    db: AsyncSession,
    org: Organisation,
    invitation_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    invitation = await db.get(OrganisationInvitation, invitation_id)
    if (
        invitation is None
        or invitation.organisation_id != org.id
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
    ):
        raise not_found("Invitation")
    invitation.revoked_at = utcnow()
    await audit.record(
        db,
        "org.invitation.revoked",
        actor_user_id=actor_id,
        organisation_id=org.id,
        target_type="organisation_invitation",
        target_id=invitation.id,
        meta=meta,
    )


async def accept_invitation(
    db: AsyncSession, user: AppUser, token: str, meta: RequestMeta | None
) -> Organisation:
    invalid = ApiError(
        status.HTTP_400_BAD_REQUEST,
        "invalid_invitation",
        "This invitation link is invalid, expired or already used.",
    )
    invitation = (
        await db.execute(
            select(OrganisationInvitation)
            .where(OrganisationInvitation.token_hash == hash_token(token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = utcnow()
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
    ):
        raise invalid
    if invitation.email.lower() != user.email.lower():
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "invitation_email_mismatch",
            "This invitation was sent to a different email address. Sign in with that address.",
        )
    org = await db.get(Organisation, invitation.organisation_id)
    if org is None or org.deleted_at is not None or org.status != OrganisationStatus.ACTIVE:
        raise invalid

    member = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.organisation_id == org.id,
                OrganisationMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        member = OrganisationMember(
            organisation_id=org.id, user_id=user.id, created_by=invitation.created_by
        )
        db.add(member)
        await db.flush()
    else:
        member.status = MemberStatus.ACTIVE
        await db.execute(delete(MemberRole).where(MemberRole.organisation_member_id == member.id))
    await _grant(db, member, invitation.role_keys, granted_by=invitation.created_by)
    invitation.accepted_at = now
    invitation.accepted_by = user.id
    if user.email_verified_at is None:  # the token arrived at this address
        user.email_verified_at = now
    await audit.record(
        db,
        "org.invitation.accepted",
        actor_user_id=user.id,
        organisation_id=org.id,
        target_type="organisation_invitation",
        target_id=invitation.id,
        meta=meta,
        details={"roles": invitation.role_keys},
    )
    return org
