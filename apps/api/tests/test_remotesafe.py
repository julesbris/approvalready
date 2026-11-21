"""RemoteSafe through the API: tenancy, roles, the approval workflow, controls, revisions,
time zones, exports and the PDF journey plan.

All journeys are SIMULATED test data (real town names, invented road conditions).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from tests.harness import ApiHarness, User, platform_user

pytestmark = pytest.mark.integration


@dataclass
class Org:
    id: str
    admin: User  # organisation administrator, also WHS administrator once enabled
    worker: User
    supervisor: User
    monitor: User
    worker2: User

    @property
    def base(self) -> str:
        return f"/v1/organisations/{self.id}/remotesafe"


async def _join(api: ApiHarness, admin: User, org_id: str, name: str) -> User:
    email = f"{name.lower()}-{uuid.uuid4().hex[:12]}@example.com"
    r = await admin.post(
        f"/v1/organisations/{org_id}/invitations", json={"email": email, "roles": ["CUSTOMER"]}
    )
    assert r.status_code == 201, r.text
    token = api.token_from(api.last_email(email, "org.invitation"), "accept")
    member = await api.user(name=name, email=email)
    r = await member.post("/v1/invitations/accept", json={"token": token})
    assert r.status_code == 200, r.text
    r = await member.put("/v1/auth/session/organisation", json={"organisation_id": org_id})
    assert r.status_code == 200, r.text
    return member


async def setup_org(api: ApiHarness, name: str = "Cape Works Pty Ltd") -> Org:
    admin = await api.user(name="Admin")
    r = await admin.post("/v1/organisations", json={"name": name, "kind": "BUSINESS"})
    assert r.status_code == 201, r.text
    org_id = str(r.json()["id"])
    r = await admin.post(f"/v1/organisations/{org_id}/remotesafe/enable", json={})
    assert r.status_code == 200, r.text
    assert r.json()["roles"] == ["WHS_ADMIN"]
    people = {n: await _join(api, admin, org_id, n) for n in ("Worker", "Super", "Monitor", "W2")}
    roles = {
        "Worker": ["WORKER"],
        "Super": ["SUPERVISOR"],
        "Monitor": ["MONITOR"],
        "W2": ["WORKER"],
    }
    for n, user in people.items():
        r = await admin.put(
            f"/v1/organisations/{org_id}/remotesafe/members/{user.id}/roles",
            json={"roles": roles[n]},
        )
        assert r.status_code == 204, r.text
    return Org(org_id, admin, people["Worker"], people["Super"], people["Monitor"], people["W2"])


def journey_body(org: Org, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Cooktown to Coen culvert inspection",
        "purpose": "Inspect culverts on the Peninsula Developmental Road (SIMULATED)",
        "supervisor_user_id": org.supervisor.id,
        "monitor_user_id": org.monitor.id,
        "worker_phone": "0400 000 000",
        "origin": "Cooktown",
        "destination": "Coen",
        "remoteness": "VERY_REMOTE",
        "timezone": "Australia/Brisbane",
        "departs_at": "2026-11-24T06:00",
        "arrives_at": "2026-11-24T13:00",
        "vehicle_description": "Toyota LandCruiser 79",
        "vehicle_registration": "SIM123",
        "occupants": 1,
        "comms_mobile": True,
        "emergency_contacts": [
            {"name": "Depot", "phone": "07 4000 0000", "escalation_order": 1},
            {"name": "Area manager", "phone": "0411 111 111", "escalation_order": 2},
        ],
        "checkin_interval_minutes": 120,
        "weather_checked_at": "2026-11-23T18:00",
        "weather_source": "Bureau of Meteorology warnings (SIMULATED)",
    }
    body.update(overrides)
    return body


LEGS: list[dict[str, Any]] = [
    {
        "origin": "Cooktown",
        "destination": "Lakeland",
        "departs_at": "2026-11-24T06:00",
        "arrives_at": "2026-11-24T07:30",
        "distance_km": 80,
        "road_surface": "SEALED",
        "mobile_coverage": "PATCHY",
        "crossings": 1,
        "closure_status": "NONE_KNOWN",
    },
    {
        "origin": "Lakeland",
        "destination": "Coen",
        "departs_at": "2026-11-24T07:45",
        "arrives_at": "2026-11-24T13:00",
        "distance_km": 305,
        "road_surface": "UNSEALED",
        "mobile_coverage": "NONE",
        "crossings": 8,
        "closure_status": "NONE_KNOWN",
    },
]
CHECKINS = {
    "checkins": [
        {"due_at": "2026-11-24T07:30", "location": "Lakeland", "method": "PHONE_CALL"},
        {"due_at": "2026-11-24T09:30", "location": "Laura", "method": "SATELLITE_MESSAGE"},
        {"due_at": "2026-11-24T11:30", "location": "Musgrave", "method": "SATELLITE_MESSAGE"},
        {"due_at": "2026-11-24T13:00", "location": "Coen", "method": "PHONE_CALL"},
    ]
}


async def planned(org: Org, user: User | None = None, **overrides: Any) -> dict[str, Any]:
    """A full plan by the worker: journey, legs and check-ins."""
    user = user or org.worker
    r = await user.post(f"{org.base}/journeys", json=journey_body(org, **overrides))
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    r = await user.put(f"{org.base}/journeys/{jid}/legs", json={"legs": LEGS})
    assert r.status_code == 200, r.text
    r = await user.put(f"{org.base}/journeys/{jid}/checkins", json=CHECKINS)
    assert r.status_code == 200, r.text
    return dict(r.json())


async def complete_controls(org: Org, jid: str, user: User, skip: tuple[str, ...] = ()) -> None:
    controls = (await user.get(f"{org.base}/journeys/{jid}/controls")).json()
    for c in controls:
        if c["key"] in skip:
            continue
        status = "DONE" if c["mandatory"] else "NOT_APPLICABLE"
        r = await user.put(
            f"{org.base}/journeys/{jid}/controls/{c['key']}", json={"status": status}
        )
        assert r.status_code == 200, r.text


# --- Switching on and roles ------------------------------------------------------------


async def test_only_business_admins_can_enable(api: ApiHarness) -> None:
    user = await api.user()
    r = await user.post(f"/v1/organisations/{user.personal_org_id}/remotesafe/enable", json={})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "remotesafe_business_only"
    org = await setup_org(api)
    r = await org.worker.get(org.base)
    assert r.json()["enabled"] is True
    assert r.json()["roles"] == ["WORKER"]
    assert r.json()["can_approve"] is False
    # Honest about what isn't built.
    features = {f["key"]: f for f in r.json()["features"]}
    assert features["checkin_monitoring"]["built"] is False
    assert any("does not replace emergency services" in x for x in r.json()["limitations"])
    r = await org.worker.put(
        f"{org.base}/members/{org.worker2.id}/roles", json={"roles": ["WHS_ADMIN"]}
    )
    assert r.status_code == 403


async def test_remotesafe_off_until_enabled(api: ApiHarness) -> None:
    admin = await api.user()
    r = await admin.post("/v1/organisations", json={"name": "Off Co", "kind": "BUSINESS"})
    org_id = r.json()["id"]
    r = await admin.get(f"/v1/organisations/{org_id}/remotesafe/journeys")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "remotesafe_off"


# --- Scenario 1: Cooktown to Coen with limited communications --------------------------


async def test_cooktown_to_coen_limited_comms_needs_satellite_and_whs_approval(
    api: ApiHarness,
) -> None:
    org = await setup_org(api)
    j = await planned(org)
    jid = j["id"]
    a = (await org.worker.get(f"{org.base}/journeys/{jid}/assessment")).json()
    assert a["outcome"] == "CRITICAL"
    assert [s["key"] for s in a["stop_conditions"]] == ["emergency_communications"]
    assert any("Not connected yet" in s for s in a["data_sources"])
    assert "not probabilities" in a["disclaimer"]
    finding = next(f for f in a["findings"] if f["hazard_key"] == "communications")
    assert finding["evidence"][0]["source"].startswith("Journey plan")
    assert finding["outstanding"]  # controls not yet confirmed

    r = await org.worker.post(f"{org.base}/journeys/{jid}/submit", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SUBMITTED"
    r = await org.supervisor.post(f"{org.base}/journeys/{jid}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "cannot_approve"

    # Adding a satellite messenger clears the stop condition: back to draft, new revision.
    r = await org.worker.patch(f"{org.base}/journeys/{jid}", json={"comms_sat_messenger": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DRAFT"
    assert r.json()["revision"] == 2
    assert r.json()["risk_outcome"] == "HIGH"
    r = await org.worker.post(f"{org.base}/journeys/{jid}/submit", json={})
    assert r.status_code == 200
    # High risk: the supervisor alone can't approve under the default policy.
    r = await org.supervisor.post(f"{org.base}/journeys/{jid}/approve", json={})
    assert r.status_code == 403
    assert "WHS administrator" in r.json()["detail"]["message"]
    r = await org.admin.post(f"{org.base}/journeys/{jid}/approve", json={"note": "OK with sat"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["approved_revision"] == 2
    assert body["approved_outcome"] == "HIGH"
    worker_view = (await org.worker.get(f"{org.base}/journeys/{jid}")).json()
    assert "commence" in worker_view["allowed_actions"]
    assert any(b.startswith("Not done:") for b in worker_view["blockers"])


# --- Scenario 2: confirmed road closure -------------------------------------------------


async def test_confirmed_road_closure_blocks_normal_approval(api: ApiHarness) -> None:
    org = await setup_org(api)
    j = await planned(org, comms_sat_phone=True)
    jid = j["id"]
    closed = [dict(LEGS[0]), {**LEGS[1], "closure_status": "CONFIRMED_CLOSED"}]
    r = await org.worker.put(f"{org.base}/journeys/{jid}/legs", json={"legs": closed})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "closure_source_needed"
    closed[1] |= {
        "closure_source": "QLDTraffic (SIMULATED)",
        "closure_observed_at": "2026-11-23T17:00:00+10:00",
    }
    r = await org.worker.put(f"{org.base}/journeys/{jid}/legs", json={"legs": closed})
    assert r.status_code == 200, r.text
    assert any("Unresolved road closure" in b for b in r.json()["blockers"])
    a = (await org.worker.get(f"{org.base}/journeys/{jid}/assessment")).json()
    stop = next(s for s in a["stop_conditions"] if s["key"] == "route_closure")
    assert "QLDTraffic (SIMULATED)" in stop["evidence"][0]["source"]
    assert stop["evidence"][0]["observed_at"].startswith("2026-11-23T07:00")

    assert (await org.worker.post(f"{org.base}/journeys/{jid}/submit", json={})).status_code == 200
    r = await org.admin.post(f"{org.base}/journeys/{jid}/approve", json={})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "alternative_process_required"
    process = "Council works crew escorts the worker through the closed section; police notified."
    r = await org.admin.post(
        f"{org.base}/journeys/{jid}/approve", json={"critical_alternative_process": process}
    )
    assert r.status_code == 200, r.text
    assert r.json()["approved_outcome"] == "CRITICAL"
    assert r.json()["critical_alternative_process"] == process


# --- Scenario 5: journey modified after approval ---------------------------------------


async def test_material_change_after_approval_needs_reapproval(api: ApiHarness) -> None:
    org = await setup_org(api)
    j = await planned(
        org, comms_sat_phone=True, occupants=2, remoteness="NOT_REMOTE", vehicle_description="Ute"
    )
    jid = j["id"]
    assert (await org.worker.post(f"{org.base}/journeys/{jid}/submit", json={})).status_code == 200
    r = await org.admin.post(f"{org.base}/journeys/{jid}/approve", json={})
    assert r.status_code == 200, r.text
    await complete_controls(org, jid, org.worker)

    # A wording change isn't material.
    r = await org.worker.patch(f"{org.base}/journeys/{jid}", json={"purpose": "Inspect drains"})
    assert r.json()["status"] == "APPROVED"
    assert r.json()["revision"] == 1

    # A later departure is.
    r = await org.worker.patch(
        f"{org.base}/journeys/{jid}",
        json={"departs_at": "2026-11-24T05:00", "arrives_at": "2026-11-24T13:00"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SUBMITTED"
    assert body["revision"] == 2
    assert body["approved_at"] is None and body["approved_revision"] is None
    controls = (await org.worker.get(f"{org.base}/journeys/{jid}/controls")).json()
    assert {c["status"] for c in controls} == {"PENDING"}
    events = [e["kind"] for e in (await org.worker.get(f"{org.base}/journeys/{jid}/events")).json()]
    assert "REASSESSMENT_REQUIRED" in events
    revisions = (await org.worker.get(f"{org.base}/journeys/{jid}/revisions")).json()
    assert [x["revision"] for x in revisions] == [1, 2]
    assert "departs_at" in revisions[1]["changed_fields"]


# --- Scenario 6: vehicle failing a mandatory pre-start check ---------------------------


async def test_failed_prestart_blocks_departure_until_authorised_exception(
    api: ApiHarness,
) -> None:
    org = await setup_org(api)
    j = await planned(org, comms_sat_phone=True)
    jid = j["id"]
    assert (await org.worker.post(f"{org.base}/journeys/{jid}/submit", json={})).status_code == 200
    assert (await org.admin.post(f"{org.base}/journeys/{jid}/approve", json={})).status_code == 200
    await complete_controls(org, jid, org.worker, skip=("vehicle_prestart",))
    r = await org.worker.put(
        f"{org.base}/journeys/{jid}/controls/vehicle_prestart",
        json={"status": "FAILED", "note": "Rear shock absorber leaking (SIMULATED)"},
    )
    assert r.status_code == 200
    r = await org.worker.post(f"{org.base}/journeys/{jid}/commence", json={})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "controls_incomplete"
    assert "Failed: Mechanical condition" in r.json()["detail"]["message"]
    # A mandatory control can't be waved through as not applicable.
    r = await org.worker.put(
        f"{org.base}/journeys/{jid}/controls/vehicle_prestart", json={"status": "NOT_APPLICABLE"}
    )
    assert r.status_code == 409
    # Only a WHS administrator can record an exception.
    reason = "Swapped to pool vehicle SIM456, pre-start done by the depot mechanic."
    r = await org.worker.post(
        f"{org.base}/journeys/{jid}/controls/vehicle_prestart/exception", json={"reason": reason}
    )
    assert r.status_code == 403
    r = await org.admin.post(
        f"{org.base}/journeys/{jid}/controls/vehicle_prestart/exception", json={"reason": reason}
    )
    assert r.status_code == 200, r.text
    c = next(x for x in r.json() if x["key"] == "vehicle_prestart")
    assert c["status"] == "EXCEPTION" and c["exception_by_name"] == "Admin"
    r = await org.worker.post(f"{org.base}/journeys/{jid}/commence", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ACTIVE"
    # Once underway the plan and controls are locked.
    r = await org.worker.patch(f"{org.base}/journeys/{jid}", json={"occupants": 2})
    assert r.status_code == 409
    r = await org.monitor.post(f"{org.base}/journeys/{jid}/complete", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "COMPLETED"
    r = await org.admin.post(f"{org.base}/journeys/{jid}/archive", json={})
    assert r.status_code == 200
    assert r.json()["archived"] is True
    kinds = [e["kind"] for e in (await org.admin.get(f"{org.base}/journeys/{jid}/events")).json()]
    for k in ("CREATED", "SUBMIT", "APPROVE", "CONTROL_FAILED", "CONTROL_EXCEPTION", "COMMENCE"):
        assert k in kinds


# --- Approvals and roles ---------------------------------------------------------------


async def test_no_self_approval_and_request_changes(api: ApiHarness) -> None:
    org = await setup_org(api)
    # The supervisor plans their own trip (they need a worker's supervisor too).
    r = await org.admin.put(
        f"{org.base}/members/{org.supervisor.id}/roles", json={"roles": ["SUPERVISOR", "WORKER"]}
    )
    assert r.status_code == 204
    r = await org.supervisor.post(
        f"{org.base}/journeys",
        json=journey_body(org, supervisor_user_id=org.supervisor.id),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_supervisor"

    j = await planned(org, comms_sat_phone=True, remoteness="NOT_REMOTE", occupants=2)
    jid = j["id"]
    assert (await org.worker.post(f"{org.base}/journeys/{jid}/approve", json={})).status_code in (
        403,
        409,
    )
    assert (await org.worker.post(f"{org.base}/journeys/{jid}/submit", json={})).status_code == 200
    assert (await org.worker.post(f"{org.base}/journeys/{jid}/approve", json={})).status_code in (
        403,
        409,
    )
    r = await org.supervisor.post(f"{org.base}/journeys/{jid}/request_changes", json={})
    assert r.status_code == 422
    r = await org.supervisor.post(
        f"{org.base}/journeys/{jid}/request_changes", json={"note": "Add a second person"}
    )
    assert r.json()["status"] == "CHANGES_REQUESTED"


async def test_worker_cannot_plan_for_someone_else(api: ApiHarness) -> None:
    org = await setup_org(api)
    r = await org.worker.post(
        f"{org.base}/journeys", json=journey_body(org, worker_user_id=org.worker2.id)
    )
    assert r.status_code == 403
    r = await org.supervisor.post(
        f"{org.base}/journeys", json=journey_body(org, worker_user_id=org.worker2.id)
    )
    assert r.status_code == 201


async def test_policy_needs_whs_admin_and_enterprise_tier(api: ApiHarness) -> None:
    org = await setup_org(api)
    change = {"overrides": {"hazards": {"working_alone": {"likelihood": 5}}}}
    assert (await org.worker.put(f"{org.base}/policy", json=change)).status_code == 403
    r = await org.admin.put(f"{org.base}/policy", json=change)
    assert r.status_code == 402
    staff = await platform_user(api)
    r = await staff.put(
        f"/v1/admin/remotesafe/organisations/{org.id}/tier", json={"tier": "ENTERPRISE"}
    )
    assert r.status_code == 204, r.text
    r = await org.admin.put(f"{org.base}/policy", json={"overrides": {"hazards": {"x": {}}}})
    assert r.status_code == 422
    r = await org.admin.put(f"{org.base}/policy", json=change)
    assert r.status_code == 200, r.text
    assert r.json()["policy_version"] == 2


# --- Tenancy and visibility -------------------------------------------------------------


async def test_journeys_are_isolated_between_organisations_and_people(api: ApiHarness) -> None:
    a = await setup_org(api, "Org A")
    b = await setup_org(api, "Org B")
    j = await planned(a)
    url = f"{a.base}/journeys/{j['id']}"
    # Another organisation's supervisor and administrator: no such organisation for them.
    assert (await b.supervisor.get(url)).status_code == 404
    assert (await b.admin.get(url)).status_code == 404
    # Org B's URL with Org A's journey id: not found either.
    assert (await b.admin.get(f"{b.base}/journeys/{j['id']}")).status_code == 404
    # Another worker in the same organisation can't see it.
    assert (await a.worker2.get(url)).status_code == 404
    assert (await a.worker2.get(f"{url}/plan.pdf")).status_code == 404
    assert (await a.worker2.get(f"{a.base}/journeys")).json() == []
    # The people on the journey and the WHS administrator can.
    for user in (a.worker, a.supervisor, a.monitor, a.admin):
        assert (await user.get(url)).status_code == 200
    # The monitor can see but not edit.
    assert (await a.monitor.patch(url, json={"occupants": 2})).status_code == 403
    # CSV export is for administrators.
    assert (await a.worker.get(f"{a.base}/journeys.csv")).status_code == 403
    r = await a.admin.get(f"{a.base}/journeys.csv")
    assert r.status_code == 200
    assert j["reference"] in r.text


async def test_removed_member_loses_remotesafe_roles(api: ApiHarness) -> None:
    org = await setup_org(api)
    j = await planned(org)
    members = (await org.admin.get(f"/v1/organisations/{org.id}/members")).json()
    sup = next(m for m in members if m["email"] == org.supervisor.email)
    r = await org.admin.delete(f"/v1/organisations/{org.id}/members/{sup['id']}")
    assert r.status_code == 204, r.text
    assert (await org.supervisor.get(f"{org.base}/journeys/{j['id']}")).status_code == 404


# --- Time zones, reports and exports ----------------------------------------------------


async def test_cross_border_legs_use_their_own_time_zone(api: ApiHarness) -> None:
    org = await setup_org(api)
    r = await org.worker.post(
        f"{org.base}/journeys",
        json=journey_body(
            org,
            origin="Thargomindah",
            destination="Broken Hill",
            departs_at="2026-11-24T06:00",
            arrives_at="2026-11-24T15:30",
            remoteness="REMOTE",
        ),
    )
    jid = r.json()["id"]
    legs = [
        {
            "origin": "Thargomindah",
            "destination": "Tibooburra",
            "departs_at": "2026-11-24T06:00",
            "arrives_at": "2026-11-24T10:00",
            "timezone": "Australia/Brisbane",
        },
        {
            # Broken Hill keeps South Australian time, on daylight saving in November.
            "origin": "Tibooburra",
            "destination": "Broken Hill",
            "departs_at": "2026-11-24T10:45",
            "arrives_at": "2026-11-24T15:30",
            "timezone": "Australia/Broken_Hill",
        },
    ]
    r = await org.worker.put(f"{org.base}/journeys/{jid}/legs", json={"legs": legs})
    assert r.status_code == 200, r.text
    out = r.json()["legs"]
    assert out[0]["departs"]["local"].endswith("AEST")
    assert out[1]["departs"]["local"].endswith("ACDT")
    assert out[1]["departs"]["utc"].startswith("2026-11-24T00:15")
    # A wall time skipped by daylight saving is refused.
    r = await org.worker.patch(
        f"{org.base}/journeys/{jid}",
        json={"timezone": "Australia/Sydney", "departs_at": "2026-10-04T02:30"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "nonexistent_local_time"


async def test_pdf_plan_and_json_export(api: ApiHarness) -> None:
    org = await setup_org(api)
    j = await planned(org, comms_sat_phone=True)
    r = await org.worker.get(f"{org.base}/journeys/{j['id']}/plan.pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    assert f"r{j['revision']}" in r.headers["content-disposition"]
    r = await org.worker.get(f"{org.base}/journeys/{j['id']}/export.json")
    assert r.status_code == 200
    data = r.json()
    assert data["journey"]["reference"] == j["reference"]
    assert data["assessment"]["outcome"] in ("HIGH", "CRITICAL")
    assert data["controls"] and data["events"]


async def test_dashboard_counts_and_honesty(api: ApiHarness) -> None:
    org = await setup_org(api)
    j = await planned(org, comms_sat_phone=True)
    await org.worker.post(f"{org.base}/journeys/{j['id']}/submit", json={})
    await planned(org, comms_sat_phone=True)
    d = (await org.admin.get(f"{org.base}/dashboard")).json()
    assert d["scope"] == "organisation"
    assert d["by_status"] == {"SUBMITTED": 1, "DRAFT": 1}
    assert d["awaiting_my_approval"] == 1
    assert d["monitoring_live"] is False
    assert d["repeated_hazards"]
    assert {h["journeys"] for h in d["repeated_hazards"]} == {2}
    d = (await org.supervisor.get(f"{org.base}/dashboard")).json()
    assert d["scope"] == "mine"
    assert d["awaiting_my_approval"] == 1


async def test_vehicle_register_fuel_range_feeds_assessment(api: ApiHarness) -> None:
    org = await setup_org(api)
    r = await org.worker.post(
        f"{org.base}/vehicles",
        json={"name": "Hilux", "registration": "SIM1", "vehicle_type": "Ute"},
    )
    assert r.status_code == 403
    r = await org.admin.post(
        f"{org.base}/vehicles",
        json={"name": "Hilux", "registration": "SIM1", "vehicle_type": "Ute", "fuel_range_km": 300},
    )
    assert r.status_code == 201, r.text
    j = await planned(org, comms_sat_phone=True, vehicle_id=r.json()["id"])
    a = (await org.worker.get(f"{org.base}/journeys/{j['id']}/assessment")).json()
    supplies = next(f for f in a["findings"] if f["hazard_key"] == "supplies")
    assert any(e["source"] == "Organisation vehicle register" for e in supplies["evidence"])
