"""RemoteSafe Stage 1 risk engine: transparent, rules-based, no prediction.

Every hazard is triggered by a stated rule over facts the planner entered (or the vehicle
register holds), and every finding lists that evidence with where it came from. Ratings are
likelihood x consequence on 1-5 planning scales set by policy. They rank hazards for
attention and choose the approval pathway; they are not probabilities.

Stop conditions are separate from ratings and cannot be configured away: while one is open
the journey is CRITICAL and cannot be approved on the normal pathway.

No external data (road closures, weather, flood, coverage, terrain) is fetched in Stage 1.
Where a rule depends on such data the planner records what they checked and where; the
engine never invents a road condition or coverage figure.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from itertools import pairwise
from typing import Any

from app.modules.remotesafe.policy import RATINGS, Policy
from app.modules.remotesafe.timezones import local

PLANNER = "Journey plan, as entered by the planner"
VEHICLE_REGISTER = "Organisation vehicle register"
ASSUMPTION = "Organisation policy assumption (not observed data)"
REMOTE_LEVELS = ("REMOTE", "VERY_REMOTE")
WEAK_COVERAGE = ("NONE", "PATCHY", "UNKNOWN")
UNSEALED = ("UNSEALED", "MIXED", "UNKNOWN")
STEP = timedelta(minutes=10)


@dataclass(frozen=True)
class LegIn:
    position: int
    origin: str
    destination: str
    departs_at: datetime
    arrives_at: datetime
    timezone: str
    distance_km: float | None = None
    road_surface: str = "UNKNOWN"
    mobile_coverage: str = "UNKNOWN"
    crossings: int = 0
    closure_status: str = "NOT_CHECKED"
    closure_source: str | None = None
    closure_observed_at: datetime | None = None


@dataclass(frozen=True)
class JourneyIn:
    departs_at: datetime
    arrives_at: datetime
    timezone: str
    legs: tuple[LegIn, ...]
    returns_at: datetime | None = None
    occupants: int = 1
    remoteness: str = "UNKNOWN"
    comms_mobile: bool = False
    comms_uhf: bool = False
    comms_sat_phone: bool = False
    comms_sat_messenger: bool = False
    has_monitor: bool = False
    emergency_contacts: int = 0
    checkins: tuple[datetime, ...] = ()
    weather_checked_at: datetime | None = None
    weather_source: str | None = None
    weather_warnings: str | None = None
    vehicle_known: bool = False
    fuel_range_km: float | None = None


@dataclass
class Finding:
    key: str
    title: str
    description: str
    evidence: list[dict[str, Any]]
    likelihood: int
    consequence: int
    residual_likelihood: int
    controls: tuple[str, ...]
    responsible: str
    initial_score: int = 0
    initial_rating: str = "LOW"
    residual_score: int = 0
    residual_rating: str = "LOW"


@dataclass
class Stop:
    key: str
    reason: str
    evidence: list[dict[str, Any]]


@dataclass
class Assessment:
    outcome: str
    findings: list[Finding]
    stops: list[Stop]
    facts: dict[str, Any]
    mandatory_controls: set[str] = field(default_factory=set)


def ev(
    fact: str, value: Any, source: str = PLANNER, observed_at: datetime | None = None
) -> dict[str, Any]:
    return {
        "fact": fact,
        "value": str(value),
        "source": source,
        "observed_at": observed_at.isoformat() if observed_at else None,
    }


def _in_night(t: time, start: time, end: time) -> bool:
    return t >= start or t < end if start > end else start <= t < end


def driving_profile(j: JourneyIn, p: Policy) -> tuple[float, float, dict[str, float]]:
    """Total driving hours, hours in the night window and hours per local day."""
    a = p.assumptions
    total = timedelta()
    night = timedelta()
    per_day: dict[str, timedelta] = defaultdict(timedelta)
    for leg in j.legs:
        total += leg.arrives_at - leg.departs_at
        t = leg.departs_at
        while t < leg.arrives_at:
            step = min(STEP, leg.arrives_at - t)
            here = local(t, leg.timezone)
            if _in_night(here.time(), a.night_start, a.night_end):
                night += step
            per_day[here.date().isoformat()] += step
            t += step
    hours = {d: round(v.total_seconds() / 3600, 2) for d, v in per_day.items()}
    return (
        round(total.total_seconds() / 3600, 2),
        round(night.total_seconds() / 3600, 2),
        hours,
    )


def assess(j: JourneyIn, p: Policy) -> Assessment:
    a = p.assumptions
    total_h, night_h, per_day = driving_profile(j, p)
    longest_day = max(per_day.values(), default=0.0)
    remote = j.remoteness in REMOTE_LEVELS
    has_sat = j.comms_sat_phone or j.comms_sat_messenger
    no_coverage = [leg for leg in j.legs if leg.mobile_coverage == "NONE"]
    weak_coverage = [leg for leg in j.legs if leg.mobile_coverage in WEAK_COVERAGE]
    unsealed = [leg for leg in j.legs if leg.road_surface in UNSEALED]
    unsealed_km = sum(leg.distance_km or 0 for leg in unsealed)
    crossings = sum(leg.crossings for leg in j.legs)
    distance = sum(leg.distance_km or 0 for leg in j.legs)
    longest_leg = max((leg.distance_km or 0 for leg in j.legs), default=0)
    months = {local(leg.departs_at, leg.timezone).month for leg in j.legs}
    early = [leg for leg in j.legs if local(leg.departs_at, leg.timezone).time() < a.night_end]
    triggered: dict[str, list[dict[str, Any]]] = {}

    def hit(key: str, *evidence: dict[str, Any]) -> None:
        triggered.setdefault(key, []).extend(evidence)

    def leg_ev(leg: LegIn, fact: str, value: Any) -> dict[str, Any]:
        return ev(f"Leg {leg.position} ({leg.origin} to {leg.destination}): {fact}", value)

    remoteness_ev = ev("Remoteness of the route", j.remoteness.replace("_", " ").lower())

    if total_h > a.fatigue_hours or early:
        hit("fatigue", ev("Planned driving time", f"{total_h} hours"))
        hit("fatigue", ev("Fatigue threshold", f"{a.fatigue_hours} hours", ASSUMPTION))
        for leg in early:
            hit("fatigue", leg_ev(leg, "departs before", a.night_end.strftime("%H:%M")))
    if longest_day > a.max_driving_hours_per_day:
        hit(
            "excessive_driving",
            ev("Most driving in one day", f"{longest_day} hours"),
            ev("Daily limit", f"{a.max_driving_hours_per_day} hours", ASSUMPTION),
        )
    if night_h > 0:
        hit(
            "night_driving",
            ev("Driving inside the night window", f"{night_h} hours"),
            ev(
                "Night window",
                f"{a.night_start:%H:%M} to {a.night_end:%H:%M} local time",
                ASSUMPTION,
            ),
        )
    if night_h > 0 or remote:
        hit("wildlife_collision", remoteness_ev if remote else ev("Night driving", f"{night_h} h"))
    for leg in unsealed:
        hit("unsealed_roads", leg_ev(leg, "road surface", leg.road_surface.lower()))
    if unsealed_km > a.corrugation_unsealed_km:
        hit(
            "corrugations",
            ev("Unsealed or unknown-surface distance", f"{unsealed_km:g} km"),
            ev("Corrugation threshold", f"{a.corrugation_unsealed_km:g} km", ASSUMPTION),
        )
    if unsealed:
        hit("recovery_equipment", ev("Legs on unsealed or unknown surface", len(unsealed)))
    if crossings:
        hit("flood_crossings", ev("Known creek, river or causeway crossings", crossings))
        hit("dangerous_wildlife", ev("Known creek, river or causeway crossings", crossings))
    for leg in j.legs:
        if leg.closure_status == "RESTRICTED":
            hit(
                "road_closure",
                ev(
                    f"Leg {leg.position}: restriction recorded",
                    leg.closure_source or "source not given",
                    f"Entered by the planner from {leg.closure_source or 'an unnamed source'}",
                    leg.closure_observed_at,
                ),
            )
        elif leg.closure_status == "NOT_CHECKED":
            hit("road_closure", leg_ev(leg, "road closures", "not checked yet"))
    if j.weather_warnings:
        hit(
            "severe_weather",
            ev(
                "Warnings recorded by the planner",
                j.weather_warnings,
                f"Entered by the planner from {j.weather_source or 'an unnamed source'}",
                j.weather_checked_at,
            ),
        )
    elif j.weather_checked_at is None:
        hit("severe_weather", ev("Weather warnings", "not checked yet"))
    if remote and months & set(a.heat_months):
        hit(
            "extreme_heat",
            remoteness_ev,
            ev("Hot months", ", ".join(str(m) for m in sorted(a.heat_months)), ASSUMPTION),
        )
    if remote or distance > a.breakdown_distance_km:
        hit("vehicle_breakdown", ev("Planned distance", f"{distance:g} km"))
        if remote:
            hit("vehicle_breakdown", remoteness_ev)
    for leg in weak_coverage:
        hit("communications", leg_ev(leg, "mobile coverage", leg.mobile_coverage.lower()))
    if remote:
        hit("remote_work", remoteness_ev)
        hit("medical_emergency", remoteness_ev)
    if j.remoteness == "VERY_REMOTE":
        hit("emergency_response", remoteness_ev)
    gaps = checkin_gaps(j)
    longest_gap = max(gaps, default=0)
    if longest_gap > a.max_checkin_gap_minutes:
        hit(
            "delayed_rescue",
            ev("Longest time without a planned check-in", f"{longest_gap} minutes"),
            ev("Longest allowed gap", f"{a.max_checkin_gap_minutes} minutes", ASSUMPTION),
        )
    if j.occupants <= 1:
        hit("working_alone", ev("People in the vehicle", j.occupants))
    if j.fuel_range_km is None:
        if remote or longest_leg > a.breakdown_distance_km:
            hit("supplies", ev("Vehicle fuel range", "not recorded", VEHICLE_REGISTER))
    elif longest_leg > j.fuel_range_km * a.fuel_margin:
        hit(
            "supplies",
            ev("Longest leg", f"{longest_leg:g} km"),
            ev("Vehicle fuel range", f"{j.fuel_range_km:g} km", VEHICLE_REGISTER),
            ev("Safe share of range", f"{a.fuel_margin:g}", ASSUMPTION),
        )
    elif remote:
        hit("supplies", remoteness_ev)

    findings: list[Finding] = []
    for key, evidence in triggered.items():
        h = p.hazards[key]
        if not h.enabled:
            continue
        f = Finding(
            key=h.key,
            title=h.title,
            description=h.description,
            evidence=evidence,
            likelihood=h.likelihood,
            consequence=h.consequence,
            residual_likelihood=h.residual_likelihood,
            controls=h.controls,
            responsible=h.responsible,
        )
        f.initial_score = h.likelihood * h.consequence
        f.initial_rating = p.rating(f.initial_score)
        # Controls lower the likelihood only; the consequence of the event stays the same.
        f.residual_score = h.residual_likelihood * h.consequence
        f.residual_rating = p.rating(f.residual_score)
        findings.append(f)
    order = list(p.hazards)
    findings.sort(key=lambda f: (-f.residual_score, order.index(f.key)))

    stops = stop_conditions(j, remote, has_sat, no_coverage)
    if stops:
        outcome = "CRITICAL"
    else:
        outcome = max((f.residual_rating for f in findings), key=RATINGS.index, default="LOW")
    mandatory = {k for k, c in p.controls.items() if c.mandatory}
    for f in findings:
        mandatory.update(f.controls)
    if remote or no_coverage:
        mandatory.add("satellite_device")
    facts = {
        "driving_hours": total_h,
        "night_hours": night_h,
        "driving_hours_by_day": per_day,
        "distance_km": round(distance, 1),
        "unsealed_km": round(unsealed_km, 1),
        "crossings": crossings,
        "longest_leg_km": longest_leg,
        "longest_checkin_gap_minutes": longest_gap,
        "remoteness": j.remoteness,
        "satellite": has_sat,
        "occupants": j.occupants,
        "legs": len(j.legs),
    }
    return Assessment(outcome, findings, stops, facts, mandatory)


def checkin_gaps(j: JourneyIn) -> list[int]:
    """Minutes between departure, each planned check-in and the expected end."""
    end = j.returns_at or j.arrives_at
    points = sorted([j.departs_at, *[c for c in j.checkins if j.departs_at < c < end], end])
    return [int((b - a).total_seconds() // 60) for a, b in pairwise(points)]


def stop_conditions(
    j: JourneyIn, remote: bool, has_sat: bool, no_coverage: list[LegIn]
) -> list[Stop]:
    stops: list[Stop] = []
    if (remote or no_coverage) and not has_sat:
        evidence = [ev("Satellite phone or messenger", "none planned")]
        if remote:
            evidence.append(ev("Remoteness of the route", j.remoteness.lower()))
        evidence += [ev(f"Leg {leg.position} mobile coverage", "none") for leg in no_coverage]
        stops.append(
            Stop(
                "emergency_communications",
                "Inadequate emergency communications plan: the route is remote or has no "
                "mobile coverage, and no satellite phone or satellite messenger is planned.",
                evidence,
            )
        )
    for leg in j.legs:
        if leg.closure_status == "CONFIRMED_CLOSED":
            stops.append(
                Stop(
                    "route_closure",
                    f"Unresolved road closure on leg {leg.position} "
                    f"({leg.origin} to {leg.destination}). Change the route or record that "
                    "it has reopened.",
                    [
                        ev(
                            f"Leg {leg.position}: confirmed closure",
                            leg.closure_source or "source not given",
                            f"Entered by the planner from "
                            f"{leg.closure_source or 'an unnamed source'}",
                            leg.closure_observed_at,
                        )
                    ],
                )
            )
    missing = []
    if not j.has_monitor:
        missing.append(ev("Journey monitor", "not assigned"))
    if j.emergency_contacts == 0:
        missing.append(ev("Emergency contacts", "none"))
    if not j.checkins:
        missing.append(ev("Planned check-ins", "none"))
    if missing:
        stops.append(
            Stop(
                "emergency_arrangements",
                "Emergency arrangements are missing: every journey needs a journey monitor, "
                "at least one emergency contact and at least one planned check-in.",
                missing,
            )
        )
    if not j.legs:
        stops.append(Stop("no_route", "The journey has no route legs yet.", []))
    return stops
