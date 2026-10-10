"""Staff accounts routes (Milestone 27).

* ``GET /v1/admin/accounts``: the newest accounts.
* ``POST /v1/admin/accounts/search``: find accounts (the query is in the body so email
  addresses stay out of request logs).
* ``GET /v1/admin/accounts/{id}``: one account, its organisations, sessions and history.
* ``POST /v1/admin/accounts/{id}/actions``: a support action (``platform.users.manage``).
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
from app.modules.accounts import service
from app.modules.accounts.schemas import (
    AccountActionIn,
    AccountActionOut,
    AccountDetail,
    AccountSearch,
    AccountSummary,
)
from app.modules.identity import service as identity
from app.modules.tenancy.rbac import Perm

admin_router = APIRouter(prefix="/v1/admin/accounts", tags=["admin: accounts"])

Reader = Annotated[OrgContext, Depends(require_platform_permission(Perm.PLATFORM_USERS_READ))]
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
