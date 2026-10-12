"""ApprovalReady Plus: the public offer, a free first month with the card taken up front and
charged automatically after, the started and ending-soon emails, and project plans included.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.billing import service, trials
from app.modules.billing.catalogue import load_bundled
from tests.harness import ApiHarness, User, platform_user
from tests.test_assessments import org_url
from tests.test_billing import FakeStripe, deliver, event, set_price
from tests.test_leads import (  # noqa: F401 - fixtures used by name
    app,
    only_new_partners,
    settings,
    stripe_api,
)
from tests.test_plans import assessed, plan_url

pytestmark = pytest.mark.integration

OFFER = "/v1/billing/membership"


def test_the_membership_is_in_the_catalogue_with_a_placeholder_price() -> None:
    product = next(p for p in load_bundled().products if p.key == service.MEMBERSHIP_KEY)
    assert product.kind == "SAAS" and product.suggested_price_cents == 2900
    assert product.features == {service.PLAN_INCLUDED_FEATURE: None}


async def _send(api: ApiHarness) -> int:
    resources = api.app.state.resources
    return await trials.send_trial_emails(
        resources.session_factory, resources.email, api.app.state.settings
    )


def _trialing(customer: str, price_id: str, sub_id: str, trial_end: int, **extra: Any) -> dict:
    return {
        "id": sub_id,
        "object": "subscription",
        "customer": customer,
        "status": "trialing",
        "cancel_at_period_end": False,
        "trial_end": trial_end,
        "items": {"data": [{"current_period_end": trial_end}]},
        "metadata": {"price_id": price_id},
        **extra,
    }


async def _start(owner: User, fake: FakeStripe) -> dict[str, str]:
    r = await owner.post(f"{org_url(owner)}/billing/membership/checkout")
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("https://checkout.stripe.com/")
    return fake.last("/v1/checkout/sessions")


async def test_the_offer_is_public_and_shows_the_price_once_set(api: ApiHarness) -> None:
    r = await api.client.get(OFFER)
    assert r.status_code == 200, r.text
    assert r.json() | {"description": None} == {
        "on_sale": False,
        "product_name": "ApprovalReady Plus",
        "description": None,
        "amount_cents": None,
        "currency": None,
        "interval": None,
        "trial_days": 30,
        "reminder_days": 7,
    }
    owner = await api.user()
    r = await owner.post(f"{org_url(owner)}/billing/membership/checkout")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "price_unavailable"

    admin = await platform_user(api, "ADMIN")
    await set_price(admin, service.MEMBERSHIP_KEY, 2_900, "MONTH")
    offer = (await api.client.get(OFFER)).json()
    assert offer["on_sale"] and offer["amount_cents"] == 2900 and offer["interval"] == "MONTH"


async def test_a_free_month_then_charged_automatically(
    api: ApiHarness,
    stripe_api: FakeStripe,  # noqa: F811
    owner_sessions: async_sessionmaker[AsyncSession],
) -> None:
    admin = await platform_user(api, "ADMIN")
    price = await set_price(admin, service.MEMBERSHIP_KEY, 2_900, "MONTH")
    owner = await api.user(name="Tess Trial")
    org = org_url(owner)
    mine = (await owner.get(f"{org}/billing/membership")).json()
    assert mine["trial_available"] and mine["subscription"] is None and not mine["other_plan"]
    # Only people who handle billing see it.
    assert (await (await api.user()).get(f"{org}/billing/membership")).status_code == 404

    # The card is taken at checkout; Stripe charges it when the 30 free days end, or cancels
    # the plan if no card was saved.
    session = await _start(owner, stripe_api)
    assert session["mode"] == "subscription"
    assert session["payment_method_collection"] == "always"
    assert session["subscription_data[trial_period_days]"] == "30"
    assert (
        session["subscription_data[trial_settings][end_behavior][missing_payment_method]"]
        == "cancel"
    )
    assert session["subscription_data[metadata][price_id]"] == price["id"]
    assert session["success_url"].endswith("/membership/start?checkout=done")

    customer = session["customer"]
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    trial_end = int(time.time()) + 30 * 86400
    await deliver(
        api,
        event("customer.subscription.created", _trialing(customer, price["id"], sub_id, trial_end)),
    )
    mine = (await owner.get(f"{org}/billing/membership")).json()
    sub = mine["subscription"]
    assert sub["status"] == "TRIALING" and sub["gives_plan"]
    assert sub["trial_end"].startswith(
        datetime.fromtimestamp(trial_end, UTC).strftime("%Y-%m-%dT%H:%M")
    )
    assert not mine["trial_available"]

    # Started email: once, to the people who handle billing, with the charge date and amount.
    await _send(api)
    [started] = api.emails_to(owner.email, "billing.trial_started")
    assert "$29.00 AUD" in started.text and "Cancel any time before" in started.text
    await _send(api)
    assert len(api.emails_to(owner.email, "billing.trial_started")) == 1
    assert api.emails_to(owner.email, "billing.trial_ending") == []

    # Seven days before the charge: the reminder, once.
    async with owner_sessions() as db:
        await db.execute(
            text(
                "UPDATE subscription SET trial_end = now() + interval '6 days' "
                "WHERE stripe_subscription_id = :s"
            ),
            {"s": sub_id},
        )
        await db.commit()
    await _send(api)
    await _send(api)
    [ending] = api.emails_to(owner.email, "billing.trial_ending")
    assert ending.subject.startswith("Your free month ends on")
    assert "$29.00 AUD a month" in ending.text

    # The trial ends and Stripe charges the card: the plan simply carries on.
    await deliver(
        api,
        event(
            "customer.subscription.updated",
            _trialing(customer, price["id"], sub_id, trial_end, status="active"),
            created=int(time.time()) + 5,
        ),
    )
    sub = (await owner.get(f"{org}/billing/membership")).json()["subscription"]
    assert sub["status"] == "ACTIVE"

    # Cancelled later: a second free month isn't offered.
    await deliver(
        api,
        event(
            "customer.subscription.deleted",
            _trialing(customer, price["id"], sub_id, trial_end, status="canceled"),
            created=int(time.time()) + 10,
        ),
    )
    mine = (await owner.get(f"{org}/billing/membership")).json()
    assert mine["subscription"] is None and not mine["trial_available"]
    again = await _start(owner, stripe_api)
    assert "subscription_data[trial_period_days]" not in again
    assert "payment_method_collection" not in again


async def test_a_short_trial_sends_one_email_and_cancelled_trials_get_no_reminder(
    api: ApiHarness,
    stripe_api: FakeStripe,  # noqa: F811
) -> None:
    admin = await platform_user(api, "ADMIN")
    price = await set_price(admin, service.MEMBERSHIP_KEY, 2_900, "MONTH")
    # A trial ending inside the reminder window: the started email is the reminder.
    short = await api.user()
    session = await _start(short, stripe_api)
    soon = int((datetime.now(UTC) + timedelta(days=5)).timestamp())
    await deliver(
        api,
        event(
            "customer.subscription.created",
            _trialing(session["customer"], price["id"], f"sub_{uuid.uuid4().hex[:12]}", soon),
        ),
    )
    await _send(api)
    await _send(api)
    assert len(api.emails_to(short.email, "billing.trial_started")) == 1
    assert api.emails_to(short.email, "billing.trial_ending") == []

    # Cancelled during the trial: told nothing will be charged, and no reminder later.
    quitter = await api.user()
    session = await _start(quitter, stripe_api)
    await deliver(
        api,
        event(
            "customer.subscription.created",
            _trialing(
                session["customer"],
                price["id"],
                f"sub_{uuid.uuid4().hex[:12]}",
                soon,
                cancel_at_period_end=True,
            ),
        ),
    )
    await _send(api)
    [started] = api.emails_to(quitter.email, "billing.trial_started")
    assert "nothing will be charged" in started.text
    assert api.emails_to(quitter.email, "billing.trial_ending") == []


async def test_members_get_project_plans_included(
    api: ApiHarness,
    stripe_api: FakeStripe,  # noqa: F811
) -> None:
    admin = await platform_user(api, "ADMIN")
    await set_price(admin, "plan.project", 14_900)
    price = await set_price(admin, service.MEMBERSHIP_KEY, 2_900, "MONTH")
    customer, project, _ = await assessed(api)
    url = plan_url(customer, project)
    offer = (await customer.get(url)).json()["offer"]
    assert offer["on_sale"] and offer["membership_on_sale"] and not offer["included_in_membership"]

    session = await _start(customer, stripe_api)
    await deliver(
        api,
        event(
            "customer.subscription.created",
            _trialing(
                session["customer"],
                price["id"],
                f"sub_{uuid.uuid4().hex[:12]}",
                int(time.time()) + 30 * 86400,
            ),
        ),
    )
    offer = (await customer.get(url)).json()["offer"]
    assert offer["included_in_membership"] and not offer["on_sale"]
    r = await customer.post(url)
    assert r.status_code == 201, r.text
    assert r.json()["plan"]["status"] == "ACTIVE" and r.json()["checkout_url"] is None
