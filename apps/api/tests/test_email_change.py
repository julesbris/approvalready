"""Change of email address (Milestone 28)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditEvent
from tests.harness import PASSWORD, ApiHarness, enable_mfa, totp_code, unique_email

pytestmark = pytest.mark.integration


async def _request(user, new_email: str, **extra: object):  # type: ignore[no-untyped-def]
    return await user.post(
        "/v1/auth/email-change",
        json={"new_email": new_email, "password": PASSWORD, **extra},
    )


async def test_change_email_after_confirming_the_link(api: ApiHarness) -> None:
    user = await api.user(name="Sam Mover")
    old = user.email
    new = unique_email("moved")

    r = await _request(user, new)
    assert r.status_code == 202, r.text
    assert r.json()["pending_email"] == new
    status = (await user.get("/v1/auth/email-change")).json()
    assert status["pending_email"] == new

    link = api.last_email(new, "auth.email_change_confirm")
    assert link.links["confirm"].startswith("http://localhost:3000/verify-email/change?token=")
    notice = api.last_email(old, "auth.email_change_requested")
    assert new not in notice.text  # masked
    assert f"m***@{new.split('@')[1]}" in notice.text

    # Nothing changes until the link is opened: the old address still signs in.
    assert (await user.get("/v1/auth/session")).json()["user"]["email"] == old
    await api.login(old)

    token = api.token_from(link, "confirm")
    c = await api.new_client()  # the link may be opened in another browser
    r = await c.post("/v1/auth/email-change/confirm", json={"token": token})
    assert r.status_code == 200, r.text
    assert api.last_email(old, "auth.email_changed")

    session = (await user.get("/v1/auth/session")).json()
    assert session["user"]["email"] == new
    assert session["user"]["email_verified"] is True
    assert (await user.get("/v1/auth/email-change")).json()["pending_email"] is None

    await api.login(new)
    bad = await (await api.new_client()).post(
        "/v1/auth/login", json={"email": old, "password": PASSWORD}
    )
    assert bad.status_code == 401

    # The link works once.
    again = await c.post("/v1/auth/email-change/confirm", json={"token": token})
    assert again.status_code == 400

    async with api.app.state.resources.session_factory() as db:
        actions = (
            await db.execute(
                select(AuditEvent.action, AuditEvent.details).where(
                    AuditEvent.target_id == session["user"]["id"],
                    AuditEvent.action.like("auth.email_change%"),
                )
            )
        ).all()
    assert {a for a, _ in actions} == {"auth.email_change.requested", "auth.email_changed"}
    assert all(new not in str(d) and old not in str(d) for _, d in actions)


async def test_needs_the_password_and_a_different_address(api: ApiHarness) -> None:
    user = await api.user()
    r = await user.post(
        "/v1/auth/email-change", json={"new_email": unique_email(), "password": "wrong"}
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_credentials"

    r = await _request(user, user.email.upper())
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "same_email"

    r = await user.post("/v1/auth/email-change", json={"new_email": "nope", "password": PASSWORD})
    assert r.status_code == 422

    anon = await api.new_client()
    r = await anon.post(
        "/v1/auth/email-change", json={"new_email": unique_email(), "password": PASSWORD}
    )
    assert r.status_code in (401, 403)


async def test_two_step_code_needed_when_on(api: ApiHarness) -> None:
    user = await api.user()
    secret = await enable_mfa(user)
    new = unique_email()
    r = await _request(user, new)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "mfa_code_required"
    r = await _request(user, new, code="000000")
    assert r.status_code == 400
    r = await _request(user, new, code=totp_code(secret, 1))
    assert r.status_code == 202, r.text
    assert api.last_email(new, "auth.email_change_confirm").links["confirm"]


async def test_address_of_another_account_is_not_revealed(api: ApiHarness) -> None:
    user = await api.user()
    taken = (await api.user(name="Other")).email

    r = await _request(user, taken)
    # Same answer as for a free address.
    assert r.status_code == 202
    assert r.json()["pending_email"] == taken
    message = api.last_email(taken, "auth.email_change_confirm")
    assert "confirm" not in message.links
    assert "already" in message.text


async def test_address_taken_before_confirming(api: ApiHarness) -> None:
    user = await api.user()
    new = unique_email("race")
    assert (await _request(user, new)).status_code == 202
    token = api.token_from(api.last_email(new, "auth.email_change_confirm"), "confirm")

    await api.user(email=new)  # someone registers the address first

    r = await api.client.post("/v1/auth/email-change/confirm", json={"token": token})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "email_in_use"
    assert (await user.get("/v1/auth/session")).json()["user"]["email"] == user.email


async def test_cancel_and_newest_link_only(api: ApiHarness) -> None:
    user = await api.user()
    first, second = unique_email("first"), unique_email("second")
    assert (await _request(user, first)).status_code == 202
    first_token = api.token_from(api.last_email(first, "auth.email_change_confirm"), "confirm")
    assert (await _request(user, second)).status_code == 202
    second_token = api.token_from(api.last_email(second, "auth.email_change_confirm"), "confirm")

    # Asking again replaces the first request.
    r = await api.client.post("/v1/auth/email-change/confirm", json={"token": first_token})
    assert r.status_code == 400

    r = await user.delete("/v1/auth/email-change")
    assert r.status_code == 200
    assert r.json()["pending_email"] is None
    r = await api.client.post("/v1/auth/email-change/confirm", json={"token": second_token})
    assert r.status_code == 400
    assert (await user.get("/v1/auth/session")).json()["user"]["email"] == user.email


async def test_old_inbox_links_stop_working(api: ApiHarness) -> None:
    user = await api.user()
    old = user.email
    r = await api.client.post("/v1/auth/password-reset/request", json={"email": old})
    assert r.status_code == 202
    reset_token = api.token_from(api.last_email(old, "auth.password_reset"), "reset")

    new = unique_email()
    assert (await _request(user, new)).status_code == 202
    token = api.token_from(api.last_email(new, "auth.email_change_confirm"), "confirm")
    r = await api.client.post("/v1/auth/email-change/confirm", json={"token": token})
    assert r.status_code == 200

    r = await api.client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": reset_token, "password": "a brand new long passphrase"},
    )
    assert r.status_code == 400
