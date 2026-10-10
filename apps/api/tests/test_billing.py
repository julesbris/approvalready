"""Customer payments (Milestone 13): the catalogue and prices, Stripe Checkout and the
portal, verified and idempotent webhooks, subscriptions and plan limits, paid reviews."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import PaymentsProviderKind, Settings
from app.main import create_app
from app.modules.billing.catalogue import load_bundled
from app.modules.billing.models import Price, StripeEvent
from app.modules.billing.stripe import (
    SignatureError,
    encode_form,
    sign_payload,
    verify_webhook,
)
from tests.conftest import make_settings
from tests.harness import ApiHarness, User, platform_user
from tests.test_assessments import org_url
from tests.test_documents import _assessed

WEBHOOK_SECRET = "whsec_test_secret"
WEBHOOK = "/v1/billing/stripe/webhook"
ADMIN = "/v1/admin/billing"


# --- Pure parts ---------------------------------------------------------------------------


def test_form_encoding_matches_stripe() -> None:
    assert encode_form(
        {
            "mode": "payment",
            "line_items": [{"price_data": {"unit_amount": 500, "currency": "aud"}, "quantity": 1}],
            "metadata": {"a": "b"},
            "invoice_creation": {"enabled": True},
            "skip": None,
        }
    ) == [
        ("mode", "payment"),
        ("line_items[0][price_data][unit_amount]", "500"),
        ("line_items[0][price_data][currency]", "aud"),
        ("line_items[0][quantity]", "1"),
        ("metadata[a]", "b"),
        ("invoice_creation[enabled]", "true"),
    ]


def test_webhook_signatures_are_checked() -> None:
    payload = json.dumps({"id": "evt_1", "object": "event", "type": "x"}).encode()
    now = 1_800_000_000
    header = sign_payload(payload, WEBHOOK_SECRET, now)
    assert verify_webhook(payload, header, WEBHOOK_SECRET, tolerance=300, now=now)["id"] == "evt_1"
    # Several v1 signatures (secret rolling): any match is enough.
    rolled = f"{header},v1={'0' * 64}"
    assert verify_webhook(payload, rolled, WEBHOOK_SECRET, tolerance=300, now=now)
    bad = [
        (payload, None),
        (payload, "nonsense"),
        (payload, sign_payload(payload, "whsec_other", now)),
        (payload + b" ", header),  # body changed after signing
        (payload, sign_payload(payload, WEBHOOK_SECRET, now - 301)),  # replayed later
    ]
    for body, sig in bad:
        with pytest.raises(SignatureError):
            verify_webhook(body, sig, WEBHOOK_SECRET, tolerance=300, now=now)
    not_event = json.dumps({"id": "x", "object": "charge"}).encode()
    with pytest.raises(SignatureError):
        verify_webhook(
            not_event,
            sign_payload(not_event, WEBHOOK_SECRET, now),
            WEBHOOK_SECRET,
            tolerance=300,
            now=now,
        )


def test_catalogue_file_is_valid() -> None:
    catalogue = load_bundled()
    keys = {p.key for p in catalogue.products}
    assert {
        f"review.{v}" for v in ("planning", "vessel", "business", "grant", "sell", "rent")
    } <= keys
    assert {"rent.manage", "rent.manage_plus"} <= keys


def test_stripe_needs_both_secrets_in_production() -> None:
    with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            app_env="production",
            secret_key="x" * 40,
            cors_origins=["https://app.example.com"],
            web_base_url="https://app.example.com",
            malware_scanner="clamav",
            payments_provider="stripe",
            stripe_secret_key="sk_live_x",
        )
    assert not make_settings().payments_enabled
    assert make_settings(
        payments_provider="stripe", stripe_secret_key="sk_test_x", stripe_webhook_secret="w"
    ).payments_enabled


# --- A fake Stripe API ------------------------------------------------------------------


@dataclass
class FakeStripe:
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    fail: bool = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(parse_qsl(request.content.decode()))
        path = request.url.path
        self.calls.append((path, params))
        if self.fail:
            return httpx.Response(500, json={"error": {"message": "Stripe is down"}})
        if path == "/v1/customers":
            return httpx.Response(200, json={"id": f"cus_{uuid.uuid4().hex[:14]}"})
        if path == "/v1/checkout/sessions":
            sid = f"cs_test_{uuid.uuid4().hex[:16]}"
            return httpx.Response(
                200, json={"id": sid, "url": f"https://checkout.stripe.com/c/pay/{sid}"}
            )
        if path.endswith("/expire"):
            return httpx.Response(200, json={"id": path.split("/")[-2], "status": "expired"})
        if path == "/v1/billing_portal/sessions":
            return httpx.Response(200, json={"url": "https://billing.stripe.com/p/session/x"})
        return httpx.Response(404, json={"error": {"message": "no such route"}})

    def last(self, path: str) -> dict[str, str]:
        return next(p for c, p in reversed(self.calls) if c == path)


@pytest.fixture
def stripe_api() -> FakeStripe:
    return FakeStripe()


@pytest.fixture
def settings() -> Settings:
    return make_settings(
        payments_provider=PaymentsProviderKind.STRIPE,
        stripe_secret_key="sk_test_123",
        stripe_webhook_secret=WEBHOOK_SECRET,
    )


@pytest.fixture
def app(settings: Settings, stripe_api: FakeStripe) -> FastAPI:
    return create_app(settings, stripe_transport=httpx.MockTransport(stripe_api.handle))


@pytest.fixture(autouse=True)
async def no_prices_left_behind(
    owner_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """Prices are platform-wide: take them off sale after each test, so plan limits and
    review prices don't reach other tests."""
    yield
    async with owner_sessions() as db:
        await db.execute(
            update(Price)
            .where(Price.active.is_(True))
            .values(active=False, deactivated_at=text("now()"))
        )
        await db.commit()


# --- Helpers ----------------------------------------------------------------------------


async def products(admin: User) -> dict[str, dict[str, Any]]:
    r = await admin.get(f"{ADMIN}/products")
    assert r.status_code == 200, r.text
    return {p["key"]: p for p in r.json()}


async def set_price(
    admin: User, key: str, cents: int, interval: str = "ONE_TIME"
) -> dict[str, Any]:
    product = (await products(admin))[key]
    r = await admin.post(
        f"{ADMIN}/products/{product['id']}/prices",
        json={"amount_cents": cents, "interval": interval},
    )
    assert r.status_code == 201, r.text
    return next(p for p in r.json()["prices"] if p["active"] and p["interval"] == interval)


async def deliver(
    api: ApiHarness, event: dict[str, Any], *, secret: str = WEBHOOK_SECRET
) -> httpx.Response:
    payload = json.dumps(event).encode()
    return await api.client.post(
        WEBHOOK,
        content=payload,
        headers={
            "stripe-signature": sign_payload(payload, secret),
            "content-type": "application/json",
        },
    )


def event(kind: str, obj: dict[str, Any], *, created: int | None = None) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex[:20]}",
        "object": "event",
        "type": kind,
        "livemode": False,
        "created": created or int(time.time()),
        "data": {"object": obj},
    }


async def stored(api: ApiHarness, stripe_event_id: str) -> list[StripeEvent]:
    async with api.app.state.resources.session_factory() as db:
        return list(
            (
                await db.execute(
                    select(StripeEvent).where(StripeEvent.stripe_event_id == stripe_event_id)
                )
            ).scalars()
        )


# --- Prices -----------------------------------------------------------------------------


@pytest.mark.integration
async def test_staff_set_prices_and_prices_never_change(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin = await platform_user(api, "ADMIN")
    staff = await platform_user(api, "STAFF")
    assert (await staff.get(f"{ADMIN}/products")).status_code == 403
    r = await admin.get(f"{ADMIN}/status")
    assert r.json()["enabled"] and r.json()["test_mode"]
    assert "checkout.session.completed" in r.json()["webhook_events"]

    catalogue = await products(admin)
    manage = catalogue["rent.manage"]
    assert manage["features"] == [
        {
            "key": "rent.properties.max",
            "description": "Rental properties managed in RentReady",
            "limit": 10,
        }
    ]
    # A plan is charged by the month or year; a review once.
    r = await admin.post(
        f"{ADMIN}/products/{manage['id']}/prices",
        json={"amount_cents": 2900, "interval": "ONE_TIME"},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "interval_required"
    review = catalogue["review.planning"]
    r = await admin.post(
        f"{ADMIN}/products/{review['id']}/prices", json={"amount_cents": 100, "interval": "MONTH"}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "one_time_only"
    r = await admin.post(
        f"{ADMIN}/products/{review['id']}/prices", json={"amount_cents": 0, "interval": "ONE_TIME"}
    )
    assert r.status_code == 422

    first = await set_price(admin, "review.planning", 19_900)
    second = await set_price(admin, "review.planning", 24_900)
    prices = (await products(admin))["review.planning"]["prices"]
    assert [
        (p["amount_cents"], p["active"]) for p in prices if p["id"] in (first["id"], second["id"])
    ] == [
        (24_900, True),
        (19_900, False),
    ]

    # Customers see only what is on sale.
    customer = await api.user()
    r = await customer.get(f"{org_url(customer)}/billing/catalogue")
    on_sale = {p["key"]: p for p in r.json()["products"]}
    assert r.json()["enabled"] and on_sale["review.planning"]["prices"][0]["amount_cents"] == 24_900
    assert "rent.manage" not in on_sale

    # The database keeps a price as it was sold, even for the owner.
    async with owner_sessions() as db:
        with pytest.raises(DBAPIError, match="never changes"):
            await db.execute(
                text("UPDATE price SET amount_cents = 1 WHERE id = :id"), {"id": second["id"]}
            )
        await db.rollback()
        with pytest.raises(DBAPIError, match="stays deactivated"):
            await db.execute(
                text("UPDATE price SET active = true WHERE id = :id"), {"id": first["id"]}
            )
        await db.rollback()
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            await db.execute(text("DELETE FROM price WHERE id = :id"), {"id": first["id"]})
        await db.rollback()

    r = await admin.post(f"{ADMIN}/prices/{second['id']}/deactivate")
    assert r.status_code == 200
    r = await customer.get(f"{org_url(customer)}/billing/catalogue")
    assert "review.planning" not in {p["key"] for p in r.json()["products"]}


@pytest.mark.integration
async def test_nothing_is_for_sale_while_payments_are_off(client_factory: Any) -> None:
    async with client_factory() as client:
        api = ApiHarness(client._transport.app, client)  # type: ignore[attr-defined]
        try:
            customer = await api.user()
            r = await customer.get(f"{org_url(customer)}/billing/catalogue")
            assert r.json() == {"enabled": False, "products": []}
            r = await customer.get(f"{org_url(customer)}/billing")
            assert r.status_code == 200 and r.json()["enabled"] is False
            r = await customer.post(f"{org_url(customer)}/billing/portal")
            assert r.status_code == 409 and r.json()["detail"]["code"] == "payments_disabled"
            assert (await client.post(WEBHOOK, content=b"{}")).status_code == 404
        finally:
            await api.aclose()


# --- Paid reviews -----------------------------------------------------------------------


@pytest.mark.integration
async def test_paid_review_waits_for_a_verified_payment(
    api: ApiHarness, stripe_api: FakeStripe
) -> None:
    admin = await platform_user(api, "ADMIN")
    await set_price(admin, "review.planning", 24_900)
    customer, project, assessment = await _assessed(api)
    org = org_url(customer)

    r = await customer.post(
        f"{org}/projects/{project['id']}/reviews", json={"assessment_id": assessment["id"]}
    )
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["status"] == "PAYMENT_PENDING"
    assert review["payment"]["amount_cents"] == 24_900 and review["payment"]["status"] == "PENDING"
    r = await customer.get(f"{org}/projects/{project['id']}")
    assert r.json()["status"] != "IN_REVIEW"  # only once paid

    # Staff can't assign an unpaid review.
    r = await admin.post(
        f"/v1/admin/reviews/{review['id']}/assign", json={"professional_id": str(uuid.uuid4())}
    )
    assert r.status_code in (404, 409)

    r = await customer.post(f"{org}/reviews/{review['id']}/checkout")
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("https://checkout.stripe.com/")
    customer_call = stripe_api.last("/v1/customers")
    assert customer_call["metadata[organisation_id]"] == customer.personal_org_id
    session = stripe_api.last("/v1/checkout/sessions")
    assert session["mode"] == "payment"
    assert session["line_items[0][price_data][unit_amount]"] == "24900"
    assert session["line_items[0][price_data][currency]"] == "aud"
    assert session["metadata[payment_id]"] == review["payment"]["id"]
    assert session["success_url"].endswith(f"/assessments/{assessment['id']}?payment=done")
    first_session = stripe_api.calls[-1]

    # Asking again replaces the page and closes the earlier one at Stripe.
    r = await customer.post(f"{org}/reviews/{review['id']}/checkout")
    assert r.status_code == 200
    assert stripe_api.calls[-1][0].endswith("/expire")
    assert len([c for c, _ in stripe_api.calls if c == "/v1/customers"]) == 1
    assert first_session[0] == "/v1/checkout/sessions"

    # The browser coming back proves nothing: only a signed webhook does.
    r = await customer.get(f"{org}/reviews/{review['id']}")
    assert r.json()["status"] == "PAYMENT_PENDING"
    forged = event(
        "checkout.session.completed",
        {
            "id": "cs_x",
            "object": "checkout.session",
            "mode": "payment",
            "payment_status": "paid",
            "customer": session["customer"],
            "metadata": {"payment_id": review["payment"]["id"]},
        },
    )
    assert (await deliver(api, forged, secret="whsec_wrong")).status_code == 400
    assert (await customer.get(f"{org}/reviews/{review['id']}")).json()[
        "status"
    ] == "PAYMENT_PENDING"

    paid = event(
        "checkout.session.completed",
        {
            "id": "cs_paid",
            "object": "checkout.session",
            "mode": "payment",
            "payment_status": "paid",
            "payment_intent": "pi_123",
            "customer": session["customer"],
            "metadata": {"payment_id": review["payment"]["id"]},
        },
    )
    r = await deliver(api, paid)
    assert r.status_code == 200 and r.json() == {"received": True}
    r = await customer.get(f"{org}/reviews/{review['id']}")
    assert r.json()["status"] == "REVIEW_REQUESTED"
    assert r.json()["payment"]["status"] == "PAID" and r.json()["payment"]["paid_at"]
    r = await customer.get(f"{org}/projects/{project['id']}")
    assert r.json()["status"] == "IN_REVIEW"

    # Stripe delivers again (or someone replays it): stored once, applied once.
    assert (await deliver(api, paid)).status_code == 200
    [row] = await stored(api, paid["id"])
    assert row.status == "PROCESSED" and row.attempts == 1
    assert str(row.organisation_id) == customer.personal_org_id

    r = await customer.get(f"{org}/billing")
    assert r.status_code == 200
    [payment] = r.json()["payments"]
    assert payment["status"] == "PAID" and payment["subject_id"] == review["id"]

    # A refund made in Stripe comes back as charge.refunded.
    refund = event(
        "charge.refunded",
        {
            "id": "ch_1",
            "object": "charge",
            "customer": session["customer"],
            "payment_intent": "pi_123",
            "amount": 24_900,
            "amount_refunded": 10_000,
        },
    )
    await deliver(api, refund)
    r = await customer.get(f"{org}/billing")
    assert r.json()["payments"][0]["status"] == "PARTIALLY_REFUNDED"
    assert r.json()["payments"][0]["refunded_cents"] == 10_000


@pytest.mark.integration
async def test_cancelling_an_unpaid_review_cancels_its_payment(
    api: ApiHarness, stripe_api: FakeStripe
) -> None:
    admin = await platform_user(api, "ADMIN")
    await set_price(admin, "review.planning", 9_900)
    customer, project, assessment = await _assessed(api)
    org = org_url(customer)
    review = (
        await customer.post(
            f"{org}/projects/{project['id']}/reviews", json={"assessment_id": assessment["id"]}
        )
    ).json()
    await customer.post(f"{org}/reviews/{review['id']}/checkout")
    session = stripe_api.last("/v1/checkout/sessions")
    r = await customer.post(f"{org}/reviews/{review['id']}/cancel")
    assert r.json()["status"] == "CANCELLED" and r.json()["payment"]["status"] == "CANCELLED"
    assert stripe_api.calls[-1][0].endswith("/expire")
    r = await customer.post(f"{org}/reviews/{review['id']}/checkout")
    assert r.status_code == 409

    # Paid anyway (the page was already open): recorded as paid, the review stays cancelled.
    late = event(
        "checkout.session.completed",
        {
            "id": "cs_late",
            "object": "checkout.session",
            "mode": "payment",
            "payment_status": "paid",
            "payment_intent": "pi_late",
            "customer": session["customer"],
            "metadata": {"payment_id": review["payment"]["id"]},
        },
    )
    await deliver(api, late)
    r = await customer.get(f"{org}/reviews/{review['id']}")
    assert r.json()["status"] == "CANCELLED" and r.json()["payment"]["status"] == "PAID"


@pytest.mark.integration
async def test_review_checkout_when_stripe_is_down(api: ApiHarness, stripe_api: FakeStripe) -> None:
    admin = await platform_user(api, "ADMIN")
    await set_price(admin, "review.planning", 9_900)
    customer, project, assessment = await _assessed(api)
    org = org_url(customer)
    review = (
        await customer.post(
            f"{org}/projects/{project['id']}/reviews", json={"assessment_id": assessment["id"]}
        )
    ).json()
    stripe_api.fail = True
    r = await customer.post(f"{org}/reviews/{review['id']}/checkout")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "payments_unavailable"
    assert "Stripe" not in r.json()["detail"]["message"]


# --- Plans and limits -------------------------------------------------------------------


async def _rent(user: User) -> int:
    r = await user.post(f"{org_url(user)}/projects", json={"vertical": "RENT", "title": "Unit"})
    assert r.status_code == 201, r.text
    r = await user.patch(f"{org_url(user)}/projects/{r.json()['id']}/rental", json={"bedrooms": 1})
    return r.status_code


def _sub(customer: str, price_id: str, status: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": extra.pop("sub_id", "sub_1"),
        "object": "subscription",
        "customer": customer,
        "status": status,
        "cancel_at_period_end": False,
        "items": {"data": [{"current_period_end": int(time.time()) + 30 * 86400}]},
        "metadata": {"price_id": price_id},
        **extra,
    }


@pytest.mark.integration
async def test_plans_come_from_stripe_and_lift_limits(
    api: ApiHarness, stripe_api: FakeStripe, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    owner = await api.user()
    org = org_url(owner)
    # No plan on sale yet: no limit applies.
    assert await _rent(owner) == 200
    assert await _rent(owner) == 200

    admin = await platform_user(api, "ADMIN")
    price = await set_price(admin, "rent.manage", 2_900, "MONTH")
    r = await owner.get(f"{org}/billing")
    body = r.json()
    [allowance] = body["allowances"]
    assert allowance == {
        "feature": "rent.properties.max",
        "description": "Rental properties managed in RentReady",
        "limit": 1,
        "in_use": 2,
        "enforced": True,
        "plan": None,
    }
    assert [p["key"] for p in body["plans"]] == ["rent.manage"]
    assert await _rent(owner) == 402

    # Only organisation admins handle billing; outsiders see nothing.
    stranger = await api.user()
    assert (await stranger.get(f"{org}/billing")).status_code == 404

    r = await owner.post(f"{org}/billing/portal")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_billing_account"
    r = await owner.post(f"{org}/billing/checkout", json={"price_id": price["id"]})
    assert r.status_code == 200, r.text
    session = stripe_api.last("/v1/checkout/sessions")
    assert session["mode"] == "subscription"
    assert session["line_items[0][price_data][recurring][interval]"] == "month"
    assert session["subscription_data[metadata][price_id]"] == price["id"]
    customer = session["customer"]

    now = int(time.time())
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    await deliver(
        api,
        event(
            "customer.subscription.created",
            _sub(customer, price["id"], "incomplete", sub_id=sub_id),
            created=now,
        ),
    )
    assert await _rent(owner) == 402
    await deliver(
        api,
        event(
            "customer.subscription.updated",
            _sub(customer, price["id"], "active", sub_id=sub_id),
            created=now + 5,
        ),
    )
    r = await owner.get(f"{org}/billing")
    [sub] = r.json()["subscriptions"]
    assert sub["status"] == "ACTIVE" and sub["gives_plan"] and sub["product_key"] == "rent.manage"
    assert r.json()["allowances"][0]["limit"] == 10
    assert r.json()["allowances"][0]["plan"] == "RentReady Manage"
    assert await _rent(owner) == 200

    # A second plan isn't sold while one is live; the portal manages it.
    r = await owner.post(f"{org}/billing/checkout", json={"price_id": price["id"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_exists"
    r = await owner.post(f"{org}/billing/portal")
    assert r.json()["url"].startswith("https://billing.stripe.com/")
    assert stripe_api.last("/v1/billing_portal/sessions")["customer"] == customer

    # An older event arriving late doesn't undo a newer one.
    late = event(
        "customer.subscription.updated",
        _sub(customer, price["id"], "incomplete", sub_id=sub_id),
        created=now + 1,
    )
    await deliver(api, late)
    assert (await stored(api, late["id"]))[0].status == "IGNORED"
    assert (await owner.get(f"{org}/billing")).json()["subscriptions"][0]["status"] == "ACTIVE"

    # Past due: the plan keeps working through the grace period, then stops.
    await deliver(
        api,
        event(
            "customer.subscription.updated",
            _sub(customer, price["id"], "past_due", sub_id=sub_id),
            created=now + 10,
        ),
    )
    r = await owner.get(f"{org}/billing")
    assert r.json()["subscriptions"][0]["gives_plan"] and r.json()["allowances"][0]["limit"] == 10
    async with owner_sessions() as db:
        await db.execute(
            text(
                "UPDATE subscription SET past_due_since = now() - interval '8 days' "
                "WHERE stripe_subscription_id = :s"
            ),
            {"s": sub_id},
        )
        await db.commit()
    r = await owner.get(f"{org}/billing")
    assert not r.json()["subscriptions"][0]["gives_plan"]
    assert r.json()["allowances"][0]["limit"] == 1

    # Cancelled in the portal.
    await deliver(
        api,
        event(
            "customer.subscription.deleted",
            _sub(customer, price["id"], "canceled", sub_id=sub_id, canceled_at=now + 20),
            created=now + 20,
        ),
    )
    r = await owner.get(f"{org}/billing")
    assert r.json()["subscriptions"][0]["status"] == "CANCELED"
    assert r.json()["subscriptions"][0]["canceled_at"]

    # Invoices: number, amounts and Stripe's links, newest first; drafts are not listed.
    invoice = {
        "id": f"in_{uuid.uuid4().hex[:12]}",
        "object": "invoice",
        "customer": customer,
        "status": "draft",
        "number": None,
        "amount_due": 2900,
        "amount_paid": 0,
        "currency": "aud",
        "created": now,
        "parent": {"subscription_details": {"subscription": sub_id}},
    }
    await deliver(api, event("invoice.created", invoice, created=now))
    assert (await owner.get(f"{org}/billing")).json()["invoices"] == []
    invoice |= {
        "status": "paid",
        "number": "AR-0001",
        "amount_paid": 2900,
        "hosted_invoice_url": "https://invoice.stripe.com/i/x",
        "invoice_pdf": "https://pay.stripe.com/x.pdf",
    }
    await deliver(api, event("invoice.paid", invoice, created=now + 1))
    [inv] = (await owner.get(f"{org}/billing")).json()["invoices"]
    assert (
        inv["number"] == "AR-0001" and inv["status"] == "PAID" and inv["amount_paid_cents"] == 2900
    )


@pytest.mark.integration
async def test_events_we_cannot_place_are_ignored_and_staff_can_follow_them(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    stranger = event(
        "customer.subscription.updated", _sub("cus_not_ours", str(uuid.uuid4()), "active")
    )
    assert (await deliver(api, stranger)).status_code == 200
    [row] = await stored(api, stranger["id"])
    assert row.status == "IGNORED" and row.organisation_id is None
    other = event("payment_intent.created", {"id": "pi_1", "object": "payment_intent"})
    await deliver(api, other)
    assert (await stored(api, other["id"]))[0].status == "IGNORED"

    admin = await platform_user(api, "ADMIN")
    r = await admin.get(f"{ADMIN}/events?status=IGNORED&limit=200")
    assert stranger["id"] in {e["stripe_event_id"] for e in r.json()}
    assert "payload" not in r.json()[0]
    r = await admin.post(f"{ADMIN}/events/{row.id}/retry")
    assert r.status_code == 409

    # A stored event never changes.
    async with owner_sessions() as db:
        with pytest.raises(DBAPIError, match="never changes"):
            await db.execute(
                text("UPDATE stripe_event SET payload = '{}' WHERE id = :id"), {"id": row.id}
            )
        await db.rollback()
