"""RemoteSafe journeys: access rules, the approval workflow, reassessment and controls.

Workflow: DRAFT -> SUBMITTED -> (CHANGES_REQUESTED -> SUBMITTED)* -> APPROVED -> ACTIVE ->
COMPLETED, then archived. CANCELLED from any state before ACTIVE. OVERDUE and ESCALATED are
reserved for check-in monitoring (Milestone 4); in Stage 1 only a person can escalate.

A material change (route, vehicle, places, communications, timing, people) to a submitted
or approved plan starts a new revision, reruns the assessment and, for an approved plan,
clears the approval and every completed control: it must be approved again.
"""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgContext
from app.core.errors import ApiError, forbidden, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity.models import AppUser
from app.modules.remotesafe import engine
from app.modules.remotesafe.models import (
    ControlStatus,
    JourneyStatus,
    RsCheckinPlan,
    RsControlCheck,
    RsHazardFinding,
    RsJourney,
    RsJourneyEvent,
    RsJourneyRevision,
    RsMemberRole,
    RsRiskAssessment,
    RsRole,
    RsRouteLeg,
    RsSettings,
    RsVehicle,
)
from app.modules.remotesafe.policy import RATINGS, Policy, build_policy
from app.modules.remotesafe.schemas import (
    CheckinIn,
    JourneyIn,
    JourneyPatch,
    LegIn,
)
from app.modules.remotesafe.timezones import check_zone, to_utc
from app.modules.tenancy.models import MemberStatus, OrganisationKind, OrganisationMember
from app.modules.tenancy.rbac import Perm

S = JourneyStatus
EDITABLE = (S.DRAFT, S.SUBMITTED, S.CHANGES_REQUESTED, S.APPROVED)
UNDERWAY = (S.ACTIVE, S.OVERDUE, S.ESCALATED)
FINISHED = (S.COMPLETED, S.CANCELLED)

# Fields whose change after submission sends the plan back through assessment and approval.
MATERIAL_FIELDS = frozenset(
    {
        "supervisor_user_id",
        "monitor_user_id",
        "origin",
        "destination",
        "remoteness",
        "return_journey",
        "timezone",
        "departs_at",
        "arrives_at",
        "returns_at",
        "vehicle_id",
        "vehicle_description",
        "vehicle_registration",
        "occupants",
        "comms_mobile",
        "comms_uhf",
        "comms_sat_phone",
        "comms_sat_messenger",
        "emergency_contacts",
        "checkin_interval_minutes",
        "weather_checked_at",
        "weather_source",
        "weather_warnings",
        "legs",
        "checkins",
    }
)
VEHICLE_FIELDS = frozenset({"vehicle_id", "vehicle_description", "vehicle_registration"})

DISCLAIMER = (
    "This assessment applies your organisation's rules to the plan as entered. Ratings are "
    "planning categories, not probabilities. Conditions on the day can differ: check them "
    "before you leave. RemoteSafe does not replace emergency services or your emergency "
    "response plan."
)
DATA_SOURCES = [
    "Journey plan as entered by the planner (route, surface, coverage, crossings, closures "
    "and weather checks, with the source they named).",
    "Your organisation's vehicle register (fuel range).",
    "Your organisation's RemoteSafe risk policy (ratings, thresholds and assumptions).",
    "Not connected yet: QLDTraffic, Bureau of Meteorology, Geoscience Australia, mobile "
    "coverage maps (Milestone 3).",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RsContext:
    org: OrgContext
    settings: RsSettings | None
    roles: frozenset[str]

    @property
    def user_id(self) -> uuid.UUID:
        return self.org.auth.user.id

    @property
    def organisation_id(self) -> uuid.UUID:
        return self.org.organisation.id

    @property
    def org_admin(self) -> bool:
        return self.org.can(Perm.ORG_MEMBERS_MANAGE)

    @property
    def whs_admin(self) -> bool:
        return RsRole.WHS_ADMIN in self.roles

    @property
    def sees_all(self) -> bool:
        return self.whs_admin or self.org_admin

    @property
    def can_plan(self) -> bool:
        return bool(self.roles & {RsRole.WORKER, RsRole.SUPERVISOR, RsRole.WHS_ADMIN})

    @property
    def can_approve(self) -> bool:
        return bool(self.roles & {RsRole.SUPERVISOR, RsRole.WHS_ADMIN})

    @property
    def policy(self) -> Policy:
        return build_policy(self.settings.policy if self.settings else None)

    def enabled(self) -> RsSettings:
        if self.settings is None:
            raise ApiError(
                404, "remotesafe_off", "RemoteSafe isn't turned on for this organisation."
            )
        return self.settings


async def active_roles(
    db: AsyncSession, organisation_id: uuid.UUID, user_id: uuid.UUID
) -> frozenset[str]:
    """RemoteSafe roles of an active member (a removed member's roles count for nothing)."""
    rows = await db.execute(
        select(RsMemberRole.role)
        .join(
            OrganisationMember,
            (OrganisationMember.user_id == RsMemberRole.user_id)
            & (OrganisationMember.organisation_id == RsMemberRole.organisation_id),
        )
        .where(
            RsMemberRole.organisation_id == organisation_id,
            RsMemberRole.user_id == user_id,
            OrganisationMember.status == MemberStatus.ACTIVE,
        )
    )
    return frozenset(rows.scalars())


async def context(db: AsyncSession, org: OrgContext) -> RsContext:
    settings = (
        await db.execute(
            select(RsSettings).where(RsSettings.organisation_id == org.organisation.id)
        )
    ).scalar_one_or_none()
    roles = await active_roles(db, org.organisation.id, org.auth.user.id)
    return RsContext(org, settings, roles)


async def enable(db: AsyncSession, ctx: RsContext, timezone: str, meta: RequestMeta) -> None:
    if not ctx.org_admin:
        raise forbidden("Only an organisation administrator can turn on RemoteSafe.")
    if ctx.org.organisation.kind != OrganisationKind.BUSINESS:
        raise ApiError(409, "remotesafe_business_only", "RemoteSafe is for business organisations.")
    if ctx.settings is not None:
        return
    settings = RsSettings(
        organisation_id=ctx.organisation_id,
        default_timezone=check_zone(timezone),
        created_by=ctx.user_id,
        policy={},
        policy_version=1,
    )
    db.add(settings)
    # The administrator who turns it on can set it up and approve journeys.
    db.add(
        RsMemberRole(
            organisation_id=ctx.organisation_id,
            user_id=ctx.user_id,
            role=RsRole.WHS_ADMIN,
            created_by=ctx.user_id,
        )
    )
    await audit.record(
        db,
        "remotesafe.enabled",
        actor_user_id=ctx.user_id,
        organisation_id=ctx.organisation_id,
        target_type="organisation",
        target_id=ctx.organisation_id,
        meta=meta,
    )
    await db.flush()
    ctx.settings = settings
    ctx.roles = ctx.roles | {RsRole.WHS_ADMIN}


# --- Members and roles -----------------------------------------------------------------


async def member_user_ids(db: AsyncSession, organisation_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        select(OrganisationMember.user_id).where(
            OrganisationMember.organisation_id == organisation_id,
            OrganisationMember.status == MemberStatus.ACTIVE,
        )
    )
    return set(rows.scalars())


async def roles_by_user(db: AsyncSession, organisation_id: uuid.UUID) -> dict[uuid.UUID, set[str]]:
    out: dict[uuid.UUID, set[str]] = {}
    for user_id, role in await db.execute(
        select(RsMemberRole.user_id, RsMemberRole.role).where(
            RsMemberRole.organisation_id == organisation_id
        )
    ):
        out.setdefault(user_id, set()).add(role)
    return out


async def set_roles(
    db: AsyncSession, ctx: RsContext, user_id: uuid.UUID, roles: list[str], meta: RequestMeta
) -> None:
    ctx.enabled()
    if not ctx.org_admin:
        raise forbidden("Only an organisation administrator can change RemoteSafe roles.")
    if user_id not in await member_user_ids(db, ctx.organisation_id):
        raise not_found("Member")
    wanted = set(roles)
    current = (await roles_by_user(db, ctx.organisation_id)).get(user_id, set())
    if user_id == ctx.user_id and RsRole.WHS_ADMIN in current - wanted:
        others = [
            u
            for u, r in (await roles_by_user(db, ctx.organisation_id)).items()
            if RsRole.WHS_ADMIN in r and u != user_id
        ]
        if not others:
            raise ApiError(409, "last_whs_admin", "Someone else needs to be WHS administrator.")
    for role in current - wanted:
        row = (
            await db.execute(
                select(RsMemberRole).where(
                    RsMemberRole.organisation_id == ctx.organisation_id,
                    RsMemberRole.user_id == user_id,
                    RsMemberRole.role == role,
                )
            )
        ).scalar_one()
        await db.delete(row)
    for role in wanted - current:
        db.add(
            RsMemberRole(
                organisation_id=ctx.organisation_id,
                user_id=user_id,
                role=role,
                created_by=ctx.user_id,
            )
        )
    await audit.record(
        db,
        "remotesafe.roles_changed",
        actor_user_id=ctx.user_id,
        organisation_id=ctx.organisation_id,
        target_type="user",
        target_id=user_id,
        meta=meta,
        details={"before": sorted(current), "after": sorted(wanted)},
    )
    await db.flush()


async def names(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted)))
    return {i: n for i, n in rows}


# --- Vehicles --------------------------------------------------------------------------


def require_fleet_admin(ctx: RsContext) -> None:
    ctx.enabled()
    if not (ctx.org_admin or ctx.whs_admin):
        raise forbidden("Only an administrator can change the vehicle register.")


async def vehicles(db: AsyncSession, ctx: RsContext) -> list[RsVehicle]:
    ctx.enabled()
    rows = await db.execute(
        select(RsVehicle)
        .where(RsVehicle.organisation_id == ctx.organisation_id)
        .order_by(RsVehicle.active.desc(), RsVehicle.name)
    )
    return list(rows.scalars())


async def vehicle(db: AsyncSession, ctx: RsContext, vehicle_id: uuid.UUID) -> RsVehicle:
    v = (
        await db.execute(
            select(RsVehicle).where(
                RsVehicle.organisation_id == ctx.organisation_id, RsVehicle.id == vehicle_id
            )
        )
    ).scalar_one_or_none()
    if v is None:
        raise not_found("Vehicle")
    return v


# --- Journeys: access ------------------------------------------------------------------


def visible_filter(ctx: RsContext) -> Any:
    me = ctx.user_id
    clause = RsJourney.organisation_id == ctx.organisation_id
    if ctx.sees_all:
        return clause
    return clause & (
        (RsJourney.worker_user_id == me)
        | (RsJourney.supervisor_user_id == me)
        | (RsJourney.monitor_user_id == me)
        | (RsJourney.created_by == me)
    )


async def journey(db: AsyncSession, ctx: RsContext, journey_id: uuid.UUID) -> RsJourney:
    ctx.enabled()
    j = (
        await db.execute(select(RsJourney).where(visible_filter(ctx), RsJourney.id == journey_id))
    ).scalar_one_or_none()
    if j is None:
        # Not visible looks the same as not there.
        raise not_found("Journey")
    return j


def can_edit(ctx: RsContext, j: RsJourney) -> bool:
    if j.status not in EDITABLE or j.archived_at is not None:
        return False
    me = ctx.user_id
    return ctx.whs_admin or me in (j.worker_user_id, j.created_by, j.supervisor_user_id)


def require_edit(ctx: RsContext, j: RsJourney) -> None:
    if j.status in UNDERWAY:
        raise ApiError(
            409,
            "journey_underway",
            "This journey has started. Changes during a journey need your supervisor "
            "(mid-journey changes arrive with check-in monitoring).",
        )
    if not can_edit(ctx, j):
        raise forbidden("You can't change this journey.")


def approval_problem(ctx: RsContext, j: RsJourney, outcome: str, policy: Policy) -> str | None:
    """Why this user can't approve this journey now, or None."""
    me = ctx.user_id
    if j.status != S.SUBMITTED:
        return "Only a submitted journey can be approved."
    if me == j.worker_user_id:
        return "You can't approve your own journey."
    supervisor = me == j.supervisor_user_id and RsRole.SUPERVISOR in ctx.roles
    if not (supervisor or ctx.whs_admin):
        return "Only the journey's supervisor or a WHS administrator can approve it."
    if outcome == "CRITICAL" and not ctx.whs_admin:
        return "A critical-risk journey needs a WHS administrator and a documented alternative."
    if outcome == "HIGH":
        allowed = (ctx.whs_admin and "WHS_ADMIN" in policy.high_risk_approver_roles) or (
            supervisor and "SUPERVISOR" in policy.high_risk_approver_roles
        )
        if not allowed:
            return "A high-risk journey needs approval from a WHS administrator."
    return None


def allowed_actions(ctx: RsContext, j: RsJourney) -> list[str]:
    me = ctx.user_id
    involved = me in (j.worker_user_id, j.supervisor_user_id, j.monitor_user_id)
    actions: list[str] = []
    if j.archived_at is not None:
        return actions
    if j.status in (S.DRAFT, S.CHANGES_REQUESTED) and can_edit(ctx, j):
        actions.append("submit")
    if (
        j.status == S.SUBMITTED
        and ctx.can_approve
        and me != j.worker_user_id
        and (ctx.whs_admin or me == j.supervisor_user_id)
    ):
        actions += ["approve", "request_changes"]
    if j.status == S.APPROVED and (me == j.worker_user_id or ctx.whs_admin):
        actions.append("commence")
    if j.status in UNDERWAY and (involved or ctx.whs_admin):
        actions.append("complete")
    if j.status in (S.ACTIVE, S.OVERDUE) and (
        me in (j.supervisor_user_id, j.monitor_user_id) or ctx.whs_admin
    ):
        actions.append("escalate")
    if j.status in EDITABLE and (can_edit(ctx, j) or me == j.supervisor_user_id):
        actions.append("cancel")
    if j.status in FINISHED and (ctx.sees_all or me == j.supervisor_user_id):
        actions.append("archive")
    return actions


# --- Journeys: people and inputs -------------------------------------------------------


async def _check_people(
    db: AsyncSession,
    ctx: RsContext,
    worker: uuid.UUID,
    supervisor: uuid.UUID | None,
    monitor: uuid.UUID | None,
) -> None:
    roles = await roles_by_user(db, ctx.organisation_id)
    members = await member_user_ids(db, ctx.organisation_id)

    def has(user: uuid.UUID, wanted: set[str]) -> bool:
        return user in members and bool(roles.get(user, set()) & wanted)

    if not has(worker, {r.value for r in RsRole}):
        raise ApiError(422, "invalid_worker", "The worker needs a RemoteSafe role here.")
    if supervisor is not None:
        if supervisor == worker:
            raise ApiError(422, "invalid_supervisor", "A worker can't supervise their own trip.")
        if not has(supervisor, {RsRole.SUPERVISOR, RsRole.WHS_ADMIN}):
            raise ApiError(422, "invalid_supervisor", "Choose someone with the supervisor role.")
    if monitor is not None:
        if monitor == worker:
            raise ApiError(422, "invalid_monitor", "A worker can't monitor their own journey.")
        if not has(monitor, {RsRole.MONITOR, RsRole.SUPERVISOR, RsRole.WHS_ADMIN}):
            raise ApiError(422, "invalid_monitor", "Choose someone with the monitor role.")


def _times(
    zone: str, departs: datetime, arrives: datetime, returns: datetime | None
) -> tuple[datetime, datetime, datetime | None]:
    d = to_utc(departs, zone, "Departure")
    a = to_utc(arrives, zone, "Arrival")
    r = to_utc(returns, zone, "Return") if returns else None
    if a <= d:
        raise ApiError(422, "invalid_times", "Arrival must be after departure.")
    if r is not None and r < a:
        raise ApiError(422, "invalid_times", "The return must be after arrival.")
    return d, a, r


def new_reference() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "RS-" + "".join(secrets.choice(alphabet) for _ in range(6))


async def create_journey(db: AsyncSession, ctx: RsContext, body: JourneyIn) -> RsJourney:
    ctx.enabled()
    if not ctx.can_plan:
        raise forbidden("You need a RemoteSafe worker or supervisor role to plan journeys.")
    worker = body.worker_user_id or ctx.user_id
    if worker != ctx.user_id and not (RsRole.SUPERVISOR in ctx.roles or ctx.whs_admin):
        raise forbidden("Only a supervisor can plan a journey for someone else.")
    await _check_people(db, ctx, worker, body.supervisor_user_id, body.monitor_user_id)
    zone = check_zone(body.timezone)
    departs, arrives, returns = _times(zone, body.departs_at, body.arrives_at, body.returns_at)
    if body.vehicle_id is not None:
        await vehicle(db, ctx, body.vehicle_id)
    data = body.model_dump(
        exclude={"worker_user_id", "departs_at", "arrives_at", "returns_at", "weather_checked_at"}
    )
    j = RsJourney(
        organisation_id=ctx.organisation_id,
        reference=new_reference(),
        worker_user_id=worker,
        departs_at=departs,
        arrives_at=arrives,
        returns_at=returns,
        weather_checked_at=(
            to_utc(body.weather_checked_at, zone) if body.weather_checked_at else None
        ),
        created_by=ctx.user_id,
        status=S.DRAFT,
        revision=1,
        **data,
    )
    db.add(j)
    await db.flush()
    await event(db, ctx, j, "CREATED", to_status=S.DRAFT)
    await reassess(db, ctx, j)
    return j


async def update_journey(
    db: AsyncSession, ctx: RsContext, j: RsJourney, body: JourneyPatch
) -> RsJourney:
    require_edit(ctx, j)
    changes = body.model_dump(exclude_unset=True)
    supervisor = changes.get("supervisor_user_id", j.supervisor_user_id)
    monitor = changes.get("monitor_user_id", j.monitor_user_id)
    if "supervisor_user_id" in changes or "monitor_user_id" in changes:
        await _check_people(db, ctx, j.worker_user_id, supervisor, monitor)
    zone = check_zone(changes.get("timezone") or j.timezone)
    if {"departs_at", "arrives_at", "returns_at", "timezone"} & set(changes):
        d, a, r = _times(
            zone,
            changes.get("departs_at") or j.departs_at,
            changes.get("arrives_at") or j.arrives_at,
            changes.get("returns_at", j.returns_at),
        )
        changes |= {"departs_at": d, "arrives_at": a, "returns_at": r}
    if changes.get("weather_checked_at"):
        changes["weather_checked_at"] = to_utc(changes["weather_checked_at"], zone)
    if changes.get("vehicle_id") is not None:
        await vehicle(db, ctx, changes["vehicle_id"])
    for required in ("title", "purpose", "origin", "destination", "timezone", "occupants"):
        if required in changes and changes[required] is None:
            raise ApiError(422, "required", f"{required.replace('_', ' ').capitalize()} is needed.")
    changed = [k for k, v in changes.items() if getattr(j, k) != v]
    for k in changed:
        setattr(j, k, changes[k])
    await db.flush()
    await after_change(db, ctx, j, changed)
    return j


async def replace_legs(
    db: AsyncSession, ctx: RsContext, j: RsJourney, legs: list[LegIn]
) -> list[RsRouteLeg]:
    require_edit(ctx, j)
    rows: list[RsRouteLeg] = []
    previous: datetime | None = None
    for i, leg in enumerate(legs, start=1):
        zone = check_zone(leg.timezone or j.timezone)
        departs = to_utc(leg.departs_at, zone, f"Leg {i} departure")
        arrives = to_utc(leg.arrives_at, zone, f"Leg {i} arrival")
        if arrives <= departs:
            raise ApiError(422, "invalid_leg", f"Leg {i} must arrive after it departs.")
        if previous is not None and departs < previous:
            raise ApiError(422, "invalid_leg", f"Leg {i} departs before leg {i - 1} arrives.")
        if leg.closure_status in ("RESTRICTED", "CONFIRMED_CLOSED") and not leg.closure_source:
            raise ApiError(
                422,
                "closure_source_needed",
                f"Leg {i}: say where the closure or restriction comes from (e.g. QLDTraffic).",
            )
        previous = arrives
        data = leg.model_dump(exclude={"timezone", "departs_at", "arrives_at"})
        if leg.closure_observed_at is not None:
            data["closure_observed_at"] = to_utc(leg.closure_observed_at, zone, "Checked at")
        for k in ("origin_lat", "origin_lng", "destination_lat", "destination_lng", "distance_km"):
            data[k] = Decimal(str(data[k])) if data[k] is not None else None
        rows.append(
            RsRouteLeg(
                organisation_id=ctx.organisation_id,
                journey_id=j.id,
                position=i,
                timezone=zone,
                departs_at=departs,
                arrives_at=arrives,
                **data,
            )
        )
    before = [_leg_key(r) for r in await legs_of(db, j)]
    for old in await legs_of(db, j):
        await db.delete(old)
    await db.flush()
    db.add_all(rows)
    await db.flush()
    if before != [_leg_key(r) for r in rows]:
        await after_change(db, ctx, j, ["legs"])
    return rows


def _leg_key(r: RsRouteLeg) -> tuple[Any, ...]:
    return (
        r.origin,
        r.destination,
        r.timezone,
        r.departs_at,
        r.arrives_at,
        r.distance_km,
        r.road_surface,
        r.mobile_coverage,
        r.crossings,
        r.closure_status,
        r.closure_source,
        r.closure_observed_at,
        r.origin_lat,
        r.origin_lng,
        r.destination_lat,
        r.destination_lng,
    )


async def replace_checkins(
    db: AsyncSession, ctx: RsContext, j: RsJourney, checkins: list[CheckinIn]
) -> list[RsCheckinPlan]:
    require_edit(ctx, j)
    times = [to_utc(c.due_at, j.timezone, "Check-in") for c in checkins]
    end = j.returns_at or j.arrives_at
    for t in times:
        if not j.departs_at < t <= end:
            raise ApiError(
                422, "invalid_checkin", "Check-ins must fall between departure and the end."
            )
    order = sorted(range(len(checkins)), key=lambda i: times[i])
    before = [(c.due_at, c.location, c.method) for c in await checkins_of(db, j)]
    for old in await checkins_of(db, j):
        await db.delete(old)
    await db.flush()
    rows = [
        RsCheckinPlan(
            organisation_id=ctx.organisation_id,
            journey_id=j.id,
            position=pos,
            due_at=times[i],
            location=checkins[i].location,
            method=checkins[i].method,
        )
        for pos, i in enumerate(order, start=1)
    ]
    db.add_all(rows)
    await db.flush()
    if before != [(r.due_at, r.location, r.method) for r in rows]:
        await after_change(db, ctx, j, ["checkins"])
    return rows


async def legs_of(db: AsyncSession, j: RsJourney) -> list[RsRouteLeg]:
    rows = await db.execute(
        select(RsRouteLeg)
        .where(RsRouteLeg.organisation_id == j.organisation_id, RsRouteLeg.journey_id == j.id)
        .order_by(RsRouteLeg.position)
    )
    return list(rows.scalars())


async def checkins_of(db: AsyncSession, j: RsJourney) -> list[RsCheckinPlan]:
    rows = await db.execute(
        select(RsCheckinPlan)
        .where(RsCheckinPlan.organisation_id == j.organisation_id, RsCheckinPlan.journey_id == j.id)
        .order_by(RsCheckinPlan.position)
    )
    return list(rows.scalars())


# --- Change handling, revisions and reassessment ---------------------------------------


async def _has_snapshot(db: AsyncSession, j: RsJourney) -> bool:
    found = await db.execute(
        select(RsJourneyRevision.id).where(
            RsJourneyRevision.journey_id == j.id, RsJourneyRevision.revision == j.revision
        )
    )
    return found.first() is not None


async def after_change(db: AsyncSession, ctx: RsContext, j: RsJourney, changed: list[str]) -> None:
    if not changed:
        return
    material = sorted(set(changed) & MATERIAL_FIELDS)
    if not material:
        await event(db, ctx, j, "EDITED", details={"fields": sorted(changed)})
        return
    if await _has_snapshot(db, j):
        j.revision += 1
    if set(changed) & VEHICLE_FIELDS:
        await reset_controls(db, j, group="VEHICLE")
    previous = j.status
    if j.status == S.SUBMITTED:
        j.status = S.DRAFT
        await event(
            db,
            ctx,
            j,
            "WITHDRAWN_FOR_CHANGES",
            from_status=previous,
            to_status=S.DRAFT,
            details={"fields": material},
        )
    elif j.status == S.APPROVED:
        j.status = S.SUBMITTED
        j.submitted_at = utcnow()
        j.approved_by = None
        j.approved_at = None
        j.approved_revision = None
        j.approved_outcome = None
        j.critical_alternative_process = None
        await reset_controls(db, j)
        await event(
            db,
            ctx,
            j,
            "REASSESSMENT_REQUIRED",
            from_status=previous,
            to_status=S.SUBMITTED,
            note="Changed after approval: the plan must be approved again.",
            details={"fields": material},
        )
        await snapshot(db, ctx, j, material)
    else:
        await event(db, ctx, j, "EDITED", details={"fields": sorted(changed)})
    await db.flush()
    await reassess(db, ctx, j)


async def reset_controls(db: AsyncSession, j: RsJourney, group: str | None = None) -> None:
    stmt = (
        update(RsControlCheck)
        .where(RsControlCheck.organisation_id == j.organisation_id)
        .where(RsControlCheck.journey_id == j.id)
        .values(
            status=ControlStatus.PENDING,
            completed_by=None,
            completed_at=None,
            completed_revision=None,
            exception_reason=None,
            exception_by=None,
            note=None,
        )
    )
    if group is not None:
        stmt = stmt.where(RsControlCheck.control_group == group)
    await db.execute(stmt)


def engine_input(
    j: RsJourney,
    legs: list[RsRouteLeg],
    checkins: list[RsCheckinPlan],
    vehicle_row: RsVehicle | None,
) -> engine.JourneyIn:
    return engine.JourneyIn(
        departs_at=j.departs_at,
        arrives_at=j.arrives_at,
        returns_at=j.returns_at,
        timezone=j.timezone,
        legs=tuple(
            engine.LegIn(
                position=leg.position,
                origin=leg.origin,
                destination=leg.destination,
                departs_at=leg.departs_at,
                arrives_at=leg.arrives_at,
                timezone=leg.timezone,
                distance_km=float(leg.distance_km) if leg.distance_km is not None else None,
                road_surface=leg.road_surface,
                mobile_coverage=leg.mobile_coverage,
                crossings=leg.crossings,
                closure_status=leg.closure_status,
                closure_source=leg.closure_source,
                closure_observed_at=leg.closure_observed_at,
            )
            for leg in legs
        ),
        occupants=j.occupants,
        remoteness=j.remoteness,
        comms_mobile=j.comms_mobile,
        comms_uhf=j.comms_uhf,
        comms_sat_phone=j.comms_sat_phone,
        comms_sat_messenger=j.comms_sat_messenger,
        has_monitor=j.monitor_user_id is not None,
        emergency_contacts=len(j.emergency_contacts or []),
        checkins=tuple(c.due_at for c in checkins),
        weather_checked_at=j.weather_checked_at,
        weather_source=j.weather_source,
        weather_warnings=j.weather_warnings,
        vehicle_known=vehicle_row is not None,
        fuel_range_km=float(vehicle_row.fuel_range_km)
        if vehicle_row is not None and vehicle_row.fuel_range_km
        else None,
    )


async def reassess(db: AsyncSession, ctx: RsContext, j: RsJourney) -> RsRiskAssessment:
    settings = ctx.enabled()
    policy = ctx.policy
    legs = await legs_of(db, j)
    checkins = await checkins_of(db, j)
    vehicle_row = await vehicle(db, ctx, j.vehicle_id) if j.vehicle_id else None
    result = engine.assess(engine_input(j, legs, checkins, vehicle_row), policy)
    a = RsRiskAssessment(
        organisation_id=j.organisation_id,
        journey_id=j.id,
        revision=j.revision,
        outcome=result.outcome,
        library_version=policy.library_version,
        policy_version=settings.policy_version,
        facts=result.facts,
        stop_conditions=[
            {"key": s.key, "reason": s.reason, "evidence": s.evidence} for s in result.stops
        ],
        created_by=ctx.user_id,
    )
    db.add(a)
    await db.flush()
    db.add_all(
        RsHazardFinding(
            organisation_id=j.organisation_id,
            assessment_id=a.id,
            position=i,
            hazard_key=f.key,
            title=f.title,
            description=f.description,
            evidence=f.evidence,
            likelihood=f.likelihood,
            consequence=f.consequence,
            initial_score=f.initial_score,
            initial_rating=f.initial_rating,
            controls=list(f.controls),
            residual_likelihood=f.residual_likelihood,
            residual_score=f.residual_score,
            residual_rating=f.residual_rating,
            responsible=f.responsible,
        )
        for i, f in enumerate(result.findings, start=1)
    )
    await sync_controls(db, j, policy, result)
    j.risk_outcome = result.outcome
    j.current_assessment_id = a.id
    await db.flush()
    return a


async def sync_controls(
    db: AsyncSession, j: RsJourney, policy: Policy, result: engine.Assessment
) -> None:
    existing = {c.control_key: c for c in await controls_of(db, j)}
    required_by: dict[str, list[str]] = {}
    for f in result.findings:
        for key in f.controls:
            required_by.setdefault(key, []).append(f.key)
    for position, (key, c) in enumerate(policy.controls.items(), start=1):
        mandatory = key in result.mandatory_controls
        row = existing.get(key)
        if row is None:
            db.add(
                RsControlCheck(
                    organisation_id=j.organisation_id,
                    journey_id=j.id,
                    control_key=key,
                    control_group=c.group,
                    label=c.label,
                    position=position,
                    mandatory=mandatory,
                    required_by=required_by.get(key, []),
                )
            )
            continue
        if mandatory and row.status == ControlStatus.NOT_APPLICABLE:
            # It applies now: ask again.
            row.status = ControlStatus.PENDING
            row.completed_by = None
            row.completed_at = None
        row.mandatory = mandatory
        row.required_by = required_by.get(key, [])
        row.label = c.label
    await db.flush()


async def snapshot(db: AsyncSession, ctx: RsContext, j: RsJourney, changed: list[str]) -> None:
    if await _has_snapshot(db, j):
        return
    legs = await legs_of(db, j)
    checkins = await checkins_of(db, j)
    columns = {c.key: getattr(j, c.key) for c in RsJourney.__table__.columns}
    data = {
        "journey": columns,
        "legs": [{c.key: getattr(r, c.key) for c in RsRouteLeg.__table__.columns} for r in legs],
        "checkins": [
            {"due_at": c.due_at, "location": c.location, "method": c.method} for c in checkins
        ],
    }
    db.add(
        RsJourneyRevision(
            organisation_id=j.organisation_id,
            journey_id=j.id,
            revision=j.revision,
            snapshot=json.loads(json.dumps(data, default=str)),
            changed_fields=changed,
            created_by=ctx.user_id,
        )
    )
    await db.flush()


async def event(
    db: AsyncSession,
    ctx: RsContext,
    j: RsJourney,
    kind: str,
    *,
    from_status: str | None = None,
    to_status: str | None = None,
    note: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        RsJourneyEvent(
            organisation_id=j.organisation_id,
            journey_id=j.id,
            kind=kind,
            from_status=from_status,
            to_status=to_status,
            revision=j.revision,
            actor_user_id=ctx.user_id,
            note=note,
            details=details or {},
        )
    )
    await db.flush()


async def latest_assessment(
    db: AsyncSession, j: RsJourney
) -> tuple[RsRiskAssessment, list[RsHazardFinding]]:
    a = (
        await db.execute(
            select(RsRiskAssessment).where(
                RsRiskAssessment.organisation_id == j.organisation_id,
                RsRiskAssessment.id == j.current_assessment_id,
            )
        )
    ).scalar_one()
    findings = (
        await db.execute(
            select(RsHazardFinding)
            .where(RsHazardFinding.assessment_id == a.id)
            .order_by(RsHazardFinding.position)
        )
    ).scalars()
    return a, list(findings)


async def controls_of(db: AsyncSession, j: RsJourney) -> list[RsControlCheck]:
    rows = await db.execute(
        select(RsControlCheck)
        .where(
            RsControlCheck.organisation_id == j.organisation_id,
            RsControlCheck.journey_id == j.id,
        )
        .order_by(RsControlCheck.position)
    )
    return list(rows.scalars())


def pathway(outcome: str) -> str:
    return {
        "LOW": "Normal approval by the supervisor.",
        "MODERATE": "Supervisor review before approval.",
        "HIGH": "Enhanced controls and approval by an authorised approver.",
        "CRITICAL": "Cannot start until every stop condition is resolved, or a WHS "
        "administrator approves a documented alternative process.",
    }[outcome]


# --- Controls --------------------------------------------------------------------------


async def set_control(
    db: AsyncSession, ctx: RsContext, j: RsJourney, key: str, status: str, note: str | None
) -> RsControlCheck:
    me = ctx.user_id
    if j.status not in EDITABLE or j.archived_at is not None:
        raise ApiError(409, "controls_locked", "Controls can't change once the journey starts.")
    if not (me in (j.worker_user_id, j.supervisor_user_id, j.created_by) or ctx.whs_admin):
        raise forbidden("Only the worker or their supervisor can complete controls.")
    row = next((c for c in await controls_of(db, j) if c.control_key == key), None)
    if row is None:
        raise not_found("Control")
    if status == ControlStatus.NOT_APPLICABLE and row.mandatory:
        raise ApiError(
            409,
            "control_mandatory",
            "This control is mandatory. If it can't be done, a WHS administrator must "
            "record an exception.",
        )
    before = row.status
    row.status = status
    row.note = note
    row.exception_reason = None
    row.exception_by = None
    if status == ControlStatus.PENDING:
        row.completed_by = None
        row.completed_at = None
        row.completed_revision = None
    else:
        row.completed_by = me
        row.completed_at = utcnow()
        row.completed_revision = j.revision
    await event(
        db,
        ctx,
        j,
        "CONTROL_FAILED" if status == ControlStatus.FAILED else "CONTROL_UPDATED",
        note=note,
        details={"control": key, "from": before, "to": status, "mandatory": row.mandatory},
    )
    return row


async def control_exception(
    db: AsyncSession, ctx: RsContext, j: RsJourney, key: str, reason: str, meta: RequestMeta
) -> RsControlCheck:
    if not ctx.whs_admin:
        raise forbidden("Only a WHS administrator can record an exception to a control.")
    if ctx.user_id == j.worker_user_id:
        raise forbidden("You can't record an exception on your own journey.")
    if j.status not in EDITABLE or j.archived_at is not None:
        raise ApiError(409, "controls_locked", "Controls can't change once the journey starts.")
    row = next((c for c in await controls_of(db, j) if c.control_key == key), None)
    if row is None:
        raise not_found("Control")
    if not row.mandatory:
        raise ApiError(409, "not_mandatory", "Exceptions are only for mandatory controls.")
    before = row.status
    row.status = ControlStatus.EXCEPTION
    row.exception_reason = reason
    row.exception_by = ctx.user_id
    row.completed_by = ctx.user_id
    row.completed_at = utcnow()
    row.completed_revision = j.revision
    await event(
        db,
        ctx,
        j,
        "CONTROL_EXCEPTION",
        note=reason,
        details={"control": key, "from": before},
    )
    await audit.record(
        db,
        "remotesafe.control_exception",
        actor_user_id=ctx.user_id,
        organisation_id=ctx.organisation_id,
        target_type="rs_journey",
        target_id=j.id,
        meta=meta,
        details={"control": key, "reason": reason},
    )
    return row


def control_blockers(controls: list[RsControlCheck]) -> list[str]:
    out = []
    for c in controls:
        if not c.mandatory:
            continue
        if c.status == ControlStatus.FAILED:
            out.append(f"Failed: {c.label}")
        elif c.status == ControlStatus.PENDING:
            out.append(f"Not done: {c.label}")
    return out


# --- Workflow transitions --------------------------------------------------------------


def submit_problems(j: RsJourney, legs: list[RsRouteLeg]) -> list[str]:
    out = []
    if j.supervisor_user_id is None:
        out.append("Choose a supervisor to approve the journey.")
    if not legs:
        out.append("Add at least one route leg.")
    elif legs[0].departs_at < j.departs_at or legs[-1].arrives_at > (j.returns_at or j.arrives_at):
        out.append("Route legs must fall between departure and the end of the journey.")
    return out


async def transition(
    db: AsyncSession,
    ctx: RsContext,
    j: RsJourney,
    action: str,
    note: str | None,
    meta: RequestMeta,
    critical_alternative_process: str | None = None,
) -> RsJourney:
    if action not in allowed_actions(ctx, j):
        # Say why when we can; otherwise the generic refusal.
        if action == "approve" and j.status == S.SUBMITTED:
            problem = approval_problem(ctx, j, j.risk_outcome or "LOW", ctx.policy)
            if problem:
                raise ApiError(403, "cannot_approve", problem)
        raise ApiError(
            409,
            "invalid_transition",
            f"You can't {action.replace('_', ' ')} a journey that is "
            f"{j.status.replace('_', ' ').lower()}.",
        )
    previous = j.status
    now = utcnow()
    if action == "submit":
        problems = submit_problems(j, await legs_of(db, j))
        if problems:
            raise ApiError(422, "not_ready", " ".join(problems))
        await reassess(db, ctx, j)
        j.status = S.SUBMITTED
        j.submitted_at = now
        await snapshot(db, ctx, j, [])
    elif action == "request_changes":
        if not note:
            raise ApiError(422, "note_required", "Say what needs to change.")
        j.status = S.CHANGES_REQUESTED
    elif action == "approve":
        assessment = await reassess(db, ctx, j)
        problem = approval_problem(ctx, j, assessment.outcome, ctx.policy)
        if problem:
            raise ApiError(403, "cannot_approve", problem)
        stops = {s["key"] for s in assessment.stop_conditions}
        if "no_route" in stops:
            raise ApiError(409, "not_ready", "The journey has no route legs.")
        if assessment.outcome == "CRITICAL":
            if not critical_alternative_process:
                raise ApiError(
                    422,
                    "alternative_process_required",
                    "This journey is critical risk. Resolve the stop conditions, or record "
                    "the documented alternative process that makes it safe to approve.",
                )
            j.critical_alternative_process = critical_alternative_process
        j.status = S.APPROVED
        j.approved_by = ctx.user_id
        j.approved_at = now
        j.approved_revision = j.revision
        j.approved_outcome = assessment.outcome
        await audit.record(
            db,
            "remotesafe.journey_approved",
            actor_user_id=ctx.user_id,
            organisation_id=ctx.organisation_id,
            target_type="rs_journey",
            target_id=j.id,
            meta=meta,
            details={
                "revision": j.revision,
                "outcome": assessment.outcome,
                "stop_conditions": sorted(stops),
            },
        )
    elif action == "commence":
        if j.approved_revision != j.revision:
            raise ApiError(409, "not_approved", "This revision of the plan isn't approved.")
        blockers = control_blockers(await controls_of(db, j))
        if blockers:
            raise ApiError(
                409,
                "controls_incomplete",
                "Mandatory controls must be done (or have an authorised exception) before "
                "departure. " + " ".join(blockers),
            )
        j.status = S.ACTIVE
        j.started_at = now
    elif action == "complete":
        j.status = S.COMPLETED
        j.completed_at = now
    elif action == "escalate":
        if not note:
            raise ApiError(422, "note_required", "Record why and who you've contacted.")
        j.status = S.ESCALATED
    elif action == "cancel":
        j.status = S.CANCELLED
        j.cancelled_at = now
    elif action == "archive":
        j.archived_at = now
    await event(
        db,
        ctx,
        j,
        action.upper(),
        from_status=previous,
        to_status=j.status,
        note=note,
        details={"critical_alternative_process": critical_alternative_process}
        if critical_alternative_process
        else None,
    )
    await db.flush()
    return j


async def blockers(db: AsyncSession, ctx: RsContext, j: RsJourney) -> list[str]:
    """What stands between this journey and its next step, in plain words."""
    out: list[str] = []
    if j.status in (S.DRAFT, S.CHANGES_REQUESTED):
        out += submit_problems(j, await legs_of(db, j))
    if j.status in (S.DRAFT, S.CHANGES_REQUESTED, S.SUBMITTED):
        a, _ = await latest_assessment(db, j)
        out += [s["reason"] for s in a.stop_conditions]
    if j.status == S.APPROVED:
        out += control_blockers(await controls_of(db, j))
    return out


# --- Lists and dashboard ---------------------------------------------------------------


async def list_journeys(
    db: AsyncSession,
    ctx: RsContext,
    *,
    status: str | None = None,
    awaiting_me: bool = False,
    include_archived: bool = False,
    limit: int = 200,
) -> list[RsJourney]:
    ctx.enabled()
    stmt = select(RsJourney).where(visible_filter(ctx))
    if status:
        stmt = stmt.where(RsJourney.status == status)
    if not include_archived:
        stmt = stmt.where(RsJourney.archived_at.is_(None))
    if awaiting_me:
        stmt = stmt.where(RsJourney.status == S.SUBMITTED, RsJourney.worker_user_id != ctx.user_id)
        if not ctx.whs_admin:
            stmt = stmt.where(RsJourney.supervisor_user_id == ctx.user_id)
    stmt = stmt.order_by(RsJourney.departs_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars())


async def dashboard(db: AsyncSession, ctx: RsContext) -> dict[str, Any]:
    journeys = await list_journeys(db, ctx, limit=1000)
    by_status: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    for j in journeys:
        by_status[j.status] = by_status.get(j.status, 0) + 1
        if j.risk_outcome:
            by_outcome[j.risk_outcome] = by_outcome.get(j.risk_outcome, 0) + 1
    awaiting = len(await list_journeys(db, ctx, awaiting_me=True)) if ctx.can_approve else 0
    ids = [j.id for j in journeys if j.status not in FINISHED]
    failures = 0
    if ids:
        failures = (
            await db.execute(
                select(func.count())
                .select_from(RsControlCheck)
                .where(
                    RsControlCheck.organisation_id == ctx.organisation_id,
                    RsControlCheck.journey_id.in_(ids),
                    RsControlCheck.mandatory.is_(True),
                    RsControlCheck.status == ControlStatus.FAILED,
                )
            )
        ).scalar_one()
    hazards: dict[str, tuple[str, int]] = {}
    all_ids = [j.id for j in journeys]
    if all_ids:
        latest = [j.current_assessment_id for j in journeys if j.current_assessment_id]
        for key, title in await db.execute(
            select(RsHazardFinding.hazard_key, RsHazardFinding.title).where(
                RsHazardFinding.organisation_id == ctx.organisation_id,
                RsHazardFinding.assessment_id.in_(latest),
            )
        ):
            hazards[key] = (title, hazards.get(key, (title, 0))[1] + 1)
    repeated = sorted(
        ({"hazard_key": k, "title": t, "journeys": n} for k, (t, n) in hazards.items() if n > 1),
        key=lambda h: -int(str(h["journeys"])),
    )[:8]
    done = by_status.get(S.COMPLETED, 0)
    ended = done + by_status.get(S.CANCELLED, 0)
    upcoming = [
        j
        for j in sorted(journeys, key=lambda j: j.departs_at)
        if j.status in (S.APPROVED, *UNDERWAY)
    ][:10]
    return {
        "scope": "organisation" if ctx.sees_all else "mine",
        "by_status": by_status,
        "by_outcome": by_outcome,
        "awaiting_my_approval": awaiting,
        "active": sum(by_status.get(s, 0) for s in UNDERWAY),
        "critical_control_failures": failures,
        "repeated_hazards": repeated,
        "completion_rate": round(done / ended, 3) if ended else None,
        "upcoming": upcoming,
        "monitoring_live": False,
    }


def outcome_rank(outcome: str | None) -> int:
    return RATINGS.index(outcome) if outcome in RATINGS else -1


# --- Policy ----------------------------------------------------------------------------


async def update_policy(
    db: AsyncSession, ctx: RsContext, overrides: dict[str, Any], meta: RequestMeta
) -> RsSettings:
    from app.modules.remotesafe.entitlements import has_feature

    settings = ctx.enabled()
    if not ctx.whs_admin:
        raise forbidden("Only a WHS administrator can change the risk policy.")
    if not has_feature(settings.tier, "risk_library"):
        raise ApiError(
            402,
            "feature_not_in_plan",
            "Changing the risk library is part of the Enterprise plan.",
        )
    build_policy(overrides)  # validates (422 on a bad value)
    before = settings.policy
    settings.policy = overrides
    settings.policy_version += 1
    await audit.record(
        db,
        "remotesafe.policy_changed",
        actor_user_id=ctx.user_id,
        organisation_id=ctx.organisation_id,
        target_type="rs_settings",
        target_id=settings.id,
        meta=meta,
        details={"before": before, "after": overrides, "version": settings.policy_version},
    )
    await db.flush()
    return settings
