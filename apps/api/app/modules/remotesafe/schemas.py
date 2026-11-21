"""RemoteSafe API shapes. Times in requests may be wall-clock times without an offset (read
in the stated Australian time zone) or full ISO times with an offset; responses give UTC
and the local time with its zone abbreviation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RsRoleName = Literal["WORKER", "SUPERVISOR", "MONITOR", "WHS_ADMIN"]
RemotenessName = Literal["UNKNOWN", "NOT_REMOTE", "REMOTE", "VERY_REMOTE"]
SurfaceName = Literal["UNKNOWN", "SEALED", "MIXED", "UNSEALED"]
CoverageName = Literal["UNKNOWN", "GOOD", "PATCHY", "NONE"]
ClosureName = Literal["NOT_CHECKED", "NONE_KNOWN", "RESTRICTED", "CONFIRMED_CLOSED"]
CheckinMethod = Literal["PHONE_CALL", "SMS", "SATELLITE_MESSAGE", "SATELLITE_CALL", "UHF", "APP"]
ControlStatusName = Literal["PENDING", "DONE", "FAILED", "NOT_APPLICABLE"]


class LocalTimeOut(BaseModel):
    utc: datetime
    local: str
    timezone: str


class RsFeatureOut(BaseModel):
    key: str
    label: str
    tier: str
    available: bool
    built: bool


class RemoteSafeMeOut(BaseModel):
    enabled: bool
    tier: str | None
    roles: list[str]
    org_admin: bool
    can_plan: bool
    can_approve: bool
    can_administer: bool
    features: list[RsFeatureOut]
    limitations: list[str]
    timezones: dict[str, str]
    default_timezone: str


class RemoteSafeEnableIn(BaseModel):
    default_timezone: str = "Australia/Brisbane"


class RsMemberOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    roles: list[str]
    org_admin: bool


class RsRolesIn(BaseModel):
    roles: list[RsRoleName] = Field(max_length=4)


class RsVehicleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    registration: str = Field(min_length=1, max_length=20)
    vehicle_type: str = Field(min_length=1, max_length=60)
    fuel_range_km: int | None = Field(default=None, ge=1, le=5000)
    notes: str | None = Field(default=None, max_length=1000)
    active: bool = True


class RsVehicleOut(RsVehicleIn):
    id: uuid.UUID


class RsEmergencyContact(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    relationship: str | None = Field(default=None, max_length=80)
    phone: str = Field(min_length=3, max_length=40)
    escalation_order: int = Field(default=1, ge=1, le=10)


class JourneyIn(BaseModel):
    """Create, or (PATCH) change any subset of, a journey plan."""

    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=1000)
    activities: str | None = Field(default=None, max_length=2000)
    worker_user_id: uuid.UUID | None = None
    supervisor_user_id: uuid.UUID | None = None
    monitor_user_id: uuid.UUID | None = None
    team: str | None = Field(default=None, max_length=120)
    worker_phone: str | None = Field(default=None, max_length=40)
    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    remoteness: RemotenessName = "UNKNOWN"
    return_journey: bool = False
    timezone: str = "Australia/Brisbane"
    departs_at: datetime
    arrives_at: datetime
    returns_at: datetime | None = None
    vehicle_id: uuid.UUID | None = None
    vehicle_description: str | None = Field(default=None, max_length=200)
    vehicle_registration: str | None = Field(default=None, max_length=20)
    occupants: int = Field(default=1, ge=1, le=60)
    comms_mobile: bool = True
    comms_uhf: bool = False
    comms_sat_phone: bool = False
    comms_sat_messenger: bool = False
    comms_notes: str | None = Field(default=None, max_length=1000)
    emergency_contacts: list[RsEmergencyContact] = Field(default_factory=list, max_length=10)
    checkin_interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    alternative_route: str | None = Field(default=None, max_length=2000)
    contingency_plan: str | None = Field(default=None, max_length=2000)
    weather_checked_at: datetime | None = None
    weather_source: str | None = Field(default=None, max_length=200)
    weather_warnings: str | None = Field(default=None, max_length=1000)


class JourneyPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = Field(default=None, min_length=1, max_length=1000)
    activities: str | None = Field(default=None, max_length=2000)
    supervisor_user_id: uuid.UUID | None = None
    monitor_user_id: uuid.UUID | None = None
    team: str | None = Field(default=None, max_length=120)
    worker_phone: str | None = Field(default=None, max_length=40)
    origin: str | None = Field(default=None, min_length=1, max_length=200)
    destination: str | None = Field(default=None, min_length=1, max_length=200)
    remoteness: RemotenessName | None = None
    return_journey: bool | None = None
    timezone: str | None = None
    departs_at: datetime | None = None
    arrives_at: datetime | None = None
    returns_at: datetime | None = None
    vehicle_id: uuid.UUID | None = None
    vehicle_description: str | None = Field(default=None, max_length=200)
    vehicle_registration: str | None = Field(default=None, max_length=20)
    occupants: int | None = Field(default=None, ge=1, le=60)
    comms_mobile: bool | None = None
    comms_uhf: bool | None = None
    comms_sat_phone: bool | None = None
    comms_sat_messenger: bool | None = None
    comms_notes: str | None = Field(default=None, max_length=1000)
    emergency_contacts: list[RsEmergencyContact] | None = Field(default=None, max_length=10)
    checkin_interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    alternative_route: str | None = Field(default=None, max_length=2000)
    contingency_plan: str | None = Field(default=None, max_length=2000)
    weather_checked_at: datetime | None = None
    weather_source: str | None = Field(default=None, max_length=200)
    weather_warnings: str | None = Field(default=None, max_length=1000)


class RouteLegIn(BaseModel):
    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    origin_lat: float | None = Field(default=None, ge=-45, le=-9)
    origin_lng: float | None = Field(default=None, ge=112, le=155)
    destination_lat: float | None = Field(default=None, ge=-45, le=-9)
    destination_lng: float | None = Field(default=None, ge=112, le=155)
    timezone: str | None = None
    departs_at: datetime
    arrives_at: datetime
    distance_km: float | None = Field(default=None, gt=0, lt=10000)
    road_surface: SurfaceName = "UNKNOWN"
    mobile_coverage: CoverageName = "UNKNOWN"
    crossings: int = Field(default=0, ge=0, le=500)
    closure_status: ClosureName = "NOT_CHECKED"
    closure_source: str | None = Field(default=None, max_length=200)
    closure_observed_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)


class RouteLegsIn(BaseModel):
    legs: list[RouteLegIn] = Field(max_length=30)


class RouteLegOut(BaseModel):
    id: uuid.UUID
    position: int
    origin: str
    destination: str
    origin_lat: float | None
    origin_lng: float | None
    destination_lat: float | None
    destination_lng: float | None
    timezone: str
    departs: LocalTimeOut
    arrives: LocalTimeOut
    distance_km: float | None
    road_surface: str
    mobile_coverage: str
    crossings: int
    closure_status: str
    closure_source: str | None
    closure_observed_at: datetime | None
    notes: str | None


class CheckinPlanIn(BaseModel):
    due_at: datetime
    location: str | None = Field(default=None, max_length=200)
    method: CheckinMethod = "PHONE_CALL"


class CheckinPlansIn(BaseModel):
    checkins: list[CheckinPlanIn] = Field(max_length=100)


class CheckinPlanOut(BaseModel):
    position: int
    due: LocalTimeOut
    location: str | None
    method: str


class RiskEvidenceOut(BaseModel):
    fact: str
    value: str
    source: str
    observed_at: str | None


class HazardFindingOut(BaseModel):
    hazard_key: str
    title: str
    description: str
    evidence: list[RiskEvidenceOut]
    likelihood: int
    consequence: int
    initial_score: int
    initial_rating: str
    controls: list[str]
    control_labels: list[str]
    residual_likelihood: int
    residual_score: int
    residual_rating: str
    responsible: str
    outstanding: list[str]


class StopConditionOut(BaseModel):
    key: str
    reason: str
    evidence: list[RiskEvidenceOut]


class JourneyAssessmentOut(BaseModel):
    id: uuid.UUID
    revision: int
    outcome: str
    pathway: str
    library_version: str
    policy_version: int
    facts: dict[str, Any]
    stop_conditions: list[StopConditionOut]
    findings: list[HazardFindingOut]
    created_at: datetime
    disclaimer: str
    data_sources: list[str]


class ControlCheckOut(BaseModel):
    key: str
    group: str
    label: str
    mandatory: bool
    required_by: list[str]
    status: str
    note: str | None
    completed_by_name: str | None
    completed_at: datetime | None
    exception_reason: str | None
    exception_by_name: str | None


class ControlCheckIn(BaseModel):
    status: ControlStatusName
    note: str | None = Field(default=None, max_length=1000)


class ControlExceptionIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


class RsPersonOut(BaseModel):
    user_id: uuid.UUID
    display_name: str


class JourneySummaryOut(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    status: str
    revision: int
    risk_outcome: str | None
    worker: RsPersonOut
    supervisor: RsPersonOut | None
    origin: str
    destination: str
    departs: LocalTimeOut
    arrives: LocalTimeOut
    archived: bool
    updated_at: datetime


class JourneyOut(JourneySummaryOut):
    purpose: str
    activities: str | None
    monitor: RsPersonOut | None
    team: str | None
    worker_phone: str | None
    remoteness: str
    return_journey: bool
    timezone: str
    returns: LocalTimeOut | None
    multi_day: bool
    vehicle_id: uuid.UUID | None
    vehicle_description: str | None
    vehicle_registration: str | None
    occupants: int
    comms_mobile: bool
    comms_uhf: bool
    comms_sat_phone: bool
    comms_sat_messenger: bool
    comms_notes: str | None
    emergency_contacts: list[RsEmergencyContact]
    checkin_interval_minutes: int | None
    alternative_route: str | None
    contingency_plan: str | None
    weather_checked_at: datetime | None
    weather_source: str | None
    weather_warnings: str | None
    approved_revision: int | None
    approved_outcome: str | None
    approved_by: RsPersonOut | None
    approved_at: datetime | None
    critical_alternative_process: str | None
    submitted_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    legs: list[RouteLegOut]
    checkins: list[CheckinPlanOut]
    allowed_actions: list[str]
    can_edit: bool
    blockers: list[str]


class JourneyTransitionIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class JourneyApproveIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    # Required to approve a CRITICAL journey: the documented alternative process followed.
    critical_alternative_process: str | None = Field(default=None, min_length=20, max_length=2000)


class JourneyEventOut(BaseModel):
    kind: str
    from_status: str | None
    to_status: str | None
    revision: int
    actor_name: str | None
    note: str | None
    details: dict[str, Any]
    occurred_at: datetime


class JourneyRevisionOut(BaseModel):
    revision: int
    changed_fields: list[str]
    created_at: datetime
    created_by_name: str | None


class RemoteSafeDashboardOut(BaseModel):
    scope: str
    by_status: dict[str, int]
    by_outcome: dict[str, int]
    awaiting_my_approval: int
    active: int
    critical_control_failures: int
    repeated_hazards: list[dict[str, Any]]
    completion_rate: float | None
    upcoming: list[JourneySummaryOut]
    monitoring_live: bool


class RiskPolicyOut(BaseModel):
    library_version: str
    policy_version: int
    overrides: dict[str, Any]
    effective: dict[str, Any]


class RiskPolicyIn(BaseModel):
    overrides: dict[str, Any]
