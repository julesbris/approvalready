"""What's left on a project, keep-going nudges and the staff view of quiet projects."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.notifications.models import Notification
from app.modules.progress import nudges
from app.modules.progress.service import Item, ProgressStep, WhatsLeft
from app.modules.projects.models import Project
from tests.harness import ApiHarness, User, platform_user
from tests.test_assessments import org_url, run, submitted_project
from tests.test_document_files import PDF
from tests.test_documents import _assessed, upload

# --- Pure helpers ----------------------------------------------------------------------


def test_nudges_go_out_after_a_day_three_days_and_a_week_then_stop() -> None:
    hours = lambda n: timedelta(hours=n)  # noqa: E731
    assert nudges.due_step(hours(23)) is None
    assert nudges.due_step(hours(24)) == 1
    assert nudges.due_step(hours(71)) == 1
    assert nudges.due_step(hours(72)) == 3
    assert nudges.due_step(timedelta(days=7)) == 7
    assert nudges.due_step(timedelta(days=13)) == 7
    assert nudges.due_step(timedelta(days=14)) is None


def test_nudge_names_what_is_missing() -> None:
    qs = [f"Q{i}" for i in range(5)]
    left = WhatsLeft(
        [
            Item(ProgressStep.QUESTIONS, "Answer 7 more questions", 7, "/q", qs),
            Item(ProgressStep.DOCUMENTS, "Send 1 document", 1, "/d", ["Site plan"]),
        ]
    )
    title, body = nudges.message("Granny flat", left, 1)
    assert title == "Pick up where you left off: Granny flat"
    assert "- Answer 7 more questions: Q0; Q1; Q2; Q3; Q4 and 2 more" in body
    assert "- Send 1 document: Site plan" in body
    assert "last reminder" not in body
    assert nudges.message("Granny flat", left, 3)[0] == "2 steps left on Granny flat"
    title, body = nudges.message("x" * 300, left, 7)
    assert title.startswith("Still working on ") and len(title) < 120
    assert body.endswith("It stays saved for whenever you're ready.")
    many = WhatsLeft([Item(ProgressStep.TASKS, "Finish 5 tasks", 5, "/t", ["y" * 200] * 5)] * 3)
    assert len(nudges.message("Flat", many, 1)[1]) <= nudges.BODY_LIMIT


# --- What's left -------------------------------------------------------------------------


async def _left(user: User, project_id: str) -> dict[str, Any]:
    r = await user.get(f"{org_url(user)}/projects/{project_id}/whats-left")
    assert r.status_code == 200, r.text
    return r.json()


def _steps(left: dict[str, Any]) -> list[str]:
    return [i["step"] for i in left["items"]]


@pytest.mark.integration
async def test_whats_left_follows_the_project(api: ApiHarness) -> None:
    user = await api.user()
    org = org_url(user)
    r = await user.post(f"{org}/projects", json={"vertical": "PLANNING", "title": "Shed"})
    pid = r.json()["id"]
    left = await _left(user, pid)
    assert left["done"] is False
    assert left["items"] == [
        {
            "step": "START",
            "title": "Answer the questions about your project",
            "count": 1,
            "link_path": f"/projects/{pid}/questionnaire",
            "details": [],
        }
    ]

    r = await user.post(f"{org}/projects/{pid}/submissions", json={})
    submission = r.json()
    [item] = (await _left(user, pid))["items"]
    assert item["step"] == "QUESTIONS"
    assert item["count"] == len(submission["missing_required"]) > 0
    assert item["title"].startswith(f"Answer {item['count']} more question")
    labels = {q["key"]: q["label"] for s in submission["questionnaire"]["sections"]
              for q in s["questions"]}  # fmt: skip
    assert item["details"] == [labels[k] for k in submission["missing_required"][:5]]

    # Tasks and required checklist items are listed too.
    r = await user.post(f"{org}/projects/{pid}/tasks", json={"title": "Ring the council"})
    assert r.status_code == 201
    left = await _left(user, pid)
    assert _steps(left) == ["QUESTIONS", "TASKS"]
    assert left["items"][1]["details"] == ["Ring the council"]
    assert left["items"][1]["link_path"] == f"/projects/{pid}#tasks-title"

    # Submitted answers: run the assessment next.
    done = await submitted_project(user, "LOT-NONE")
    assert _steps(await _left(user, done["id"])) == ["RESULTS"]
    assert (await run(user, done["id"])).status_code == 201
    assert await _left(user, done["id"]) == {"done": True, "items": []}

    # A completed project has nothing left, whatever is open.
    r = await user.post(f"{org}/projects/{pid}/status", json={"status": "IN_PROGRESS"})
    r = await user.post(f"{org}/projects/{pid}/status", json={"status": "ARCHIVED"})
    assert r.status_code == 200, r.text
    assert (await _left(user, pid))["done"] is True

    outsider = await api.user()
    r = await outsider.get(f"{org_url(outsider)}/projects/{pid}/whats-left")
    assert r.status_code == 404


@pytest.mark.integration
async def test_documents_still_to_send_are_listed_until_provided(api: ApiHarness) -> None:
    customer, project, assessment = await _assessed(api)
    [requirement] = assessment["evidence_requirements"]
    # The finding also suggested tasks; documents come first.
    item = (await _left(customer, project["id"]))["items"][0]
    assert item["step"] == "DOCUMENTS"
    assert item["title"] == "Send 1 document"
    assert item["details"] == [requirement["title"]]
    assert item["link_path"] == (
        f"/projects/{project['id']}/assessments/{assessment['id']}#evidence-title"
    )
    doc = (await upload(customer, project["id"], PDF)).json()
    r = await customer.post(
        f"{org_url(customer)}/evidence",
        json={"evidence_requirement_id": requirement["id"], "uploaded_document_id": doc["id"]},
    )
    assert r.status_code == 201, r.text
    assert "DOCUMENTS" not in _steps(await _left(customer, project["id"]))


# --- Nudges ------------------------------------------------------------------------------


async def _nudges(
    owner_sessions: async_sessionmaker[AsyncSession], project_id: str
) -> list[Notification]:
    async with owner_sessions() as db:
        return list(
            (
                await db.execute(
                    select(Notification)
                    .where(
                        Notification.project_id == uuid.UUID(project_id),
                        Notification.kind == "KEEP_GOING",
                    )
                    .order_by(Notification.created_at)
                )
            ).scalars()
        )


async def _send(api: ApiHarness, now: datetime) -> int:
    resources = api.app.state.resources
    return await nudges.send_nudges(
        resources.session_factory, resources.email, api.app.state.settings, now=now, limit=10
    )


@pytest.mark.integration
async def test_quiet_projects_get_three_nudges_then_stop(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await api.user()
    org = org_url(user)
    r = await user.post(f"{org}/projects", json={"vertical": "PLANNING", "title": "Deck"})
    pid = r.json()["id"]
    await user.post(f"{org}/projects/{pid}/submissions", json={})
    start = datetime.now(UTC)

    await _send(api, start + timedelta(hours=12))
    assert await _nudges(owner_sessions, pid) == []

    await _send(api, start + timedelta(days=1, minutes=5))
    [first] = await _nudges(owner_sessions, pid)
    assert first.title == "Pick up where you left off: Deck"
    assert first.link_path == f"/projects/{pid}/questionnaire"
    assert first.body and "more question" in first.body
    [email] = api.emails_to(user.email, "notification")
    assert email.subject == first.title
    assert email.links["open"].endswith(f"/projects/{pid}/questionnaire")
    assert "List-Unsubscribe" in email.headers
    assert ".PROGRESS." in email.links["unsubscribe"]

    # Running again the same day, or the next, repeats nothing.
    await _send(api, start + timedelta(days=1, hours=3))
    await _send(api, start + timedelta(days=2, minutes=5))
    assert len(await _nudges(owner_sessions, pid)) == 1

    await _send(api, start + timedelta(days=3, minutes=5))
    await _send(api, start + timedelta(days=7, minutes=5))
    await _send(api, start + timedelta(days=10))
    await _send(api, start + timedelta(days=15))
    titles = [n.title for n in await _nudges(owner_sessions, pid)]
    assert titles == [
        "Pick up where you left off: Deck",
        "1 step left on Deck",
        "Still working on Deck? Here's what's left",
    ]
    assert len(api.emails_to(user.email, "notification")) == 3

    # Picking the project up again starts a new series once they go quiet again.
    r = await user.post(f"{org}/projects/{pid}/tasks", json={"title": "Measure the yard"})
    assert r.status_code == 201
    await _send(api, datetime.now(UTC) + timedelta(hours=12))
    assert len(await _nudges(owner_sessions, pid)) == 3
    await _send(api, datetime.now(UTC) + timedelta(days=1, minutes=5))
    latest = (await _nudges(owner_sessions, pid))[-1]
    assert latest.title == "Pick up where you left off: Deck"
    assert latest.body and "Measure the yard" in latest.body


@pytest.mark.integration
async def test_no_nudges_when_turned_off_finished_or_in_review(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    later = lambda: datetime.now(UTC) + timedelta(days=1, minutes=5)  # noqa: E731
    quiet = await api.user()
    r = await quiet.post(f"{org_url(quiet)}/projects", json={"vertical": "RENT", "title": "Unit"})
    unit = r.json()["id"]
    r = await quiet.put(
        "/v1/auth/notification-preferences",
        json={"items": [{"category": "PROGRESS", "channel": "OFF"}]},
    )
    assert r.status_code == 200, r.text
    await _send(api, later())
    assert await _nudges(owner_sessions, unit) == []

    # In the app only: the nudge is there, no email.
    await quiet.put(
        "/v1/auth/notification-preferences",
        json={"items": [{"category": "PROGRESS", "channel": "IN_APP"}]},
    )
    await _send(api, later())
    assert len(await _nudges(owner_sessions, unit)) == 1
    assert api.emails_to(quiet.email, "notification") == []

    finished = await api.user()
    project = await submitted_project(finished, "LOT-NONE")
    assert (await run(finished, project["id"])).status_code == 201
    await _send(api, later())
    assert await _nudges(owner_sessions, project["id"]) == []


@pytest.mark.integration
async def test_one_nudge_email_a_day_per_person(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await api.user()
    ids = []
    for title in ("First", "Second"):
        r = await user.post(f"{org_url(user)}/projects", json={"vertical": "GRANT", "title": title})
        ids.append(r.json()["id"])
    now = datetime.now(UTC) + timedelta(days=1, minutes=5)
    assert await _send(api, now) >= 1
    counts = [len(await _nudges(owner_sessions, pid)) for pid in ids]
    assert sorted(counts) == [0, 1]
    # The most recently active project goes first; the other follows the next day.
    assert counts == [0, 1]
    await _send(api, now + timedelta(days=1))
    assert [len(await _nudges(owner_sessions, pid)) for pid in ids] == [1, 1]


# --- Staff view --------------------------------------------------------------------------


@pytest.mark.integration
async def test_staff_see_who_is_stuck_where(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    customer = await api.user(name="Quiet Customer")
    r = await customer.post(
        f"{org_url(customer)}/projects", json={"vertical": "PLANNING", "title": "Pool"}
    )
    pid = r.json()["id"]
    staff = await platform_user(api, "STAFF")
    r = await staff.get("/v1/admin/progress/quiet", params={"days": 1})
    assert r.status_code == 200, r.text
    assert pid not in {row["project_id"] for row in r.json()}

    async with owner_sessions() as db:
        await db.execute(
            update(Project)
            .where(Project.id == uuid.UUID(pid))
            .values(updated_at=datetime.now(UTC) - timedelta(days=2))
        )
        await db.commit()
    r = await staff.get("/v1/admin/progress/quiet", params={"days": 1})
    [row] = [x for x in r.json() if x["project_id"] == pid]
    assert row["stage"] == "START"
    assert row["reference_code"].startswith("PLN-")
    assert (row["owner_email"], row["owner_name"]) == (customer.email, "Quiet Customer")
    assert (row["nudges_sent"], row["last_nudged_at"]) == (0, None)
    assert "title" not in row
    r = await staff.get("/v1/admin/progress/quiet", params={"days": 3})
    assert pid not in {x["project_id"] for x in r.json()}

    await _send(api, datetime.now(UTC))
    r = await staff.get("/v1/admin/progress/quiet", params={"days": 1})
    [row] = [x for x in r.json() if x["project_id"] == pid]
    assert row["nudges_sent"] == 1 and row["last_nudged_at"] is not None

    assert (await customer.get("/v1/admin/progress/quiet")).status_code == 403
    assert (await staff.get("/v1/admin/progress/quiet", params={"days": 0})).status_code == 422
