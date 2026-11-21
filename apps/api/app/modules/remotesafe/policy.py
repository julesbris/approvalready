"""RemoteSafe risk policy: the reviewed baseline library plus an organisation's overrides.

The baseline lives in ``library.json``. An organisation's WHS administrator may change
ratings, rating bands and planning assumptions, switch off hazards that do not apply to
them, and make more controls mandatory. They can never switch off a stop condition or make
a baseline mandatory control optional: those only ever get stricter. Nor can they stop a
material change to an approved journey from sending it back for approval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import time
from functools import cache
from pathlib import Path
from typing import Any

from app.core.errors import ApiError

LIBRARY_PATH = Path(__file__).with_name("library.json")

RATINGS = ("LOW", "MODERATE", "HIGH", "CRITICAL")


@dataclass(frozen=True)
class ControlDef:
    key: str
    group: str
    label: str
    mandatory: bool


@dataclass(frozen=True)
class HazardDef:
    key: str
    title: str
    description: str
    likelihood: int
    consequence: int
    residual_likelihood: int
    controls: tuple[str, ...]
    responsible: str
    enabled: bool = True


@dataclass(frozen=True)
class Assumptions:
    night_start: time
    night_end: time
    fatigue_hours: float
    max_driving_hours_per_day: float
    max_checkin_gap_minutes: int
    corrugation_unsealed_km: float
    breakdown_distance_km: float
    fuel_margin: float
    heat_months: tuple[int, ...]


@dataclass(frozen=True)
class Policy:
    library_version: str
    bands: dict[str, int]
    assumptions: Assumptions
    controls: dict[str, ControlDef]
    hazards: dict[str, HazardDef]
    high_risk_approver_roles: tuple[str, ...] = ("WHS_ADMIN",)
    overrides: dict[str, Any] = field(default_factory=dict)

    def rating(self, score: int) -> str:
        if score >= self.bands["critical"]:
            return "CRITICAL"
        if score >= self.bands["high"]:
            return "HIGH"
        if score >= self.bands["moderate"]:
            return "MODERATE"
        return "LOW"


@cache
def library() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    return data


def _invalid(message: str) -> ApiError:
    return ApiError(422, "invalid_policy", message)


def _scale(value: Any, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise _invalid(f"{what} must be a whole number from 1 to 5.")
    return value


def _clock(value: str, what: str) -> time:
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        raise _invalid(f"{what} must be a time like 18:30.") from None


def build_policy(overrides: dict[str, Any] | None = None) -> Policy:
    """Merge ``overrides`` onto the baseline, validating every value (422 on a bad one)."""
    base = library()
    o = overrides or {}
    unknown = set(o) - {
        "rating_bands",
        "assumptions",
        "hazards",
        "extra_mandatory_controls",
        "high_risk_approver_roles",
    }
    if unknown:
        raise _invalid(f"Unknown policy settings: {', '.join(sorted(unknown))}.")

    bands = dict(base["rating_bands"]) | dict(o.get("rating_bands") or {})
    if set(bands) != {"moderate", "high", "critical"}:
        raise _invalid("Rating bands are moderate, high and critical.")
    if not all(isinstance(v, int) and 1 <= v <= 25 for v in bands.values()):
        raise _invalid("Rating band thresholds must be whole numbers from 1 to 25.")
    if not 1 < bands["moderate"] < bands["high"] < bands["critical"] <= 25:
        raise _invalid("Rating bands must rise: moderate below high below critical.")

    a = dict(base["assumptions"]) | dict(o.get("assumptions") or {})
    if set(a) != set(base["assumptions"]):
        raise _invalid("Unknown planning assumption.")
    try:
        assumptions = Assumptions(
            night_start=_clock(a["night_start"], "Night starts"),
            night_end=_clock(a["night_end"], "Night ends"),
            fatigue_hours=float(a["fatigue_hours"]),
            max_driving_hours_per_day=float(a["max_driving_hours_per_day"]),
            max_checkin_gap_minutes=int(a["max_checkin_gap_minutes"]),
            corrugation_unsealed_km=float(a["corrugation_unsealed_km"]),
            breakdown_distance_km=float(a["breakdown_distance_km"]),
            fuel_margin=float(a["fuel_margin"]),
            heat_months=tuple(int(m) for m in a["heat_months"]),
        )
    except (TypeError, ValueError):
        raise _invalid("A planning assumption has the wrong type.") from None
    if not 0.5 <= assumptions.fatigue_hours <= 24:
        raise _invalid("Fatigue hours must be between 0.5 and 24.")
    if not 1 <= assumptions.max_driving_hours_per_day <= 24:
        raise _invalid("Maximum driving hours per day must be between 1 and 24.")
    if not 15 <= assumptions.max_checkin_gap_minutes <= 24 * 60:
        raise _invalid("The longest gap between check-ins must be 15 minutes to 24 hours.")
    if not 0.1 <= assumptions.fuel_margin <= 1:
        raise _invalid("Fuel margin must be between 0.1 and 1.")
    if any(not 1 <= m <= 12 for m in assumptions.heat_months):
        raise _invalid("Heat months are numbers from 1 to 12.")

    hazard_overrides: dict[str, Any] = dict(o.get("hazards") or {})
    known = {h["key"] for h in base["hazards"]}
    if set(hazard_overrides) - known:
        raise _invalid(f"Unknown hazards: {', '.join(sorted(set(hazard_overrides) - known))}.")
    hazards: dict[str, HazardDef] = {}
    for h in base["hazards"]:
        change = dict(hazard_overrides.get(h["key"]) or {})
        if set(change) - {"likelihood", "consequence", "residual_likelihood", "enabled"}:
            raise _invalid(f"Only ratings and enabled can change for hazard {h['key']}.")
        likelihood = _scale(change.get("likelihood", h["likelihood"]), "Likelihood")
        consequence = _scale(change.get("consequence", h["consequence"]), "Consequence")
        residual = _scale(
            change.get("residual_likelihood", h["residual_likelihood"]), "Residual likelihood"
        )
        if residual > likelihood:
            raise _invalid(f"Residual likelihood can't be above likelihood ({h['key']}).")
        enabled = change.get("enabled", True)
        if not isinstance(enabled, bool):
            raise _invalid("Enabled is true or false.")
        hazards[h["key"]] = HazardDef(
            key=h["key"],
            title=h["title"],
            description=h["description"],
            likelihood=likelihood,
            consequence=consequence,
            residual_likelihood=residual,
            controls=tuple(h["controls"]),
            responsible=h["responsible"],
            enabled=enabled,
        )

    extra = o.get("extra_mandatory_controls") or []
    control_keys = {c["key"] for c in base["controls"]}
    if not isinstance(extra, list) or set(extra) - control_keys:
        raise _invalid("Extra mandatory controls must be known control keys.")
    controls = {
        c["key"]: ControlDef(c["key"], c["group"], c["label"], c["mandatory"] or c["key"] in extra)
        for c in base["controls"]
    }

    approvers = tuple(o.get("high_risk_approver_roles") or ("WHS_ADMIN",))
    if not set(approvers) <= {"SUPERVISOR", "WHS_ADMIN"}:
        raise _invalid("High-risk approvers are SUPERVISOR or WHS_ADMIN.")
    return Policy(
        library_version=str(base["version"]),
        bands=bands,
        assumptions=assumptions,
        controls=controls,
        hazards=hazards,
        high_risk_approver_roles=approvers,
        overrides=o,
    )
