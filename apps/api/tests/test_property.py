"""PropertyReady (Milestone 11): SellReady (sale workflow, vault, disclosure, offers,
enquiries), RentReady (listing, applications, tenancies, inspections, maintenance), system
reminders, notifications and their delivery, and cross-sell offers."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.assessments.router import _cross_sell
from app.modules.notifications import delivery, reminders
from app.modules.projects.models import Reminder, ReminderStatus
from app.modules.rules.payload import validate_payload
from tests.harness import ApiHarness, User
from tests.test_document_files import PDF


def _org(user: User) -> str:
    return f"/v1/organisations/{user.personal_org_id}"


async def _project(user: User, vertical: str) -> str:
    r = await user.post(f"{_org(user)}/projects", json={"vertical": vertical, "title": "Home"})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _upload(user: User, project_id: str, name: str = "statement.pdf") -> str:
    r = await user.post(
        f"{_org(user)}/projects/{project_id}/documents",
        files={"file": (name, PDF, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _reminders(
    owner_sessions: async_sessionmaker[AsyncSession], prefix: str
) -> list[Reminder]:
    async with owner_sessions() as db:
        return list(
            (
                await db.execute(
                    select(Reminder)
                    .where(Reminder.source_key.startswith(prefix))
                    .order_by(Reminder.fires_at)
                )
            ).scalars()
        )


# --- Pure helpers ----------------------------------------------------------------------


def test_reminders_before_collapses_past_offsets_into_today() -> None:
    today = date(2027, 1, 10)
    planned = reminders.before("t:", date(2027, 1, 20), (60, 14, 1), "Lease ends", today=today)
    assert [(p.key, p.fires_on) for p in planned] == [
        ("t:2027-01-20:14", today),  # 60 and 14 days before have passed: one reminder today
        ("t:2027-01-20:1", date(2027, 1, 19)),
    ]
    assert reminders.before("t:", date(2027, 1, 9), (1,), "x", today=today) == []
    assert reminders.before("t:", None, (1,), "x", today=today) == []


def test_next_occurrence_steps_past_now() -> None:
    start = datetime(2027, 1, 31, 9, 0, tzinfo=reminders.BRISBANE)
    now = datetime(2027, 2, 1, tzinfo=UTC)
    assert delivery.next_occurrence(start, "MONTHLY", now).date() == date(2027, 2, 28)
    assert delivery.next_occurrence(start, "WEEKLY", now).date() == date(2027, 2, 7)
    assert delivery.next_occurrence(start, "YEARLY", now).date() == date(2028, 1, 31)


def test_cross_sell_payload_only_on_cross_sell_outcomes() -> None:
    assert validate_payload("CROSS_SELL", {"cross_sell": ["RENT"]}) == {"cross_sell": ["RENT"]}
    with pytest.raises(ValueError, match="only a cross_sell outcome"):
        validate_payload("INFO", {"cross_sell": ["RENT"]})
    with pytest.raises(ValueError):
        validate_payload("CROSS_SELL", {"cross_sell": ["BOATS"]})


def test_cross_sell_lists_each_product_once_from_matched_findings() -> None:
    class F:
        def __init__(self, outcome_type: str | None, payload: dict[str, Any] | None) -> None:
            self.id = uuid.uuid4()
            self.outcome_type = outcome_type
            self.payload = payload
            self.title = "Keep the tenancy in order until settlement"
            self.detail = None
            self.confidence = "LIKELY"

    findings: Any = [
        F("CROSS_SELL", {"cross_sell": ["RENT"]}),
        F("CROSS_SELL", {"cross_sell": ["RENT"]}),
        F(None, None),  # rule didn't match: no outcome
        F("INFO", None),
    ]
    offers = _cross_sell(findings)
    assert [o.vertical for o in offers] == ["RENT"]
    assert offers[0].finding_id == findings[0].id


def test_round_alerts_pick_closing_soon_and_newly_open_rounds() -> None:
    class R:
        def __init__(self, opens: date | None, closes: date | None) -> None:
            self.id = uuid.uuid4()
            self.status = "OPEN"
            self.opens_on = opens
            self.closes_on = closes
            self.title = "Round 1"

    class P:
        id = uuid.uuid4()
        title = "Growth Fund"

    today = date(2027, 3, 1)
    rounds: Any = [
        (R(None, today + timedelta(days=10)), P()),  # closing soon
        (R(today - timedelta(days=3), today + timedelta(days=90)), P()),  # newly open
        (R(today - timedelta(days=30), today + timedelta(days=90)), P()),  # neither
        (R(None, today - timedelta(days=1)), P()),  # closed
    ]
    kinds = [kind for _, _, kind, _ in delivery._round_alerts(rounds, today)]
    assert kinds == ["closing", "open"]


# --- SellReady -------------------------------------------------------------------------


@pytest.mark.integration
async def test_sale_workflow_disclosure_vault_and_offers(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await api.user()
    pid = await _project(user, "SELL")
    base = f"{_org(user)}/projects/{pid}/sale"

    r = await user.get(base)
    assert r.status_code == 200
    assert r.json()["id"] is None and r.json()["status"] == "PREPARING"
    assert r.json()["disclosure"]["state"] == "NOT_STARTED"

    r = await user.patch(base, json={"asking_price_cents": 85_000_000, "status": "LISTED"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "LISTED" and r.json()["listed_on"] is not None

    r = await user.patch(base, json={"status": "SETTLED"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "invalid_transition"
    r = await user.patch(base, json={"status": "UNDER_CONTRACT"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "disclosure_not_given"

    # Vault and disclosure.
    r = await user.post(f"{base}/disclosure", json={"given_on": "2026-10-01", "given_to": "A"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_disclosure_documents"
    doc = await _upload(user, pid)
    other_project = await _project(user, "SELL")
    elsewhere = await _upload(user, other_project)
    r = await user.post(
        f"{base}/documents", json={"uploaded_document_id": elsewhere, "category": "OTHER"}
    )
    assert r.status_code == 422
    r = await user.post(
        f"{base}/documents",
        json={
            "uploaded_document_id": doc,
            "category": "DISCLOSURE_STATEMENT",
            "in_disclosure": True,
        },
    )
    assert r.status_code == 201, r.text
    vault_id = r.json()["id"]
    assert r.json()["filename"] == "statement.pdf"
    assert (await user.get(base)).json()["disclosure"]["state"] == "PREPARING"

    r = await user.post(f"{base}/disclosure", json={"given_on": "2026-10-01", "given_to": "Buyer"})
    assert r.status_code == 200, r.text
    disclosure = r.json()["disclosure"]
    assert disclosure["state"] == "GIVEN" and disclosure["document_ids"] == [doc]
    r = await user.patch(f"{_org(user)}/sale-documents/{vault_id}", json={"in_disclosure": False})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "disclosure_already_given"

    # Offers: accepting one puts the listing under offer; only one can be accepted.
    r = await user.post(f"{base}/offers", json={"buyer_name": "B One", "amount_cents": 80_000_000})
    assert r.status_code == 201
    first = r.json()["id"]
    r = await user.post(f"{base}/offers", json={"buyer_name": "B Two", "amount_cents": 82_000_000})
    second = r.json()["id"]
    r = await user.patch(f"{_org(user)}/sale-offers/{first}", json={"status": "ACCEPTED"})
    assert r.status_code == 200, r.text
    assert (await user.get(base)).json()["status"] == "UNDER_OFFER"
    r = await user.patch(f"{_org(user)}/sale-offers/{second}", json={"status": "ACCEPTED"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "offer_already_accepted"
    r = await user.patch(f"{_org(user)}/sale-offers/{first}", json={"status": "WITHDRAWN"})
    assert (await user.get(base)).json()["status"] == "LISTED"
    await user.patch(f"{_org(user)}/sale-offers/{second}", json={"status": "ACCEPTED"})

    # Contract with a settlement date schedules reminders; settling cancels them.
    settles = (date.today() + timedelta(days=40)).isoformat()
    r = await user.patch(base, json={"status": "UNDER_CONTRACT", "settlement_on": settles})
    assert r.status_code == 200, r.text
    sale_id = r.json()["id"]
    scheduled = [
        x
        for x in await _reminders(owner_sessions, f"sale:{sale_id}:")
        if x.status == ReminderStatus.SCHEDULED
    ]
    assert len(scheduled) == 2
    assert all(x.link_path == f"/projects/{pid}/sale" for x in scheduled)
    r = await user.delete(f"{base}/disclosure")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sale_under_contract"
    r = await user.patch(base, json={"status": "SETTLED"})
    assert r.json()["status"] == "SETTLED"
    assert {x.status for x in await _reminders(owner_sessions, f"sale:{sale_id}:")} == {
        ReminderStatus.CANCELLED
    }

    # Enquiries.
    r = await user.post(f"{base}/enquiries", json={"name": "Curious", "message": "Pets?"})
    assert r.status_code == 201
    r = await user.patch(
        f"{_org(user)}/sale-enquiries/{r.json()['id']}", json={"status": "RESPONDED"}
    )
    assert r.json()["status"] == "RESPONDED"
    assert len((await user.get(f"{base}/enquiries")).json()) == 1


@pytest.mark.integration
async def test_sale_routes_are_tenant_and_vertical_scoped(api: ApiHarness) -> None:
    owner, stranger = await api.user(), await api.user()
    pid = await _project(owner, "SELL")
    await owner.patch(f"{_org(owner)}/projects/{pid}/sale", json={"asking_price_cents": 1})
    offer = await owner.post(
        f"{_org(owner)}/projects/{pid}/sale/offers", json={"buyer_name": "B", "amount_cents": 5}
    )
    assert (await stranger.get(f"{_org(stranger)}/projects/{pid}/sale")).status_code == 404
    assert (await stranger.get(f"{_org(owner)}/projects/{pid}/sale")).status_code == 404
    r = await stranger.patch(
        f"{_org(stranger)}/sale-offers/{offer.json()['id']}", json={"status": "ACCEPTED"}
    )
    assert r.status_code == 404
    rent = await _project(owner, "RENT")
    r = await owner.get(f"{_org(owner)}/projects/{rent}/sale")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_a_sale_project"


# --- RentReady -------------------------------------------------------------------------


@pytest.mark.integration
async def test_rental_listing_applications_and_tenancy(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await api.user()
    pid = await _project(user, "RENT")
    base = f"{_org(user)}/projects/{pid}/rental"

    r = await user.patch(base, json={"bedrooms": 2, "listing_status": "ADVERTISED"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "rent_required"
    r = await user.patch(
        base, json={"bedrooms": 2, "rent_cents": 60_000, "listing_status": "ADVERTISED"}
    )
    assert r.status_code == 200 and r.json()["listing_status"] == "ADVERTISED"

    r = await user.post(f"{base}/applications", json={"applicant_name": "Sam"})
    assert r.status_code == 201
    app_id = r.json()["id"]
    assert len(r.json()["missing"]) == 4
    assert "score" not in r.json() and "rank" not in r.json()
    r = await user.patch(
        f"{_org(user)}/tenant-applications/{app_id}",
        json={"checks": {"identity": True, "income": False}, "status": "SHORTLISTED"},
    )
    assert r.status_code == 200, r.text
    assert {c["key"]: c["provided"] for c in r.json()["checks"]}["identity"] is True
    assert len(r.json()["missing"]) == 3
    r = await user.patch(
        f"{_org(user)}/tenant-applications/{app_id}", json={"checks": {"score": True}}
    )
    assert r.status_code == 422

    start = date.today() + timedelta(days=7)
    tenancy = {
        "tenant_names": "Sam",
        "start_on": start.isoformat(),
        "end_on": (start + timedelta(days=365)).isoformat(),
        "rent_cents": 60_000,
        "bond_cents": 240_000,
        "next_rent_review_on": (start + timedelta(days=365)).isoformat(),
    }
    r = await user.post(f"{_org(user)}/tenant-applications/{app_id}/tenancy", json=tenancy)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["status"] == "UPCOMING" and r.json()["bond_to_lodge"] is True
    r = await user.post(f"{_org(user)}/tenant-applications/{app_id}/tenancy", json=tenancy)
    assert r.status_code == 409
    summary = (await user.get(base)).json()
    assert summary["listing_status"] == "LEASED" and summary["current_tenancy_id"] == tid
    apps = (await user.get(f"{base}/applications")).json()
    assert apps[0]["status"] == "APPROVED" and apps[0]["tenancy_id"] == tid

    keys = {x.source_key for x in await _reminders(owner_sessions, f"tenancy:{tid}:")}
    assert any(":end:" in k for k in keys if k)
    assert any(":rent_review:" in k for k in keys if k)
    assert any(":bond:" in k for k in keys if k)

    # Lodging the bond cancels its reminder; ending the tenancy cancels the rest.
    r = await user.patch(
        f"{_org(user)}/tenancies/{tid}",
        json={"bond_lodged_on": start.isoformat(), "bond_reference": "RTA123"},
    )
    assert r.json()["bond_to_lodge"] is False
    bond = await _reminders(owner_sessions, f"tenancy:{tid}:bond:")
    assert {x.status for x in bond} == {ReminderStatus.CANCELLED}
    r = await user.patch(
        f"{_org(user)}/tenancies/{tid}", json={"end_on": (start - timedelta(days=1)).isoformat()}
    )
    assert r.status_code == 422
    r = await user.patch(f"{_org(user)}/tenancies/{tid}", json={"ended_on": start.isoformat()})
    assert r.status_code == 200
    left = [
        x
        for x in await _reminders(owner_sessions, f"tenancy:{tid}:")
        if x.status == ReminderStatus.SCHEDULED
    ]
    assert left == []


@pytest.mark.integration
async def test_inspection_on_a_phone_and_maintenance(api: ApiHarness) -> None:
    user = await api.user()
    pid = await _project(user, "RENT")
    base = f"{_org(user)}/projects/{pid}/rental"
    await user.patch(base, json={"bedrooms": 2, "bathrooms": 1})
    when = (datetime.now(UTC) + timedelta(days=20)).isoformat()
    r = await user.post(f"{base}/inspections", json={"kind": "ENTRY", "scheduled_at": when})
    assert r.status_code == 201, r.text
    inspection = r.json()
    rooms = {i["room"] for i in inspection["items"]}
    assert {"Kitchen", "Bedroom 1", "Bedroom 2", "Bathroom"} <= rooms
    item = inspection["items"][0]

    photo = await _upload(user, pid, "wall.pdf")
    r = await user.patch(
        f"{_org(user)}/inspection-items/{item['id']}",
        json={"condition": "FAIR", "notes": "Scuff", "photo_document_ids": [photo]},
    )
    assert r.status_code == 200, r.text
    detail = (await user.get(f"{_org(user)}/inspections/{inspection['id']}")).json()
    assert detail["status"] == "IN_PROGRESS" and detail["items_checked"] == 1

    r = await user.post(
        f"{_org(user)}/inspections/{inspection['id']}/items",
        json={"room": "Kitchen", "item": "Dishwasher"},
    )
    assert r.status_code == 201
    r = await user.patch(
        f"{_org(user)}/inspections/{inspection['id']}", json={"status": "COMPLETED"}
    )
    assert r.json()["status"] == "COMPLETED" and r.json()["completed_at"]
    r = await user.patch(f"{_org(user)}/inspection-items/{item['id']}", json={"condition": "POOR"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "inspection_closed"

    r = await user.post(
        f"{base}/maintenance", json={"title": "Hot water out", "priority": "EMERGENCY"}
    )
    assert r.status_code == 201
    mid = r.json()["id"]
    await user.post(f"{base}/maintenance", json={"title": "Loose tap"})
    listed = (await user.get(f"{base}/maintenance")).json()
    assert listed[0]["priority"] == "EMERGENCY"
    r = await user.patch(f"{_org(user)}/maintenance-items/{mid}", json={"status": "DONE"})
    assert r.json()["resolved_on"] is not None
    assert (await user.get(base)).json()["open_maintenance"] == 1


# --- Notifications ---------------------------------------------------------------------


@pytest.mark.integration
async def test_due_reminders_become_notifications_and_emails(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await api.user()
    pid = await _project(user, "RENT")
    soon = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    once = await user.post(
        f"{_org(user)}/projects/{pid}/reminders", json={"title": "Water meter", "fires_at": soon}
    )
    weekly = await user.post(
        f"{_org(user)}/projects/{pid}/reminders",
        json={"title": "Weekly", "fires_at": soon, "recurrence": "WEEKLY", "channel": "IN_APP"},
    )
    ids = [once.json()["id"], weekly.json()["id"]]
    async with owner_sessions() as db:
        await db.execute(
            update(Reminder)
            .where(Reminder.id.in_(ids))
            .values(fires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    resources = api.app.state.resources
    settings = api.app.state.settings
    delivered = await delivery.deliver_due_reminders(
        resources.session_factory, resources.email, settings
    )
    assert delivered >= 2
    # Running again delivers nothing new for these.
    await delivery.deliver_due_reminders(resources.session_factory, resources.email, settings)

    r = await user.get(f"{_org(user)}/notifications")
    assert r.status_code == 200
    body = r.json()
    titles = sorted(n["title"] for n in body["items"])
    assert titles == ["Water meter", "Weekly"]
    assert body["unread"] == 2
    emails = api.emails_to(user.email, "notification")
    assert [e.subject for e in emails] == ["Water meter"]
    assert emails[0].links["open"].endswith(f"/projects/{pid}")

    async with owner_sessions() as db:
        rows = {
            str(x.id): x
            for x in (await db.execute(select(Reminder).where(Reminder.id.in_(ids)))).scalars()
        }
    assert rows[ids[0]].status == ReminderStatus.SENT
    assert rows[ids[1]].status == ReminderStatus.SCHEDULED
    assert rows[ids[1]].fires_at > datetime.now(UTC) + timedelta(days=6)

    first = body["items"][0]["id"]
    r = await user.post(f"{_org(user)}/notifications/{first}/read")
    assert r.json()["read_at"] is not None
    r = await user.post(f"{_org(user)}/notifications/read-all")
    assert r.json()["marked"] == 1
    assert (await user.get(f"{_org(user)}/notifications")).json()["unread"] == 0

    stranger = await api.user()
    r = await stranger.post(f"{_org(stranger)}/notifications/{first}/read")
    assert r.status_code == 404


@pytest.mark.integration
async def test_reminders_for_deleted_projects_are_cancelled_not_sent(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await api.user()
    pid = await _project(user, "SELL")
    soon = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    r = await user.post(
        f"{_org(user)}/projects/{pid}/reminders", json={"title": "Gone", "fires_at": soon}
    )
    rid = r.json()["id"]
    assert (await user.delete(f"{_org(user)}/projects/{pid}")).status_code == 204
    async with owner_sessions() as db:
        await db.execute(
            update(Reminder)
            .where(Reminder.id == rid)
            .values(fires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()
    resources = api.app.state.resources
    await delivery.deliver_due_reminders(
        resources.session_factory, resources.email, api.app.state.settings
    )
    async with owner_sessions() as db:
        reminder = await db.get(Reminder, uuid.UUID(rid))
        assert reminder is not None and reminder.status == ReminderStatus.CANCELLED
    assert api.emails_to(user.email, "notification") == []


@pytest.mark.integration
async def test_vessel_certificate_expiry_schedules_reminders(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await api.user()
    r = await user.post(
        f"{_org(user)}/vessels", json={"name": "Reef Runner", "vessel_type": "MOTOR"}
    )
    assert r.status_code == 201, r.text
    vessel = r.json()["id"]
    expires = (date.today() + timedelta(days=90)).isoformat()
    r = await user.post(
        f"{_org(user)}/vessels/{vessel}/certificates",
        json={"kind": "CERTIFICATE_OF_SURVEY", "expires_on": expires},
    )
    assert r.status_code == 201, r.text
    cert = r.json()["id"]
    scheduled = await _reminders(owner_sessions, f"vessel_certificate:{cert}:")
    assert len(scheduled) == 2
    assert scheduled[0].project_id is None
    assert "Reef Runner" in scheduled[0].title
    await user.delete(f"{_org(user)}/vessel-certificates/{cert}")
    assert {x.status for x in await _reminders(owner_sessions, f"vessel_certificate:{cert}:")} == {
        ReminderStatus.CANCELLED
    }
