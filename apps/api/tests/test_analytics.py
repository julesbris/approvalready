"""Marketplace analytics (Milestone 16): a partner's own figures, k-anonymous benchmarks and
the staff marketplace view, built on the lead engine's journey from ``test_leads``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import PaymentsProviderKind, Settings
from app.modules.analytics import service
from app.modules.analytics.schemas import BenchmarkOut
from tests.conftest import make_settings
from tests.harness import ApiHarness, platform_user
from tests.regulatory_helpers import unique
from tests.test_billing import WEBHOOK_SECRET
from tests.test_leads import (  # noqa: F401  (fixtures)
    app,
    assessed,
    consent,
    leads_url,
    no_pii,
    offers_for,
    only_new_partners,
    partner,
    stripe_api,
)

MIN_PARTNERS = 3


@pytest.fixture
def settings() -> Settings:
    return make_settings(
        payments_provider=PaymentsProviderKind.STRIPE,
        stripe_secret_key="sk_test_123",
        stripe_webhook_secret=WEBHOOK_SECRET,
        partners_base_url="http://partners.localhost:3000",
        analytics_min_partners=MIN_PARTNERS,
    )


@pytest.fixture(autouse=True)
async def earlier_referrals_are_old(
    migrated: None, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Referrals from earlier tests share the database: move them out of every period, so
    each test's benchmarks only count the partners it made."""
    async with owner_sessions() as db:
        for statement in (
            "UPDATE lead SET created_at = created_at - interval '2 years' "
            "WHERE created_at > now() - interval '1 year'",
            "UPDATE lead_match SET offered_at = offered_at - interval '2 years', "
            "responded_at = responded_at - interval '2 years' "
            "WHERE offered_at > now() - interval '1 year'",
            "UPDATE lead_claim SET created_at = created_at - interval '2 years' "
            "WHERE created_at > now() - interval '1 year'",
        ):
            await db.execute(text(statement))
        await db.commit()


def analytics_url(p: dict[str, Any], what: str = "analytics") -> str:
    return f"/v1/organisations/{p['organisation_id']}/partner/{what}"


# --- Pure helpers --------------------------------------------------------------------


def test_period_start_counts_calendar_months_in_brisbane() -> None:
    # 2026-10-10 03:00 UTC is 13:00 in Brisbane.
    now = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
    assert service.period_start(now, 1).isoformat() == "2026-10-01T00:00:00+10:00"
    assert service.period_start(now, 3).isoformat() == "2026-08-01T00:00:00+10:00"
    assert service.period_start(now, 12).isoformat() == "2025-11-01T00:00:00+10:00"
    # Late on the last day of a month in UTC is already the next month in Brisbane.
    edge = datetime(2026, 9, 30, 15, 0, tzinfo=UTC)
    assert service.period_start(edge, 1).isoformat() == "2026-10-01T00:00:00+10:00"
    months = service.months_between(service.period_start(now, 12), now)
    assert months[0] == "2025-11" and months[-1] == "2026-10" and len(months) == 12


def test_benchmark_withholds_each_figure_below_k() -> None:
    def fig(offered: int, accepted: int, won: int, lost: int, hrs: float | None):
        return service.PartnerFigures(offered, accepted, won, lost, hrs)

    others = [fig(4, 2, 1, 1, 3.0), fig(2, 2, 2, 0, 1.0), fig(5, 0, 0, 0, None)]
    out = service.benchmark(others, 3)
    # Three partners were offered referrals; only two have outcomes or replies.
    assert out == {
        "accept_rate": 0.5,
        "win_rate": None,
        "median_response_hours": None,
        "withheld": False,
    }
    out = service.benchmark(others[:2], 3)
    assert out["withheld"] is True
    assert set(out) == set(BenchmarkOut.model_fields) - {"category_key", "category_label"}


# --- The partner's own figures -------------------------------------------------------


async def test_partner_sees_own_funnel_spend_and_breakdowns(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    pat, p = await partner(api, staff, name=unique("Analytics Planning"))
    other, q = await partner(api, staff, name=unique("Analytics Other"))
    customer, project, assessment = await assessed(api)
    await consent(customer, project, assessment)

    # Partner p accepts and wins; partner q declines.
    [offer] = await offers_for(pat, p)
    match_id = offer["lead"]["match_id"]
    r = await pat.post(f"{leads_url(p)}/{match_id}/claim")
    assert r.status_code == 200, r.text
    for step in ("CONTACTED", "QUOTED", "WON"):
        r = await pat.post(f"{leads_url(p)}/{match_id}/outcome", json={"status": step})
        assert r.status_code == 200, r.text
    [offer_q] = await offers_for(other, q)
    r = await other.post(
        f"{leads_url(q)}/{offer_q['lead']['match_id']}/decline", json={"reason": "Too far"}
    )
    assert r.status_code == 200, r.text

    r = await pat.get(analytics_url(p))
    assert r.status_code == 200, r.text
    report = r.json()
    no_pii(report)
    assert report["months"] == 6
    totals = report["totals"]
    assert {k: totals[k] for k in ("offered", "accepted", "declined", "quoted", "won")} == {
        "offered": 1,
        "accepted": 1,
        "declined": 0,
        "quoted": 1,
        "won": 1,
    }
    assert totals["accept_rate"] == 1.0 and totals["win_rate"] == 1.0
    assert totals["answered_within_48h_rate"] == 1.0
    assert totals["median_response_hours"] is not None and totals["median_response_hours"] < 1
    assert (totals["included"], totals["fees_cents"]) == (1, 0)
    [cat] = report["by_category"]
    assert (cat["category_key"], cat["offered"], cat["won"]) == ("town_planner", 1, 1)
    [area] = report["by_area"]
    assert (area["area"], area["state"]) == ("Cairns Regional Council", "QLD")
    assert report["by_month"][-1]["month"] == service.month_key(datetime.now(UTC))
    assert report["by_month"][-1]["offered"] == 1
    assert len(report["by_month"]) == 6

    # The other partner sees only its own decline; nothing of partner p.
    r = await other.get(analytics_url(q, "analytics"), params={"months": 1})
    theirs = r.json()
    assert theirs["totals"]["declined"] == 1 and theirs["totals"]["accepted"] == 0
    assert theirs["totals"]["accept_rate"] == 0.0
    assert p["organisation_id"] not in json.dumps(theirs)

    # Periods are 1, 3, 6 or 12 months.
    r = await pat.get(analytics_url(p), params={"months": 4})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_period"
    # One partner can't read another's figures, and customers have none.
    assert (await pat.get(analytics_url(q))).status_code in (403, 404)
    r = await customer.get(f"/v1/organisations/{customer.personal_org_id}/partner/analytics")
    assert r.status_code in (403, 404)


# --- Benchmarks ------------------------------------------------------------------------


async def test_benchmarks_need_enough_other_partners(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    pat, p = await partner(api, staff, name=unique("Bench A"))
    others = [await partner(api, staff, name=unique("Bench B")) for _ in range(2)]

    customer, project, assessment = await assessed(api)
    await consent(customer, project, assessment)
    # Two other partners: below the threshold, so everything is withheld.
    r = await pat.get(analytics_url(p, "benchmarks"))
    assert r.status_code == 200, r.text
    bench = r.json()
    assert bench["min_partners"] == MIN_PARTNERS
    assert [row["category_key"] for row in bench["rows"]] == [None, "town_planner"]
    assert all(row["withheld"] for row in bench["rows"])

    # A third partner joins and a second referral reaches everyone.
    others.append(await partner(api, staff, name=unique("Bench C")))
    for user, q in others[:2]:
        [offer, *_] = await offers_for(user, q)
        r = await user.post(f"{leads_url(q)}/{offer['lead']['match_id']}/claim")
        assert r.status_code == 200, r.text
    customer2, project2, assessment2 = await assessed(api)
    await consent(customer2, project2, assessment2)
    for user, q in others:
        open_ = [o for o in await offers_for(user, q) if o["claim"] is None]
        if open_:
            r = await user.post(f"{leads_url(q)}/{open_[0]['lead']['match_id']}/decline", json={})
            assert r.status_code == 200, r.text

    bench = (await pat.get(analytics_url(p, "benchmarks"))).json()
    overall, planner = bench["rows"]
    assert overall["withheld"] is False and planner["withheld"] is False
    # Three partners each answered everything: accept rates 1/2, 1/2 and 0 → median 0.5.
    assert planner["accept_rate"] == 0.5
    assert planner["median_response_hours"] is not None
    assert planner["win_rate"] is None  # nobody has an outcome yet
    # Nothing names or counts the other partners.
    dumped = json.dumps(bench)
    for _, q in others:
        assert q["organisation_id"] not in dumped and q["id"] not in dumped
    no_pii(bench)


# --- Staff -----------------------------------------------------------------------------


async def test_staff_marketplace_view(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    name = unique("Market Partner")
    pat, p = await partner(api, staff, name=name)
    customer, project, assessment = await assessed(api)
    await consent(customer, project, assessment, categories=["town_planner", "building_certifier"])
    [offer, *_] = await offers_for(pat, p)
    r = await pat.post(f"{leads_url(p)}/{offer['lead']['match_id']}/claim")
    assert r.status_code == 200, r.text

    admin = await platform_user(api, "ADMIN")
    r = await admin.get("/v1/admin/analytics/marketplace", params={"months": 1})
    assert r.status_code == 200, r.text
    report = r.json()
    no_pii(report)
    totals = report["totals"]
    assert totals["leads"] >= 2 and totals["claims"] >= 1 and totals["found_partner"] >= 1
    keys = {c["category_key"] for c in report["by_category"]}
    assert {"town_planner", "building_certifier"} <= keys
    assert any(a["area"] == "Cairns Regional Council" for a in report["by_area"])
    [mine] = [x for x in report["partners"] if x["name"] == name]
    assert (mine["offered"], mine["accepted"], mine["status"]) == (2, 1, "ACTIVE")
    assert report["by_month"][-1]["leads"] >= 2

    # STAFF without lead.manage, and partners, can't see it.
    assert (await staff.get("/v1/admin/analytics/marketplace")).status_code == 403
    assert (await pat.get("/v1/admin/analytics/marketplace")).status_code == 403
