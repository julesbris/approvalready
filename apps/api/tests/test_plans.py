"""Project plans: starting one (free while it isn't on sale, or after a verified payment),
the timeline and parts built from the checklist, partners to call for each part, working
through the steps, and keeping the plan in step with the project.

Partners are platform-wide, so the lead tests' fixtures pause partners made before each test
and take prices off sale afterwards.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.billing.catalogue import load_bundled
from app.modules.partners.models import PartnerOrganisation
from app.modules.plans import checklist, service
from app.modules.plans.models import ProjectPlan
from app.modules.projects.models import Reminder
from tests.harness import ApiHarness, User, platform_user
from tests.regulatory_helpers import content, reference, rule_set, unique
from tests.test_assessments import FLOOR_OVER_80, org_url, run, scoped
from tests.test_assessments import submitted_project as submitted
from tests.test_billing import FakeStripe, deliver, event, set_price
from tests.test_documents import upload
from tests.test_leads import (  # noqa: F401 - fixtures used by name
    app,
    only_new_partners,
    partner,
    settings,
    stripe_api,
)
from tests.test_requirements import _publish

pytestmark = pytest.mark.integration


async def assessed(api: ApiHarness, **answers: Any) -> tuple[User, dict[str, Any], dict[str, Any]]:
    """A planning assessment naming an approval, a document, a task and two kinds of help."""
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    lot = unique("LOT")
    rs = await rule_set(staff, vertical="PLANNING", applies_when=scoped(lot))
    ref = await reference(staff)
    body = content(FLOOR_OVER_80, [ref["id"]])
    body["outcomes"][0] = {
        "on_result": "MATCH",
        "outcome_type": "APPROVAL_LIKELY",
        "title": "A development application is likely",
        "payload": {
            "approval": {
                "kind": "PLANNING_MATERIAL_CHANGE_OF_USE",
                "authority": "Test Council",
                "pathway": "Code assessment",
            },
            "evidence": [{"kind": "SITE_PLAN", "title": "Site plan", "detail": "Show parking."}],
            "referral_categories": ["town_planner", "building_certifier"],
            "task": "Book a pre-lodgement meeting",
        },
    }
    await _publish(admin, rs["id"], FLOOR_OVER_80, body)
    customer = await api.user(name="Casey Customer")
    project = await submitted(customer, lot, **answers)
    r = await run(customer, project["id"])
    assert r.status_code == 201, r.text
    return customer, project, r.json()


def plan_url(customer: User, project: dict[str, Any]) -> str:
    return f"{org_url(customer)}/projects/{project['id']}/plan"


def steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [st for s in plan["sections"] for st in s["steps"]]


def section(plan: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in plan["sections"] if s["key"] == key)


# --- Pure ------------------------------------------------------------------------------


def test_the_plan_product_is_in_the_catalogue_with_a_placeholder_price() -> None:
    product = next(p for p in load_bundled().products if p.key == service.PRODUCT_KEY)
    assert product.kind == "ONE_OFF" and product.suggested_price_cents == 14_900


def test_the_timeline_gives_each_part_a_window_and_documents_come_early() -> None:
    start = date(2026, 11, 2)
    sections = [
        checklist.Section(
            key="approval:A",
            kind=checklist.SectionKind.APPROVAL,
            title="A",
            steps=[checklist.Step(key=f"a{i}", kind="STEP", title="x") for i in range(4)],
        ),
        checklist.Section(
            key="approval:B",
            kind=checklist.SectionKind.APPROVAL,
            title="B",
            steps=[checklist.Step(key="b0", kind="STEP", title="x")],
        ),
        checklist.Section(
            key="documents",
            kind=checklist.SectionKind.DOCUMENTS,
            title="Docs",
            steps=[checklist.Step(key="d0", kind="DOCUMENT", title="x")],
        ),
    ]
    due = service.schedule(start, sections)
    assert [due[f"a{i}"] for i in range(4)] == [start + timedelta(days=d) for d in (4, 7, 11, 14)]
    assert due["b0"] == start + timedelta(days=28)
    assert due["d0"] == start + timedelta(days=14)


# --- Starting a plan -------------------------------------------------------------------


async def test_a_plan_starts_free_while_it_is_not_on_sale(api: ApiHarness) -> None:
    customer, project, _ = await assessed(api, **{"property.lga": "cairns"})
    url = plan_url(customer, project)

    r = await customer.get(url)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "NONE"
    assert r.json()["offer"]["on_sale"] is False and r.json()["offer"]["price_cents"] is None

    r = await customer.post(url)
    assert r.status_code == 201, r.text
    assert r.json()["checkout_url"] is None
    plan = r.json()["plan"]
    assert plan["status"] == "ACTIVE" and plan["complimentary"] is True
    keys = [s["key"] for s in plan["sections"]]
    assert keys[0] == "approval:PLANNING_MATERIAL_CHANGE_OF_USE"
    assert "council:cairns" in keys and "documents" in keys and "tasks" in keys
    approval = section(plan, "approval:PLANNING_MATERIAL_CHANGE_OF_USE")
    assert approval["authority"] == "Test Council"
    assert {h["key"] for h in approval["help"]} == {"town_planner", "building_certifier"}
    council = section(plan, "council:cairns")
    assert council["title"] == "Apply to Cairns Regional Council"
    assert council["contacts"] and council["sources"]
    assert [st["title"] for st in section(plan, "documents")["steps"]] == ["Site plan"]
    every = steps(plan)
    assert all(st["due_on"] and st["owner"] == "You" for st in every)
    assert all(st["status"] == "OPEN" for st in every)
    assert plan["progress"]["total"] == len(every) and plan["progress"]["done"] == 0
    assert plan["progress"]["finish_on"] == max(st["due_on"] for st in every)

    # One plan per project.
    r = await customer.post(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_exists"


async def test_a_plan_needs_an_assessment_and_stays_in_its_organisation(
    api: ApiHarness,
) -> None:
    customer = await api.user()
    org = org_url(customer)
    r = await customer.post(f"{org}/projects", json={"vertical": "BUSINESS", "title": "Cafe"})
    project = r.json()
    r = await customer.post(plan_url(customer, project))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "assessment_required"

    customer, project, _ = await assessed(api)
    assert (await customer.post(plan_url(customer, project))).status_code == 201
    outsider = await api.user()
    assert (await outsider.get(plan_url(customer, project))).status_code == 404
    assert (await outsider.post(f"{plan_url(customer, project)}/refresh")).status_code == 404


async def test_a_priced_plan_starts_only_once_payment_is_confirmed(
    api: ApiHarness,
    stripe_api: FakeStripe,  # noqa: F811 - the lead tests' fixture
) -> None:
    admin = await platform_user(api, "ADMIN")
    await set_price(admin, service.PRODUCT_KEY, 14_900)
    customer, project, _ = await assessed(api)
    url = plan_url(customer, project)
    assert (await customer.get(url)).json()["offer"]["price_cents"] == 14_900

    r = await customer.post(url)
    assert r.status_code == 201, r.text
    assert r.json()["plan"]["status"] == "PAYMENT_PENDING"
    assert r.json()["checkout_url"].startswith("https://checkout.stripe.com/")
    session = stripe_api.last("/v1/checkout/sessions")
    assert session["line_items[0][price_data][unit_amount]"] == "14900"
    assert session["success_url"].endswith(f"/projects/{project['id']}/plan?payment=done")
    # Clicking again doesn't make a second payment.
    again = await customer.post(url)
    assert again.status_code == 201 and again.json()["plan"]["id"] == r.json()["plan"]["id"]
    # Steps can't be worked on before it is paid for.
    assert (
        await customer.post(f"{url}/steps", json={"title": "Call the builder"})
    ).status_code == 404

    paid = event(
        "checkout.session.completed",
        {
            "id": "cs_paid",
            "object": "checkout.session",
            "mode": "payment",
            "payment_status": "paid",
            "payment_intent": "pi_plan",
            "customer": session["customer"],
            "metadata": {"payment_id": session["metadata[payment_id]"]},
        },
    )
    assert (await deliver(api, paid)).status_code == 200
    plan = (await customer.get(url)).json()
    assert plan["status"] == "ACTIVE" and plan["complimentary"] is False
    assert steps(plan)


async def test_a_plan_not_paid_for_can_be_cancelled(
    api: ApiHarness,
    stripe_api: FakeStripe,  # noqa: F811 - the lead tests' fixture
    owner_sessions: async_sessionmaker[AsyncSession],
) -> None:
    admin = await platform_user(api, "ADMIN")
    await set_price(admin, service.PRODUCT_KEY, 14_900)
    customer, project, _ = await assessed(api)
    url = plan_url(customer, project)
    plan_id = (await customer.post(url)).json()["plan"]["id"]

    r = await customer.post(f"{url}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "NONE"
    assert stripe_api.calls[-1][0].endswith("/expire")
    async with owner_sessions() as db:
        assert await db.get(ProjectPlan, uuid.UUID(plan_id)) is None
    r = await customer.get(f"{org_url(customer)}/billing")
    assert [p["status"] for p in r.json()["payments"]] == ["CANCELLED"]


# --- Working through it ----------------------------------------------------------------


async def test_working_through_the_steps(api: ApiHarness) -> None:
    customer, project, _ = await assessed(api)
    org = org_url(customer)
    url = plan_url(customer, project)
    plan = (await customer.post(url)).json()["plan"]

    # Ticking a step from a project task ticks the task.
    [task_step] = section(plan, "tasks")["steps"]
    r = await customer.patch(f"{url}/steps/{task_step['id']}", json={"status": "DONE"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DONE" and r.json()["completed_at"]
    tasks = (await customer.get(f"{org}/projects/{project['id']}/tasks")).json()
    assert [t["status"] for t in tasks if t["title"] == "Book a pre-lodgement meeting"] == ["DONE"]
    r = await customer.patch(f"{url}/steps/{task_step['id']}", json={"status": "OPEN"})
    assert r.json()["completed_at"] is None
    tasks = (await customer.get(f"{org}/projects/{project['id']}/tasks")).json()
    assert [t["status"] for t in tasks if t["title"] == "Book a pre-lodgement meeting"] == ["OPEN"]

    # Dates, owners, notes and files.
    [doc_step] = section(plan, "documents")["steps"]
    doc = (await upload(customer, project["id"], name="Site plan v3.pdf")).json()
    r = await customer.patch(
        f"{url}/steps/{doc_step['id']}",
        json={
            "due_on": "2027-01-15",
            "owner": "Sam (designer)",
            "note": "Asked for the parking layout",
            "document_ids": [doc["id"]],
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["due_on"], out["owner"], out["note"]) == (
        "2027-01-15",
        "Sam (designer)",
        "Asked for the parking layout",
    )
    assert out["documents"] == [{"id": doc["id"], "filename": "Site plan v3.pdf"}]
    r = await customer.patch(
        f"{url}/steps/{doc_step['id']}", json={"document_ids": [str(uuid.uuid4())]}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "document_unavailable"
    # Built steps keep their wording and can't be removed, only marked as not applying.
    assert (
        await customer.patch(f"{url}/steps/{doc_step['id']}", json={"title": "Other"})
    ).status_code == 409
    assert (await customer.delete(f"{url}/steps/{doc_step['id']}")).status_code == 409
    r = await customer.patch(f"{url}/steps/{doc_step['id']}", json={"status": "NOT_APPLICABLE"})
    assert r.json()["status"] == "NOT_APPLICABLE"

    # Their own steps.
    r = await customer.post(
        f"{url}/steps", json={"title": "Get three quotes", "due_on": "2027-02-01"}
    )
    assert r.status_code == 201, r.text
    own = r.json()
    assert own["editable"] and own["section_key"] == "own"
    r = await customer.patch(f"{url}/steps/{own['id']}", json={"title": "Get two quotes"})
    assert r.json()["title"] == "Get two quotes"
    r = await customer.post(
        f"{url}/steps", json={"title": "Ask council", "section_key": "approval:NOPE"}
    )
    assert r.status_code == 422

    plan = (await customer.get(url)).json()
    assert section(plan, "own")["steps"][0]["title"] == "Get two quotes"
    assert plan["progress"]["total"] == len(steps(plan)) - 1  # not counting the one not applying
    assert (await customer.delete(f"{url}/steps/{own['id']}")).status_code == 204

    # Refreshing adds nothing new and never reopens or drops a step.
    r = await customer.post(f"{url}/refresh")
    assert r.status_code == 200, r.text
    assert len(steps(r.json())) == len(steps(plan)) - 1


async def test_partners_to_call_and_follow_ups(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    staff = await platform_user(api, "STAFF")
    _, near = await partner(api, staff, name="Reef Planning")
    _, paused = await partner(api, staff, name="Quiet Planners")
    async with owner_sessions() as db:  # paused partners are never suggested
        row = await db.get(PartnerOrganisation, uuid.UUID(paused["id"]))
        assert row is not None
        row.paused = True
        await db.commit()

    customer, project, _ = await assessed(api)
    url = plan_url(customer, project)
    plan = (await customer.post(url)).json()["plan"]
    approval = section(plan, "approval:PLANNING_MATERIAL_CHANGE_OF_USE")
    planners = next(h for h in approval["help"] if h["key"] == "town_planner")
    assert [p["name"] for p in planners["partners"]] == ["Reef Planning"]
    suggested = planners["partners"][0]
    assert suggested["phone"] == "(07) 4000 0000"
    assert suggested["email"] == "hello@reefcertifiers.example.com.au"
    assert suggested["introduced"] is False and suggested["why"]
    assert planners["introduction_open"] is False

    r = await customer.post(
        f"{url}/follow-ups",
        json={"partner_id": near["id"], "section_key": approval["key"]},
    )
    assert r.status_code == 201, r.text
    follow = r.json()
    assert follow["kind"] == "FOLLOW_UP" and follow["title"] == "Call Reef Planning"
    assert follow["partner"]["phone"] == "(07) 4000 0000"
    assert follow["due_on"] == (service.today() + timedelta(days=3)).isoformat()
    assert follow["section_key"] == approval["key"] and follow["editable"]
    async with owner_sessions() as db:
        reminders = list(
            (
                await db.execute(
                    select(Reminder).where(Reminder.project_id == uuid.UUID(project["id"]))
                )
            ).scalars()
        )
    assert [r.title for r in reminders] == ["Follow up with Reef Planning"]
    assert reminders[0].link_path == f"/projects/{project['id']}/plan"

    r = await customer.post(f"{url}/follow-ups", json={"partner_id": str(uuid.uuid4())})
    assert r.status_code == 404
