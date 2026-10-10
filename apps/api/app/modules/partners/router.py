"""Partner routes.

* ``POST /v1/partners/applications``: anyone signed in applies; this creates the partner
  organisation with the applicant as its admin.
* ``/v1/organisations/{id}/partner...``: the partner's own account (``org.read`` to see it,
  ``partner.manage`` to change it). The organisation must be a partner organisation.
* ``/v1/admin/partners...``: staff verification (``partner.verify``).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

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
from app.core.errors import not_found
from app.db.tenant import bind_tenant
from app.modules.assessments.service import assessment_date
from app.modules.identity import service as identity
from app.modules.partners import emails, entitlements, service
from app.modules.partners.models import PartnerOrganisation, PartnerStatus
from app.modules.partners.schemas import (
    PartnerApplicationIn,
    PartnerApplicationOut,
    PartnerCategoryCheckIn,
    PartnerCategoryCredentialIn,
    PartnerCategoryIn,
    PartnerCategoryOut,
    PartnerCredentialCheckIn,
    PartnerCredentialIn,
    PartnerCredentialOut,
    PartnerMemberOut,
    PartnerOut,
    PartnerPlanLimitOut,
    PartnerPlanOut,
    PartnerProfileUpdate,
    PartnerServiceAreaIn,
    PartnerServiceAreaOut,
    PartnerStatusIn,
    PartnerSummaryOut,
    StaffPartnerOut,
)
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import OrganisationKind
from app.modules.tenancy.rbac import Perm

apply_router = APIRouter(prefix="/v1/partners", tags=["partners"])
router = APIRouter(prefix="/v1/organisations/{organisation_id}/partner", tags=["partners"])
admin_router = APIRouter(prefix="/v1/admin/partners", tags=["admin: partners"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_READ))]
Manage = Annotated[OrgContext, Depends(require_org_permission(Perm.PARTNER_MANAGE))]
Verify = Annotated[OrgContext, Depends(require_platform_permission(Perm.PARTNER_VERIFY))]


# --- Output ------------------------------------------------------------------------------


def _plan_out(p: entitlements.Plan) -> PartnerPlanOut:
    sub = p.subscription
    return PartnerPlanOut(
        name=p.name,
        status=sub.status if sub else None,
        current_period_end=sub.current_period_end if sub else None,
        cancel_at_period_end=sub.cancel_at_period_end if sub else False,
        grace_ends_at=p.grace_ends_at,
        limits=[
            PartnerPlanLimitOut(
                feature=x.feature, description=x.description, limit=x.limit, in_use=x.in_use
            )
            for x in p.limits
        ],
    )


async def _out(
    db: DbDep, partner: PartnerOrganisation, *, plan: bool, staff: bool = False
) -> PartnerOut:
    """The partner as its members (or staff) see it. ``plan``: the partner organisation is
    bound as the tenant, so its subscription can be read."""
    partner_id = partner.id
    db.expire_all()
    partner = await service.get_partner(db, partner_id)
    v = await service.view(db, partner)
    on = assessment_date()
    plan_view = await entitlements.plan(db, partner.organisation_id) if plan else None
    s = await entitlements.standing(db, partner, on=on, plan_view=plan_view)
    by_id = {c.row.id: c for c in s.categories}
    counted_areas = {a.row.id: a.counts for a in s.areas}
    fields = {
        "id": partner.id,
        "organisation_id": partner.organisation_id,
        "name": v.organisation.name,
        "abn": v.organisation.abn,
        "status": partner.verification_status,
        "status_reason": partner.status_reason,
        "status_changed_at": partner.status_changed_at,
        "submitted_at": partner.submitted_at,
        "website": partner.website,
        "phone": partner.phone,
        "contact_email": partner.contact_email,
        "description": partner.description,
        "categories": [
            PartnerCategoryOut(
                id=pc.id,
                category_key=mc.key,
                label=mc.label,
                description=mc.description,
                verticals=mc.verticals,
                requires_credential=mc.requires_credential,
                restricted=mc.restricted,
                status=pc.status,
                credential_id=pc.credential_id,
                notes=pc.notes,
                counts=by_id[pc.id].counts,
                problems=by_id[pc.id].problems,
            )
            for pc, mc in v.categories
        ],
        "service_areas": [
            PartnerServiceAreaOut(
                id=a.id, kind=a.kind, state=a.state, value=a.value, counts=counted_areas[a.id]
            )
            for a in v.areas
        ],
        "credentials": [
            PartnerCredentialOut(
                id=c.id,
                kind=c.kind,
                issuer=c.issuer,
                number=c.number,
                cover_cents=c.cover_cents,
                expires_on=c.expires_on,
                status=c.status,
                notes=c.notes,
                verified_at=c.verified_at,
                current=entitlements.credential_current(c, on),
            )
            for c in v.credentials
        ],
        "applications": [
            PartnerApplicationOut(
                id=a.id,
                status=a.status,
                submitted_at=a.created_at,
                reviewed_at=a.reviewed_at,
                decision_notes=a.decision_notes,
                submitted_payload=a.submitted_payload if staff else None,
            )
            for a in v.applications
        ],
        "plan": _plan_out(plan_view) if plan_view else None,
        "receiving_referrals": s.receiving_referrals,
        "problems": s.problems,
        "details_locked": partner.verification_status not in service.DETAILS_EDITABLE,
    }
    if not staff:
        return PartnerOut(**fields)
    members = [
        PartnerMemberOut(
            user_id=m.user.id,
            display_name=m.user.display_name,
            email=str(m.user.email),
            roles=list(m.role_keys),
        )
        for m in await tenancy.list_members(db, partner.organisation_id)
    ]
    return StaffPartnerOut(**fields, members=members)


async def _own(ctx: OrgContext, db: DbDep, *, lock: bool = False) -> PartnerOrganisation:
    if ctx.organisation.kind != OrganisationKind.PARTNER:
        raise not_found("Partner account")
    return await service.for_organisation(db, ctx.organisation.id, lock=lock)


# --- Applying ----------------------------------------------------------------------------


@apply_router.post("/applications", response_model=PartnerOut, status_code=201)
async def apply(
    body: PartnerApplicationIn,
    auth: AuthDep,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> PartnerOut:
    """Apply to become a partner. Creates the partner organisation (switch to it to manage
    the account) and sends the application to our team."""
    email, name = str(auth.user.email), auth.user.display_name
    partner = await service.apply(db, user=auth.user, data=body, meta=meta)
    await db.commit()
    await bind_tenant(db, partner.organisation_id)
    out = await _out(db, partner, plan=True)
    await identity.send_email(resources.email, emails.applied(settings, email, name, body.name))
    return out


# --- The partner's own account -----------------------------------------------------------


@router.get("", response_model=PartnerOut)
async def get_partner(ctx: Read, db: DbDep) -> PartnerOut:
    return await _out(db, await _own(ctx, db), plan=True)


@router.patch("", response_model=PartnerOut)
async def update_partner(
    body: PartnerProfileUpdate, ctx: Manage, db: DbDep, meta: MetaDep
) -> PartnerOut:
    partner = await _own(ctx, db, lock=True)
    await service.update_profile(
        db, partner, body.model_dump(exclude_unset=True), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await _out(db, partner, plan=True)


@router.post("/resubmit", response_model=PartnerOut)
async def resubmit(ctx: Manage, db: DbDep, meta: MetaDep) -> PartnerOut:
    """Send an application that wasn't approved back to our team, after fixing it."""
    partner = await _own(ctx, db, lock=True)
    await service.resubmit(db, partner, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await _out(db, partner, plan=True)


@router.post("/categories", response_model=PartnerOut, status_code=201)
async def add_category(
    body: PartnerCategoryIn, ctx: Manage, db: DbDep, meta: MetaDep
) -> PartnerOut:
    partner = await _own(ctx, db, lock=True)
    await service.add_category(
        db, partner, body.category_key, body.credential_id, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await _out(db, partner, plan=True)


@router.patch("/categories/{partner_category_id}", response_model=PartnerOut)
async def set_category_credential(
    partner_category_id: uuid.UUID,
    body: PartnerCategoryCredentialIn,
    ctx: Manage,
    db: DbDep,
    meta: MetaDep,
) -> PartnerOut:
    """Name the licence or accreditation that covers a category (it is checked again)."""
    partner = await _own(ctx, db, lock=True)
    await service.set_category_credential(
        db, partner, partner_category_id, body.credential_id, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await _out(db, partner, plan=True)


@router.delete("/categories/{partner_category_id}", response_model=PartnerOut)
async def remove_category(
    partner_category_id: uuid.UUID, ctx: Manage, db: DbDep, meta: MetaDep
) -> PartnerOut:
    partner = await _own(ctx, db, lock=True)
    await service.remove_category(
        db, partner, partner_category_id, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await _out(db, partner, plan=True)


@router.post("/service-areas", response_model=PartnerOut, status_code=201)
async def add_service_area(
    body: PartnerServiceAreaIn, ctx: Manage, db: DbDep, meta: MetaDep
) -> PartnerOut:
    partner = await _own(ctx, db, lock=True)
    await service.add_service_area(db, partner, body, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await _out(db, partner, plan=True)


@router.delete("/service-areas/{area_id}", response_model=PartnerOut)
async def remove_service_area(
    area_id: uuid.UUID, ctx: Manage, db: DbDep, meta: MetaDep
) -> PartnerOut:
    partner = await _own(ctx, db, lock=True)
    await service.remove_service_area(db, partner, area_id, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await _out(db, partner, plan=True)


@router.post("/credentials", response_model=PartnerOut, status_code=201)
async def add_credential(
    body: PartnerCredentialIn, ctx: Manage, db: DbDep, meta: MetaDep
) -> PartnerOut:
    partner = await _own(ctx, db, lock=True)
    await service.add_credential(db, partner, body, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await _out(db, partner, plan=True)


@router.delete("/credentials/{credential_id}", response_model=PartnerOut)
async def remove_credential(
    credential_id: uuid.UUID, ctx: Manage, db: DbDep, meta: MetaDep
) -> PartnerOut:
    partner = await _own(ctx, db, lock=True)
    await service.remove_credential(
        db, partner, credential_id, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await _out(db, partner, plan=True)


# --- Staff -------------------------------------------------------------------------------


async def _staff_out(db: DbDep, partner: PartnerOrganisation) -> StaffPartnerOut:
    # Read the partner's plan as that organisation (subscriptions are tenant rows).
    await bind_tenant(db, partner.organisation_id)
    out = await _out(db, partner, plan=True, staff=True)
    assert isinstance(out, StaffPartnerOut)
    return out


@admin_router.get("", response_model=list[PartnerSummaryOut])
async def list_partners(
    ctx: Verify,
    db: DbDep,
    status: Annotated[PartnerStatus | None, Query()] = None,
) -> list[PartnerSummaryOut]:
    """Partners, newest submission first (filter by status for the review queue)."""
    return [
        PartnerSummaryOut(
            id=s.partner.id,
            organisation_id=s.organisation.id,
            name=s.organisation.name,
            abn=s.organisation.abn,
            status=s.partner.verification_status,
            submitted_at=s.partner.submitted_at,
            categories=s.categories,
            pending_categories=s.pending_categories,
            unchecked_credentials=s.unchecked_credentials,
        )
        for s in await service.list_partners(db, status)
    ]


@admin_router.get("/{partner_id}", response_model=StaffPartnerOut)
async def get_partner_staff(partner_id: uuid.UUID, ctx: Verify, db: DbDep) -> StaffPartnerOut:
    return await _staff_out(db, await service.get_partner(db, partner_id))


@admin_router.post("/{partner_id}/status", response_model=StaffPartnerOut)
async def set_status(
    partner_id: uuid.UUID,
    body: PartnerStatusIn,
    ctx: Verify,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> StaffPartnerOut:
    """Start the review, approve, reject, suspend or reinstate a partner."""
    partner = await service.get_partner(db, partner_id, lock=True)
    before = partner.verification_status
    await service.set_status(
        db, partner, body.status, body.reason, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    out = await _staff_out(db, partner)
    if before != body.status:
        for user in await service.managers(db, partner.organisation_id):
            message = emails.status_changed(
                settings, str(user.email), user.display_name, out.name, body.status
            )
            if message is not None:
                await identity.send_email(resources.email, message)
    return out


@admin_router.post("/{partner_id}/categories/{partner_category_id}", response_model=StaffPartnerOut)
async def check_category(
    partner_id: uuid.UUID,
    partner_category_id: uuid.UUID,
    body: PartnerCategoryCheckIn,
    ctx: Verify,
    db: DbDep,
    meta: MetaDep,
) -> StaffPartnerOut:
    """Approve or reject one of the partner's categories."""
    partner = await service.get_partner(db, partner_id, lock=True)
    await service.check_category(
        db,
        partner,
        partner_category_id,
        body.status,
        body.notes,
        actor_id=ctx.auth.user.id,
        meta=meta,
        on=assessment_date(),
    )
    await db.commit()
    return await _staff_out(db, partner)


@admin_router.post("/{partner_id}/credentials/{credential_id}", response_model=StaffPartnerOut)
async def check_credential(
    partner_id: uuid.UUID,
    credential_id: uuid.UUID,
    body: PartnerCredentialCheckIn,
    ctx: Verify,
    db: DbDep,
    meta: MetaDep,
) -> StaffPartnerOut:
    """Mark a licence, insurance or accreditation checked (against the issuer's register) or
    not accepted."""
    partner = await service.get_partner(db, partner_id, lock=True)
    await service.check_credential(
        db,
        partner,
        credential_id,
        body.status,
        body.notes,
        actor_id=ctx.auth.user.id,
        meta=meta,
        on=assessment_date(),
    )
    await db.commit()
    return await _staff_out(db, partner)
