"""RentReady: the rental and its listing, applications, tenancies, inspections and
maintenance.

Callers check permissions and bind the tenant; queries still filter by organisation. Audit
events name what changed (fields, statuses), never applicants' or tenants' names, contact
details, rents or notes.

Dates the customer records drive reminders (a lease end, a rent review, a bond still to
lodge, an inspection). The reminders point at the project's checklist and findings for the
rules: this module never decides a notice period or deadline itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.documents import service as documents
from app.modules.notifications import reminders
from app.modules.projects.models import Project, Vertical
from app.modules.rentals.models import (
    ApplicationStatus,
    Inspection,
    InspectionItem,
    InspectionStatus,
    ListingStatus,
    MaintenanceItem,
    MaintenanceStatus,
    Rental,
    Tenancy,
    TenancyStatus,
    TenantApplication,
)

# What an application can show, as documents provided or not. Objective facts only; no
# scores, rankings or judgements about the person.
APPLICATION_CHECKS: dict[str, str] = {
    "identity": "Identity documents",
    "income": "Evidence of income or ability to pay the rent",
    "rental_history": "Rental history or a reference from a previous landlord or agent",
    "references": "Personal or employer references",
}

LEASE_END_REMIND_DAYS = (60, 14)
RENT_REVIEW_REMIND_DAYS = (70,)
INSPECTION_REMIND_DAYS = (10, 1)

DEFAULT_ITEMS: dict[str, tuple[str, ...]] = {
    "Entry and hallways": ("Walls", "Floor", "Ceiling", "Doors", "Lights and switches"),
    "Lounge and dining": (
        "Walls",
        "Floor",
        "Ceiling",
        "Windows and screens",
        "Blinds or curtains",
        "Lights and switches",
    ),
    "Kitchen": (
        "Benches and cupboards",
        "Sink and taps",
        "Stove and oven",
        "Rangehood",
        "Floor",
        "Walls",
        "Windows and screens",
    ),
    "Bedroom": ("Walls", "Floor", "Ceiling", "Windows and screens", "Wardrobe", "Lights"),
    "Bathroom": ("Shower or bath", "Toilet", "Basin and taps", "Tiles", "Exhaust fan", "Mirror"),
    "Laundry": ("Tub and taps", "Floor", "Walls"),
    "Outside": ("Yard and garden", "Fences and gates", "Driveway or parking", "Clothesline"),
    "Safety": ("Smoke alarms", "Locks and keys", "Pool fence and gate"),
}

MAINTENANCE_OPEN = (
    MaintenanceStatus.REPORTED,
    MaintenanceStatus.SCHEDULED,
    MaintenanceStatus.IN_PROGRESS,
)


def today() -> date:
    return reminders.local_today()


def utcnow() -> datetime:
    return datetime.now(UTC)


def _fmt(on: date) -> str:
    return on.strftime("%-d %B %Y")


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


def _invalid(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


def require_rent_project(project: Project) -> None:
    if project.vertical != Vertical.RENT:
        raise _conflict("not_a_rental_project", "Rentals belong to a renting project.")


async def _audit(
    db: AsyncSession,
    action: str,
    organisation_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    **details: Any,
) -> None:
    await audit.record(
        db,
        action,
        actor_user_id=actor_id,
        organisation_id=organisation_id,
        target_type=target_type,
        target_id=target_id,
        meta=meta,
        details={k: v for k, v in details.items() if v is not None},
    )


def _apply(record: Any, changes: dict[str, Any]) -> list[str]:
    changed = [k for k, v in changes.items() if getattr(record, k) != v]
    for key in changed:
        setattr(record, key, changes[key])
    return changed


async def _one(db: AsyncSession, query: Any, what: str) -> Any:
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise not_found(what)
    return row


def _in_live_project(model: Any, organisation_id: uuid.UUID) -> Any:
    """Select ``(model, Rental, Project)`` for a row whose project isn't deleted."""
    return (
        select(model, Rental, Project)
        .join(
            Rental,
            (Rental.organisation_id == model.organisation_id) & (Rental.id == model.rental_id),
        )
        .join(
            Project,
            (Project.organisation_id == Rental.organisation_id) & (Project.id == Rental.project_id),
        )
        .where(model.organisation_id == organisation_id, Project.deleted_at.is_(None))
    )


# --- Rental and listing ----------------------------------------------------------------


async def get_rental(db: AsyncSession, project: Project, *, lock: bool = False) -> Rental | None:
    require_rent_project(project)
    query = select(Rental).where(
        Rental.organisation_id == project.organisation_id, Rental.project_id == project.id
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def ensure_rental(db: AsyncSession, project: Project, actor_id: uuid.UUID) -> Rental:
    rental = await get_rental(db, project, lock=True)
    if rental is None:
        rental = Rental(
            organisation_id=project.organisation_id, project_id=project.id, created_by=actor_id
        )
        db.add(rental)
        await db.flush()
    return rental


async def update_rental(
    db: AsyncSession,
    project: Project,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Rental:
    rental = await ensure_rental(db, project, actor_id)
    for key in ("listing_status", "rent_period"):
        if key in changes and changes[key] is None:
            del changes[key]
    listing = changes.get("listing_status", rental.listing_status)
    rent = changes.get("rent_cents", rental.rent_cents)
    if listing == ListingStatus.ADVERTISED and rent is None:
        raise _invalid(
            "rent_required",
            "Set the rent before advertising: a listing states a fixed rent, not a range or "
            "an invitation to offer more.",
        )
    changed = _apply(rental, changes)
    if changed:
        await db.flush()
        await _audit(
            db,
            "rental.updated",
            rental.organisation_id,
            "rental_property",
            rental.id,
            actor_id=actor_id,
            meta=meta,
            fields=sorted(changed),
        )
    return rental


async def summary_counts(
    db: AsyncSession, rental: Rental
) -> tuple[int, uuid.UUID | None, int, int]:
    org = rental.organisation_id
    applications = (
        await db.execute(
            select(func.count()).where(
                TenantApplication.organisation_id == org,
                TenantApplication.rental_id == rental.id,
                TenantApplication.deleted_at.is_(None),
                TenantApplication.status.in_(
                    (ApplicationStatus.RECEIVED, ApplicationStatus.SHORTLISTED)
                ),
            )
        )
    ).scalar_one()
    current = next(
        (t.id for t in await list_tenancies(db, rental) if tenancy_status(t) != "ENDED"), None
    )
    maintenance = (
        await db.execute(
            select(func.count()).where(
                MaintenanceItem.organisation_id == org,
                MaintenanceItem.rental_id == rental.id,
                MaintenanceItem.deleted_at.is_(None),
                MaintenanceItem.status.in_(MAINTENANCE_OPEN),
            )
        )
    ).scalar_one()
    inspections = (
        await db.execute(
            select(func.count()).where(
                Inspection.organisation_id == org,
                Inspection.rental_id == rental.id,
                Inspection.deleted_at.is_(None),
                Inspection.status.in_((InspectionStatus.SCHEDULED, InspectionStatus.IN_PROGRESS)),
            )
        )
    ).scalar_one()
    return int(applications), current, int(maintenance), int(inspections)


# --- Applications ----------------------------------------------------------------------


def application_checks(a: TenantApplication) -> list[tuple[str, str, bool | None]]:
    return [(key, label, a.checks.get(key)) for key, label in APPLICATION_CHECKS.items()]


async def list_applications(db: AsyncSession, rental: Rental) -> list[TenantApplication]:
    return list(
        (
            await db.execute(
                select(TenantApplication)
                .where(
                    TenantApplication.organisation_id == rental.organisation_id,
                    TenantApplication.rental_id == rental.id,
                    TenantApplication.deleted_at.is_(None),
                )
                .order_by(TenantApplication.received_on, TenantApplication.created_at)
            )
        ).scalars()
    )


async def get_application(
    db: AsyncSession, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> tuple[TenantApplication, Rental, Project]:
    row = await _one(
        db,
        _in_live_project(TenantApplication, organisation_id).where(
            TenantApplication.id == application_id, TenantApplication.deleted_at.is_(None)
        ),
        "Application",
    )
    return row[0], row[1], row[2]


async def add_application(
    db: AsyncSession,
    project: Project,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> TenantApplication:
    rental = await ensure_rental(db, project, actor_id)
    data["received_on"] = data.get("received_on") or today()
    application = TenantApplication(
        organisation_id=rental.organisation_id,
        rental_id=rental.id,
        created_by=actor_id,
        checks={},
        **data,
    )
    db.add(application)
    await db.flush()
    await _audit(
        db,
        "rental.application_recorded",
        rental.organisation_id,
        "tenant_application",
        application.id,
        actor_id=actor_id,
        meta=meta,
    )
    return application


async def update_application(
    db: AsyncSession,
    application: TenantApplication,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> TenantApplication:
    if changes.get("status") is None:
        changes.pop("status", None)
    if "checks" in changes:
        checks = changes.pop("checks") or {}
        unknown = set(checks) - set(APPLICATION_CHECKS)
        if unknown:
            raise _invalid("unknown_check", f"Unknown check: {', '.join(sorted(unknown))}.")
        merged = {**application.checks, **checks}
        changes["checks"] = {k: v for k, v in merged.items() if v is not None}
    before = application.status
    changed = _apply(application, changes)
    if changed:
        await db.flush()
        await _audit(
            db,
            "rental.application_updated",
            application.organisation_id,
            "tenant_application",
            application.id,
            actor_id=actor_id,
            meta=meta,
            fields=sorted(changed),
            **(
                {"from_status": before, "to_status": application.status}
                if "status" in changed
                else {}
            ),
        )
    return application


async def tenancy_for_application(
    db: AsyncSession, application: TenantApplication
) -> uuid.UUID | None:
    return (
        await db.execute(
            select(Tenancy.id).where(
                Tenancy.organisation_id == application.organisation_id,
                Tenancy.application_id == application.id,
                Tenancy.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


# --- Tenancies -------------------------------------------------------------------------


def tenancy_status(t: Tenancy, on: date | None = None) -> TenancyStatus:
    on = on or today()
    if t.ended_on is not None and t.ended_on <= on:
        return TenancyStatus.ENDED
    if t.start_on > on:
        return TenancyStatus.UPCOMING
    return TenancyStatus.ACTIVE


async def list_tenancies(db: AsyncSession, rental: Rental) -> list[Tenancy]:
    return list(
        (
            await db.execute(
                select(Tenancy)
                .where(
                    Tenancy.organisation_id == rental.organisation_id,
                    Tenancy.rental_id == rental.id,
                    Tenancy.deleted_at.is_(None),
                )
                .order_by(Tenancy.start_on.desc(), Tenancy.created_at.desc())
            )
        ).scalars()
    )


async def get_tenancy(
    db: AsyncSession, organisation_id: uuid.UUID, tenancy_id: uuid.UUID
) -> tuple[Tenancy, Rental, Project]:
    row = await _one(
        db,
        _in_live_project(Tenancy, organisation_id).where(
            Tenancy.id == tenancy_id, Tenancy.deleted_at.is_(None)
        ),
        "Tenancy",
    )
    return row[0], row[1], row[2]


def _check_tenancy_dates(t: dict[str, Any]) -> None:
    start = t["start_on"]
    for key, message in (
        ("end_on", "The lease can't end before it starts."),
        ("ended_on", "The tenancy can't end before it starts."),
        ("bond_lodged_on", None),
    ):
        value = t.get(key)
        if value is not None and message is not None and value < start:
            raise _invalid("dates_out_of_order", message)
    if t.get("bond_lodged_on") and not t.get("bond_cents"):
        raise _invalid("no_bond", "Record the bond amount as well as when it was lodged.")


async def _sync_tenancy_reminders(
    db: AsyncSession, project: Project, t: Tenancy, actor_id: uuid.UUID
) -> None:
    org, base = t.organisation_id, f"tenancy:{t.id}:"
    link = f"/projects/{project.id}/rental"
    if t.deleted_at is not None or t.ended_on is not None:  # leaving or left
        await reminders.cancel(db, org, base)
        return
    common: dict[str, Any] = {
        "recipient_user_id": actor_id,
        "project_id": project.id,
        "link_path": link,
    }
    end = f"{base}end:"
    await reminders.sync(
        db,
        org,
        end,
        reminders.before(
            end,
            t.end_on,
            LEASE_END_REMIND_DAYS,
            f"The lease ends {_fmt(t.end_on)}" if t.end_on else "",
            "Decide whether to offer a new lease. Your rental checklist has the notice "
            "periods for ending or renewing.",
        ),
        actor_id=actor_id,
        **common,
    )
    review = f"{base}rent_review:"
    await reminders.sync(
        db,
        org,
        review,
        reminders.before(
            review,
            t.next_rent_review_on,
            RENT_REVIEW_REMIND_DAYS,
            f"Rent review planned for {_fmt(t.next_rent_review_on)}"
            if t.next_rent_review_on
            else "",
            "Check the rules on how often rent can go up and how much notice to give before "
            "you write to the tenant.",
        ),
        actor_id=actor_id,
        **common,
    )
    bond = f"{base}bond:"
    due = max(t.start_on, today()) if t.bond_cents and t.bond_lodged_on is None else None
    await reminders.sync(
        db,
        org,
        bond,
        reminders.before(
            bond,
            due,
            (0,),
            "Lodge the tenancy bond",
            "Bonds go to the state bond authority within a set time. Record the lodgement in "
            "RentReady once it's done.",
        ),
        actor_id=actor_id,
        **common,
    )


async def add_tenancy(
    db: AsyncSession,
    project: Project,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    application: TenantApplication | None = None,
) -> Tenancy:
    rental = await ensure_rental(db, project, actor_id)
    _check_tenancy_dates(data)
    tenancy = Tenancy(
        organisation_id=rental.organisation_id,
        rental_id=rental.id,
        application_id=application.id if application else None,
        created_by=actor_id,
        **data,
    )
    db.add(tenancy)
    await db.flush()
    await _audit(
        db,
        "rental.tenancy_recorded",
        rental.organisation_id,
        "tenancy",
        tenancy.id,
        actor_id=actor_id,
        meta=meta,
        application_id=str(application.id) if application else None,
    )
    if application is not None:
        await update_application(
            db, application, {"status": ApplicationStatus.APPROVED}, actor_id=actor_id, meta=meta
        )
        if rental.listing_status == ListingStatus.ADVERTISED:
            await update_rental(
                db,
                project,
                {"listing_status": ListingStatus.LEASED},
                actor_id=actor_id,
                meta=meta,
            )
    await _sync_tenancy_reminders(db, project, tenancy, actor_id)
    return tenancy


async def tenancy_from_application(
    db: AsyncSession,
    application: TenantApplication,
    project: Project,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Tenancy:
    if application.status in (ApplicationStatus.DECLINED, ApplicationStatus.WITHDRAWN):
        raise _conflict("application_closed", "This application was declined or withdrawn.")
    if await tenancy_for_application(db, application) is not None:
        raise _conflict("tenancy_exists", "A tenancy was already recorded for this application.")
    return await add_tenancy(
        db, project, data, actor_id=actor_id, meta=meta, application=application
    )


async def update_tenancy(
    db: AsyncSession,
    tenancy: Tenancy,
    project: Project,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Tenancy:
    required = {"tenant_names", "start_on", "rent_cents", "rent_period"}
    changes = {k: v for k, v in changes.items() if not (v is None and k in required)}
    merged = {
        k: changes.get(k, getattr(tenancy, k))
        for k in ("start_on", "end_on", "ended_on", "bond_cents", "bond_lodged_on")
    }
    _check_tenancy_dates(merged)
    changed = _apply(tenancy, changes)
    if changed:
        await db.flush()
        await _audit(
            db,
            "rental.tenancy_updated",
            tenancy.organisation_id,
            "tenancy",
            tenancy.id,
            actor_id=actor_id,
            meta=meta,
            fields=sorted(changed),
        )
    await _sync_tenancy_reminders(db, project, tenancy, actor_id)
    return tenancy


# --- Inspections -----------------------------------------------------------------------


def default_rooms(rental: Rental, kind: str) -> list[str]:
    bedrooms = rental.bedrooms if rental.bedrooms is not None else 1
    bathrooms = rental.bathrooms if rental.bathrooms is not None else 1
    rooms = ["Entry and hallways", "Lounge and dining", "Kitchen"]
    rooms += ["Bedroom" if bedrooms == 1 else f"Bedroom {n}" for n in range(1, bedrooms + 1)]
    rooms += ["Bathroom" if bathrooms == 1 else f"Bathroom {n}" for n in range(1, bathrooms + 1)]
    return [*rooms, "Laundry", "Outside", "Safety"]


def _items_for(room: str) -> tuple[str, ...]:
    base = room.rstrip("0123456789 ").strip()
    return DEFAULT_ITEMS.get(room) or DEFAULT_ITEMS.get(base) or ("General condition",)


async def list_inspections(db: AsyncSession, rental: Rental) -> list[Inspection]:
    return list(
        (
            await db.execute(
                select(Inspection)
                .where(
                    Inspection.organisation_id == rental.organisation_id,
                    Inspection.rental_id == rental.id,
                    Inspection.deleted_at.is_(None),
                )
                .order_by(Inspection.scheduled_at.desc())
            )
        ).scalars()
    )


async def get_inspection(
    db: AsyncSession, organisation_id: uuid.UUID, inspection_id: uuid.UUID
) -> tuple[Inspection, Rental, Project]:
    row = await _one(
        db,
        _in_live_project(Inspection, organisation_id).where(
            Inspection.id == inspection_id, Inspection.deleted_at.is_(None)
        ),
        "Inspection",
    )
    return row[0], row[1], row[2]


async def inspection_items(db: AsyncSession, inspection: Inspection) -> list[InspectionItem]:
    return list(
        (
            await db.execute(
                select(InspectionItem)
                .where(
                    InspectionItem.organisation_id == inspection.organisation_id,
                    InspectionItem.inspection_id == inspection.id,
                )
                .order_by(InspectionItem.position, InspectionItem.id)
            )
        ).scalars()
    )


async def item_counts(
    db: AsyncSession, organisation_id: uuid.UUID, inspection_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    if not inspection_ids:
        return {}
    rows = await db.execute(
        select(
            InspectionItem.inspection_id,
            func.count(),
            func.count(InspectionItem.condition),
        )
        .where(
            InspectionItem.organisation_id == organisation_id,
            InspectionItem.inspection_id.in_(inspection_ids),
        )
        .group_by(InspectionItem.inspection_id)
    )
    return {r[0]: (int(r[1]), int(r[2])) for r in rows}


async def _check_tenancy(db: AsyncSession, rental: Rental, tenancy_id: uuid.UUID | None) -> None:
    if tenancy_id is None:
        return
    _, owner, _ = await get_tenancy(db, rental.organisation_id, tenancy_id)
    if owner.id != rental.id:
        raise _invalid("tenancy_elsewhere", "That tenancy belongs to another rental.")


async def _sync_inspection_reminders(
    db: AsyncSession, project: Project, inspection: Inspection, actor_id: uuid.UUID
) -> None:
    prefix = f"inspection:{inspection.id}:"
    if inspection.status != InspectionStatus.SCHEDULED or inspection.deleted_at is not None:
        await reminders.cancel(db, inspection.organisation_id, prefix)
        return
    on = inspection.scheduled_at.astimezone(reminders.BRISBANE).date()
    kind = inspection.kind.lower()
    await reminders.sync(
        db,
        inspection.organisation_id,
        prefix,
        reminders.before(
            prefix,
            on,
            INSPECTION_REMIND_DAYS,
            f"{kind.capitalize()} inspection on {_fmt(on)}",
            "If the tenant is living there, give written notice of entry in time. Your rental "
            "checklist has the notice periods.",
        ),
        recipient_user_id=actor_id,
        project_id=project.id,
        link_path=f"/projects/{project.id}/rental/inspections/{inspection.id}",
        actor_id=actor_id,
    )


async def add_inspection(
    db: AsyncSession,
    project: Project,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Inspection:
    rental = await ensure_rental(db, project, actor_id)
    if data["scheduled_at"].tzinfo is None:
        raise _invalid("timezone_required", "Include a time zone with the inspection time.")
    await _check_tenancy(db, rental, data.get("tenancy_id"))
    rooms = data.pop("rooms", None) or default_rooms(rental, data["kind"])
    if len(set(rooms)) != len(rooms):
        raise _invalid("duplicate_rooms", "List each room once.")
    inspection = Inspection(
        organisation_id=rental.organisation_id, rental_id=rental.id, created_by=actor_id, **data
    )
    db.add(inspection)
    await db.flush()
    position = 0
    for room in rooms:
        for item in _items_for(room):
            db.add(
                InspectionItem(
                    organisation_id=rental.organisation_id,
                    inspection_id=inspection.id,
                    position=position,
                    room=room,
                    item=item,
                    photo_document_ids=[],
                )
            )
            position += 1
    await db.flush()
    await _audit(
        db,
        "rental.inspection_scheduled",
        rental.organisation_id,
        "inspection",
        inspection.id,
        actor_id=actor_id,
        meta=meta,
        kind=inspection.kind,
    )
    await _sync_inspection_reminders(db, project, inspection, actor_id)
    return inspection


INSPECTION_TRANSITIONS: dict[InspectionStatus, tuple[InspectionStatus, ...]] = {
    InspectionStatus.SCHEDULED: (
        InspectionStatus.IN_PROGRESS,
        InspectionStatus.COMPLETED,
        InspectionStatus.CANCELLED,
    ),
    InspectionStatus.IN_PROGRESS: (
        InspectionStatus.SCHEDULED,
        InspectionStatus.COMPLETED,
        InspectionStatus.CANCELLED,
    ),
    InspectionStatus.COMPLETED: (InspectionStatus.IN_PROGRESS,),
    InspectionStatus.CANCELLED: (InspectionStatus.SCHEDULED,),
}


async def update_inspection(
    db: AsyncSession,
    inspection: Inspection,
    project: Project,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Inspection:
    for key in ("status", "scheduled_at"):
        if key in changes and changes[key] is None:
            del changes[key]
    if "scheduled_at" in changes and changes["scheduled_at"].tzinfo is None:
        raise _invalid("timezone_required", "Include a time zone with the inspection time.")
    to = changes.get("status")
    if to is not None and to != inspection.status:
        if to not in INSPECTION_TRANSITIONS[InspectionStatus(inspection.status)]:
            raise _conflict(
                "invalid_transition",
                f"An inspection that is {inspection.status.lower().replace('_', ' ')} can't "
                f"become {to.lower().replace('_', ' ')}.",
            )
        changes["completed_at"] = utcnow() if to == InspectionStatus.COMPLETED else None
    elif inspection.status == InspectionStatus.COMPLETED and changes:
        raise _conflict(
            "inspection_completed", "This inspection is completed. Reopen it to change it."
        )
    changed = _apply(inspection, changes)
    if changed:
        await db.flush()
        await _audit(
            db,
            "rental.inspection_updated",
            inspection.organisation_id,
            "inspection",
            inspection.id,
            actor_id=actor_id,
            meta=meta,
            fields=sorted(changed),
            status=inspection.status if "status" in changed else None,
        )
    await _sync_inspection_reminders(db, project, inspection, actor_id)
    return inspection


def _require_open(inspection: Inspection) -> None:
    if inspection.status in (InspectionStatus.COMPLETED, InspectionStatus.CANCELLED):
        raise _conflict(
            "inspection_closed", "This inspection is closed. Reopen it to change its items."
        )


async def get_item(
    db: AsyncSession, organisation_id: uuid.UUID, item_id: uuid.UUID
) -> tuple[InspectionItem, Inspection, Project]:
    row = await _one(
        db,
        select(InspectionItem, Inspection, Project)
        .join(
            Inspection,
            (Inspection.organisation_id == InspectionItem.organisation_id)
            & (Inspection.id == InspectionItem.inspection_id),
        )
        .join(
            Rental,
            (Rental.organisation_id == Inspection.organisation_id)
            & (Rental.id == Inspection.rental_id),
        )
        .join(
            Project,
            (Project.organisation_id == Rental.organisation_id) & (Project.id == Rental.project_id),
        )
        .where(
            InspectionItem.id == item_id,
            InspectionItem.organisation_id == organisation_id,
            Inspection.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        ),
        "Inspection item",
    )
    return row[0], row[1], row[2]


async def add_item(
    db: AsyncSession, inspection: Inspection, room: str, item: str
) -> InspectionItem:
    _require_open(inspection)
    items = await inspection_items(db, inspection)
    if any(i.room == room and i.item == item for i in items):
        raise _conflict("item_exists", "That item is already on the list for this room.")
    in_room = [i.position for i in items if i.room == room]
    position = (max(in_room) if in_room else max((i.position for i in items), default=-1)) + 1
    for i in items:
        if i.position >= position:
            i.position += 1
    record = InspectionItem(
        organisation_id=inspection.organisation_id,
        inspection_id=inspection.id,
        position=position,
        room=room,
        item=item,
        photo_document_ids=[],
    )
    db.add(record)
    await db.flush()
    return record


async def update_item(
    db: AsyncSession,
    item: InspectionItem,
    inspection: Inspection,
    project: Project,
    changes: dict[str, Any],
) -> InspectionItem:
    _require_open(inspection)
    photos = changes.get("photo_document_ids")
    if photos is not None:
        if len(set(photos)) != len(photos):
            raise _invalid("duplicate_photos", "Add each photo once.")
        for document_id in photos:
            upload = await documents.get_document(db, item.organisation_id, document_id)
            if upload.project_id != project.id:
                raise _invalid("document_not_in_project", "Upload the photo to this project.")
            documents.require_clean(upload)
    else:
        changes.pop("photo_document_ids", None)
    _apply(item, changes)
    await db.flush()
    if inspection.status == InspectionStatus.SCHEDULED:
        inspection.status = InspectionStatus.IN_PROGRESS
        await db.flush()
    return item


async def remove_item(db: AsyncSession, item: InspectionItem, inspection: Inspection) -> None:
    _require_open(inspection)
    await db.delete(item)
    await db.flush()


# --- Maintenance -----------------------------------------------------------------------


async def list_maintenance(db: AsyncSession, rental: Rental) -> list[MaintenanceItem]:
    priority_rank = {"EMERGENCY": 0, "URGENT": 1, "ROUTINE": 2}
    items = list(
        (
            await db.execute(
                select(MaintenanceItem)
                .where(
                    MaintenanceItem.organisation_id == rental.organisation_id,
                    MaintenanceItem.rental_id == rental.id,
                    MaintenanceItem.deleted_at.is_(None),
                )
                .order_by(MaintenanceItem.reported_on.desc(), MaintenanceItem.created_at.desc())
            )
        ).scalars()
    )
    # Open items first, the most pressing at the top; then closed ones, newest first.
    return sorted(
        items,
        key=lambda m: (
            m.status not in MAINTENANCE_OPEN,
            priority_rank.get(m.priority, 3) if m.status in MAINTENANCE_OPEN else 0,
        ),
    )


async def get_maintenance(
    db: AsyncSession, organisation_id: uuid.UUID, item_id: uuid.UUID
) -> tuple[MaintenanceItem, Rental, Project]:
    row = await _one(
        db,
        _in_live_project(MaintenanceItem, organisation_id).where(
            MaintenanceItem.id == item_id, MaintenanceItem.deleted_at.is_(None)
        ),
        "Maintenance item",
    )
    return row[0], row[1], row[2]


async def add_maintenance(
    db: AsyncSession,
    project: Project,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> MaintenanceItem:
    rental = await ensure_rental(db, project, actor_id)
    await _check_tenancy(db, rental, data.get("tenancy_id"))
    data["reported_on"] = data.get("reported_on") or today()
    item = MaintenanceItem(
        organisation_id=rental.organisation_id, rental_id=rental.id, created_by=actor_id, **data
    )
    db.add(item)
    await db.flush()
    await _audit(
        db,
        "rental.maintenance_reported",
        rental.organisation_id,
        "maintenance_item",
        item.id,
        actor_id=actor_id,
        meta=meta,
        priority=item.priority,
    )
    return item


async def update_maintenance(
    db: AsyncSession,
    item: MaintenanceItem,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> MaintenanceItem:
    for key in ("title", "priority", "status"):
        if key in changes and changes[key] is None:
            del changes[key]
    to = changes.get("status", item.status)
    if to == MaintenanceStatus.DONE:
        changes["resolved_on"] = changes.get("resolved_on") or item.resolved_on or today()
        if changes["resolved_on"] < item.reported_on:
            raise _invalid("dates_out_of_order", "It can't be fixed before it was reported.")
    else:
        changes["resolved_on"] = None
    changed = _apply(item, changes)
    if changed:
        await db.flush()
        await _audit(
            db,
            "rental.maintenance_updated",
            item.organisation_id,
            "maintenance_item",
            item.id,
            actor_id=actor_id,
            meta=meta,
            fields=sorted(changed),
            status=item.status if "status" in changed else None,
        )
    return item
