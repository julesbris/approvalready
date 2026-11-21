"""RemoteSafe: ``/v1/organisations/{organisation_id}/remotesafe/...`` (journeys, route legs,
check-in plans, risk assessment, controls, approvals, dashboard, exports and settings), and
``/v1/admin/remotesafe/organisations/{id}/tier`` for staff.

Every route needs membership of the organisation (``org.read``) and then RemoteSafe's own
roles, checked in ``service``. A journey the caller may not see answers 404.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    DbDep,
    MetaDep,
    OrgContext,
    require_org_permission,
    require_platform_permission,
)
from app.core.errors import ApiError, forbidden, not_found
from app.db.tenant import bind_tenant
from app.modules.audit import service as audit
from app.modules.remotesafe import service
from app.modules.remotesafe.entitlements import FEATURES, LIMITATIONS, TIERS, available
from app.modules.remotesafe.models import (
    RsJourney,
    RsJourneyEvent,
    RsJourneyRevision,
    RsSettings,
    RsVehicle,
)
from app.modules.remotesafe.policy import build_policy
from app.modules.remotesafe.report import plan_html, plan_pdf
from app.modules.remotesafe.schemas import (
    CheckinPlanOut,
    CheckinPlansIn,
    ControlCheckIn,
    ControlCheckOut,
    ControlExceptionIn,
    HazardFindingOut,
    JourneyApproveIn,
    JourneyAssessmentOut,
    JourneyEventOut,
    JourneyIn,
    JourneyOut,
    JourneyPatch,
    JourneyRevisionOut,
    JourneySummaryOut,
    JourneyTransitionIn,
    LocalTimeOut,
    RemoteSafeDashboardOut,
    RemoteSafeEnableIn,
    RemoteSafeMeOut,
    RiskEvidenceOut,
    RiskPolicyIn,
    RiskPolicyOut,
    RouteLegOut,
    RouteLegsIn,
    RsEmergencyContact,
    RsFeatureOut,
    RsMemberOut,
    RsPersonOut,
    RsRolesIn,
    RsVehicleIn,
    RsVehicleOut,
    StopConditionOut,
)
from app.modules.remotesafe.timezones import AUSTRALIAN_ZONES, DEFAULT_ZONE, label, local
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}/remotesafe", tags=["remotesafe"])
admin_router = APIRouter(prefix="/v1/admin/remotesafe", tags=["remotesafe"])

Member = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_READ))]


async def rs(db: AsyncSession, ctx: OrgContext) -> service.RsContext:
    return await service.context(db, ctx)


def lt(value: datetime, zone: str) -> LocalTimeOut:
    return LocalTimeOut(utc=value, local=label(value, zone), timezone=zone)


def person(user_id: uuid.UUID | None, names: dict[uuid.UUID, str]) -> RsPersonOut | None:
    if user_id is None:
        return None
    return RsPersonOut(user_id=user_id, display_name=names.get(user_id, "Former member"))


def summary(j: RsJourney, names: dict[uuid.UUID, str]) -> JourneySummaryOut:
    worker = person(j.worker_user_id, names)
    assert worker is not None
    return JourneySummaryOut(
        id=j.id,
        reference=j.reference,
        title=j.title,
        status=j.status,
        revision=j.revision,
        risk_outcome=j.risk_outcome,
        worker=worker,
        supervisor=person(j.supervisor_user_id, names),
        origin=j.origin,
        destination=j.destination,
        departs=lt(j.departs_at, j.timezone),
        arrives=lt(j.arrives_at, j.timezone),
        archived=j.archived_at is not None,
        updated_at=j.updated_at,
    )


async def summaries(db: AsyncSession, rows: list[RsJourney]) -> list[JourneySummaryOut]:
    names = await service.names(
        db, {*(j.worker_user_id for j in rows), *(j.supervisor_user_id for j in rows)}
    )
    return [summary(j, names) for j in rows]


def _f(v: Any) -> float | None:
    return float(v) if v is not None else None


async def journey_out(db: AsyncSession, ctx: service.RsContext, j: RsJourney) -> JourneyOut:
    names = await service.names(
        db, {j.worker_user_id, j.supervisor_user_id, j.monitor_user_id, j.approved_by}
    )
    legs = await service.legs_of(db, j)
    checkins = await service.checkins_of(db, j)
    end_zone = legs[-1].timezone if legs else j.timezone
    multi_day = (
        local(j.departs_at, j.timezone).date()
        != local(j.returns_at or j.arrives_at, end_zone).date()
    )
    base = summary(j, names).model_dump()
    return JourneyOut(
        **base,
        purpose=j.purpose,
        activities=j.activities,
        monitor=person(j.monitor_user_id, names),
        team=j.team,
        worker_phone=j.worker_phone,
        remoteness=j.remoteness,
        return_journey=j.return_journey,
        timezone=j.timezone,
        returns=lt(j.returns_at, j.timezone) if j.returns_at else None,
        multi_day=multi_day,
        vehicle_id=j.vehicle_id,
        vehicle_description=j.vehicle_description,
        vehicle_registration=j.vehicle_registration,
        occupants=j.occupants,
        comms_mobile=j.comms_mobile,
        comms_uhf=j.comms_uhf,
        comms_sat_phone=j.comms_sat_phone,
        comms_sat_messenger=j.comms_sat_messenger,
        comms_notes=j.comms_notes,
        emergency_contacts=[RsEmergencyContact(**c) for c in j.emergency_contacts or []],
        checkin_interval_minutes=j.checkin_interval_minutes,
        alternative_route=j.alternative_route,
        contingency_plan=j.contingency_plan,
        weather_checked_at=j.weather_checked_at,
        weather_source=j.weather_source,
        weather_warnings=j.weather_warnings,
        approved_revision=j.approved_revision,
        approved_outcome=j.approved_outcome,
        approved_by=person(j.approved_by, names),
        approved_at=j.approved_at,
        critical_alternative_process=j.critical_alternative_process,
        submitted_at=j.submitted_at,
        started_at=j.started_at,
        completed_at=j.completed_at,
        cancelled_at=j.cancelled_at,
        legs=[
            RouteLegOut(
                id=leg.id,
                position=leg.position,
                origin=leg.origin,
                destination=leg.destination,
                origin_lat=_f(leg.origin_lat),
                origin_lng=_f(leg.origin_lng),
                destination_lat=_f(leg.destination_lat),
                destination_lng=_f(leg.destination_lng),
                timezone=leg.timezone,
                departs=lt(leg.departs_at, leg.timezone),
                arrives=lt(leg.arrives_at, leg.timezone),
                distance_km=_f(leg.distance_km),
                road_surface=leg.road_surface,
                mobile_coverage=leg.mobile_coverage,
                crossings=leg.crossings,
                closure_status=leg.closure_status,
                closure_source=leg.closure_source,
                closure_observed_at=leg.closure_observed_at,
                notes=leg.notes,
            )
            for leg in legs
        ],
        checkins=[
            CheckinPlanOut(
                position=c.position,
                due=lt(c.due_at, j.timezone),
                location=c.location,
                method=c.method,
            )
            for c in checkins
        ],
        allowed_actions=service.allowed_actions(ctx, j),
        can_edit=service.can_edit(ctx, j),
        blockers=await service.blockers(db, ctx, j),
    )


async def assessment_out(
    db: AsyncSession, ctx: service.RsContext, j: RsJourney
) -> JourneyAssessmentOut:
    a, findings = await service.latest_assessment(db, j)
    controls = {c.control_key: c for c in await service.controls_of(db, j)}
    policy = ctx.policy

    def labels(keys: list[str]) -> list[str]:
        return [policy.controls[k].label if k in policy.controls else k for k in keys]

    def outstanding(keys: list[str]) -> list[str]:
        out = []
        for k in keys:
            c = controls.get(k)
            if c is None or c.status not in ("DONE", "EXCEPTION"):
                out.append(c.label if c else k)
        return out

    return JourneyAssessmentOut(
        id=a.id,
        revision=a.revision,
        outcome=a.outcome,
        pathway=service.pathway(a.outcome),
        library_version=a.library_version,
        policy_version=a.policy_version,
        facts=a.facts,
        stop_conditions=[StopConditionOut(**s) for s in a.stop_conditions],
        findings=[
            HazardFindingOut(
                hazard_key=f.hazard_key,
                title=f.title,
                description=f.description,
                evidence=[RiskEvidenceOut(**e) for e in f.evidence],
                likelihood=f.likelihood,
                consequence=f.consequence,
                initial_score=f.initial_score,
                initial_rating=f.initial_rating,
                controls=f.controls,
                control_labels=labels(f.controls),
                residual_likelihood=f.residual_likelihood,
                residual_score=f.residual_score,
                residual_rating=f.residual_rating,
                responsible=f.responsible,
                outstanding=outstanding(f.controls),
            )
            for f in findings
        ],
        created_at=a.created_at,
        disclaimer=service.DISCLAIMER,
        data_sources=service.DATA_SOURCES,
    )


async def controls_out(db: AsyncSession, j: RsJourney) -> list[ControlCheckOut]:
    rows = await service.controls_of(db, j)
    names = await service.names(db, {c.completed_by for c in rows} | {c.exception_by for c in rows})
    return [
        ControlCheckOut(
            key=c.control_key,
            group=c.control_group,
            label=c.label,
            mandatory=c.mandatory,
            required_by=c.required_by,
            status=c.status,
            note=c.note,
            completed_by_name=names.get(c.completed_by) if c.completed_by else None,
            completed_at=c.completed_at,
            exception_reason=c.exception_reason,
            exception_by_name=names.get(c.exception_by) if c.exception_by else None,
        )
        for c in rows
    ]


async def events_out(db: AsyncSession, j: RsJourney) -> list[JourneyEventOut]:
    rows = list(
        (
            await db.execute(
                select(RsJourneyEvent)
                .where(
                    RsJourneyEvent.organisation_id == j.organisation_id,
                    RsJourneyEvent.journey_id == j.id,
                )
                .order_by(RsJourneyEvent.occurred_at, RsJourneyEvent.id)
            )
        ).scalars()
    )
    names = await service.names(db, {e.actor_user_id for e in rows})
    return [
        JourneyEventOut(
            kind=e.kind,
            from_status=e.from_status,
            to_status=e.to_status,
            revision=e.revision,
            actor_name=names.get(e.actor_user_id) if e.actor_user_id else None,
            note=e.note,
            details=e.details,
            occurred_at=e.occurred_at,
        )
        for e in rows
    ]


# --- About me, switching on, members ---------------------------------------------------


@router.get("", response_model=RemoteSafeMeOut)
async def me(ctx: Member, db: DbDep) -> RemoteSafeMeOut:
    r = await rs(db, ctx)
    tier = r.settings.tier if r.settings else None
    return RemoteSafeMeOut(
        enabled=r.settings is not None,
        tier=tier,
        roles=sorted(r.roles),
        org_admin=r.org_admin,
        can_plan=r.can_plan,
        can_approve=r.can_approve,
        can_administer=r.org_admin or r.whs_admin,
        features=[
            RsFeatureOut(
                key=f.key,
                label=f.label,
                tier=f.tier,
                available=bool(tier) and available(tier or "STARTER", f),
                built=f.built,
            )
            for f in FEATURES
        ],
        limitations=list(LIMITATIONS),
        timezones=AUSTRALIAN_ZONES,
        default_timezone=r.settings.default_timezone if r.settings else DEFAULT_ZONE,
    )


@router.post("/enable", response_model=RemoteSafeMeOut)
async def enable(
    body: RemoteSafeEnableIn, ctx: Member, db: DbDep, meta: MetaDep
) -> RemoteSafeMeOut:
    r = await rs(db, ctx)
    await service.enable(db, r, body.default_timezone, meta)
    await db.commit()
    return await me(ctx, db)


@router.get("/members", response_model=list[RsMemberOut])
async def members(ctx: Member, db: DbDep) -> list[RsMemberOut]:
    r = await rs(db, ctx)
    r.enabled()
    roles = await service.roles_by_user(db, r.organisation_id)
    out = []
    for m in await tenancy.list_members(db, r.organisation_id):
        user_roles = sorted(roles.get(m.user.id, set()))
        if not (r.org_admin or r.can_approve or user_roles):
            continue
        out.append(
            RsMemberOut(
                user_id=m.user.id,
                display_name=m.user.display_name,
                # Email only for those who manage people.
                email=m.user.email if r.org_admin or r.whs_admin else "",
                roles=user_roles,
                org_admin="ORG_ADMIN" in m.role_keys,
            )
        )
    return out


@router.put("/members/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
async def set_roles(
    user_id: uuid.UUID, body: RsRolesIn, ctx: Member, db: DbDep, meta: MetaDep
) -> Response:
    r = await rs(db, ctx)
    await service.set_roles(db, r, user_id, list(body.roles), meta)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Vehicles --------------------------------------------------------------------------


def vehicle_out(v: RsVehicle) -> RsVehicleOut:
    return RsVehicleOut(
        id=v.id,
        name=v.name,
        registration=v.registration,
        vehicle_type=v.vehicle_type,
        fuel_range_km=v.fuel_range_km,
        notes=v.notes,
        active=v.active,
    )


@router.get("/vehicles", response_model=list[RsVehicleOut])
async def list_vehicles(ctx: Member, db: DbDep) -> list[RsVehicleOut]:
    r = await rs(db, ctx)
    return [vehicle_out(v) for v in await service.vehicles(db, r)]


@router.post("/vehicles", response_model=RsVehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(body: RsVehicleIn, ctx: Member, db: DbDep) -> RsVehicleOut:
    r = await rs(db, ctx)
    service.require_fleet_admin(r)
    v = RsVehicle(organisation_id=r.organisation_id, created_by=r.user_id, **body.model_dump())
    db.add(v)
    await db.commit()
    return vehicle_out(v)


@router.put("/vehicles/{vehicle_id}", response_model=RsVehicleOut)
async def update_vehicle(
    vehicle_id: uuid.UUID, body: RsVehicleIn, ctx: Member, db: DbDep
) -> RsVehicleOut:
    r = await rs(db, ctx)
    service.require_fleet_admin(r)
    v = await service.vehicle(db, r, vehicle_id)
    for k, value in body.model_dump().items():
        setattr(v, k, value)
    await db.commit()
    return vehicle_out(v)


# --- Journeys --------------------------------------------------------------------------


@router.get("/journeys", response_model=list[JourneySummaryOut])
async def list_journeys(
    ctx: Member,
    db: DbDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    awaiting_me: bool = False,
    include_archived: bool = False,
) -> list[JourneySummaryOut]:
    r = await rs(db, ctx)
    rows = await service.list_journeys(
        db, r, status=status_filter, awaiting_me=awaiting_me, include_archived=include_archived
    )
    return await summaries(db, rows)


@router.post("/journeys", response_model=JourneyOut, status_code=status.HTTP_201_CREATED)
async def create_journey(body: JourneyIn, ctx: Member, db: DbDep) -> JourneyOut:
    r = await rs(db, ctx)
    j = await service.create_journey(db, r, body)
    await db.commit()
    return await journey_out(db, r, j)


@router.get("/journeys/{journey_id}", response_model=JourneyOut)
async def get_journey(journey_id: uuid.UUID, ctx: Member, db: DbDep) -> JourneyOut:
    r = await rs(db, ctx)
    return await journey_out(db, r, await service.journey(db, r, journey_id))


@router.patch("/journeys/{journey_id}", response_model=JourneyOut)
async def update_journey(
    journey_id: uuid.UUID, body: JourneyPatch, ctx: Member, db: DbDep
) -> JourneyOut:
    r = await rs(db, ctx)
    j = await service.update_journey(db, r, await service.journey(db, r, journey_id), body)
    await db.commit()
    return await journey_out(db, r, j)


@router.put("/journeys/{journey_id}/legs", response_model=JourneyOut)
async def put_legs(journey_id: uuid.UUID, body: RouteLegsIn, ctx: Member, db: DbDep) -> JourneyOut:
    r = await rs(db, ctx)
    j = await service.journey(db, r, journey_id)
    await service.replace_legs(db, r, j, body.legs)
    await db.commit()
    return await journey_out(db, r, j)


@router.put("/journeys/{journey_id}/checkins", response_model=JourneyOut)
async def put_checkins(
    journey_id: uuid.UUID, body: CheckinPlansIn, ctx: Member, db: DbDep
) -> JourneyOut:
    r = await rs(db, ctx)
    j = await service.journey(db, r, journey_id)
    await service.replace_checkins(db, r, j, body.checkins)
    await db.commit()
    return await journey_out(db, r, j)


@router.get("/journeys/{journey_id}/assessment", response_model=JourneyAssessmentOut)
async def get_assessment(journey_id: uuid.UUID, ctx: Member, db: DbDep) -> JourneyAssessmentOut:
    r = await rs(db, ctx)
    return await assessment_out(db, r, await service.journey(db, r, journey_id))


@router.get("/journeys/{journey_id}/controls", response_model=list[ControlCheckOut])
async def get_controls(journey_id: uuid.UUID, ctx: Member, db: DbDep) -> list[ControlCheckOut]:
    r = await rs(db, ctx)
    return await controls_out(db, await service.journey(db, r, journey_id))


@router.put("/journeys/{journey_id}/controls/{key}", response_model=list[ControlCheckOut])
async def put_control(
    journey_id: uuid.UUID, key: str, body: ControlCheckIn, ctx: Member, db: DbDep
) -> list[ControlCheckOut]:
    r = await rs(db, ctx)
    j = await service.journey(db, r, journey_id)
    await service.set_control(db, r, j, key, body.status, body.note)
    await db.commit()
    return await controls_out(db, j)


@router.post(
    "/journeys/{journey_id}/controls/{key}/exception", response_model=list[ControlCheckOut]
)
async def control_exception(
    journey_id: uuid.UUID, key: str, body: ControlExceptionIn, ctx: Member, db: DbDep, meta: MetaDep
) -> list[ControlCheckOut]:
    r = await rs(db, ctx)
    j = await service.journey(db, r, journey_id)
    await service.control_exception(db, r, j, key, body.reason, meta)
    await db.commit()
    return await controls_out(db, j)


Action = Literal[
    "submit", "request_changes", "commence", "complete", "escalate", "cancel", "archive"
]


@router.post("/journeys/{journey_id}/approve", response_model=JourneyOut)
async def approve(
    journey_id: uuid.UUID, body: JourneyApproveIn, ctx: Member, db: DbDep, meta: MetaDep
) -> JourneyOut:
    r = await rs(db, ctx)
    j = await service.journey(db, r, journey_id)
    await service.transition(
        db, r, j, "approve", body.note, meta, body.critical_alternative_process
    )
    await db.commit()
    return await journey_out(db, r, j)


@router.post("/journeys/{journey_id}/{action}", response_model=JourneyOut)
async def act(
    journey_id: uuid.UUID,
    action: Action,
    body: JourneyTransitionIn,
    ctx: Member,
    db: DbDep,
    meta: MetaDep,
) -> JourneyOut:
    r = await rs(db, ctx)
    j = await service.journey(db, r, journey_id)
    await service.transition(db, r, j, action, body.note, meta)
    await db.commit()
    return await journey_out(db, r, j)


@router.get("/journeys/{journey_id}/events", response_model=list[JourneyEventOut])
async def get_events(journey_id: uuid.UUID, ctx: Member, db: DbDep) -> list[JourneyEventOut]:
    r = await rs(db, ctx)
    return await events_out(db, await service.journey(db, r, journey_id))


@router.get("/journeys/{journey_id}/revisions", response_model=list[JourneyRevisionOut])
async def get_revisions(journey_id: uuid.UUID, ctx: Member, db: DbDep) -> list[JourneyRevisionOut]:
    r = await rs(db, ctx)
    j = await service.journey(db, r, journey_id)
    rows = list(
        (
            await db.execute(
                select(RsJourneyRevision)
                .where(
                    RsJourneyRevision.organisation_id == j.organisation_id,
                    RsJourneyRevision.journey_id == j.id,
                )
                .order_by(RsJourneyRevision.revision)
            )
        ).scalars()
    )
    names = await service.names(db, {x.created_by for x in rows})
    return [
        JourneyRevisionOut(
            revision=x.revision,
            changed_fields=x.changed_fields,
            created_at=x.created_at,
            created_by_name=names.get(x.created_by) if x.created_by else None,
        )
        for x in rows
    ]


def _filename(j: RsJourney, ext: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "-", j.title).strip("-").lower()[:60]
    return f"journey-plan-{j.reference.lower()}-r{j.revision}-{name}.{ext}"


@router.get("/journeys/{journey_id}/plan.pdf", response_class=Response)
async def plan(journey_id: uuid.UUID, ctx: Member, db: DbDep) -> Response:
    r = await rs(db, ctx)
    j = await service.journey(db, r, journey_id)
    out = await journey_out(db, r, j)
    html = plan_html(
        out,
        await assessment_out(db, r, j),
        await controls_out(db, j),
        await events_out(db, j),
        created=label(datetime.now(UTC), j.timezone),
        approved=label(j.approved_at, j.timezone) if j.approved_at else "",
    )
    pdf = await asyncio.to_thread(plan_pdf, html)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"content-disposition": f'attachment; filename="{_filename(j, "pdf")}"'},
    )


@router.get("/journeys/{journey_id}/export.json")
async def export_journey(journey_id: uuid.UUID, ctx: Member, db: DbDep) -> Response:
    r = await rs(db, ctx)
    j = await service.journey(db, r, journey_id)
    body = {
        "exported_at": datetime.now(UTC).isoformat(),
        "journey": (await journey_out(db, r, j)).model_dump(mode="json"),
        "assessment": (await assessment_out(db, r, j)).model_dump(mode="json"),
        "controls": [c.model_dump(mode="json") for c in await controls_out(db, j)],
        "events": [e.model_dump(mode="json") for e in await events_out(db, j)],
    }
    return Response(
        json.dumps(body, indent=2),
        media_type="application/json",
        headers={"content-disposition": f'attachment; filename="{_filename(j, "json")}"'},
    )


CSV_COLUMNS = (
    "reference",
    "title",
    "status",
    "revision",
    "risk_outcome",
    "approved_outcome",
    "worker",
    "supervisor",
    "origin",
    "destination",
    "departs_local",
    "arrives_local",
    "timezone",
    "occupants",
    "remoteness",
    "archived",
)


@router.get("/journeys.csv")
async def export_csv(ctx: Member, db: DbDep) -> Response:
    r = await rs(db, ctx)
    if not r.sees_all:
        raise forbidden("Exports are for WHS and organisation administrators.")
    rows = await service.list_journeys(db, r, include_archived=True, limit=5000)
    names = await service.names(
        db, {*(j.worker_user_id for j in rows), *(j.supervisor_user_id for j in rows)}
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for j in rows:
        values = [
            j.reference,
            j.title,
            j.status,
            j.revision,
            j.risk_outcome or "",
            j.approved_outcome or "",
            names.get(j.worker_user_id, ""),
            names.get(j.supervisor_user_id, "") if j.supervisor_user_id else "",
            j.origin,
            j.destination,
            label(j.departs_at, j.timezone),
            label(j.arrives_at, j.timezone),
            j.timezone,
            j.occupants,
            j.remoteness,
            "yes" if j.archived_at else "no",
        ]
        # Spreadsheet formula injection: text starting with = + - @ is quoted.
        writer.writerow(
            [f"'{v}" if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in values]
        )
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"content-disposition": 'attachment; filename="remotesafe-journeys.csv"'},
    )


@router.get("/dashboard", response_model=RemoteSafeDashboardOut)
async def dashboard(ctx: Member, db: DbDep) -> RemoteSafeDashboardOut:
    r = await rs(db, ctx)
    data = await service.dashboard(db, r)
    data["upcoming"] = await summaries(db, data["upcoming"])
    return RemoteSafeDashboardOut(**data)


# --- Policy ----------------------------------------------------------------------------


def policy_out(settings: RsSettings) -> RiskPolicyOut:
    p = build_policy(settings.policy)
    return RiskPolicyOut(
        library_version=p.library_version,
        policy_version=settings.policy_version,
        overrides=settings.policy,
        effective={
            "rating_bands": p.bands,
            "assumptions": {
                k: (v.strftime("%H:%M") if hasattr(v, "strftime") else v)
                for k, v in p.assumptions.__dict__.items()
            },
            "hazards": [h.__dict__ for h in p.hazards.values()],
            "controls": [c.__dict__ for c in p.controls.values()],
            "high_risk_approver_roles": list(p.high_risk_approver_roles),
        },
    )


@router.get("/policy", response_model=RiskPolicyOut)
async def get_policy(ctx: Member, db: DbDep) -> RiskPolicyOut:
    r = await rs(db, ctx)
    return policy_out(r.enabled())


@router.put("/policy", response_model=RiskPolicyOut)
async def put_policy(body: RiskPolicyIn, ctx: Member, db: DbDep, meta: MetaDep) -> RiskPolicyOut:
    r = await rs(db, ctx)
    settings = await service.update_policy(db, r, body.overrides, meta)
    await db.commit()
    return policy_out(settings)


# --- Staff: tier -----------------------------------------------------------------------


class RsTierIn(BaseModel):
    tier: Literal["STARTER", "PROFESSIONAL", "ENTERPRISE"]


Staff = Annotated[OrgContext, Depends(require_platform_permission(Perm.BILLING_CONFIGURE))]


@admin_router.put("/organisations/{organisation_id}/tier", status_code=204)
async def set_tier(
    organisation_id: uuid.UUID, body: RsTierIn, staff: Staff, db: DbDep, meta: MetaDep
) -> Response:
    """No payment in Stage 1: staff set the plan by hand."""
    assert body.tier in TIERS
    org = await db.get(Organisation, organisation_id)
    if org is None:
        raise not_found("Organisation")
    await bind_tenant(db, organisation_id)
    settings = (
        await db.execute(select(RsSettings).where(RsSettings.organisation_id == organisation_id))
    ).scalar_one_or_none()
    if settings is None:
        raise ApiError(404, "remotesafe_off", "RemoteSafe isn't turned on for that organisation.")
    before = settings.tier
    settings.tier = body.tier
    await audit.record(
        db,
        "remotesafe.tier_changed",
        actor_user_id=staff.auth.user.id,
        organisation_id=organisation_id,
        target_type="rs_settings",
        target_id=settings.id,
        meta=meta,
        details={"before": before, "after": body.tier},
    )
    await db.commit()
    return Response(status_code=204)
