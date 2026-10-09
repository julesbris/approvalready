"""RentReady: ``/v1/organisations/{organisation_id}/projects/{id}/rental`` (the rental and
its listing, applications, tenancies, inspections and maintenance), and
``/tenant-applications/{id}``, ``/tenancies/{id}``, ``/inspections/{id}``,
``/inspection-items/{id}`` and ``/maintenance-items/{id}``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbDep, MetaDep, OrgContext, require_org_permission
from app.modules.projects import service as projects
from app.modules.projects.models import Project
from app.modules.rentals import service
from app.modules.rentals.models import (
    Inspection,
    InspectionItem,
    MaintenanceItem,
    Rental,
    Tenancy,
    TenantApplication,
)
from app.modules.rentals.schemas import (
    ApplicationCheckOut,
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    InspectionCreate,
    InspectionDetailOut,
    InspectionItemCreate,
    InspectionItemOut,
    InspectionItemUpdate,
    InspectionOut,
    InspectionUpdate,
    MaintenanceCreate,
    MaintenanceOut,
    MaintenanceUpdate,
    RentalOut,
    RentalUpdate,
    TenancyCreate,
    TenancyOut,
    TenancyUpdate,
)
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["rentals"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]


async def _project(db: AsyncSession, ctx: OrgContext, project_id: uuid.UUID) -> Project:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    service.require_rent_project(project)
    return project


async def rental_out(db: AsyncSession, project: Project, r: Rental | None) -> RentalOut:
    applications, current, maintenance, inspections = (
        await service.summary_counts(db, r) if r is not None else (0, None, 0, 0)
    )
    return RentalOut(
        id=r.id if r else None,
        project_id=project.id,
        bedrooms=r.bedrooms if r else None,
        bathrooms=r.bathrooms if r else None,
        parking=r.parking if r else None,
        furnished=r.furnished if r else None,
        pets_considered=r.pets_considered if r else None,
        listing_status=r.listing_status if r else "NOT_LISTED",
        headline=r.headline if r else None,
        description=r.description if r else None,
        rent_cents=r.rent_cents if r else None,
        rent_period=r.rent_period if r else "WEEK",
        available_from=r.available_from if r else None,
        applications=applications,
        current_tenancy_id=current,
        open_maintenance=maintenance,
        upcoming_inspections=inspections,
        updated_at=r.updated_at if r else None,
    )


async def application_out(db: AsyncSession, a: TenantApplication) -> ApplicationOut:
    checks = service.application_checks(a)
    return ApplicationOut(
        id=a.id,
        applicant_name=a.applicant_name,
        applicant_contact=a.applicant_contact,
        household_size=a.household_size,
        preferred_start_on=a.preferred_start_on,
        received_on=a.received_on,
        status=a.status,
        checks=[ApplicationCheckOut(key=k, label=label, provided=v) for k, label, v in checks],
        missing=[label for _, label, v in checks if v is not True],
        notes=a.notes,
        tenancy_id=await service.tenancy_for_application(db, a),
        created_at=a.created_at,
    )


def tenancy_out(t: Tenancy) -> TenancyOut:
    return TenancyOut(
        id=t.id,
        application_id=t.application_id,
        tenant_names=t.tenant_names,
        tenant_contact=t.tenant_contact,
        status=service.tenancy_status(t),
        start_on=t.start_on,
        end_on=t.end_on,
        periodic=t.end_on is None,
        rent_cents=t.rent_cents,
        rent_period=t.rent_period,
        bond_cents=t.bond_cents,
        bond_lodged_on=t.bond_lodged_on,
        bond_reference=t.bond_reference,
        bond_to_lodge=bool(t.bond_cents) and t.bond_lodged_on is None,
        last_rent_increase_on=t.last_rent_increase_on,
        next_rent_review_on=t.next_rent_review_on,
        ended_on=t.ended_on,
        notes=t.notes,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def inspection_out(i: Inspection, counts: tuple[int, int]) -> InspectionOut:
    return InspectionOut(
        id=i.id,
        tenancy_id=i.tenancy_id,
        kind=i.kind,
        status=i.status,
        scheduled_at=i.scheduled_at,
        completed_at=i.completed_at,
        notes=i.notes,
        items_total=counts[0],
        items_checked=counts[1],
        created_at=i.created_at,
    )


def item_out(i: InspectionItem) -> InspectionItemOut:
    return InspectionItemOut.model_validate(i, from_attributes=True)


async def inspection_detail(
    db: AsyncSession, inspection: Inspection, project: Project
) -> InspectionDetailOut:
    items = await service.inspection_items(db, inspection)
    summary = inspection_out(inspection, (len(items), sum(1 for i in items if i.condition)))
    return InspectionDetailOut(
        **summary.model_dump(), project_id=project.id, items=[item_out(i) for i in items]
    )


def maintenance_out(m: MaintenanceItem) -> MaintenanceOut:
    return MaintenanceOut.model_validate(m, from_attributes=True)


# --- Rental ----------------------------------------------------------------------------


@router.get("/projects/{project_id}/rental", response_model=RentalOut)
async def get_rental(project_id: uuid.UUID, ctx: Read, db: DbDep) -> RentalOut:
    project = await _project(db, ctx, project_id)
    return await rental_out(db, project, await service.get_rental(db, project))


@router.patch("/projects/{project_id}/rental", response_model=RentalOut)
async def update_rental(
    project_id: uuid.UUID, body: RentalUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> RentalOut:
    """The rental's details and listing. Advertising needs a fixed rent."""
    project = await _project(db, ctx, project_id)
    rental = await service.update_rental(
        db, project, body.model_dump(exclude_unset=True), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await rental_out(db, project, rental)


# --- Applications ----------------------------------------------------------------------


@router.get("/projects/{project_id}/rental/applications", response_model=list[ApplicationOut])
async def list_applications(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[ApplicationOut]:
    """In the order received. No scores or rankings."""
    project = await _project(db, ctx, project_id)
    rental = await service.get_rental(db, project)
    if rental is None:
        return []
    return [await application_out(db, a) for a in await service.list_applications(db, rental)]


@router.post(
    "/projects/{project_id}/rental/applications",
    status_code=status.HTTP_201_CREATED,
    response_model=ApplicationOut,
)
async def add_application(
    project_id: uuid.UUID, body: ApplicationCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> ApplicationOut:
    project = await _project(db, ctx, project_id)
    application = await service.add_application(
        db, project, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await application_out(db, application)


@router.patch("/tenant-applications/{application_id}", response_model=ApplicationOut)
async def update_application(
    application_id: uuid.UUID, body: ApplicationUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> ApplicationOut:
    application, _, _ = await service.get_application(db, ctx.organisation.id, application_id)
    await service.update_application(
        db,
        application,
        body.model_dump(exclude_unset=True),
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await application_out(db, application)


@router.post(
    "/tenant-applications/{application_id}/tenancy",
    status_code=status.HTTP_201_CREATED,
    response_model=TenancyOut,
)
async def tenancy_from_application(
    application_id: uuid.UUID, body: TenancyCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> TenancyOut:
    """Approve the application and record the tenancy it leads to."""
    application, _, project = await service.get_application(db, ctx.organisation.id, application_id)
    tenancy = await service.tenancy_from_application(
        db, application, project, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return tenancy_out(tenancy)


# --- Tenancies -------------------------------------------------------------------------


@router.get("/projects/{project_id}/rental/tenancies", response_model=list[TenancyOut])
async def list_tenancies(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[TenancyOut]:
    project = await _project(db, ctx, project_id)
    rental = await service.get_rental(db, project)
    return [tenancy_out(t) for t in await service.list_tenancies(db, rental)] if rental else []


@router.post(
    "/projects/{project_id}/rental/tenancies",
    status_code=status.HTTP_201_CREATED,
    response_model=TenancyOut,
)
async def add_tenancy(
    project_id: uuid.UUID, body: TenancyCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> TenancyOut:
    """Record a tenancy (an existing one, or one not from an application here)."""
    project = await _project(db, ctx, project_id)
    tenancy = await service.add_tenancy(
        db, project, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return tenancy_out(tenancy)


@router.patch("/tenancies/{tenancy_id}", response_model=TenancyOut)
async def update_tenancy(
    tenancy_id: uuid.UUID, body: TenancyUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> TenancyOut:
    tenancy, _, project = await service.get_tenancy(db, ctx.organisation.id, tenancy_id)
    await service.update_tenancy(
        db,
        tenancy,
        project,
        body.model_dump(exclude_unset=True),
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return tenancy_out(tenancy)


# --- Inspections -----------------------------------------------------------------------


@router.get("/projects/{project_id}/rental/inspections", response_model=list[InspectionOut])
async def list_inspections(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[InspectionOut]:
    project = await _project(db, ctx, project_id)
    rental = await service.get_rental(db, project)
    if rental is None:
        return []
    inspections = await service.list_inspections(db, rental)
    counts = await service.item_counts(db, rental.organisation_id, [i.id for i in inspections])
    return [inspection_out(i, counts.get(i.id, (0, 0))) for i in inspections]


@router.post(
    "/projects/{project_id}/rental/inspections",
    status_code=status.HTTP_201_CREATED,
    response_model=InspectionDetailOut,
)
async def add_inspection(
    project_id: uuid.UUID, body: InspectionCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> InspectionDetailOut:
    """Schedule an inspection with a room-by-room list to fill in on a phone."""
    project = await _project(db, ctx, project_id)
    inspection = await service.add_inspection(
        db, project, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await inspection_detail(db, inspection, project)


@router.get("/inspections/{inspection_id}", response_model=InspectionDetailOut)
async def get_inspection(inspection_id: uuid.UUID, ctx: Read, db: DbDep) -> InspectionDetailOut:
    inspection, _, project = await service.get_inspection(db, ctx.organisation.id, inspection_id)
    return await inspection_detail(db, inspection, project)


@router.patch("/inspections/{inspection_id}", response_model=InspectionDetailOut)
async def update_inspection(
    inspection_id: uuid.UUID, body: InspectionUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> InspectionDetailOut:
    inspection, _, project = await service.get_inspection(db, ctx.organisation.id, inspection_id)
    await service.update_inspection(
        db,
        inspection,
        project,
        body.model_dump(exclude_unset=True),
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await inspection_detail(db, inspection, project)


@router.post(
    "/inspections/{inspection_id}/items",
    status_code=status.HTTP_201_CREATED,
    response_model=InspectionItemOut,
)
async def add_item(
    inspection_id: uuid.UUID, body: InspectionItemCreate, ctx: Write, db: DbDep
) -> InspectionItemOut:
    inspection, _, _ = await service.get_inspection(db, ctx.organisation.id, inspection_id)
    item = await service.add_item(db, inspection, body.room, body.item)
    await db.commit()
    return item_out(item)


@router.patch("/inspection-items/{item_id}", response_model=InspectionItemOut)
async def update_item(
    item_id: uuid.UUID, body: InspectionItemUpdate, ctx: Write, db: DbDep
) -> InspectionItemOut:
    """Record an item's condition, notes and photos (clean uploads on the project)."""
    item, inspection, project = await service.get_item(db, ctx.organisation.id, item_id)
    await service.update_item(db, item, inspection, project, body.model_dump(exclude_unset=True))
    await db.commit()
    return item_out(item)


@router.delete("/inspection-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(item_id: uuid.UUID, ctx: Write, db: DbDep) -> None:
    item, inspection, _ = await service.get_item(db, ctx.organisation.id, item_id)
    await service.remove_item(db, item, inspection)
    await db.commit()


# --- Maintenance -----------------------------------------------------------------------


@router.get("/projects/{project_id}/rental/maintenance", response_model=list[MaintenanceOut])
async def list_maintenance(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[MaintenanceOut]:
    """Open items first (emergencies at the top), then closed ones."""
    project = await _project(db, ctx, project_id)
    rental = await service.get_rental(db, project)
    return (
        [maintenance_out(m) for m in await service.list_maintenance(db, rental)] if rental else []
    )


@router.post(
    "/projects/{project_id}/rental/maintenance",
    status_code=status.HTTP_201_CREATED,
    response_model=MaintenanceOut,
)
async def add_maintenance(
    project_id: uuid.UUID, body: MaintenanceCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> MaintenanceOut:
    project = await _project(db, ctx, project_id)
    item = await service.add_maintenance(
        db, project, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return maintenance_out(item)


@router.patch("/maintenance-items/{item_id}", response_model=MaintenanceOut)
async def update_maintenance(
    item_id: uuid.UUID, body: MaintenanceUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> MaintenanceOut:
    item, _, _ = await service.get_maintenance(db, ctx.organisation.id, item_id)
    await service.update_maintenance(
        db, item, body.model_dump(exclude_unset=True), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return maintenance_out(item)
