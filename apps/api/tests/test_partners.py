"""Partner accounts (Milestone 14): applying, staff verification of credentials, categories
and the partner, service areas, and partner plans with their limits and grace period."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import PaymentsProviderKind, Settings
from app.main import create_app
from app.modules.billing.catalogue import load_bundled
from app.modules.billing.models import Price
from tests.conftest import make_settings
from tests.harness import ApiHarness, User, platform_user
from tests.test_billing import WEBHOOK_SECRET, FakeStripe, _sub, deliver, event, set_price

pytestmark = pytest.mark.integration

ADMIN = "/v1/admin/partners"
ABN = "51824753556"


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
async def no_prices_left_behind(
    owner_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """Prices are platform-wide: take them off sale so plan limits don't leak."""
    yield
    async with owner_sessions() as db:
        await db.execute(
            update(Price)
            .where(Price.active.is_(True))
            .values(active=False, deactivated_at=text("now()"))
        )
        await db.commit()


def application(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Reef Certifiers",
        "abn": "51 824 753 556",
        "website": "reefcertifiers.example.com.au",
        "phone": "(07) 4000 0000",
        "contact_email": "hello@reefcertifiers.example.com.au",
        "description": "Building certification for homes and small commercial fit-outs in Cairns.",
        "categories": ["building_certifier", "town_planner"],
        "service_areas": [
            {"kind": "LGA", "state": "QLD", "value": "  Cairns "},
            {"kind": "POSTCODE", "state": "QLD", "value": "4870"},
        ],
        "credentials": [
            {
                "kind": "LICENCE",
                "issuer": "QBCC",
                "number": "1234567",
                "expires_on": "2099-06-30",
                "category_keys": ["building_certifier"],
            },
            {
                "kind": "PI_INSURANCE",
                "issuer": "Example Insurance",
                "number": "PI-42",
                "cover_cents": 200_000_000,
                "expires_on": "2099-01-31",
            },
        ],
        "declaration": True,
    }
    body.update(overrides)
    return body


async def apply(api: ApiHarness, **overrides: Any) -> tuple[User, dict[str, Any]]:
    user = await api.user(name="Pat Partner")
    r = await user.post("/v1/partners/applications", json=application(**overrides))
    assert r.status_code == 201, r.text
    partner = r.json()
    r = await user.put(
        "/v1/auth/session/organisation", json={"organisation_id": partner["organisation_id"]}
    )
    assert r.status_code == 200, r.text
    return user, partner


def url(partner: dict[str, Any]) -> str:
    return f"/v1/organisations/{partner['organisation_id']}/partner"


def category(partner: dict[str, Any], key: str) -> dict[str, Any]:
    return next(c for c in partner["categories"] if c["category_key"] == key)


def credential(partner: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(c for c in partner["credentials"] if c["kind"] == kind)


async def approve(api: ApiHarness, staff: User, partner: dict[str, Any]) -> dict[str, Any]:
    """Staff check the licence, approve both categories and the partner."""
    base = f"{ADMIN}/{partner['id']}"
    r = await staff.post(
        f"{base}/credentials/{credential(partner, 'LICENCE')['id']}",
        json={"status": "VERIFIED", "notes": "Checked on the QBCC register."},
    )
    assert r.status_code == 200, r.text
    for key in ("building_certifier", "town_planner"):
        r = await staff.post(
            f"{base}/categories/{category(partner, key)['id']}", json={"status": "APPROVED"}
        )
        assert r.status_code == 200, r.text
    r = await staff.post(f"{base}/status", json={"status": "ACTIVE"})
    assert r.status_code == 200, r.text
    return dict(r.json())


# --- Pure parts ---------------------------------------------------------------------------


def test_partner_plans_are_in_the_catalogue() -> None:
    catalogue = load_bundled()
    plans = {p.key: p for p in catalogue.products if p.kind == "PARTNER_PLAN"}
    assert set(plans) == {"partner.standard", "partner.pro"}
    assert plans["partner.pro"].features["partner.categories.max"] is None
    features = {f.key: f.default_limit for f in catalogue.features}
    assert features["partner.categories.max"] == 1


def test_partner_portal_origin_is_always_allowed() -> None:
    s = make_settings(
        cors_origins=["https://approvalready.au"],
        web_base_url="https://app.approvalready.au/",
        partners_base_url="https://partners.approvalready.au",
    )
    assert s.allowed_origins == [
        "https://approvalready.au",
        "https://app.approvalready.au",
        "https://partners.approvalready.au",
    ]
    assert make_settings(web_base_url="https://app.example").partners_url == "https://app.example"


# --- Applying -----------------------------------------------------------------------------


async def test_applications_are_checked(api: ApiHarness) -> None:
    user = await api.user()
    bad = [
        application(abn="12345678901"),
        application(declaration=False),
        application(description="Too short"),
        application(categories=[]),
        application(categories=["town_planner", "town_planner"]),
        application(service_areas=[{"kind": "POSTCODE", "state": "QLD", "value": "48"}]),
        application(
            credentials=[
                {"kind": "LICENCE", "issuer": "x", "number": "1", "category_keys": ["plumber"]}
            ]
        ),
        application(website="not a website"),
    ]
    for body in bad:
        r = await user.post("/v1/partners/applications", json=body)
        assert r.status_code == 422, (body, r.text)
    r = await user.post(
        "/v1/partners/applications", json=application(categories=["not_a_category"], credentials=[])
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_category"
    assert (await api.client.post("/v1/partners/applications", json=application())).status_code in (
        401,
        403,
    )


async def test_apply_creates_a_partner_account(api: ApiHarness) -> None:
    user, partner = await apply(api)
    assert partner["status"] == "APPLIED"
    assert partner["name"] == "Reef Certifiers" and partner["abn"] == ABN
    assert partner["website"] == "https://reefcertifiers.example.com.au"
    assert [(a["kind"], a["value"]) for a in partner["service_areas"]] == [
        ("LGA", "Cairns"),
        ("POSTCODE", "4870"),
    ]
    certifier = category(partner, "building_certifier")
    assert certifier["status"] == "PENDING" and certifier["requires_credential"]
    assert certifier["credential_id"] == credential(partner, "LICENCE")["id"]
    assert category(partner, "town_planner")["credential_id"] is None
    assert not partner["receiving_referrals"]
    assert "We haven't checked your application yet." in partner["problems"]
    assert partner["plan"]["name"] == "Free"
    assert partner["details_locked"] is False
    [submitted] = partner["applications"]
    assert submitted["status"] == "SUBMITTED" and submitted["submitted_payload"] is None
    assert api.last_email(user.email, "partner.applied").links["portal"] == (
        "http://partners.localhost:3000/partner"
    )

    # The applicant administers the new partner organisation.
    r = await user.get(f"/v1/organisations/{partner['organisation_id']}")
    assert r.json()["kind"] == "PARTNER" and r.json()["roles"] == ["PARTNER_ADMIN"]
    assert "partner.manage" in r.json()["permissions"]
    # One open application at a time.
    r = await user.post("/v1/partners/applications", json=application(name="Second"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "application_open"
    # A customer's own organisation isn't a partner account; strangers see nothing.
    assert (await user.get(f"/v1/organisations/{user.personal_org_id}/partner")).status_code == 404
    stranger = await api.user()
    assert (await stranger.get(url(partner))).status_code == 404


async def test_partner_edits_its_profile(api: ApiHarness) -> None:
    user, partner = await apply(api)
    base = url(partner)
    r = await user.patch(base, json={"name": "Reef Certifiers Pty Ltd", "phone": "0400 000 000"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Reef Certifiers Pty Ltd" and r.json()["phone"] == "0400 000 000"

    r = await user.post(f"{base}/categories", json={"category_key": "plumber"})
    assert r.status_code == 201
    r = await user.post(f"{base}/categories", json={"category_key": "plumber"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "category_exists"
    r = await user.post(
        f"{base}/service-areas", json={"kind": "LGA", "state": "QLD", "value": "cairns"}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "area_exists"
    r = await user.post(f"{base}/service-areas", json={"kind": "STATE", "state": "QLD"})
    assert r.status_code == 201
    assert r.json()["service_areas"][-1] == {
        **r.json()["service_areas"][-1],
        "kind": "STATE",
        "value": "QLD",
    }
    r = await user.post(
        f"{base}/credentials",
        json={
            "kind": "LICENCE",
            "issuer": "QBCC",
            "number": "P-99",
            "category_keys": ["plumber"],
        },
    )
    assert r.status_code == 201, r.text
    plumber = category(r.json(), "plumber")
    licence = next(c for c in r.json()["credentials"] if c["number"] == "P-99")
    assert plumber["credential_id"] == licence["id"]
    r = await user.delete(f"{base}/credentials/{licence['id']}")
    assert category(r.json(), "plumber")["credential_id"] is None
    r = await user.delete(f"{base}/categories/{plumber['id']}")
    assert "plumber" not in [c["category_key"] for c in r.json()["categories"]]
    area = r.json()["service_areas"][-1]
    r = await user.delete(f"{base}/service-areas/{area['id']}")
    assert len(r.json()["service_areas"]) == 2


async def test_staff_verify_and_approve_a_partner(api: ApiHarness) -> None:
    user, partner = await apply(api)
    staff = await platform_user(api, "STAFF")
    customer = await api.user()
    assert (await customer.get(ADMIN)).status_code == 403
    r = await staff.get(ADMIN, params={"status": "APPLIED"})
    summary = next(p for p in r.json() if p["id"] == partner["id"])
    assert summary["pending_categories"] == 2 and summary["unchecked_credentials"] == 2
    r = await staff.get(f"{ADMIN}/{partner['id']}")
    detail = r.json()
    assert detail["members"][0]["email"] == user.email
    payload = detail["applications"][0]["submitted_payload"]
    assert sorted(payload["categories"]) == ["building_certifier", "town_planner"]
    assert payload["abn"] == ABN and len(payload["credentials"]) == 2

    base = f"{ADMIN}/{partner['id']}"
    r = await staff.post(f"{base}/status", json={"status": "UNDER_REVIEW"})
    assert r.json()["status"] == "UNDER_REVIEW"
    # Approving needs an approved category; a certifier needs a checked licence first.
    r = await staff.post(f"{base}/status", json={"status": "ACTIVE"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_ready"
    certifier = category(partner, "building_certifier")
    r = await staff.post(f"{base}/categories/{certifier['id']}", json={"status": "APPROVED"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "credential_needed"
    r = await staff.post(
        f"{base}/credentials/{credential(partner, 'LICENCE')['id']}", json={"status": "REJECTED"}
    )
    assert r.status_code == 422  # say why
    r = await staff.post(f"{base}/status", json={"status": "SUSPENDED", "reason": "Not active yet"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "bad_transition"

    approved = await approve(api, staff, partner)
    assert approved["status"] == "ACTIVE" and approved["receiving_referrals"]
    assert approved["applications"][0]["status"] == "APPROVED"
    assert all(c["counts"] for c in approved["categories"])
    assert api.last_email(user.email, "partner.status_changed").subject.endswith("approved")

    r = await user.get(url(partner))
    assert r.json()["receiving_referrals"] and r.json()["problems"] == []
    assert r.json()["details_locked"]
    r = await user.patch(url(partner), json={"abn": "53004085616"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "details_locked"
    r = await user.patch(
        url(partner), json={"description": "We certify homes and fit-outs in Far North Queensland."}
    )
    assert r.status_code == 200

    # Changing the credential behind an approved certifier category sends it back for checking.
    r = await user.post(
        f"{url(partner)}/credentials",
        json={
            "kind": "LICENCE",
            "issuer": "QBCC",
            "number": "NEW-1",
            "category_keys": ["building_certifier"],
        },
    )
    assert category(r.json(), "building_certifier")["status"] == "PENDING"
    assert category(r.json(), "town_planner")["counts"] and r.json()["receiving_referrals"]

    # Suspend (with a reason the partner sees) and reinstate.
    r = await staff.post(f"{base}/status", json={"status": "SUSPENDED"})
    assert r.status_code == 422
    r = await staff.post(
        f"{base}/status", json={"status": "SUSPENDED", "reason": "Insurance certificate lapsed."}
    )
    assert r.json()["status"] == "SUSPENDED"
    r = await user.get(url(partner))
    assert not r.json()["receiving_referrals"]
    assert r.json()["status_reason"] == "Insurance certificate lapsed."
    assert "suspended" in api.last_email(user.email, "partner.status_changed").subject
    r = await staff.post(f"{base}/status", json={"status": "ACTIVE"})
    assert r.json()["status"] == "ACTIVE" and r.json()["status_reason"] is None


async def test_rejected_partner_fixes_and_resubmits(api: ApiHarness) -> None:
    user, partner = await apply(api)
    staff = await platform_user(api, "STAFF")
    base = f"{ADMIN}/{partner['id']}"
    r = await staff.post(
        f"{base}/categories/{category(partner, 'town_planner')['id']}",
        json={"status": "REJECTED", "notes": "Add your PIA membership."},
    )
    assert category(r.json(), "town_planner")["problems"] == ["Not approved."]
    r = await staff.post(f"{base}/status", json={"status": "REJECTED", "reason": "short"})
    assert r.status_code == 422
    r = await staff.post(
        f"{base}/status",
        json={"status": "REJECTED", "reason": "We couldn't confirm the licence on the register."},
    )
    assert r.json()["status"] == "REJECTED"
    assert r.json()["applications"][0]["status"] == "REJECTED"

    r = await user.get(url(partner))
    assert r.json()["status_reason"] == "We couldn't confirm the licence on the register."
    assert r.json()["applications"][0]["decision_notes"] == r.json()["status_reason"]
    assert not r.json()["details_locked"]
    r = await user.post(f"{url(partner)}/resubmit")
    assert r.status_code == 200, r.text
    again = r.json()
    assert again["status"] == "APPLIED" and again["status_reason"] is None
    assert [a["status"] for a in again["applications"]] == ["SUBMITTED", "REJECTED"]
    assert category(again, "town_planner")["status"] == "PENDING"
    r = await user.post(f"{url(partner)}/resubmit")
    assert r.status_code == 409


async def test_who_can_do_what(api: ApiHarness) -> None:
    user, partner = await apply(api)
    org_id = partner["organisation_id"]
    member_email = f"staffer-{uuid.uuid4().hex[:8]}@example.com"
    r = await user.post(
        f"/v1/organisations/{org_id}/invitations",
        json={"email": member_email, "roles": ["PARTNER_USER"]},
    )
    assert r.status_code == 201, r.text
    token = api.token_from(api.last_email(member_email, "org.invitation"), "accept")
    member = await api.user(email=member_email)
    assert (await member.post("/v1/invitations/accept", json={"token": token})).status_code == 200
    assert (await member.get(url(partner))).status_code == 200
    r = await member.post(f"{url(partner)}/service-areas", json={"kind": "STATE", "state": "NSW"})
    assert r.status_code == 403

    # Staff never check their own partner account.
    staff = await platform_user(api, "STAFF")
    r = await staff.post("/v1/partners/applications", json=application(name="Staff Side Hustle"))
    own = r.json()
    r = await staff.post(
        f"{ADMIN}/{own['id']}/credentials/{credential(own, 'LICENCE')['id']}",
        json={"status": "VERIFIED"},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "own_partner"


async def test_expired_credentials_stop_referrals(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user, partner = await apply(api)
    staff = await platform_user(api, "STAFF")
    await approve(api, staff, partner)
    licence = credential(partner, "LICENCE")
    async with owner_sessions() as db:
        await db.execute(
            text("UPDATE partner_credential SET expires_on = current_date - 1 WHERE id = :id"),
            {"id": licence["id"]},
        )
        await db.commit()
    r = await user.get(url(partner))
    certifier = category(r.json(), "building_certifier")
    assert not certifier["counts"]
    assert certifier["problems"] == ["Its licence or accreditation has expired."]
    assert not credential(r.json(), "LICENCE")["current"]
    # The town planner category needs no licence, so referrals continue for it.
    assert category(r.json(), "town_planner")["counts"] and r.json()["receiving_referrals"]
    r = await staff.post(
        f"{ADMIN}/{partner['id']}/credentials/{licence['id']}", json={"status": "VERIFIED"}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "credential_expired"


# --- Plans --------------------------------------------------------------------------------


async def test_partner_plans_lift_limits_with_a_grace_period(
    api: ApiHarness, stripe_api: FakeStripe, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user, partner = await apply(api)
    staff = await platform_user(api, "STAFF")
    await approve(api, staff, partner)
    org = f"/v1/organisations/{partner['organisation_id']}"
    # No partner plan on sale: no limit applies, both categories count.
    r = await user.get(url(partner))
    assert all(c["counts"] for c in r.json()["categories"])
    assert {x["feature"]: x["limit"] for x in r.json()["plan"]["limits"]} == {
        "partner.categories.max": None,
        "partner.service_areas.max": None,
        "partner.members.max": None,
    }

    admin = await platform_user(api, "ADMIN")
    standard = await set_price(admin, "partner.standard", 9_900, "MONTH")
    rent = await set_price(admin, "rent.manage", 2_900, "MONTH")
    r = await user.get(url(partner))
    body = r.json()
    assert body["plan"]["name"] == "Free"
    # The free plan covers one category: the first one approved still counts.
    assert [c["counts"] for c in body["categories"]].count(True) == 1
    blocked = next(c for c in body["categories"] if not c["counts"])
    assert blocked["problems"] == ["Your plan doesn't cover this many categories."]
    assert body["receiving_referrals"]

    # The billing page offers partner plans to partners (and customer plans to customers).
    r = await user.get(f"{org}/billing")
    assert [p["key"] for p in r.json()["plans"]] == ["partner.standard"]
    assert {a["feature"] for a in r.json()["allowances"]} == {
        "partner.categories.max",
        "partner.service_areas.max",
        "partner.members.max",
    }
    r = await user.post(f"{org}/billing/checkout", json={"price_id": rent["id"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "price_unavailable"
    customer = await api.user()
    r = await customer.post(
        f"/v1/organisations/{customer.personal_org_id}/billing/checkout",
        json={"price_id": standard["id"]},
    )
    assert r.status_code == 409

    # The free plan has 2 seats: the applicant and one more.
    r = await user.post(
        f"{org}/invitations",
        json={"email": f"a-{uuid.uuid4().hex[:6]}@example.com", "roles": ["PARTNER_USER"]},
    )
    assert r.status_code == 201
    r = await user.post(
        f"{org}/invitations",
        json={"email": f"b-{uuid.uuid4().hex[:6]}@example.com", "roles": ["PARTNER_USER"]},
    )
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_limit"

    r = await user.post(f"{org}/billing/checkout", json={"price_id": standard["id"]})
    assert r.status_code == 200, r.text
    session = stripe_api.last("/v1/checkout/sessions")
    assert session["success_url"] == "http://partners.localhost:3000/partner/billing?checkout=done"
    now = int(time.time())
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    await deliver(
        api,
        event(
            "customer.subscription.created",
            _sub(session["customer"], standard["id"], "active", sub_id=sub_id),
            created=now,
        ),
    )
    r = await user.get(url(partner))
    assert r.json()["plan"]["name"] == "Partner Standard"
    assert r.json()["plan"]["status"] == "ACTIVE"
    assert all(c["counts"] for c in r.json()["categories"])

    # Payment fails: the plan keeps working through the grace period, then lapses.
    await deliver(
        api,
        event(
            "customer.subscription.updated",
            _sub(session["customer"], standard["id"], "past_due", sub_id=sub_id),
            created=now + 5,
        ),
    )
    r = await user.get(url(partner))
    assert r.json()["plan"]["grace_ends_at"] and all(c["counts"] for c in r.json()["categories"])
    r = await user.get(f"{org}/billing")
    assert r.json()["subscriptions"][0]["grace_ends_at"]
    async with owner_sessions() as db:
        await db.execute(
            text(
                "UPDATE subscription SET past_due_since = now() - interval '8 days' "
                "WHERE stripe_subscription_id = :s"
            ),
            {"s": sub_id},
        )
        await db.commit()
    r = await user.get(url(partner))
    assert [c["counts"] for c in r.json()["categories"]].count(True) == 1
    assert r.json()["plan"]["status"] == "PAST_DUE"
