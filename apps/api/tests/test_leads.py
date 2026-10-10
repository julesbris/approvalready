"""The lead engine (Milestone 15): referral consent, matching and ranking, release waves,
claiming (with row locks), lead fees and credits, outcomes, withdrawal and expiry.

``test_partner_journey`` is the 16-step partner journey through the API; the rest are the
negative cases. Partners are platform-wide, so each test pauses every partner made before it
(``only_new_partners``) and every lead price and plan price is removed afterwards.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import PaymentsProviderKind, Settings
from app.main import create_app
from app.modules.billing.models import Feature, Price
from app.modules.leads import jobs, service
from app.modules.leads.models import (
    Lead,
    LeadContact,
    LeadMatch,
    LeadPrice,
    LeadStatusEvent,
    ReferralConsent,
)
from app.modules.leads.policy import ReleasePolicy
from app.modules.leads.schemas import LeadPublicView
from app.modules.partners.models import PartnerOrganisation
from tests.conftest import make_settings
from tests.harness import ApiHarness, User, platform_user
from tests.regulatory_helpers import content, reference, rule_set, unique
from tests.test_assessments import FLOOR_OVER_80, org_url, run, scoped
from tests.test_assessments import submitted_project as submitted
from tests.test_billing import WEBHOOK_SECRET, FakeStripe, deliver, event, set_price
from tests.test_partners import ADMIN as PARTNERS_ADMIN
from tests.test_partners import application, category
from tests.test_requirements import _publish

pytestmark = pytest.mark.integration

LEADS_ADMIN = "/v1/admin/leads"
CUSTOMER_NAME = "Casey Customer"
CUSTOMER_PHONE = "0400 111 222"
CUSTOMER_EMAIL = "casey@example.com.au"
SITE = "12 Example Street, Edge Hill QLD 4870"


@pytest.fixture
def stripe_api() -> FakeStripe:
    return FakeStripe()


@pytest.fixture
def settings() -> Settings:
    return make_settings(
        payments_provider=PaymentsProviderKind.STRIPE,
        stripe_secret_key="sk_test_123",
        stripe_webhook_secret=WEBHOOK_SECRET,
        partners_base_url="http://partners.localhost:3000",
    )


@pytest.fixture
def app(settings: Settings, stripe_api: FakeStripe) -> FastAPI:
    return create_app(settings, stripe_transport=httpx.MockTransport(stripe_api.handle))


@pytest.fixture(autouse=True)
async def only_new_partners(
    migrated: None, owner_sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[None]:
    """Partners and open leads from earlier tests stay out of the way (the sweep would match
    new partners to old leads); prices are taken off sale after."""
    async with owner_sessions() as db:
        await db.execute(update(PartnerOrganisation).values(paused=True))
        await db.execute(
            update(Lead)
            .where(Lead.status == "OPEN")
            .values(status="EXPIRED", closed_at=text("now()"))
        )
        await db.commit()
    yield
    async with owner_sessions() as db:
        await db.execute(
            update(Price)
            .where(Price.active.is_(True))
            .values(active=False, deactivated_at=text("now()"))
        )
        await db.execute(
            update(LeadPrice)
            .where(LeadPrice.deactivated_at.is_(None))
            .values(deactivated_at=text("now()"))
        )
        await db.commit()


# --- Helpers ----------------------------------------------------------------------------


async def partner(
    api: ApiHarness,
    staff: User,
    *,
    name: str = "Reef Certifiers",
    areas: list[dict[str, str]] | None = None,
    approve_status: str = "ACTIVE",
) -> tuple[User, dict[str, Any]]:
    """An approved partner in building certification and town planning (Cairns)."""
    # Many sign-ups from one test client: reset the per-address registration limit.
    await api.app.state.resources.redis.flushdb()
    user = await api.user(name=f"{name} admin")
    body = application(name=name)
    if areas is not None:
        body["service_areas"] = areas
    r = await user.post("/v1/partners/applications", json=body)
    assert r.status_code == 201, r.text
    p = r.json()
    r = await user.put(
        "/v1/auth/session/organisation", json={"organisation_id": p["organisation_id"]}
    )
    assert r.status_code == 200, r.text
    base = f"{PARTNERS_ADMIN}/{p['id']}"
    for c in p["credentials"]:
        r = await staff.post(f"{base}/credentials/{c['id']}", json={"status": "VERIFIED"})
        assert r.status_code == 200, r.text
    for key in ("building_certifier", "town_planner"):
        r = await staff.post(
            f"{base}/categories/{category(p, key)['id']}", json={"status": "APPROVED"}
        )
        assert r.status_code == 200, r.text
    r = await staff.post(f"{base}/status", json={"status": "ACTIVE"})
    assert r.status_code == 200, r.text
    if approve_status == "SUSPENDED":
        r = await staff.post(
            f"{base}/status", json={"status": "SUSPENDED", "reason": "Insurance lapsed for now."}
        )
        assert r.status_code == 200, r.text
    return user, r.json()


def leads_url(p: dict[str, Any]) -> str:
    return f"/v1/organisations/{p['organisation_id']}/partner/leads"


async def assessed(api: ApiHarness) -> tuple[User, dict[str, Any], dict[str, Any]]:
    """A customer whose planning assessment says a town planner and certifier can help."""
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
            "approval": {"kind": "PLANNING_MATERIAL_CHANGE_OF_USE", "authority": "Test Council"},
            "referral_categories": ["town_planner", "building_certifier"],
        },
    }
    await _publish(admin, rs["id"], FLOOR_OVER_80, body)
    customer = await api.user(name=CUSTOMER_NAME)
    project = await submitted(customer, lot)
    r = await run(customer, project["id"])
    assert r.status_code == 201, r.text
    return customer, project, r.json()


def referrals_url(customer: User, project: dict[str, Any]) -> str:
    return f"{org_url(customer)}/projects/{project['id']}/referrals"


async def consent_body(
    customer: User,
    project: dict[str, Any],
    assessment: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    r = await customer.get(
        f"{referrals_url(customer, project)}/options",
        params={"assessment_id": assessment["id"]},
    )
    assert r.status_code == 200, r.text
    options = r.json()
    body: dict[str, Any] = {
        "assessment_id": assessment["id"],
        "consent_text_version_id": options["consent"]["id"],
        "agreed": True,
        "categories": ["town_planner"],
        "max_providers": 2,
        "fields_released": ["name", "phone"],
        "contact": {
            "name": CUSTOMER_NAME,
            "email": CUSTOMER_EMAIL,
            "phone": CUSTOMER_PHONE,
            "site_address": SITE,
        },
        "location": {
            "suburb": "Edge Hill",
            "lga": "Cairns Regional Council",
            "state": "QLD",
            "postcode": "4870",
        },
        "timing": "WITHIN_3_MONTHS",
        "summary": "One-bedroom granny flat behind the house, about 92 square metres.",
    }
    body.update(overrides)
    return body


async def consent(
    customer: User, project: dict[str, Any], assessment: dict[str, Any], **overrides: Any
) -> list[dict[str, Any]]:
    body = await consent_body(customer, project, assessment, **overrides)
    r = await customer.post(referrals_url(customer, project), json=body)
    assert r.status_code == 201, r.text
    return list(r.json())


async def offers_for(user: User, p: dict[str, Any]) -> list[dict[str, Any]]:
    r = await user.get(leads_url(p))
    assert r.status_code == 200, r.text
    return list(r.json())


async def lead_rows(
    owner_sessions: async_sessionmaker[AsyncSession], lead_id: str
) -> tuple[Lead, list[LeadMatch], bool]:
    async with owner_sessions() as db:
        lead = await db.get(Lead, uuid.UUID(lead_id))
        assert lead is not None
        matches = list(
            (
                await db.execute(
                    select(LeadMatch).where(LeadMatch.lead_id == lead.id).order_by(LeadMatch.rank)
                )
            ).scalars()
        )
        contact = await db.get(LeadContact, lead.id) is not None
        return lead, matches, contact


def no_pii(payload: Any) -> None:
    dumped = json.dumps(payload)
    for value in (CUSTOMER_NAME, CUSTOMER_PHONE, CUSTOMER_EMAIL, "12 Example Street"):
        assert value not in dumped, f"{value!r} leaked"


async def sweep(api: ApiHarness) -> int:
    resources = api.app.state.resources
    return await jobs.sweep(resources.session_factory, resources.email, api.app.state.settings)


# --- The partner journey ---------------------------------------------------------------


async def test_partner_journey(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    staff = await platform_user(api, "STAFF")
    # 1-2. A partner applies; staff check its licence and insurance, approve its categories
    # and approve it.
    pat, p = await partner(api, staff)
    assert p["receiving_referrals"] is True

    # 3. The partner caps how many accepted referrals can be in progress.
    prefs = f"/v1/organisations/{p['organisation_id']}/partner/lead-preferences"
    r = await pat.patch(prefs, json={"max_open_leads": 5})
    assert r.status_code == 200, r.text
    assert r.json() == {"paused": False, "max_open_leads": 5, "in_progress": 0}

    # 4. A customer's assessment says a town planner can help.
    customer, project, assessment = await assessed(api)
    assert {c["key"] for c in assessment["referral_categories"]} == {
        "town_planner",
        "building_certifier",
    }

    # 5. The introduction form: the current consent text, the categories, suggestions.
    r = await customer.get(
        f"{referrals_url(customer, project)}/options",
        params={"assessment_id": assessment["id"]},
    )
    options = r.json()
    assert options["consent"]["version"] >= 1
    assert "Partners do not pay to rank higher" in options["consent"]["body"]
    assert {c["key"] for c in options["categories"]} == {"town_planner", "building_certifier"}
    assert options["contact"]["name"] == CUSTOMER_NAME
    assert options["max_providers"] == 3

    # 6. The customer agrees: name and phone only, up to two partners.
    [referral] = await consent(customer, project, assessment)
    assert referral["contact"] == {"name": CUSTOMER_NAME, "phone": CUSTOMER_PHONE}
    assert referral["fields_released"] == ["name", "phone"]
    [lead] = referral["leads"]
    assert (lead["category_key"], lead["status"], lead["offered_count"]) == (
        "town_planner",
        "OPEN",
        1,
    )

    # 7. Matching offered it to the partner, who is told by email: no customer details.
    [mail] = api.emails_to(pat.email, "notification")
    assert "New referral: Town planner in Edge Hill QLD 4870" in mail.subject
    no_pii(mail.text)

    # 8. The partner's list shows the public view only, with why it was matched and what
    # accepting would cost.
    [offer] = await offers_for(pat, p)
    no_pii(offer)
    assert offer["claim"] is None
    view = offer["lead"]
    assert set(view) == set(LeadPublicView.model_fields)
    assert view["requirements"] == ["A development application is likely"]
    assert (view["lga"], view["postcode"], view["claims_left"]) == (
        "Cairns Regional Council",
        "4870",
        2,
    )
    factors = {f["factor"]: f for f in view["score_breakdown"]}
    assert factors["area"]["points"] == 40  # the postcode, beating the council area
    assert factors["insurance"]["points"] == 10
    assert view["score"] == sum(f["points"] for f in view["score_breakdown"])
    assert offer["fee"]["included"] is True and offer["fee"]["fee_cents"] == 0

    # 9. Opening it marks it viewed.
    match_id = view["match_id"]
    r = await pat.get(f"{leads_url(p)}/{match_id}")
    assert r.json()["lead"]["status"] == "VIEWED"

    # 10. Accepting releases exactly the details the customer chose.
    r = await pat.post(f"{leads_url(p)}/{match_id}/claim")
    assert r.status_code == 200, r.text
    claim = r.json()["claim"]
    assert claim["contact"] == {"name": CUSTOMER_NAME, "phone": CUSTOMER_PHONE}
    assert (claim["fee_cents"], claim["included"]) == (0, True)
    r = await pat.post(f"{leads_url(p)}/{match_id}/claim")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_claimed"

    # 11. The customer hears who accepted, with the partner's business details.
    [mail] = api.emails_to(customer.email, "notification")
    assert mail.subject.startswith("Reef Certifiers accepted your request")
    [referral] = (await customer.get(referrals_url(customer, project))).json()
    [claimed] = referral["leads"][0]["claims"]
    assert claimed["name"] == "Reef Certifiers"
    assert claimed["phone"] == "(07) 4000 0000" and claimed["is_promoted"] is False

    # 12-14. The partner records contacting, quoting and winning the work.
    for step in ("CONTACTED", "QUOTED", "WON"):
        r = await pat.post(f"{leads_url(p)}/{match_id}/outcome", json={"status": step})
        assert r.status_code == 200, r.text
        assert r.json()["lead"]["status"] == step
    r = await pat.post(f"{leads_url(p)}/{match_id}/outcome", json={"status": "LOST"})
    assert r.status_code == 409

    # 15. Staff see the lead, its matches and scores, never the customer's details.
    lead_admin = await platform_user(api, "ADMIN")
    r = await lead_admin.get(LEADS_ADMIN)
    assert r.status_code == 200, r.text
    mine = next(x for x in r.json() if x["id"] == lead["id"])
    no_pii(mine)
    assert [m["status"] for m in mine["matches"]] == ["WON"]
    assert (await staff.get(LEADS_ADMIN)).status_code == 403  # STAFF lacks lead.manage

    # 16. Every step is recorded; the included referral cost nothing.
    async with owner_sessions() as db:
        events = list(
            (
                await db.execute(
                    select(LeadStatusEvent.to_status)
                    .where(LeadStatusEvent.lead_match_id == uuid.UUID(match_id))
                    .order_by(LeadStatusEvent.occurred_at)
                )
            ).scalars()
        )
        assert events == ["VIEWED", "CLAIMED", "CONTACTED", "QUOTED", "WON"]
        actions = set(
            (
                await db.execute(
                    text(
                        "SELECT action FROM audit_event WHERE target_id IN (:m, :c) "
                        "OR (action = 'referral.consented' AND target_id = :c)"
                    ),
                    {"m": match_id, "c": referral["id"]},
                )
            ).scalars()
        )
        assert {
            "referral.consented",
            "lead.claimed",
            "contact.released",
            "lead.outcome",
        } <= actions
    r = await pat.get(f"/v1/organisations/{p['organisation_id']}/partner/credits")
    assert r.json()["balance_cents"] == 0 and r.json()["included_used"] == 1
    assert r.json()["entries"] == []


# --- Consent ---------------------------------------------------------------------------


async def test_consent_is_explicit_versioned_and_fixed(api: ApiHarness) -> None:
    customer, project, assessment = await assessed(api)
    url = referrals_url(customer, project)

    async def post(**overrides: Any) -> httpx.Response:
        body = await consent_body(customer, project, assessment, **overrides)
        return await customer.post(url, json=body)

    r = await post(agreed=False)
    assert r.status_code == 422
    r = await post(consent_text_version_id=str(uuid.uuid4()))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_changed"
    r = await post(categories=["mortgage_broker"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "category_not_offered"
    r = await post(fields_released=["email"], contact={"name": "Casey"})
    assert r.status_code == 422
    r = await post(max_providers=4)
    assert r.status_code == 422

    r = await post()
    assert r.status_code == 201, r.text
    record_id = r.json()[0]["id"]
    r = await post()
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_requested"
    # Another category from the same assessment is fine.
    assert (await post(categories=["building_certifier"])).status_code == 201

    # What was agreed never changes, even for the database's own role.
    async with api.app.state.resources.session_factory() as db:
        from app.db.tenant import bind_tenant

        await bind_tenant(db, uuid.UUID(customer.personal_org_id))
        with pytest.raises(DBAPIError, match="never changes"):
            await db.execute(
                update(ReferralConsent)
                .where(ReferralConsent.id == uuid.UUID(record_id))
                .values(max_providers=3)
            )
        await db.rollback()

    # Another customer can't see or withdraw it.
    other = await api.user()
    r = await other.get(
        f"/v1/organisations/{customer.personal_org_id}/projects/{project['id']}/referrals"
    )
    assert r.status_code == 404


async def test_public_view_is_a_whitelist() -> None:
    assert set(LeadPublicView.model_fields) == {
        "match_id",
        "lead_id",
        "category_key",
        "category_label",
        "vertical",
        "suburb",
        "lga",
        "state",
        "postcode",
        "timing",
        "summary",
        "requirements",
        "max_claims",
        "claims_left",
        "lead_status",
        "status",
        "offered_at",
        "expires_at",
        "score",
        "score_breakdown",
    }
    with pytest.raises(ValueError):
        LeadPublicView.model_validate({"contact": {}})


# --- Who is matched ----------------------------------------------------------------------


async def test_only_eligible_partners_in_the_area_are_matched(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    staff = await platform_user(api, "STAFF")
    good_user, good = await partner(api, staff, name="Good Planning")
    await partner(api, staff, name="Suspended Planning", approve_status="SUSPENDED")
    paused_user, paused = await partner(api, staff, name="Paused Planning")
    r = await paused_user.patch(
        f"/v1/organisations/{paused['organisation_id']}/partner/lead-preferences",
        json={"paused": True},
    )
    assert r.json()["paused"] is True
    await partner(
        api,
        staff,
        name="Far Away Planning",
        areas=[{"kind": "POSTCODE", "state": "QLD", "value": "4000"}],
    )
    await partner(
        api, staff, name="Wrong State", areas=[{"kind": "STATE", "state": "NSW", "value": "NSW"}]
    )
    council = await partner(
        api,
        staff,
        name="Council Area Planning",
        areas=[{"kind": "LGA", "state": "QLD", "value": "Cairns"}],
    )
    whole_state = await partner(
        api,
        staff,
        name="Statewide Planning",
        areas=[{"kind": "STATE", "state": "QLD", "value": "QLD"}],
    )

    customer, project, assessment = await assessed(api)
    # The customer is also a member of a partner: that partner never gets their referral.
    own_user, own = await partner(api, staff, name="Customer's Own Firm")
    r = await own_user.post(
        f"/v1/organisations/{own['organisation_id']}/invitations",
        json={"email": customer.email, "roles": ["PARTNER_USER"]},
    )
    assert r.status_code == 201, r.text
    token = api.token_from(api.last_email(customer.email, "org.invitation"), "accept")
    r = await customer.post("/v1/invitations/accept", json={"token": token})
    assert r.status_code == 200, r.text

    [referral] = await consent(customer, project, assessment)
    lead_id = referral["leads"][0]["id"]
    _, matches, _ = await lead_rows(owner_sessions, lead_id)
    by_partner = {m.partner_organisation_id: m for m in matches}
    ids = {uuid.UUID(x["id"]) for x in (good, council[1], whole_state[1])}
    assert set(by_partner) == ids
    # Ranked by area fit: postcode, then council area, then state.
    ranked = [m.partner_organisation_id for m in matches]
    assert ranked == [
        uuid.UUID(good["id"]),
        uuid.UUID(council[1]["id"]),
        uuid.UUID(whole_state[1]["id"]),
    ]
    area = {m.partner_organisation_id: m.score_breakdown[0]["points"] for m in matches}
    assert sorted(area.values(), reverse=True) == [40, 30, 15]

    # A partner that wasn't matched can't open it.
    r = await paused_user.get(f"{leads_url(paused)}/{matches[0].id}")
    assert r.status_code == 404
    assert await offers_for(good_user, good) != []


async def test_waves_declines_and_expiry(
    api: ApiHarness,
    owner_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    one_at_a_time = ReleasePolicy(
        max_providers=3, first_wave=1, wave_size=1, wave_hours=24, expires_after_days=14
    )
    monkeypatch.setattr(service, "for_category", lambda key: one_at_a_time)
    staff = await platform_user(api, "STAFF")
    first = await partner(api, staff, name="First Planning")
    second = await partner(
        api,
        staff,
        name="Second Planning",
        areas=[{"kind": "LGA", "state": "QLD", "value": "Cairns"}],
    )
    third = await partner(
        api, staff, name="Third Planning", areas=[{"kind": "STATE", "state": "QLD", "value": "QLD"}]
    )
    customer, project, assessment = await assessed(api)
    [referral] = await consent(customer, project, assessment, max_providers=1)
    lead_id = referral["leads"][0]["id"]

    # Only the best-ranked partner sees it at first.
    assert len(await offers_for(*first)) == 1
    assert await offers_for(*second) == []
    # Declining offers it to the next partner straight away.
    [offer] = await offers_for(*first)
    r = await first[0].post(
        f"{leads_url(first[1])}/{offer['lead']['match_id']}/decline", json={"reason": "Too busy"}
    )
    assert r.status_code == 200 and r.json()["lead"]["status"] == "DECLINED"
    r = await first[0].post(f"{leads_url(first[1])}/{offer['lead']['match_id']}/claim")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "declined"
    assert len(await offers_for(*second)) == 1
    assert await offers_for(*third) == []

    # The next wave comes after wave_hours, from the scheduled sweep.
    assert await sweep(api) == 0
    async with owner_sessions() as db:
        await db.execute(
            update(Lead)
            .where(Lead.id == uuid.UUID(lead_id))
            .values(last_wave_at=func.now() - timedelta(hours=25))
        )
        await db.commit()
    assert await sweep(api) >= 1
    assert len(await offers_for(*third)) == 1

    # After its date it expires: open offers end and the contact details are deleted.
    async with owner_sessions() as db:
        await db.execute(
            update(Lead)
            .where(Lead.id == uuid.UUID(lead_id))
            .values(expires_at=func.now() - timedelta(minutes=1))
        )
        await db.commit()
    await sweep(api)
    lead, matches, has_contact = await lead_rows(owner_sessions, lead_id)
    assert lead.status == "EXPIRED" and not has_contact
    assert [m.status for m in matches] == ["DECLINED", "EXPIRED", "EXPIRED"]
    [offer] = await offers_for(*third)
    r = await third[0].post(f"{leads_url(third[1])}/{offer['lead']['match_id']}/claim")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "lead_closed"
    [referral] = (await customer.get(referrals_url(customer, project))).json()
    assert referral["leads"][0]["status"] == "EXPIRED"


# --- Claiming ----------------------------------------------------------------------------


async def test_claims_never_exceed_what_the_customer_allowed(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    staff = await platform_user(api, "STAFF")
    partners = [await partner(api, staff, name=f"Racing Planning {i}") for i in range(4)]
    customer, project, assessment = await assessed(api)
    [referral] = await consent(customer, project, assessment, max_providers=2)
    lead_id = referral["leads"][0]["id"]
    match_ids = [(await offers_for(u, p))[0]["lead"]["match_id"] for u, p in partners]

    results = await asyncio.gather(
        *(
            u.post(f"{leads_url(p)}/{m}/claim")
            for (u, p), m in zip(partners, match_ids, strict=True)
        )
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 200, 409, 409], [r.text for r in results]
    for r in results:
        if r.status_code == 409:
            assert r.json()["detail"]["code"] in ("lead_full", "lead_closed")
    lead, matches, has_contact = await lead_rows(owner_sessions, lead_id)
    assert (lead.status, lead.claimed_count, has_contact) == ("FILLED", 2, False)
    assert sorted(m.status for m in matches) == ["CLAIMED", "CLAIMED", "EXPIRED", "EXPIRED"]
    # The partners who accepted keep the copy released to them.
    for (u, p), m, r in zip(partners, match_ids, results, strict=True):
        if r.status_code == 200:
            got = (await u.get(f"{leads_url(p)}/{m}")).json()
            assert got["claim"]["contact"]["name"] == CUSTOMER_NAME


async def test_lead_fees_come_from_credits(
    api: ApiHarness,
    owner_sessions: async_sessionmaker[AsyncSession],
    stripe_api: FakeStripe,
) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    pat, p = await partner(api, staff)
    credits_url = f"/v1/organisations/{p['organisation_id']}/partner/credits"

    # Staff price town-planning referrals; regulated advice can't be priced.
    r = await admin.put(f"{LEADS_ADMIN}/prices/town_planner", json={"amount_cents": 2_500})
    assert r.status_code == 200, r.text
    assert next(x for x in r.json() if x["category_key"] == "town_planner")["amount_cents"] == 2_500
    r = await admin.put(f"{LEADS_ADMIN}/prices/lawyer", json={"amount_cents": 2_500})
    assert r.status_code == 422

    async with owner_sessions() as db:
        await db.execute(
            update(Feature).where(Feature.key == "partner.leads.included").values(default_limit=0)
        )
        await db.commit()
    try:
        customer, project, assessment = await assessed(api)
        [referral] = await consent(customer, project, assessment)
        [offer] = await offers_for(pat, p)
        assert offer["fee"] == {
            "included": False,
            "fee_cents": 2_500,
            "currency": "AUD",
            "included_used": 0,
            "included_limit": 0,
            "balance_cents": 0,
            "can_afford": False,
            "explanation": offer["fee"]["explanation"],
        }
        claim_url = f"{leads_url(p)}/{offer['lead']['match_id']}/claim"
        r = await pat.post(claim_url)
        assert r.status_code == 402 and r.json()["detail"]["code"] == "insufficient_credit"

        # Staff give promotional credit; the claim is charged from it in the same step.
        r = await admin.post(
            f"{LEADS_ADMIN}/partners/{p['id']}/credits",
            json={"kind": "PROMO", "delta_cents": 4_000, "note": "Welcome credit"},
        )
        assert r.status_code == 200 and r.json()["balance_cents"] == 4_000
        r = await pat.post(claim_url)
        assert r.status_code == 200, r.text
        assert (r.json()["claim"]["fee_cents"], r.json()["claim"]["included"]) == (2_500, False)
        credits = (await pat.get(credits_url)).json()
        assert credits["balance_cents"] == 1_500
        assert [e["kind"] for e in credits["entries"]] == ["LEAD_CHARGE", "PROMO"]

        # A bad lead: staff refund the fee as credit, once.
        r = await admin.get(LEADS_ADMIN)
        lead = next(x for x in r.json() if x["id"] == referral["leads"][0]["id"])
        claim_id = lead["matches"][0]["claim_id"]
        r = await admin.post(f"{LEADS_ADMIN}/claims/{claim_id}/refund", json={"note": "Duplicate"})
        assert r.status_code == 200 and r.json()["balance_cents"] == 4_000
        r = await admin.post(f"{LEADS_ADMIN}/claims/{claim_id}/refund", json={"note": "Again!"})
        assert r.status_code == 409

        # Buying credit: a Stripe Checkout page; credit lands when the signed webhook does.
        r = await pat.post(f"{credits_url}/checkout")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_on_sale"
        await set_price(admin, "lead.credits", 10_000)
        r = await pat.post(f"{credits_url}/checkout")
        assert r.status_code == 200, r.text
        session = stripe_api.last("/v1/checkout/sessions")
        assert (
            session["success_url"] == "http://partners.localhost:3000/partner/leads?credits=bought"
        )
        paid = event(
            "checkout.session.completed",
            {
                "id": "cs_credits",
                "object": "checkout.session",
                "mode": "payment",
                "payment_status": "paid",
                "payment_intent": f"pi_{uuid.uuid4().hex[:8]}",
                "customer": session["customer"],
                "metadata": {"payment_id": session["metadata[payment_id]"]},
            },
        )
        assert (await deliver(api, paid)).status_code == 200
        assert (await deliver(api, paid)).status_code == 200  # Stripe retries: credited once
        credits = (await pat.get(credits_url)).json()
        assert credits["balance_cents"] == 14_000
        assert credits["entries"][0]["kind"] == "PURCHASE"
        assert [e["balance_after_cents"] for e in credits["entries"]] == [
            14_000,
            4_000,
            1_500,
            4_000,
        ]
    finally:
        async with owner_sessions() as db:
            await db.execute(
                update(Feature)
                .where(Feature.key == "partner.leads.included")
                .values(default_limit=3)
            )
            await db.commit()
    # The ledger is append-only and can't go below zero.
    async with api.app.state.resources.session_factory() as db:
        from app.db.tenant import bind_tenant
        from app.modules.leads.models import CreditLedgerEntry

        await bind_tenant(db, uuid.UUID(p["organisation_id"]))
        with pytest.raises(DBAPIError):
            await db.execute(update(CreditLedgerEntry).values(note="edited"))
        await db.rollback()


async def test_withdrawing_stops_new_claims(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    staff = await platform_user(api, "STAFF")
    first = await partner(api, staff, name="Early Planning")
    second = await partner(api, staff, name="Late Planning")
    customer, project, assessment = await assessed(api)
    [referral] = await consent(customer, project, assessment)
    [early] = await offers_for(*first)
    r = await first[0].post(f"{leads_url(first[1])}/{early['lead']['match_id']}/claim")
    assert r.status_code == 200

    r = await customer.post(f"{referrals_url(customer, project)}/{referral['id']}/withdraw")
    assert r.status_code == 200, r.text
    [body] = r.json()
    assert body["withdrawn_at"] and body["leads"][0]["status"] == "WITHDRAWN"
    [late] = await offers_for(*second)
    r = await second[0].post(f"{leads_url(second[1])}/{late['lead']['match_id']}/claim")
    assert r.status_code == 409
    _, _, has_contact = await lead_rows(owner_sessions, referral["leads"][0]["id"])
    assert not has_contact
    # The partner who accepted first keeps what was released to it.
    got = (await first[0].get(f"{leads_url(first[1])}/{early['lead']['match_id']}")).json()
    assert got["claim"]["contact"]["phone"] == CUSTOMER_PHONE
    # Asking again for the same work is allowed once withdrawn.
    assert len(await consent(customer, project, assessment)) == 2


async def test_partner_roles_and_isolation(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    pat, p = await partner(api, staff)
    other_user, other = await partner(api, staff, name="Other Planning")
    customer, project, assessment = await assessed(api)
    await consent(customer, project, assessment, max_providers=1)
    [offer] = await offers_for(pat, p)
    match_id = offer["lead"]["match_id"]

    # Another partner can't reach this partner's offer, even through its own account.
    r = await other_user.get(f"{leads_url(other)}/{match_id}")
    if (await offers_for(other_user, other)) and r.status_code == 200:
        assert r.json()["lead"]["match_id"] != match_id
    r = await other_user.get(f"{leads_url(p)}/{match_id}")
    assert r.status_code == 404
    # Customers have no partner routes.
    r = await customer.get(f"/v1/organisations/{customer.personal_org_id}/partner/leads")
    assert r.status_code in (403, 404)

    # A partner team member can accept referrals but not change lead preferences.
    member = await api.user(name="Team Member")
    r = await pat.post(
        f"/v1/organisations/{p['organisation_id']}/invitations",
        json={"email": member.email, "roles": ["PARTNER_USER"]},
    )
    assert r.status_code == 201, r.text
    token = api.token_from(api.last_email(member.email, "org.invitation"), "accept")
    assert (await member.post("/v1/invitations/accept", json={"token": token})).status_code == 200
    r = await member.patch(
        f"/v1/organisations/{p['organisation_id']}/partner/lead-preferences",
        json={"paused": True},
    )
    assert r.status_code == 403
    r = await member.post(f"{leads_url(p)}/{match_id}/claim")
    assert r.status_code == 200, r.text
