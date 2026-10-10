"""Quotes (Milestone 23): partners who accepted a referral send the customer written quotes;
the customer compares, accepts or declines them.

Reuses the lead engine's fixtures and helpers (``tests/test_leads.py``): each test pauses the
partners made before it.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.assessments.service import assessment_date
from app.modules.leads import service
from app.modules.leads.models import LeadMatch, LeadQuote, LeadStatusEvent
from app.modules.leads.quotes import gst_amounts
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

pytestmark = pytest.mark.integration


def quote_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Development application for a secondary dwelling",
        "scope": "Prepare and lodge the DA, including the planning report. Excludes fees.",
        "line_items": [
            {"description": "Planning report", "amount_cents": 180000},
            {"description": "Lodgement and liaison with council", "amount_cents": 70000},
        ],
        "gst": "EXCLUDED",
        "valid_until": (assessment_date() + timedelta(days=30)).isoformat(),
        "start_estimate": "Within two weeks",
        "terms": "50% deposit on acceptance.",
    }
    body.update(overrides)
    return body


def quotes_url(customer: User, project: dict[str, Any]) -> str:
    return f"{org_url(customer)}/projects/{project['id']}/quotes"


async def claimed(
    api: ApiHarness, names: list[str]
) -> tuple[User, dict[str, Any], list[tuple[User, dict[str, Any], str]]]:
    """A customer's referral accepted by one partner per name: (user, partner, match id)."""
    staff = await platform_user(api, "STAFF")
    partners = [await partner(api, staff, name=n) for n in names]
    customer, project, assessment = await assessed(api)
    await consent(customer, project, assessment, max_providers=len(names))
    out = []
    for user, p in partners:
        [offer] = await offers_for(user, p)
        match_id = offer["lead"]["match_id"]
        r = await user.post(f"{leads_url(p)}/{match_id}/claim")
        assert r.status_code == 200, r.text
        out.append((user, p, match_id))
    return customer, project, out


async def send(user: User, p: dict[str, Any], match_id: str, **overrides: Any) -> dict[str, Any]:
    r = await user.post(f"{leads_url(p)}/{match_id}/quotes", json=quote_body(**overrides))
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_gst_amounts() -> None:
    assert gst_amounts(110000, "INCLUDED") == (10000, 110000)
    assert gst_amounts(100000, "EXCLUDED") == (10000, 110000)
    assert gst_amounts(5, "EXCLUDED") == (1, 6)  # half a cent rounds up
    assert gst_amounts(12345, "NOT_REGISTERED") == (0, 12345)


async def test_quote_journey(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    customer, project, [(first, p1, m1), (second, p2, m2)] = await claimed(
        api, ["Reef Planning", "Tableland Planning"]
    )

    # 1. The first partner sends a quote: their referral is now QUOTED.
    offer = await send(first, p1, m1)
    assert offer["lead"]["status"] == "QUOTED"
    [quote] = offer["quotes"]
    assert (quote["version"], quote["status"], quote["expired"]) == (1, "SENT", False)
    assert (quote["total_cents"], quote["gst_cents"], quote["total_inc_gst_cents"]) == (
        250000,
        25000,
        275000,
    )

    # 2. The customer is told, with the price they'd pay.
    mails = api.emails_to(customer.email, "notification")
    assert any(m.subject.startswith("Reef Planning sent you a quote: $2,750.00") for m in mails)

    # 3. A revision replaces it: the customer only sees the current version.
    offer = await send(
        first,
        p1,
        m1,
        gst="INCLUDED",
        line_items=[{"description": "Everything", "amount_cents": 220000}],
    )
    assert [(q["version"], q["status"]) for q in offer["quotes"]] == [
        (2, "SENT"),
        (1, "SUPERSEDED"),
    ]
    # 4. The second partner quotes too.
    await send(second, p2, m2, gst="NOT_REGISTERED")
    r = await customer.get(quotes_url(customer, project))
    assert r.status_code == 200, r.text
    listed = r.json()
    assert [(q["partner"]["name"], q["version"]) for q in listed] == [
        ("Tableland Planning", 1),
        ("Reef Planning", 2),
    ]
    reef = listed[1]
    assert (reef["total_inc_gst_cents"], reef["gst_cents"]) == (220000, 20000)
    assert reef["category_label"] == "Town planner" and reef["partner"]["phone"]

    # 5. The customer accepts the revised quote and declines the other in one go.
    r = await customer.post(
        f"{quotes_url(customer, project)}/{reef['id']}/accept", json={"decline_others": True}
    )
    assert r.status_code == 200, r.text
    assert sorted((q["partner"]["name"], q["status"]) for q in r.json()) == [
        ("Reef Planning", "ACCEPTED"),
        ("Tableland Planning", "DECLINED"),
    ]
    r = await customer.post(f"{quotes_url(customer, project)}/{reef['id']}/accept", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_waiting"

    # 6. Each partner hears the answer; the referrals are won and lost.
    assert any(m.subject.startswith("Quote accepted") for m in api.emails_to(first.email))
    assert any(m.subject.startswith("Quote declined") for m in api.emails_to(second.email))
    got = (await first.get(f"{leads_url(p1)}/{m1}")).json()
    assert got["lead"]["status"] == "WON" and got["quotes"][0]["status"] == "ACCEPTED"
    got = (await second.get(f"{leads_url(p2)}/{m2}")).json()
    assert got["lead"]["status"] == "LOST"
    assert got["quotes"][0]["response_note"] == "The customer chose another quote."

    # 7. A finished job can't be quoted again; everything is recorded.
    r = await first.post(f"{leads_url(p1)}/{m1}/quotes", json=quote_body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "job_finished"
    async with owner_sessions() as db:
        events = list(
            (
                await db.execute(
                    select(LeadStatusEvent.to_status)
                    .where(LeadStatusEvent.lead_match_id == uuid.UUID(m1))
                    .order_by(LeadStatusEvent.occurred_at)
                )
            ).scalars()
        )
        assert events[-2:] == ["QUOTED", "WON"]
        actions = set(
            (
                await db.execute(
                    text(
                        "SELECT action FROM audit_event "
                        "WHERE target_type = 'lead_quote' AND target_id = :q"
                    ),
                    {"q": reef["id"]},
                )
            ).scalars()
        )
        assert actions == {"quote.sent", "quote.accepted"}


async def test_quote_rules(
    api: ApiHarness,
    owner_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staff = await platform_user(api, "STAFF")
    late_user, late = await partner(api, staff, name="Unclaimed Planning")
    customer, project, [(user, p, match_id)] = await claimed(api, ["Rules Planning"])
    url = f"{leads_url(p)}/{match_id}/quotes"

    # Only after accepting the referral.
    [unclaimed] = await offers_for(late_user, late)
    r = await late_user.post(
        f"{leads_url(late)}/{unclaimed['lead']['match_id']}/quotes", json=quote_body()
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_claimed"

    # Valid-until dates: not in the past, at most 180 days ahead.
    today = assessment_date()
    for bad in (today - timedelta(days=1), today + timedelta(days=181)):
        r = await user.post(url, json=quote_body(valid_until=bad.isoformat()))
        assert r.status_code == 422, r.text
    r = await user.post(url, json=quote_body(line_items=[]))
    assert r.status_code == 422

    # Withdrawing a waiting quote; then one can't be withdrawn twice.
    quote = (await send(user, p, match_id))["quotes"][0]
    r = await user.post(f"{url}/{quote['id']}/withdraw")
    assert r.status_code == 200 and r.json()["quotes"][0]["status"] == "WITHDRAWN"
    r = await user.post(f"{url}/{quote['id']}/withdraw")
    assert r.status_code == 409

    # An expired quote can't be accepted, but can still be declined.
    quote = (await send(user, p, match_id, valid_until=today.isoformat()))["quotes"][0]
    later = service.utcnow() + timedelta(days=2)
    monkeypatch.setattr(service, "utcnow", lambda: later)
    listed = (await customer.get(quotes_url(customer, project))).json()
    assert next(q for q in listed if q["id"] == quote["id"])["expired"] is True
    r = await customer.post(f"{quotes_url(customer, project)}/{quote['id']}/accept", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "quote_expired"
    r = await customer.post(
        f"{quotes_url(customer, project)}/{quote['id']}/decline", json={"note": "Too slow."}
    )
    assert r.status_code == 200, r.text
    monkeypatch.undo()

    # Declining leaves the referral open for a revision; recording it lost withdraws it.
    quote = (await send(user, p, match_id))["quotes"][0]
    r = await user.post(f"{leads_url(p)}/{match_id}/outcome", json={"status": "LOST"})
    assert r.status_code == 200, r.text
    got = (await user.get(f"{leads_url(p)}/{match_id}")).json()
    assert got["quotes"][0]["status"] == "WITHDRAWN"

    # A quote never changes once sent, and is never deleted, even by the owner.
    async with owner_sessions() as db:
        for sql in (
            "UPDATE lead_quote SET total_cents = 1 WHERE id = :q",
            "UPDATE lead_quote SET status = 'SENT' WHERE id = :q",
            "DELETE FROM lead_quote WHERE id = :q",
        ):
            with pytest.raises(DBAPIError):
                await db.execute(text(sql), {"q": quote["id"]})
            await db.rollback()


async def test_quotes_are_private(api: ApiHarness) -> None:
    customer, project, [(user, p, match_id)] = await claimed(api, ["Private Planning"])
    quote = (await send(user, p, match_id))["quotes"][0]

    # Another customer can't see or answer them.
    stranger = await api.user(name="Someone Else")
    r = await stranger.get(f"{org_url(stranger)}/projects/{project['id']}/quotes")
    assert r.status_code in (403, 404)
    r = await stranger.post(
        f"{org_url(stranger)}/projects/{project['id']}/quotes/{quote['id']}/accept", json={}
    )
    assert r.status_code in (403, 404)

    # Another partner can't send or withdraw on this referral.
    staff = await platform_user(api, "STAFF")
    other_user, other = await partner(api, staff, name="Other Planning")
    r = await other_user.post(f"{leads_url(other)}/{match_id}/quotes", json=quote_body())
    assert r.status_code == 404
    r = await other_user.post(f"{leads_url(other)}/{match_id}/quotes/{quote['id']}/withdraw")
    assert r.status_code == 404

    # The customer's own list is the only place it shows.
    [listed] = (await customer.get(quotes_url(customer, project))).json()
    assert listed["id"] == quote["id"] and listed["status"] == "SENT"


async def test_match_status_follows_the_quote(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    customer, project, [(user, p, match_id)] = await claimed(api, ["Status Planning"])
    await send(user, p, match_id)
    [quote] = (await customer.get(quotes_url(customer, project))).json()
    r = await customer.post(
        f"{quotes_url(customer, project)}/{quote['id']}/decline", json={"note": "Over budget."}
    )
    assert r.status_code == 200, r.text
    async with owner_sessions() as db:
        match = await db.get(LeadMatch, uuid.UUID(match_id))
        assert match is not None and match.status == "QUOTED"
        row = await db.get(LeadQuote, uuid.UUID(quote["id"]))
        assert row is not None and row.response_note == "Over budget."
        assert row.valid_until > date(2000, 1, 1)
    # The partner can revise it after a decline.
    offer = await send(user, p, match_id)
    assert [q["status"] for q in offer["quotes"]] == ["SENT", "DECLINED"]
