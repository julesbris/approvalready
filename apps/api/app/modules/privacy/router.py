"""Privacy and legal routes (Milestone 19).

* ``POST /v1/auth/policies/accept``: agree to the current Terms of Use / Privacy Policy.
* ``GET /v1/auth/account/export``: download my data (JSON attachment).
* ``POST /v1/auth/account/close``: close my account (password, and a code with two-step
  sign-in on).
* ``POST /v1/privacy/requests``: a privacy request from the contact page (no sign-in).
* ``GET /v1/admin/privacy/requests``, ``PATCH /v1/admin/privacy/requests/{id}``: staff
  (``privacy.manage``) work the requests.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import (
    AuthDep,
    DbDep,
    LimiterDep,
    MetaDep,
    OrgContext,
    ResourcesDep,
    SettingsDep,
    clear_session_cookies,
    require_platform_permission,
)
from app.core.errors import rate_limited
from app.core.ratelimit import Limit
from app.modules.audit import service as audit
from app.modules.identity import service as identity
from app.modules.privacy import acceptance, service
from app.modules.privacy.models import PrivacyRequestStatus
from app.modules.privacy.schemas import (
    AcceptPoliciesRequest,
    CloseAccountRequest,
    PolicyOut,
    PrivacyRequestCreated,
    PrivacyRequestIn,
    PrivacyRequestOut,
    PrivacyRequestUpdate,
)
from app.modules.tenancy.rbac import Perm

account_router = APIRouter(prefix="/v1/auth", tags=["account"])
public_router = APIRouter(prefix="/v1/privacy", tags=["privacy"])
admin_router = APIRouter(prefix="/v1/admin/privacy", tags=["admin: privacy"])

Staff = Annotated[OrgContext, Depends(require_platform_permission(Perm.PRIVACY_MANAGE))]

EXPORTS_PER_HOUR = Limit("data-export", 10, 3600)
REQUESTS_PER_IP_PER_HOUR = Limit("privacy-request-ip", 5, 3600)


@account_router.post("/policies/accept", response_model=list[PolicyOut])
async def accept_policies(
    body: AcceptPoliciesRequest, auth: AuthDep, db: DbDep, meta: MetaDep
) -> list[PolicyOut]:
    """Agree to the current versions of the named documents. Returns what is still
    outstanding."""
    await acceptance.record_acceptance(db, auth.user.id, body.documents, meta)
    await db.commit()
    return [
        PolicyOut(document=p.document, title=p.title, path=p.path, version=p.version)
        for p in await acceptance.outstanding(db, auth.user.id)
    ]


@account_router.get("/account/export")
async def export_my_data(auth: AuthDep, db: DbDep, limiter: LimiterDep, meta: MetaDep) -> Response:
    """Everything held about this account and its personal workspace, as a JSON file."""
    subject = str(auth.user.id)
    if await limiter.hit(EXPORTS_PER_HOUR, subject) > EXPORTS_PER_HOUR.max_hits:
        raise rate_limited(await limiter.retry_after(EXPORTS_PER_HOUR, subject))
    data = await service.export_data(db, auth.user)
    await audit.record(
        db,
        "privacy.data_exported",
        actor_user_id=auth.user.id,
        meta=meta,
        target_type="app_user",
        target_id=auth.user.id,
    )
    await db.commit()
    day = data["exported_at"][:10]
    return Response(
        content=json.dumps(data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "content-disposition": f'attachment; filename="approvalready-my-data-{day}.json"',
            "cache-control": "no-store",
        },
    )


@account_router.post("/account/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_my_account(
    body: CloseAccountRequest,
    auth: AuthDep,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> None:
    """Close the account. Signs out everywhere; can't be undone."""
    limits = identity.AuthLimits.from_settings(settings)
    await identity.guard_request_rate(limiter, limits, meta.ip)
    message = await service.close_account(
        db, settings, limiter, auth.user, password=body.password, code=body.code, meta=meta
    )
    await db.commit()
    clear_session_cookies(response, settings)
    await identity.send_email(resources.email, message)


@public_router.post(
    "/requests", status_code=status.HTTP_202_ACCEPTED, response_model=PrivacyRequestCreated
)
async def create_privacy_request(
    body: PrivacyRequestIn,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> PrivacyRequestCreated:
    """Ask about, correct or delete personal information, or make a privacy complaint."""
    subject = meta.ip or "unknown"
    if await limiter.hit(REQUESTS_PER_IP_PER_HOUR, subject) > REQUESTS_PER_IP_PER_HOUR.max_hits:
        raise rate_limited(await limiter.retry_after(REQUESTS_PER_IP_PER_HOUR, subject))
    request = await service.create_request(
        db, name=body.name, email=body.email, kind=body.kind, details=body.details, meta=meta
    )
    await db.commit()
    await service.notify_staff(resources.email, settings, request)
    return PrivacyRequestCreated(reference=str(request.id)[-8:].upper(), due_at=request.due_at)


@admin_router.get("/requests", response_model=list[PrivacyRequestOut])
async def list_privacy_requests(
    _: Staff, db: DbDep, status: PrivacyRequestStatus | None = None
) -> list[PrivacyRequestOut]:
    return [PrivacyRequestOut.model_validate(r) for r in await service.list_requests(db, status)]


@admin_router.patch("/requests/{request_id}", response_model=PrivacyRequestOut)
async def update_privacy_request(
    request_id: uuid.UUID, body: PrivacyRequestUpdate, ctx: Staff, db: DbDep, meta: MetaDep
) -> PrivacyRequestOut:
    request = await service.resolve_request(
        db,
        request_id,
        staff_user_id=ctx.auth.user.id,
        new_status=body.status,
        note=body.note,
        meta=meta,
    )
    await db.commit()
    return PrivacyRequestOut.model_validate(request)
