"""Staff notes, logged calls and emailing a person from Admin > Accounts."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.accounts.models import StaffNote
from app.modules.audit.models import AuditEvent
from tests.harness import PASSWORD, ApiHarness, platform_user

pytestmark = pytest.mark.integration


async def test_any_staff_member_can_add_notes_and_log_calls(api: ApiHarness) -> None:
    customer = await api.user(name="Noted Person")
    staff = await platform_user(api, role="STAFF", name="Sam Support")
    url = f"/v1/admin/accounts/{customer.id}/notes"

    assert (await customer.post(url, json={"body": "hi"})).status_code == 403
    r = await staff.post(url, json={"body": "   "})
    assert r.status_code == 422, r.text

    r = await staff.post(
        url, json={"body": "Wants a call after 3pm", "project_reference": " PLN-ABC123 "}
    )
    assert r.status_code == 201, r.text
    assert r.json()["message"] == "Note saved."
    r = await staff.post(url, json={"kind": "CALL", "body": "Talked through the DA steps"})
    assert r.status_code == 201, r.text
    account = r.json()["account"]
    assert account["can_contact"] is True
    call, note = account["notes"]
    assert (call["kind"], call["body"], call["author_name"]) == (
        "CALL",
        "Talked through the DA steps",
        "Sam Support",
    )
    assert note["project_reference"] == "PLN-ABC123" and note["can_delete"] is True

    # The audit log says a note was written, not what it said.
    events = account["events"]
    added = next(e for e in events if e["action"] == "admin.account.note_added")
    assert added["by"] == "other" and added["details"]["project"] == "PLN-ABC123"
    assert "Wants a call" not in str(events)
    assert any(e["action"] == "admin.account.call_logged" for e in events)

    # Staff don't write notes on their own account.
    r = await staff.post(f"/v1/admin/accounts/{staff.id}/notes", json={"body": "me"})
    assert r.status_code == 403


async def test_deleting_is_for_the_author_or_an_administrator(api: ApiHarness) -> None:
    customer = await api.user()
    writer = await platform_user(api, role="STAFF", name="Writer")
    other = await platform_user(api, role="STAFF", name="Other")
    admin = await platform_user(api, role="ADMIN", name="Admin")
    url = f"/v1/admin/accounts/{customer.id}/notes"
    first = (await writer.post(url, json={"body": "one"})).json()["account"]["notes"][0]
    second = (await writer.post(url, json={"body": "two"})).json()["account"]["notes"][0]

    seen = (await other.get(f"/v1/admin/accounts/{customer.id}")).json()["notes"]
    assert [n["can_delete"] for n in seen] == [False, False]
    assert (await other.delete(f"{url}/{first['id']}")).status_code == 403

    r = await writer.delete(f"{url}/{first['id']}")
    assert r.status_code == 200, r.text
    assert [n["body"] for n in r.json()["account"]["notes"]] == ["two"]
    r = await admin.delete(f"{url}/{second['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["account"]["notes"] == []
    assert (await admin.delete(f"{url}/{second['id']}")).status_code == 404
    # A note can only be deleted through the account it belongs to.
    third = (await writer.post(url, json={"body": "three"})).json()["account"]["notes"][0]
    assert (
        await admin.delete(f"/v1/admin/accounts/{writer.id}/notes/{third['id']}")
    ).status_code == 404


async def test_emailing_a_person_keeps_a_copy(api: ApiHarness) -> None:
    customer = await api.user(name="Robin")
    staff = await platform_user(api, role="STAFF", name="Sam Support")
    url = f"/v1/admin/accounts/{customer.id}/email"

    r = await staff.post(url, json={"subject": " ", "message": "x"})
    assert r.status_code == 422, r.text
    r = await staff.post(
        url,
        json={
            "subject": "Your pool approval",
            "message": "I saw you stopped at the site plan.\nHappy to help.",
            "project_reference": "PLN-POOL01",
        },
    )
    assert r.status_code == 200, r.text
    assert customer.email in r.json()["message"]
    [email] = api.emails_to(customer.email, "support.message")
    assert email.subject == "Your pool approval"
    assert email.text.startswith("Hi Robin,\n\nAbout your project PLN-POOL01.")
    assert "Happy to help.\n\nSam\nApprovalReady" in email.text

    [copy] = r.json()["account"]["notes"]
    assert (copy["kind"], copy["subject"]) == ("EMAIL", "Your pool approval")
    assert copy["project_reference"] == "PLN-POOL01"
    assert any(e["action"] == "admin.account.emailed" for e in r.json()["account"]["events"])
    assert (await customer.post(url, json={"subject": "a", "message": "b"})).status_code == 403


async def test_closing_an_account_deletes_its_notes(api: ApiHarness) -> None:
    customer = await api.user()
    admin = await platform_user(api)
    url = f"/v1/admin/accounts/{customer.id}"
    assert (await admin.post(f"{url}/notes", json={"body": "remember"})).status_code == 201
    r = await customer.post("/v1/auth/account/close", json={"password": PASSWORD})
    assert r.status_code == 204, r.text

    detail = (await admin.get(url)).json()
    assert detail["notes"] == [] and detail["can_contact"] is False
    assert (await admin.post(f"{url}/notes", json={"body": "again"})).status_code == 409
    r = await admin.post(f"{url}/email", json={"subject": "a", "message": "b"})
    assert r.status_code == 409
    async with api.app.state.resources.session_factory() as db:
        left = (await db.execute(select(StaffNote).where(StaffNote.user_id == customer.id))).all()
        audited = (
            await db.execute(
                select(AuditEvent.id).where(
                    AuditEvent.action == "admin.account.note_added",
                    AuditEvent.target_id == customer.id,
                )
            )
        ).all()
    assert left == [] and len(audited) == 1
