"""``/v1/organisations`` and ``/v1/invitations``: organisations, members, invitations,
organisation audit log. ``/v1/admin``: platform administration."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from app.api.deps import (
    AuthDep,
    DbDep,
    MetaDep,
    OrgContext,
    ResourcesDep,
    SettingsDep,
    require_org_permission,
    require_platform_permission,
)
from app.core.errors import forbidden, not_found
from app.modules.audit import service as audit
from app.modules.audit.models import AuditEvent
from app.modules.identity import emails
from app.modules.identity import service as identity
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import OrganisationKind
from app.modules.tenancy.rbac import Perm
from app.modules.tenancy.schemas import (
    AuditChainOut,
    AuditEventOut,
    InvitationAccept,
    InvitationCreate,
    InvitationOut,
    MemberOut,
    MemberRolesUpdate,
    OrganisationCreate,
    OrganisationOut,
    OrganisationUpdate,
)

router = APIRouter(prefix="/v1", tags=["organisations"])

OrgRead = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_READ))]
OrgUpdate = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_UPDATE))]
MembersRead = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_MEMBERS_READ))]
MembersManage = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_MEMBERS_MANAGE))]
InvitesManage = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_INVITATIONS_MANAGE))]
OrgAudit = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_AUDIT_READ))]
PlatformAudit = Annotated[
    OrgContext, Depends(require_platform_permission(Perm.PLATFORM_AUDIT_READ))
]


def _org_out(ctx: OrgContext) -> OrganisationOut:
    org = ctx.organisation
    return OrganisationOut(
        id=org.id,
        kind=org.kind,
        name=org.name,
        abn=org.abn,
        status=org.status,
        created_at=org.created_at,
        roles=list(ctx.role_keys),
        permissions=sorted(ctx.permissions),
    )


def _member_out(view: tenancy.MemberView) -> MemberOut:
    return MemberOut(
        id=view.member.id,
        user_id=view.user.id,
        email=view.user.email,
        display_name=view.user.display_name,
        roles=list(view.role_keys),
        joined_at=view.member.created_at,
    )


# --- Organisations ---------------------------------------------------------------------


@router.get("/organisations", response_model=list[OrganisationOut])
async def list_organisations(auth: AuthDep, db: DbDep) -> list[OrganisationOut]:
    return [
        _org_out(OrgContext(auth, m.organisation, m.role_keys, m.permissions))
        for m in await tenancy.memberships(db, auth.user.id)
    ]


@router.post("/organisations", status_code=status.HTTP_201_CREATED, response_model=OrganisationOut)
async def create_organisation(
    body: OrganisationCreate, auth: AuthDep, db: DbDep, meta: MetaDep
) -> OrganisationOut:
    org = await tenancy.create_organisation(
        db,
        creator=auth.user,
        kind=OrganisationKind(body.kind),
        name=body.name.strip(),
        abn=body.abn,
        meta=meta,
    )
    await db.commit()
    found = await tenancy.membership(db, auth.user.id, org.id)
    assert found is not None
    return _org_out(OrgContext(auth, found.organisation, found.role_keys, found.permissions))


@router.get("/organisations/{organisation_id}", response_model=OrganisationOut)
async def get_organisation(ctx: OrgRead) -> OrganisationOut:
    return _org_out(ctx)


@router.patch("/organisations/{organisation_id}", response_model=OrganisationOut)
async def update_organisation(
    body: OrganisationUpdate, ctx: OrgUpdate, db: DbDep, meta: MetaDep
) -> OrganisationOut:
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        del changes["name"]
    await tenancy.update_organisation(
        db, ctx.organisation, actor_id=ctx.auth.user.id, changes=changes, meta=meta
    )
    await db.commit()
    return _org_out(ctx)


# --- Members ---------------------------------------------------------------------------


@router.get("/organisations/{organisation_id}/members", response_model=list[MemberOut])
async def list_members(ctx: MembersRead, db: DbDep) -> list[MemberOut]:
    return [_member_out(v) for v in await tenancy.list_members(db, ctx.organisation.id)]


@router.put("/organisations/{organisation_id}/members/{member_id}/roles", response_model=MemberOut)
async def set_member_roles(
    member_id: uuid.UUID, body: MemberRolesUpdate, ctx: MembersManage, db: DbDep, meta: MetaDep
) -> MemberOut:
    view = await tenancy.set_member_roles(
        db,
        ctx.organisation,
        member_id,
        body.roles,
        actor_id=ctx.auth.user.id,
        actor_permissions=ctx.permissions,
        meta=meta,
    )
    await db.commit()
    return _member_out(view)


@router.delete(
    "/organisations/{organisation_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(member_id: uuid.UUID, ctx: OrgRead, db: DbDep, meta: MetaDep) -> None:
    """Remove a member (needs org.members.manage) or leave the organisation (own membership)."""
    own = await tenancy.membership(db, ctx.auth.user.id, ctx.organisation.id)
    is_self = own is not None and own.member.id == member_id
    if not is_self and not ctx.can(Perm.ORG_MEMBERS_MANAGE):
        raise forbidden()
    await tenancy.remove_member(
        db,
        ctx.organisation,
        member_id,
        actor_id=ctx.auth.user.id,
        actor_permissions=ctx.permissions,
        meta=meta,
    )
    await db.commit()


# --- Invitations -----------------------------------------------------------------------


@router.get("/organisations/{organisation_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(ctx: InvitesManage, db: DbDep) -> list[InvitationOut]:
    return [
        InvitationOut(
            id=i.id,
            email=i.email,
            roles=i.role_keys,
            expires_at=i.expires_at,
            created_at=i.created_at,
        )
        for i in await tenancy.list_open_invitations(db, ctx.organisation.id)
    ]


@router.post(
    "/organisations/{organisation_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationOut,
)
async def create_invitation(
    body: InvitationCreate,
    ctx: InvitesManage,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    meta: MetaDep,
) -> InvitationOut:
    invitation, token = await tenancy.create_invitation(
        db,
        settings,
        ctx.organisation,
        email=str(body.email).lower(),
        role_keys=body.roles,
        actor_id=ctx.auth.user.id,
        actor_permissions=ctx.permissions,
        meta=meta,
    )
    await db.commit()
    await identity.send_email(
        resources.email,
        emails.invitation(
            settings, invitation.email, ctx.organisation.name, ctx.auth.user.display_name, token
        ),
    )
    return InvitationOut(
        id=invitation.id,
        email=invitation.email,
        roles=invitation.role_keys,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


@router.delete(
    "/organisations/{organisation_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    invitation_id: uuid.UUID, ctx: InvitesManage, db: DbDep, meta: MetaDep
) -> None:
    await tenancy.revoke_invitation(
        db, ctx.organisation, invitation_id, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()


@router.post("/invitations/accept", response_model=OrganisationOut)
async def accept_invitation(
    body: InvitationAccept, auth: AuthDep, db: DbDep, meta: MetaDep
) -> OrganisationOut:
    org = await tenancy.accept_invitation(db, auth.user, body.token, meta)
    await db.commit()
    found = await tenancy.membership(db, auth.user.id, org.id)
    if found is None:
        raise not_found("Organisation")
    return _org_out(OrgContext(auth, found.organisation, found.role_keys, found.permissions))


# --- Audit -----------------------------------------------------------------------------


@router.get("/organisations/{organisation_id}/audit-events", response_model=list[AuditEventOut])
async def list_audit_events(
    ctx: OrgAudit,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_seq: Annotated[int | None, Query(ge=1)] = None,
) -> list[AuditEventOut]:
    stmt = select(AuditEvent).where(AuditEvent.organisation_id == ctx.organisation.id)
    if before_seq is not None:
        stmt = stmt.where(AuditEvent.seq < before_seq)
    rows = (await db.execute(stmt.order_by(AuditEvent.seq.desc()).limit(limit))).scalars()
    return [
        AuditEventOut(
            seq=e.seq,
            id=e.id,
            occurred_at=e.occurred_at,
            action=e.action,
            actor_user_id=e.actor_user_id,
            target_type=e.target_type,
            target_id=e.target_id,
            details=e.details,
        )
        for e in rows
    ]


@router.get("/admin/audit/verify", response_model=AuditChainOut, tags=["admin"])
async def verify_audit_chain(ctx: PlatformAudit, db: DbDep) -> AuditChainOut:
    result = await audit.verify_chain(db)
    return AuditChainOut(ok=result.ok, checked=result.checked, first_bad_seq=result.first_bad_seq)
