"""Notification preferences and unsubscribe links (Milestone 21)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.email import OutgoingEmail
from app.modules.notifications import delivery, emails, preferences
from app.modules.notifications.models import NotificationCategory
from app.modules.outbox.service import _pack, _unpack
from app.modules.projects.models import Reminder
from tests.conftest import make_settings
from tests.harness import ApiHarness, User

SECRET = "x" * 40


def _org(user: User) -> str:
    return f"/v1/organisations/{user.personal_org_id}"


def _token(message: OutgoingEmail) -> str:
    return parse_qs(urlparse(message.links["unsubscribe"]).query)["token"][0]


async def _fire_reminder(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession], user: User, title: str
) -> None:
    r = await user.post(f"{_org(user)}/projects", json={"vertical": "RENT", "title": "Home"})
    pid = r.json()["id"]
    soon = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    r = await user.post(
        f"{_org(user)}/projects/{pid}/reminders", json={"title": title, "fires_at": soon}
    )
    assert r.status_code == 201, r.text
    async with owner_sessions() as db:
        await db.execute(
            update(Reminder)
            .where(Reminder.id == uuid.UUID(r.json()["id"]))
            .values(fires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()
    resources = api.app.state.resources
    await delivery.deliver_due_reminders(
        resources.session_factory, resources.email, api.app.state.settings
    )


async def _titles(user: User) -> list[str]:
    r = await user.get(f"{_org(user)}/notifications")
    return [n["title"] for n in r.json()["items"]]


def _channels(body: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    return {i["category"]: i["channel"] for i in body["items"]}


# --- Pure helpers ----------------------------------------------------------------------


def test_unsubscribe_tokens_round_trip_and_reject_tampering() -> None:
    user_id = uuid.uuid4()
    token = preferences.unsubscribe_token(SECRET, user_id, NotificationCategory.REMINDERS)
    assert preferences.read_unsubscribe_token(SECRET, token) == (
        user_id,
        NotificationCategory.REMINDERS,
    )
    # Another category, another person or another key: not genuine.
    user_hex, _, signature = token.split(".")
    assert preferences.read_unsubscribe_token(SECRET, f"{user_hex}.REFERRALS.{signature}") is None
    other = uuid.uuid4().hex
    assert preferences.read_unsubscribe_token(SECRET, f"{other}.REMINDERS.{signature}") is None
    assert preferences.read_unsubscribe_token("y" * 40, token) is None
    for bad in ("", "a.b", "a.b.c.d", f"nothex.REMINDERS.{signature}"):
        assert preferences.read_unsubscribe_token(SECRET, bad) is None


def test_notification_email_carries_one_click_unsubscribe() -> None:
    settings = make_settings()
    user_id = uuid.uuid4()
    page, one_click = preferences.unsubscribe_links(
        settings, user_id, NotificationCategory.GRANT_ROUNDS
    )
    assert "/unsubscribe?token=" in page
    assert "/api/v1/auth/unsubscribe?token=" in one_click
    message = emails.notification(
        settings, "a@example.com", "Alex", "Round open", None, "/projects/1",
        unsubscribe=(page, one_click),
    )  # fmt: skip
    assert message.headers == {
        "List-Unsubscribe": f"<{one_click}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    assert page in message.text
    assert "/account#notifications" in message.text
    # Ops alerts can't be turned off: no unsubscribe offered.
    ops = emails.notification(settings, "a@example.com", "Alex", "Backups", None, "/admin/ops")
    assert ops.headers == {} and "unsubscribe" not in ops.links


def test_outbox_keeps_headers() -> None:
    settings = make_settings()
    message = OutgoingEmail(
        to="a@example.com",
        subject="s",
        text="t",
        kind="notification",
        headers={"List-Unsubscribe": "<https://example.com/u>"},
    )
    assert _unpack(settings, _pack(settings, message)) == message


# --- API -------------------------------------------------------------------------------


@pytest.mark.integration
async def test_preferences_default_to_everything_and_can_be_changed(api: ApiHarness) -> None:
    user = await api.user()
    r = await user.get("/v1/auth/notification-preferences")
    assert r.status_code == 200
    assert _channels(r.json()) == {c.value: "ALL" for c in NotificationCategory}

    r = await user.put(
        "/v1/auth/notification-preferences",
        json={"items": [{"category": "REFERRALS", "channel": "OFF"}]},
    )
    assert r.status_code == 200, r.text
    assert _channels(r.json())["REFERRALS"] == "OFF"
    assert _channels(r.json())["REMINDERS"] == "ALL"

    # Needs the session check, and a session.
    r = await user.client.put(
        "/v1/auth/notification-preferences",
        json={"items": [{"category": "REFERRALS", "channel": "ALL"}]},
    )
    assert r.status_code == 403
    anonymous = await api.new_client()
    assert (await anonymous.get("/v1/auth/notification-preferences")).status_code == 401
    r = await user.put(
        "/v1/auth/notification-preferences",
        json={"items": [{"category": "REFERRALS", "channel": "LOUD"}]},
    )
    assert r.status_code == 422


@pytest.mark.integration
async def test_in_app_only_drops_the_email_and_off_drops_the_notification(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await api.user()
    await user.put(
        "/v1/auth/notification-preferences",
        json={"items": [{"category": "REMINDERS", "channel": "IN_APP"}]},
    )
    await _fire_reminder(api, owner_sessions, user, "Quiet")
    assert await _titles(user) == ["Quiet"]
    assert api.emails_to(user.email, "notification") == []

    await user.put(
        "/v1/auth/notification-preferences",
        json={"items": [{"category": "REMINDERS", "channel": "OFF"}]},
    )
    await _fire_reminder(api, owner_sessions, user, "Silent")
    assert await _titles(user) == ["Quiet"]


@pytest.mark.integration
async def test_unsubscribe_link_stops_emails_without_signing_in(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await api.user()
    await _fire_reminder(api, owner_sessions, user, "First")
    [message] = api.emails_to(user.email, "notification")
    assert message.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    token = _token(message)
    assert message.headers["List-Unsubscribe"].endswith(f"?token={token}>")

    browser = await api.new_client()
    r = await browser.get("/v1/auth/unsubscribe", params={"token": token})
    assert r.status_code == 200
    assert r.json() == {"category": "REMINDERS", "channel": "ALL"}

    # What a mail provider sends for one click (RFC 8058): a form body, no cookies.
    r = await browser.post(
        "/v1/auth/unsubscribe",
        params={"token": token},
        content="List-Unsubscribe=One-Click",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, r.text
    assert _channels(r.json())["REMINDERS"] == "IN_APP"
    assert _channels(r.json())["GRANT_ROUNDS"] == "ALL"

    await _fire_reminder(api, owner_sessions, user, "Second")
    assert len(api.emails_to(user.email, "notification")) == 1
    assert "Second" in await _titles(user)

    # Every optional email; a category the person turned off stays off.
    await user.put(
        "/v1/auth/notification-preferences",
        json={"items": [{"category": "REFERRALS", "channel": "OFF"}]},
    )
    r = await browser.post("/v1/auth/unsubscribe", params={"token": token, "scope": "all"})
    assert r.status_code == 200
    assert _channels(r.json()) == {
        "REMINDERS": "IN_APP",
        "GRANT_ROUNDS": "IN_APP",
        "REFERRALS": "OFF",
        "SOURCE_REVIEWS": "IN_APP",
    }


@pytest.mark.integration
async def test_bad_unsubscribe_links_are_refused(api: ApiHarness) -> None:
    browser = await api.new_client()
    forged = preferences.unsubscribe_token(SECRET, uuid.uuid4(), NotificationCategory.REMINDERS)
    for token in ("nonsense", forged):
        r = await browser.post("/v1/auth/unsubscribe", params={"token": token})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "invalid_link"
    # A genuine token for someone who doesn't exist.
    settings = api.app.state.settings
    ghost = preferences.unsubscribe_token(
        settings.secret_key.get_secret_value(), uuid.uuid4(), NotificationCategory.REMINDERS
    )
    assert (await browser.get("/v1/auth/unsubscribe", params={"token": ghost})).status_code == 400
    assert (await browser.post("/v1/auth/unsubscribe")).status_code == 422
