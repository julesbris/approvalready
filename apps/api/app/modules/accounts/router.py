"""Staff accounts routes (Milestone 27).

* ``GET /v1/admin/accounts``: the newest accounts.
* ``POST /v1/admin/accounts/search``: find accounts (the query is in the body so email
  addresses stay out of request logs).
* ``GET /v1/admin/accounts/{id}``: one account, its organisations, sessions and history.
* ``POST /v1/admin/accounts/{id}/actions``: a support action (``platform.users.manage``).
* ``POST /v1/admin/accounts/{id}/notes``: add a note or log a call (any platform role).
* ``DELETE /v1/admin/accounts/{id}/notes/{note_id}``: delete a note (its author, or
  ``platform.users.manage``).
* ``PUT /v1/admin/accounts/{id}/staff-role``: give, change or take away a staff role
  (``platform.roles.manage``).
* ``PUT /v1/admin/accounts/{id}/organisations/{org_id}/status``: suspend or restore a business
  workspace the person belongs to (``platform.users.manage``).
* ``POST /v1/admin/accounts/{id}/email``: email the person from the team address and keep a
  copy as a note (any platform role).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    DbDep,
    LimiterDep,
    MetaDep,
    OrgContext,
    ResourcesDep,
    SettingsDep,
    require_platform_permission,
)
from app.modules.accounts import notes, organisations, service, staff_roles
from app.modules.accounts.schemas import (
    AccountActionIn,
    AccountActionOut,
    AccountDetail,
    AccountSearch,
    AccountSummary,
    OrganisationStatusIn,
    StaffEmailIn,
    StaffNoteIn,
    StaffRoleIn,
)
from app.modules.identity import service as identity
from app.modules.tenancy.rbac import Perm

admin_router = APIRouter(prefix="/v1/admin/accounts", tags=["admin: accounts"])

Reader = Annotated[OrgContext, Depends(require_platform_permission(Perm.PLATFORM_USERS_READ))]
RoleManager = Annotated[
    OrgContext, Depends(require_platform_permission(Perm.PLATFORM_ROLES_MANAGE))
]
Manager = Annotated[OrgContext, Depends(require_platform_permission(Perm.PLATFORM_USERS_MANAGE))]


def _staff(ctx: OrgContext) -> service.Staff:
    return service.Staff(user_id=ctx.auth.user.id, permissions=ctx.permissions)


@admin_router.get("", response_model=list[AccountSummary])
async def newest_accounts(_: Reader, db: DbDep) -> list[AccountSummary]:
    return await service.search(db, "", None)


@admin_router.post("/search", response_model=list[AccountSummary])
async def search_accounts(body: AccountSearch, _: Reader, db: DbDep) -> list[AccountSummary]:
    return await service.search(db, body.query, body.status)


@admin_router.get("/{user_id}", response_model=AccountDetail)
async def get_account(user_id: uuid.UUID, ctx: Reader, db: DbDep, meta: MetaDep) -> AccountDetail:
    staff = _staff(ctx)
    account = await service.detail(db, staff, user_id)
    await service.record_view(db, staff, user_id, meta)
    await db.commit()
    return account


@admin_router.post("/{user_id}/actions", response_model=AccountActionOut)
async def account_action(
    user_id: uuid.UUID,
    body: AccountActionIn,
    ctx: Manager,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> AccountActionOut:
    staff = _staff(ctx)
    result = await service.perform(
        db, settings, limiter, staff, user_id, body.action, body.reason, meta
    )
    await db.commit()
    if result.email is not None:
        await identity.send_email(resources.email, result.email)
    account = await service.detail(db, staff, user_id)
    return AccountActionOut(message=result.message, account=account)


@admin_router.post("/{user_id}/notes", response_model=AccountActionOut, status_code=201)
async def add_note(
    user_id: uuid.UUID, body: StaffNoteIn, ctx: Reader, db: DbDep, meta: MetaDep
) -> AccountActionOut:
    staff = _staff(ctx)
    message = await notes.add(db, staff.permissions, staff.user_id, user_id, body, meta)
    await db.commit()
    return AccountActionOut(message=message, account=await service.detail(db, staff, user_id))


@admin_router.delete("/{user_id}/notes/{note_id}", response_model=AccountActionOut)
async def delete_note(
    user_id: uuid.UUID, note_id: uuid.UUID, ctx: Reader, db: DbDep, meta: MetaDep
) -> AccountActionOut:
    staff = _staff(ctx)
    message = await notes.remove(db, staff.permissions, staff.user_id, user_id, note_id, meta)
    await db.commit()
    return AccountActionOut(message=message, account=await service.detail(db, staff, user_id))


@admin_router.post("/{user_id}/email", response_model=AccountActionOut)
async def email_account(
    user_id: uuid.UUID,
    body: StaffEmailIn,
    ctx: Reader,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> AccountActionOut:
    staff = _staff(ctx)
    message, email = await notes.contact(
        db, settings, limiter, staff.permissions, staff.user_id, user_id, body, meta
    )
    await db.commit()
    await identity.send_email(resources.email, email)
    return AccountActionOut(message=message, account=await service.detail(db, staff, user_id))


@admin_router.put("/{user_id}/staff-role", response_model=AccountActionOut)
async def set_staff_role(
    user_id: uuid.UUID,
    body: StaffRoleIn,
    ctx: RoleManager,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    meta: MetaDep,
) -> AccountActionOut:
    staff = _staff(ctx)
    message, email = await staff_roles.set_role(
        db,
        settings,
        staff.permissions,
        staff.user_id,
        ctx.organisation,
        user_id,
        body.role,
        body.reason,
        meta,
    )
    await db.commit()
    if email is not None:
        await identity.send_email(resources.email, email)
    return AccountActionOut(message=message, account=await service.detail(db, staff, user_id))


@admin_router.put(
    "/{user_id}/organisations/{organisation_id}/status", response_model=AccountActionOut
)
async def set_organisation_status(
    user_id: uuid.UUID,
    organisation_id: uuid.UUID,
    body: OrganisationStatusIn,
    ctx: Manager,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    meta: MetaDep,
) -> AccountActionOut:
    staff = _staff(ctx)
    message, emails = await organisations.set_status(
        db,
        settings,
        staff.permissions,
        staff.user_id,
        user_id,
        organisation_id,
        body.status,
        body.reason,
        meta,
    )
    await db.commit()
    for email in emails:
        await identity.send_email(resources.email, email)
    return AccountActionOut(message=message, account=await service.detail(db, staff, user_id))
