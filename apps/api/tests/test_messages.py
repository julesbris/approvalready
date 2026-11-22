"""Messages (Milestone 26): the customer and a partner who accepted their referral write to
each other about the job.

Reuses the lead engine's fixtures (``tests/test_leads.py``) and the quote helpers.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.leads import messages
from app.modules.leads.models import LeadMessage
from tests.harness import ApiHarness, User, platform_user
from tests.test_assessments import org_url
from tests.test_leads import (  # noqa: F401 - fixtures used by name
    app,
    assessed,
    consent,
    leads_url,
    offers_for,
    only_new_partners,
    partner,
    settings,
    stripe_api,
)
from tests.test_quotes import claimed, quotes_url, send

pytestmark = pytest.mark.integration


def conversations_url(customer: User, project: dict[str, Any]) -> str:
    return f"{org_url(customer)}/projects/{project['id']}/conversations"


async def write(user: User, url: str, body: str) -> dict[str, Any]:
    r = await user.post(url, json={"body": body})
    assert r.status_code == 201, r.text
    return dict(r.json())


async def test_message_journey(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    customer, project, [(first, p1, m1), (second, p2, m2)] = await claimed(
        api, ["Reef Planning", "Tableland Planning"]
    )
    partner_url = f"{leads_url(p1)}/{m1}/messages"
    customer_url = conversations_url(customer, project)

    # 1. The customer sees one empty conversation per partner who accepted.
    r = await customer.get(customer_url)
    assert r.status_code == 200, r.text
    listed = r.json()
    assert sorted(c["partner_name"] for c in listed) == ["Reef Planning", "Tableland Planning"]
    assert all(c["messages"] == [] and c["can_send"] and c["unread"] == 0 for c in listed)

    # 2. The partner writes; the customer is told once, with the start of the message.
    convo = await write(first, partner_url, "Hi, could you send the site plan?")
    [msg] = convo["messages"]
    assert (msg["sender"], msg["from_you"], msg["read_at"]) == ("PARTNER", True, None)
    await write(first, partner_url, "Also the lot number, please.")
    mails = [m for m in api.emails_to(customer.email, "notification") if "New message" in m.subject]
    assert len(mails) == 1 and mails[0].subject.startswith("New message from Reef Planning")
    assert "could you send the site plan" in mails[0].text

    # 3. The customer sees two unread messages, opens the conversation and replies.
    reef = next(c for c in (await customer.get(customer_url)).json() if c["match_id"] == m1)
    assert reef["unread"] == 2
    assert [(m["from_you"], m["body"]) for m in reef["messages"]] == [
        (False, "Hi, could you send the site plan?"),
        (False, "Also the lot number, please."),
    ]
    r = await customer.post(f"{customer_url}/{m1}/read")
    assert r.status_code == 200 and r.json()["unread"] == 0
    reply = await write(customer, f"{customer_url}/{m1}/messages", "  Lot 12 on RP123456.  ")
    assert reply["messages"][-1]["body"] == "Lot 12 on RP123456."

    # 4. The partner sees it as unread on the referral and in the conversation.
    offer = (await first.get(f"{leads_url(p1)}/{m1}")).json()
    assert offer["unread_messages"] == 1
    got = (await first.get(partner_url)).json()
    assert [m["from_you"] for m in got["messages"]] == [True, True, False]
    assert got["messages"][0]["read_at"] is not None  # the customer opened it
    assert any(
        m.subject.startswith("New message from a customer") for m in api.emails_to(first.email)
    )
    r = await first.post(f"{partner_url}/read")
    assert r.status_code == 200 and r.json()["unread"] == 0

    # 5. The other partner's conversation is separate.
    got = (await second.get(f"{leads_url(p2)}/{m2}/messages")).json()
    assert got["messages"] == []

    # 6. Messages never change; the text stays out of the audit log.
    async with owner_sessions() as db:
        row_id = (
            (
                await db.execute(
                    select(LeadMessage.id).where(LeadMessage.lead_match_id == uuid.UUID(m1))
                )
            )
            .scalars()
            .first()
        )
        assert row_id is not None
        with pytest.raises(DBAPIError, match="never changes"):
            await db.execute(
                text("UPDATE lead_message SET body = 'edited' WHERE id = :id"), {"id": row_id}
            )
        await db.rollback()
        with pytest.raises(DBAPIError, match="marked read once"):
            await db.execute(
                text("UPDATE lead_message SET read_at = now() + interval '1 day' WHERE id = :id"),
                {"id": row_id},
            )
        await db.rollback()
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            await db.execute(text("DELETE FROM lead_message WHERE id = :id"), {"id": row_id})
        await db.rollback()
        details = list(
            (
                await db.execute(
                    text(
                        "SELECT details::text FROM audit_event WHERE action = 'message.sent' "
                        "AND target_id = :id"
                    ),
                    {"id": str(row_id)},
                )
            ).scalars()
        )
        assert len(details) == 1 and "site plan" not in details[0]


async def test_message_rules(api: ApiHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    staff = await platform_user(api, "STAFF")
    late_user, late = await partner(api, staff, name="Unclaimed Planning")
    customer, project, [(user, p, match_id)] = await claimed(api, ["Rules Planning"])
    partner_url = f"{leads_url(p)}/{match_id}/messages"
    customer_url = conversations_url(customer, project)

    # Only after accepting the referral, and only your own.
    [unclaimed] = await offers_for(late_user, late)
    r = await late_user.post(
        f"{leads_url(late)}/{unclaimed['lead']['match_id']}/messages", json={"body": "Hi"}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_claimed"
    r = await late_user.get(f"{leads_url(late)}/{match_id}/messages")
    assert r.status_code == 404

    # Another customer can't see or write in this conversation.
    other, other_project, _ = await assessed(api)
    r = await other.post(
        f"{conversations_url(other, other_project)}/{match_id}/messages", json={"body": "Hi"}
    )
    assert r.status_code == 404

    # Blank and overlong messages are refused.
    assert (await user.post(partner_url, json={"body": "   "})).status_code == 422
    assert (await user.post(partner_url, json={"body": "x" * 4001})).status_code == 422

    # An hourly limit per side.
    monkeypatch.setattr(messages, "HOURLY_LIMIT", 2)
    await write(user, partner_url, "One")
    await write(user, partner_url, "Two")
    r = await user.post(partner_url, json={"body": "Three"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_messages"
    await write(customer, f"{customer_url}/{match_id}/messages", "Customer side is separate")
    monkeypatch.setattr(messages, "HOURLY_LIMIT", 30)

    # Won: still open. Lost: read-only for both sides.
    quote = await send(user, p, match_id)
    quote_id = quote["quotes"][0]["id"]
    r = await customer.post(f"{quotes_url(customer, project)}/{quote_id}/decline", json={})
    assert r.status_code == 200, r.text
    r = await user.post(f"{leads_url(p)}/{match_id}/outcome", json={"status": "LOST"})
    assert r.status_code == 200, r.text
    r = await user.post(partner_url, json={"body": "Any news?"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "conversation_closed"
    r = await customer.post(f"{customer_url}/{match_id}/messages", json={"body": "Hello"})
    assert r.status_code == 409
    [convo] = (await customer.get(customer_url)).json()
    assert convo["can_send"] is False and len(convo["messages"]) == 3


# --- Files in messages ---------------------------------------------------------------------

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


async def send_file(
    user: User, url: str, data: bytes, name: str, mime: str, body: str | None = None
) -> Any:
    return await user.post(
        url,
        files={"file": (name, data, mime)},
        data={"body": body} if body is not None else None,
    )


async def test_files_in_messages(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    from app.modules.documents.scanner import EICAR
    from app.modules.leads.models import LeadMessageAttachment
    from tests.test_documents import read_stored

    customer, project, [(first, p1, m1), (second, p2, m2)] = await claimed(
        api, ["Reef Files", "Tableland Files"]
    )
    partner_url = f"{leads_url(p1)}/{m1}"
    customer_url = f"{conversations_url(customer, project)}/{m1}"

    # 1. The customer sends a site plan with a note; it passes the virus check.
    r = await send_file(
        customer,
        f"{customer_url}/files",
        PDF,
        "site plan.pdf",
        "application/pdf",
        "Here is the plan.",
    )
    assert r.status_code == 201, r.text
    [msg] = r.json()["messages"]
    assert msg["body"] == "Here is the plan."
    a = msg["attachment"]
    assert (a["filename"], a["content_type"], a["size_bytes"], a["scan_status"]) == (
        "site plan.pdf",
        "application/pdf",
        len(PDF),
        "CLEAN",
    )
    assert read_stored("messages", m1, a["id"]) == PDF

    # 2. The partner is told, sees the file and downloads it; so can the customer.
    assert any(
        m.subject.startswith("New message from a customer") for m in api.emails_to(first.email)
    )
    got = (await first.get(f"{partner_url}/messages")).json()
    assert got["messages"][0]["attachment"]["id"] == a["id"]
    r = await first.get(f"{partner_url}/files/{a['id']}/content")
    assert r.status_code == 200 and r.content == PDF
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    r = await customer.get(f"{customer_url}/files/{a['id']}/content")
    assert r.status_code == 200 and r.content == PDF

    # 3. The other partner can't reach it, through their own conversation or this one.
    r = await second.get(f"{leads_url(p2)}/{m2}/files/{a['id']}/content")
    assert r.status_code == 404
    r = await second.get(f"{leads_url(p2)}/{m1}/files/{a['id']}/content")
    assert r.status_code == 404
    other, other_project, _ = await assessed(api)
    r = await other.get(f"{conversations_url(other, other_project)}/{m1}/files/{a['id']}/content")
    assert r.status_code == 404

    # 4. The partner replies with a file and no text: the message names the file.
    r = await send_file(
        first, f"{partner_url}/files", b"Quote: $1,200 incl. GST\n", "quote.txt", "text/plain"
    )
    assert r.status_code == 201, r.text
    last = r.json()["messages"][-1]
    assert last["body"] == "Sent a file: quote.txt" and last["attachment"]["scan_status"] == "CLEAN"

    # 5. An infected file is quarantined and never served.
    r = await send_file(first, f"{partner_url}/files", EICAR, "x.txt", "text/plain")
    bad = r.json()["messages"][-1]["attachment"]
    assert bad["scan_status"] == "INFECTED"
    assert read_stored("messages", m1, bad["id"]) is None
    assert read_stored("quarantine", "messages", m1, bad["id"]) == EICAR
    r = await customer.get(f"{customer_url}/files/{bad['id']}/content")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "document_infected"

    # 6. File types are checked like uploads.
    r = await send_file(
        customer, f"{customer_url}/files", b"MZ\x90\x00", "run.exe", "application/octet-stream"
    )
    assert r.status_code == 415

    # 7. What was sent never changes; the scan result is recorded once.
    async with owner_sessions() as db:
        with pytest.raises(DBAPIError, match="never changes"):
            await db.execute(
                text("UPDATE lead_message_attachment SET original_filename = 'x' WHERE id = :id"),
                {"id": a["id"]},
            )
        await db.rollback()
        with pytest.raises(DBAPIError, match="scanned once"):
            await db.execute(
                text("UPDATE lead_message_attachment SET scan_status = 'PENDING' WHERE id = :id"),
                {"id": a["id"]},
            )
        await db.rollback()
        count = (
            await db.execute(
                select(LeadMessageAttachment.id).where(
                    LeadMessageAttachment.lead_match_id == uuid.UUID(m1)
                )
            )
        ).all()
        assert len(count) == 3


async def test_file_waits_for_scan(api: ApiHarness, settings: Settings) -> None:  # noqa: F811
    from dataclasses import replace

    from app.modules.documents import jobs
    from tests.test_documents import DownScanner, NoJobs

    customer, project, [(first, p1, m1)] = await claimed(api, ["Pending Files"])
    api.app.state.resources.jobs = NoJobs()
    r = await send_file(
        customer,
        f"{conversations_url(customer, project)}/{m1}/files",
        PDF,
        "plan.pdf",
        "application/pdf",
    )
    assert r.status_code == 201, r.text
    a = r.json()["messages"][-1]["attachment"]
    assert a["scan_status"] == "PENDING"
    r = await first.get(f"{leads_url(p1)}/{m1}/files/{a['id']}/content")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "document_not_scanned"

    # The sweep finds it; a scanner outage retries, then gives up as ERROR.
    found = await jobs.stalled_attachment_scans(settings, 0)
    assert (m1, a["id"]) in found
    resources = api.app.state.resources
    ctx = jobs.create_job_context(settings, resources.session_factory, resources.storage)
    down = replace(ctx, scanner=DownScanner())
    match, aid = uuid.UUID(m1), uuid.UUID(a["id"])
    with pytest.raises(jobs.RetryLater):
        await jobs.attachment_scan_job(down, match, aid, final_attempt=False)
    assert await jobs.attachment_scan_job(down, match, aid, final_attempt=True) == "ERROR"
    r = await customer.get(f"{conversations_url(customer, project)}/{m1}/files/{a['id']}/content")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "document_scan_failed"
    assert (m1, a["id"]) not in await jobs.stalled_attachment_scans(settings, 0)
