"""``/v1/organisations/{organisation_id}/projects/{project_id}/plan``: the project plan.

* ``GET``: the plan (or ``NONE``) with what it costs; when active, every part with its steps,
  fees, contacts and the partners to call for it, and progress.
* ``POST``: start one from the latest assessment (a checkout page when it is on sale);
  ``/checkout`` pays for one waiting; ``/cancel`` gives up on one not paid for.
* ``/refresh``: add what a newer assessment found.
* ``/steps``: add, change, tick or remove steps; ``/follow-ups``: add a call to a partner.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select

from app.api.deps import DbDep, MetaDep, OrgContext, SettingsDep, require_org_permission
from app.core.errors import ApiError, not_found
from app.modules.billing import service as billing
from app.modules.billing.catalogue import load_bundled
from app.modules.billing.router import StripeDep
from app.modules.leads.service import _open_categories
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.partners.models import PartnerOrganisation
from app.modules.plans import partners, service
from app.modules.plans.models import PlanStatus, ProjectPlan, ProjectPlanItem
from app.modules.plans.schemas import (
    FollowUpCreate,
    PlanCheckoutOut,
    PlanDocumentOut,
    PlanHelpOut,
    PlanOfferOut,
    PlanPartnerOut,
    PlanProgressOut,
    PlanSectionOut,
    PlanStartOut,
    PlanStepCreate,
    PlanStepOut,
    PlanStepUpdate,
    ProjectPlanOut,
    SuggestedPartnerOut,
)
from app.modules.projects import service as projects
from app.modules.projects.models import Project
from app.modules.tenancy.models import Organisation
from app.modules.tenancy.rbac import Perm

router = APIRouter(
    prefix="/v1/organisations/{organisation_id}/projects/{project_id}/plan", tags=["plans"]
)

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]

FOLLOW_UP_DAYS = 3


async def _offer(db: DbDep, settings: SettingsDep) -> PlanOfferOut:
    product = next(p for p in load_bundled().products if p.key == service.PRODUCT_KEY)
    price = await service.plan_price(db) if settings.payments_enabled else None
    return PlanOfferOut(
        on_sale=price is not None,
        price_cents=price[1].amount_cents if price else None,
        currency=price[1].currency if price else None,
        product_name=product.name,
        product_description=product.description,
    )


async def _partners_by_id(
    db: DbDep, ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, PlanPartnerOut]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(
        select(PartnerOrganisation, Organisation)
        .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
        .where(PartnerOrganisation.id.in_(wanted))
    )
    return {
        p.id: PlanPartnerOut(
            id=p.id, name=o.name, phone=p.phone, email=p.contact_email, website=p.website
        )
        for p, o in rows.all()
    }


def step_out(
    item: ProjectPlanItem,
    documents: dict[uuid.UUID, str],
    partner_rows: dict[uuid.UUID, PlanPartnerOut],
) -> PlanStepOut:
    return PlanStepOut(
        id=item.id,
        section_key=item.section_key,
        position=item.position,
        kind=item.kind,
        title=item.title,
        detail=item.detail,
        timeframe=item.timeframe,
        cost=item.cost,
        link_url=item.link_url,
        link_label=item.link_label,
        owner=item.owner,
        assignee_user_id=item.assignee_user_id,
        due_on=item.due_on,
        status=item.status,
        completed_at=item.completed_at,
        note=item.note,
        documents=[
            PlanDocumentOut(id=d, filename=documents[d])
            for d in item.document_ids
            if d in documents
        ],
        partner=partner_rows.get(item.partner_organisation_id)
        if item.partner_organisation_id
        else None,
        editable=item.kind in service.EDITABLE_KINDS,
    )


async def _plan_out(
    db: DbDep, settings: SettingsDep, project: Project, plan: ProjectPlan | None
) -> ProjectPlanOut:
    offer = await _offer(db, settings)
    if plan is None:
        return ProjectPlanOut(status="NONE", offer=offer)
    base: dict[str, Any] = {
        "offer": offer,
        "id": plan.id,
        "assessment_id": plan.assessment_id,
        "starts_on": plan.starts_on,
        "activated_at": plan.activated_at,
        "complimentary": plan.complimentary,
    }
    if plan.status != PlanStatus.ACTIVE:
        return ProjectPlanOut(status="PAYMENT_PENDING", **base)
    rows = await service.items(db, plan)
    documents = await service.project_documents(db, project)
    partner_rows = await _partners_by_id(db, (i.partner_organisation_id for i in rows))
    on = service.today()
    keys: list[str] = []
    for s in plan.sections:
        for k in s.get("category_keys", []):
            if k not in keys:
                keys.append(k)
    open_ids = await _open_categories(db, project)
    open_keys = (
        set(
            (
                await db.execute(
                    select(MarketplaceCategory.key).where(MarketplaceCategory.id.in_(open_ids))
                )
            ).scalars()
        )
        if open_ids
        else set()
    )
    # Last: it binds each partner's organisation in turn while reading their plans.
    helpers = {h.key: h for h in await partners.suggestions(db, project, keys, on=on)}

    sections = []
    by_section: dict[str, list[ProjectPlanItem]] = {}
    for item in rows:
        by_section.setdefault(item.section_key, []).append(item)
    known = {s["key"] for s in plan.sections}
    orphans = [i for k, group in by_section.items() if k not in known for i in group]
    for s in plan.sections:
        group = by_section.get(s["key"], [])
        if s["key"] == service.OWN_SECTION["key"]:
            group = group + orphans
        if not group and s["key"] != service.OWN_SECTION["key"]:
            continue
        counted = [i for i in group if i.status != "NOT_APPLICABLE"]
        dates = [i.due_on for i in group if i.due_on]
        help_out = []
        for k in s.get("category_keys", []):
            h = helpers.get(k)
            if h is None:
                continue
            help_out.append(
                PlanHelpOut(
                    key=h.key,
                    label=h.label,
                    description=h.description,
                    introduction_open=h.key in open_keys,
                    partners=[
                        SuggestedPartnerOut(
                            id=p.partner_id,
                            name=p.name,
                            phone=p.phone,
                            email=p.email,
                            website=p.website,
                            description=p.description,
                            why=p.why,
                            introduced=p.introduced,
                        )
                        for p in h.partners
                    ],
                )
            )
        sections.append(
            PlanSectionOut(
                **{k: v for k, v in s.items() if k not in ("category_keys",)},
                help=help_out,
                steps=[step_out(i, documents, partner_rows) for i in group],
                done=sum(1 for i in counted if i.status == "DONE"),
                total=len(counted),
                starts_on=min(dates) if dates else None,
                ends_on=max(dates) if dates else None,
            )
        )
    p = service.progress(rows, on)
    return ProjectPlanOut(status="ACTIVE", progress=PlanProgressOut(**p), sections=sections, **base)


async def _project(ctx: OrgContext, db: DbDep, project_id: uuid.UUID) -> Project:
    return await projects.get_project(db, ctx.organisation.id, project_id)


@router.get("", response_model=ProjectPlanOut)
async def get_plan(
    project_id: uuid.UUID, ctx: Read, db: DbDep, settings: SettingsDep
) -> ProjectPlanOut:
    project = await _project(ctx, db, project_id)
    return await _plan_out(db, settings, project, await service.get_plan(db, project))


@router.post("", response_model=PlanStartOut, status_code=status.HTTP_201_CREATED)
async def start_plan(
    project_id: uuid.UUID,
    ctx: Write,
    db: DbDep,
    settings: SettingsDep,
    stripe: StripeDep,
    meta: MetaDep,
) -> PlanStartOut:
    """Start a plan from the latest assessment. When it is on sale this returns a checkout
    page, and the plan starts once Stripe confirms payment; otherwise it starts now."""
    project = await _project(ctx, db, project_id)
    price = None
    if settings.payments_enabled and stripe is not None:
        price = await service.plan_price(db)
    plan = await service.start(db, project, price=price, actor_id=ctx.auth.user.id, meta=meta)
    url = None
    if plan.status == PlanStatus.PAYMENT_PENDING:
        url = await _checkout(ctx, db, settings, stripe, project, plan)
    await db.commit()
    return PlanStartOut(plan=await _plan_out(db, settings, project, plan), checkout_url=url)


async def _checkout(
    ctx: OrgContext,
    db: DbDep,
    settings: SettingsDep,
    stripe: StripeDep,
    project: Project,
    plan: ProjectPlan,
) -> str:
    if stripe is None:
        raise ApiError(409, "payments_disabled", "Payments are switched off on this server.")
    assert plan.payment_id is not None
    payment = await billing.get_payment(db, ctx.organisation.id, plan.payment_id, lock=True)
    back = f"{settings.web_base_url}/projects/{project.id}/plan"
    return await billing.checkout_for_payment(
        db,
        stripe,
        organisation=ctx.organisation,
        user=ctx.auth.user,
        payment=payment,
        success_url=f"{back}?payment=done",
        cancel_url=f"{back}?payment=cancelled",
    )


@router.post("/checkout", response_model=PlanCheckoutOut)
async def plan_checkout(
    project_id: uuid.UUID, ctx: Write, db: DbDep, settings: SettingsDep, stripe: StripeDep
) -> PlanCheckoutOut:
    """A checkout page for a plan waiting for payment."""
    project = await _project(ctx, db, project_id)
    plan = await service.get_plan(db, project, lock=True)
    if plan is None or plan.status != PlanStatus.PAYMENT_PENDING:
        raise ApiError(409, "payment_not_pending", "This plan doesn't need paying for.")
    url = await _checkout(ctx, db, settings, stripe, project, plan)
    await db.commit()
    return PlanCheckoutOut(url=url)


@router.post("/cancel", response_model=ProjectPlanOut)
async def cancel_plan(
    project_id: uuid.UUID, ctx: Write, db: DbDep, settings: SettingsDep, stripe: StripeDep
) -> ProjectPlanOut:
    """Give up on a plan that hasn't been paid for."""
    project = await _project(ctx, db, project_id)
    plan = await service.get_plan(db, project, lock=True)
    if plan is None:
        raise not_found("Project plan")
    session_id = await service.cancel_pending(db, plan)
    await db.commit()
    if session_id and stripe is not None:
        await billing.close_checkout(stripe, session_id)
    return await _plan_out(db, settings, project, None)


@router.post("/refresh", response_model=ProjectPlanOut)
async def refresh_plan(
    project_id: uuid.UUID, ctx: Write, db: DbDep, settings: SettingsDep
) -> ProjectPlanOut:
    """Add the steps a newer assessment found; nothing is removed or reopened."""
    project = await _project(ctx, db, project_id)
    plan = await service.require_active(db, project, lock=True)
    await service.refresh(db, project, plan, actor_id=ctx.auth.user.id)
    await db.commit()
    return await _plan_out(db, settings, project, plan)


async def _step_out(db: DbDep, project: Project, item: ProjectPlanItem) -> PlanStepOut:
    return step_out(
        item,
        await service.project_documents(db, project),
        await _partners_by_id(db, [item.partner_organisation_id]),
    )


@router.post("/steps", response_model=PlanStepOut, status_code=status.HTTP_201_CREATED)
async def add_step(
    project_id: uuid.UUID, body: PlanStepCreate, ctx: Write, db: DbDep
) -> PlanStepOut:
    project = await _project(ctx, db, project_id)
    plan = await service.require_active(db, project, lock=True)
    item = await service.add_item(db, project, plan, body.model_dump(), actor_id=ctx.auth.user.id)
    await db.commit()
    return await _step_out(db, project, item)


@router.patch("/steps/{step_id}", response_model=PlanStepOut)
async def update_step(
    project_id: uuid.UUID, step_id: uuid.UUID, body: PlanStepUpdate, ctx: Write, db: DbDep
) -> PlanStepOut:
    """Tick, untick or mark a step as not applying; change its date, owner or note; attach
    files from the project's uploads. Send only what changes."""
    project = await _project(ctx, db, project_id)
    plan = await service.require_active(db, project)
    item = await service.get_item(db, plan, step_id)
    item = await service.update_item(
        db,
        project,
        plan,
        item,
        body.model_dump(exclude_unset=True),
        actor_id=ctx.auth.user.id,
    )
    await db.commit()
    return await _step_out(db, project, item)


@router.delete("/steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_step(project_id: uuid.UUID, step_id: uuid.UUID, ctx: Write, db: DbDep) -> Response:
    """Remove one of your own steps or follow-ups."""
    project = await _project(ctx, db, project_id)
    plan = await service.require_active(db, project)
    await service.delete_item(db, await service.get_item(db, plan, step_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/follow-ups", response_model=PlanStepOut, status_code=status.HTTP_201_CREATED)
async def add_follow_up(
    project_id: uuid.UUID, body: FollowUpCreate, ctx: Write, db: DbDep
) -> PlanStepOut:
    """Add a step to call a partner, with their contact details and (by default) an email
    reminder on the morning it is due."""
    project = await _project(ctx, db, project_id)
    plan = await service.require_active(db, project, lock=True)
    found = await partners.partner_contact(db, body.partner_id)
    if found is None:
        raise not_found("Partner")
    partner, organisation = found
    contact = ", ".join(
        x
        for x in (
            f"phone {partner.phone}" if partner.phone else None,
            f"email {partner.contact_email}" if partner.contact_email else None,
            partner.website,
        )
        if x
    )
    due_on = body.due_on or service.today() + timedelta(days=FOLLOW_UP_DAYS)
    if due_on < date.today() - timedelta(days=1):
        raise ApiError(422, "in_the_past", "Choose today or a later date.")
    item = await service.add_follow_up(
        db,
        project,
        plan,
        partner_id=partner.id,
        name=organisation.name,
        contact=contact or None,
        section_key=body.section_key,
        due_on=due_on,
        remind=body.remind,
        actor_id=ctx.auth.user.id,
    )
    await db.commit()
    return await _step_out(db, project, item)
