"""Projects, status workflow, tasks, reminders, and tenant isolation through the API."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from tests.harness import ApiHarness, User, unique_email

pytestmark = pytest.mark.integration


def base(org_id: str) -> str:
    return f"/v1/organisations/{org_id}"


async def create_project(user: User, org_id: str, **body: object) -> dict[str, object]:
    payload = {"vertical": "PLANNING", "title": "Granny flat", **body}
    r = await user.post(f"{base(org_id)}/projects", json=payload)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def business_with_member(api: ApiHarness, roles: list[str]) -> tuple[User, User, str]:
    owner = await api.user(name="Owner")
    r = await owner.post("/v1/organisations", json={"name": "Acme", "kind": "BUSINESS"})
    org_id = r.json()["id"]
    email = unique_email("member")
    r = await owner.post(f"{base(org_id)}/invitations", json={"email": email, "roles": roles})
    assert r.status_code == 201, r.text
    token = api.token_from(api.last_email(email, "org.invitation"), "accept")
    member = await api.user(name="Member", email=email)
    assert (await member.post("/v1/invitations/accept", json={"token": token})).status_code == 200
    return owner, member, org_id


async def test_create_list_get_update(api: ApiHarness) -> None:
    user = await api.user()
    org = user.personal_org_id
    project = await create_project(user, org, description="Two bedrooms out the back")
    assert re.fullmatch(r"PLN-[0-9A-HJKMNP-TV-Z]{6}", str(project["reference_code"]))
    assert project["status"] == "DRAFT"
    assert project["allowed_status_changes"] == ["ARCHIVED", "IN_PROGRESS"]
    assert project["submissions"] == [] and project["open_tasks"] == 0

    other = await create_project(user, org, vertical="VESSEL", title="Charter boat")
    assert str(other["reference_code"]).startswith("VSL-")

    listed = (await user.get(f"{base(org)}/projects")).json()
    assert {p["id"] for p in listed} == {project["id"], other["id"]}
    vessels = (await user.get(f"{base(org)}/projects", params={"vertical": "VESSEL"})).json()
    assert [p["id"] for p in vessels] == [other["id"]]

    r = await user.patch(
        f"{base(org)}/projects/{project['id']}", json={"title": "Secondary dwelling"}
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Secondary dwelling"
    assert (await user.get(f"{base(org)}/projects/{project['id']}")).json()["title"] == (
        "Secondary dwelling"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"vertical": "MINING", "title": "x"},
        {"vertical": "PLANNING", "title": ""},
        {"vertical": "PLANNING", "title": "x" * 201},
        {"vertical": "PLANNING", "title": "x", "status": "COMPLETED"},
        {
            "vertical": "PLANNING",
            "title": "x",
            "organisation_id": "00000000-0000-0000-0000-000000000000",
        },
    ],
)
async def test_invalid_project_rejected(api: ApiHarness, body: dict[str, object]) -> None:
    user = await api.user()
    r = await user.post(f"{base(user.personal_org_id)}/projects", json=body)
    assert r.status_code == 422


async def test_status_workflow_is_enforced_and_recorded(api: ApiHarness) -> None:
    user = await api.user()
    org = user.personal_org_id
    project = await create_project(user, org)
    url = f"{base(org)}/projects/{project['id']}"

    r = await user.post(f"{url}/status", json={"status": "COMPLETED"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "invalid_status_change"
    # Assessment and review states are system-only.
    assert (await user.post(f"{url}/status", json={"status": "ASSESSED"})).status_code == 422

    for status in ("IN_PROGRESS", "COMPLETED", "ARCHIVED", "IN_PROGRESS"):
        r = await user.post(f"{url}/status", json={"status": status})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status

    events = (await user.get(f"{url}/status-events")).json()
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        (None, "DRAFT"),
        ("DRAFT", "IN_PROGRESS"),
        ("IN_PROGRESS", "COMPLETED"),
        ("COMPLETED", "ARCHIVED"),
        ("ARCHIVED", "IN_PROGRESS"),
    ]
    assert all(e["actor_id"] == user.id for e in events)

    audit = (await user.get(f"{base(org)}/audit-events")).json()
    actions = [e["action"] for e in audit]
    assert actions.count("project.status_changed") == 4
    assert "project.created" in actions


async def test_archived_projects_hidden_by_default_and_delete_is_soft(api: ApiHarness) -> None:
    user = await api.user()
    org = user.personal_org_id
    keep = await create_project(user, org, title="Keep")
    archived = await create_project(user, org, title="Old")
    gone = await create_project(user, org, title="Gone")
    await user.post(f"{base(org)}/projects/{archived['id']}/status", json={"status": "ARCHIVED"})

    titles = [p["title"] for p in (await user.get(f"{base(org)}/projects")).json()]
    assert set(titles) == {"Keep", "Gone"}
    everything = (
        await user.get(f"{base(org)}/projects", params={"include_archived": "true"})
    ).json()
    assert {p["title"] for p in everything} == {"Keep", "Old", "Gone"}

    assert (await user.delete(f"{base(org)}/projects/{gone['id']}")).status_code == 204
    assert (await user.get(f"{base(org)}/projects/{gone['id']}")).status_code == 404
    assert [p["id"] for p in (await user.get(f"{base(org)}/projects")).json()] == [keep["id"]]


async def test_tasks(api: ApiHarness) -> None:
    owner, member, org = await business_with_member(api, ["CUSTOMER"])
    outsider = await api.user(name="Outsider")
    project = await create_project(owner, org)
    url = f"{base(org)}/projects/{project['id']}/tasks"

    r = await owner.post(url, json={"title": "Book a surveyor", "due_on": "2026-11-01"})
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["status"] == "OPEN" and task["source"] == "USER"

    r = await owner.post(url, json={"title": "Call council", "assignee_user_id": member.id})
    assert r.status_code == 201
    r = await owner.post(url, json={"title": "x", "assignee_user_id": outsider.id})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "not_a_member"

    r = await member.patch(f"{url}/{task['id']}", json={"status": "DONE"})
    assert r.status_code == 200
    assert r.json()["completed_at"] is not None
    r = await member.patch(f"{url}/{task['id']}", json={"status": "OPEN"})
    assert r.json()["completed_at"] is None

    detail = (await owner.get(f"{base(org)}/projects/{project['id']}")).json()
    assert detail["open_tasks"] == 2
    assert (await owner.delete(f"{url}/{task['id']}")).status_code == 204
    assert [t["title"] for t in (await owner.get(url)).json()] == ["Call council"]


async def test_reminders(api: ApiHarness) -> None:
    owner, member, org = await business_with_member(api, ["CUSTOMER"])
    project = await create_project(owner, org)
    url = f"{base(org)}/projects/{project['id']}/reminders"
    soon = (datetime.now(UTC) + timedelta(days=7)).isoformat()

    r = await owner.post(url, json={"title": "Chase surveyor", "fires_at": soon})
    assert r.status_code == 201, r.text
    reminder = r.json()
    assert reminder["recipient_user_id"] == owner.id
    assert reminder["status"] == "SCHEDULED" and reminder["channel"] == "EMAIL"

    r = await owner.post(
        url,
        json={
            "title": "Yearly check",
            "fires_at": soon,
            "recurrence": "YEARLY",
            "recipient_user_id": member.id,
        },
    )
    assert r.status_code == 201

    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    r = await owner.post(url, json={"title": "Too late", "fires_at": past})
    assert r.json()["detail"]["code"] == "in_the_past"
    r = await owner.post(url, json={"title": "No zone", "fires_at": "2030-01-01T09:00:00"})
    assert r.json()["detail"]["code"] == "timezone_required"

    assert (await owner.delete(f"{url}/{reminder['id']}")).status_code == 204
    statuses = {r["title"]: r["status"] for r in (await owner.get(url)).json()}
    assert statuses == {"Chase surveyor": "CANCELLED", "Yearly check": "SCHEDULED"}


async def test_permissions_within_an_organisation(api: ApiHarness) -> None:
    """ORG_ADMIN alone (no CUSTOMER role) manages members but not projects."""
    owner, admin, org = await business_with_member(api, ["ORG_ADMIN"])
    project = await create_project(owner, org)
    assert (await admin.get(f"{base(org)}/projects")).status_code == 403
    r = await admin.post(f"{base(org)}/projects", json={"vertical": "PLANNING", "title": "x"})
    assert r.status_code == 403
    assert (await admin.get(f"{base(org)}/projects/{project['id']}")).status_code == 403


async def test_other_tenants_get_404_everywhere(api: ApiHarness) -> None:
    owner = await api.user(name="Owner")
    outsider = await api.user(name="Outsider")
    org = owner.personal_org_id
    project = await create_project(owner, org)
    pid = project["id"]
    task = (await owner.post(f"{base(org)}/projects/{pid}/tasks", json={"title": "t"})).json()
    submission = (await owner.post(f"{base(org)}/projects/{pid}/submissions", json={})).json()

    # Through the victim's organisation: no membership, so 404 before anything is read.
    for method, path, kwargs in [
        ("get", f"/projects/{pid}", {}),
        ("patch", f"/projects/{pid}", {"json": {"title": "x"}}),
        ("post", f"/projects/{pid}/status", {"json": {"status": "ARCHIVED"}}),
        ("delete", f"/projects/{pid}", {}),
        ("get", f"/projects/{pid}/tasks", {}),
        ("patch", f"/projects/{pid}/tasks/{task['id']}", {"json": {"status": "DONE"}}),
        ("get", f"/submissions/{submission['id']}", {}),
        ("put", f"/submissions/{submission['id']}/answers", {"json": {"answers": {}}}),
        ("get", "/projects", {}),
        ("get", "/properties", {}),
    ]:
        r = await getattr(outsider, method)(f"{base(org)}{path}", **kwargs)
        assert r.status_code == 404, (method, path, r.status_code)

    # Through the attacker's own organisation: the ids simply don't exist there.
    mine = base(outsider.personal_org_id)
    for method, path, kwargs in [
        ("get", f"/projects/{pid}", {}),
        ("patch", f"/projects/{pid}", {"json": {"title": "x"}}),
        ("get", f"/projects/{pid}/tasks", {}),
        ("get", f"/submissions/{submission['id']}", {}),
        ("post", f"/submissions/{submission['id']}/submit", {}),
    ]:
        r = await getattr(outsider, method)(f"{mine}{path}", **kwargs)
        assert r.status_code == 404, (method, path, r.status_code)

    assert (await owner.get(f"{base(org)}/projects/{pid}")).json()["title"] == "Granny flat"


async def test_unauthenticated_and_csrf(api: ApiHarness) -> None:
    user = await api.user()
    url = f"{base(user.personal_org_id)}/projects"
    assert (await api.client.get(url)).status_code == 401
    r = await user.client.post(url, json={"vertical": "PLANNING", "title": "x"})  # no CSRF header
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "csrf_failed"
