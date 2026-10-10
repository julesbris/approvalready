"""Registration, verification, login, sessions, CSRF, throttling and password flows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import update

from app.core.config import Environment
from app.core.security import hash_token
from app.modules.identity.models import AuthSession
from tests.harness import PASSWORD, ApiHarness, unique_email

pytestmark = pytest.mark.integration


async def _db_update_session(api: ApiHarness, user_id: str, **values: object) -> None:
    async with api.app.state.resources.session_factory() as db:
        await db.execute(update(AuthSession).where(AuthSession.user_id == user_id).values(**values))
        await db.commit()


# --- Registration and verification -----------------------------------------------------


async def test_register_verify_login_creates_personal_org(api: ApiHarness) -> None:
    email = await api.register(name="Alex Citizen")
    message = api.last_email(email, "auth.verify_email")
    assert message.links["verify"].startswith("http://localhost:3000/verify-email?token=")

    # Unverified accounts cannot sign in (only revealed after a correct password).
    c = await api.new_client()
    r = await c.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "email_not_verified"

    await api.verify(email)
    user = await api.login(email)
    session = user.session
    assert session["user"]["email"] == email
    assert session["user"]["email_verified"] is True
    [org] = session["organisations"]
    assert org["kind"] == "PERSONAL"
    assert org["name"] == "Alex Citizen"
    assert set(org["roles"]) == {"CUSTOMER", "ORG_ADMIN"}
    assert session["active_organisation_id"] == org["organisation_id"]
    assert "project.write" in session["permissions"]

    me = await user.get("/v1/auth/session")
    assert me.status_code == 200
    assert me.json()["user"]["id"] == session["user"]["id"]


async def test_email_is_case_insensitive(api: ApiHarness) -> None:
    email = await api.register(email=unique_email("Mixed").replace("Mixed", "MiXeD"))
    await api.verify(email)
    await api.login(email.upper())


async def test_duplicate_registration_is_indistinguishable(api: ApiHarness) -> None:
    email = await api.register()
    second = await api.client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "another long password",
            "display_name": "X",
            "accept_terms": True,
        },
    )
    assert second.status_code == 202
    assert second.json() == {"status": "accepted"}
    assert api.last_email(email).kind == "auth.already_registered"


@pytest.mark.parametrize("password", ["short", "x" * 257])
async def test_weak_passwords_rejected(api: ApiHarness, password: str) -> None:
    r = await api.client.post(
        "/v1/auth/register",
        json={
            "email": unique_email(),
            "password": password,
            "display_name": "X",
            "accept_terms": True,
        },
    )
    assert r.status_code == 422


async def test_password_equal_to_email_rejected(api: ApiHarness) -> None:
    email = unique_email()
    r = await api.client.post(
        "/v1/auth/register",
        json={"email": email, "password": email, "display_name": "X", "accept_terms": True},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "weak_password"


async def test_verification_token_is_single_use(api: ApiHarness) -> None:
    email = await api.register()
    token = api.token_from(api.last_email(email, "auth.verify_email"), "verify")
    assert (
        await api.client.post("/v1/auth/verify-email", json={"token": token})
    ).status_code == 200
    again = await api.client.post("/v1/auth/verify-email", json={"token": token})
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "invalid_token"


async def test_resend_only_newest_link_works(api: ApiHarness) -> None:
    email = await api.register()
    old = api.token_from(api.last_email(email, "auth.verify_email"), "verify")
    r = await api.client.post("/v1/auth/verify-email/resend", json={"email": email})
    assert r.status_code == 202
    new = api.token_from(api.last_email(email, "auth.verify_email"), "verify")
    assert old != new
    assert (await api.client.post("/v1/auth/verify-email", json={"token": old})).status_code == 400
    assert (await api.client.post("/v1/auth/verify-email", json={"token": new})).status_code == 200


async def test_resend_for_unknown_email_looks_the_same(api: ApiHarness) -> None:
    email = unique_email()
    r = await api.client.post("/v1/auth/verify-email/resend", json={"email": email})
    assert r.status_code == 202
    assert api.emails_to(email) == []


async def test_emails_per_address_are_capped(api: ApiHarness) -> None:
    email = await api.register()  # 1st verification email
    for _ in range(4):
        await api.client.post("/v1/auth/verify-email/resend", json={"email": email})
    assert len(api.emails_to(email, "auth.verify_email")) == 3


# --- Login, throttling, cookies --------------------------------------------------------


async def test_wrong_password_and_unknown_user_look_the_same(api: ApiHarness) -> None:
    email = await api.register()
    await api.verify(email)
    wrong = await api.client.post("/v1/auth/login", json={"email": email, "password": "nope"})
    unknown = await api.client.post(
        "/v1/auth/login", json={"email": unique_email(), "password": "nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_account_locks_after_repeated_failures(api: ApiHarness) -> None:
    email = await api.register()
    await api.verify(email)
    for _ in range(5):
        r = await api.client.post("/v1/auth/login", json={"email": email, "password": "wrong"})
        assert r.status_code == 401
    blocked = await api.client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


async def test_ip_throttle_across_accounts(client_factory, migrated: None) -> None:  # type: ignore[no-untyped-def]
    async with client_factory(login_max_failures_per_ip=3) as client:
        await client._transport.app.state.resources.redis.flushdb()  # type: ignore[attr-defined]
        for _ in range(3):
            r = await client.post(
                "/v1/auth/login", json={"email": unique_email(), "password": "wrong"}
            )
            assert r.status_code == 401
        r = await client.post("/v1/auth/login", json={"email": unique_email(), "password": "x"})
        assert r.status_code == 429


async def test_session_cookie_attributes_in_secure_mode(client_factory, migrated: None) -> None:  # type: ignore[no-untyped-def]
    async with client_factory(cookie_secure=True) as client:
        app = client._transport.app  # type: ignore[attr-defined]
        await app.state.resources.redis.flushdb()
        api = ApiHarness(app, client)
        email = await api.register()
        await api.verify(email)
        r = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("__Host-ar_session="))
    csrf = next(c for c in cookies if c.startswith("__Host-ar_csrf="))
    for attr in ("Secure", "Path=/", "SameSite=lax"):
        assert attr in session and attr in csrf
    assert "HttpOnly" in session
    assert "HttpOnly" not in csrf  # the web app reads it to send the CSRF header
    assert "Domain=" not in session  # __Host- cookies are host-only


async def test_session_token_is_stored_hashed(api: ApiHarness) -> None:
    user = await api.user()
    token = user.client.cookies.get("ar_session")
    assert token
    async with api.app.state.resources.session_factory() as db:
        from sqlalchemy import select

        hashes = (
            (await db.execute(select(AuthSession.token_hash).where(AuthSession.user_id == user.id)))
            .scalars()
            .all()
        )
    assert hashes == [hash_token(token)]
    assert token.encode() not in hashes


async def test_requests_without_session_are_rejected(api: ApiHarness) -> None:
    r = await api.client.get("/v1/auth/session")
    assert r.status_code == 401
    assert await api.session_status("forged-token-value") == 401


# --- CSRF and origin -------------------------------------------------------------------


async def test_state_change_requires_csrf_header(api: ApiHarness) -> None:
    user = await api.user()
    r = await user.client.post("/v1/auth/logout")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "csrf_failed"
    r = await user.client.post("/v1/auth/logout", headers={"x-csrf-token": "wrong"})
    assert r.status_code == 403
    assert (await user.post("/v1/auth/logout")).status_code == 204


async def test_csrf_token_matches_cookie_and_session_body(api: ApiHarness) -> None:
    user = await api.user()
    assert user.session["csrf_token"] == user.client.cookies.get("ar_csrf")


async def test_foreign_origin_rejected_for_state_changes(api: ApiHarness) -> None:
    r = await api.client.post(
        "/v1/auth/login",
        json={"email": unique_email(), "password": "x"},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "origin_rejected"
    ok = await api.client.post(
        "/v1/auth/login",
        json={"email": unique_email(), "password": "x"},
        headers={"origin": "http://localhost:3000"},
    )
    assert ok.status_code == 401


# --- Logout, expiry, rotation ----------------------------------------------------------


async def test_logout_revokes_server_side(api: ApiHarness) -> None:
    user = await api.user()
    token = user.client.cookies.get("ar_session")
    assert (await user.post("/v1/auth/logout")).status_code == 204
    assert await api.session_status(token) == 401


async def test_logout_all_revokes_every_session(api: ApiHarness) -> None:
    first = await api.user()
    second = await api.login(first.email)
    assert (await second.post("/v1/auth/logout-all")).status_code == 204
    assert (await first.get("/v1/auth/session")).status_code == 401


async def test_idle_timeout(api: ApiHarness) -> None:
    user = await api.user()
    await _db_update_session(api, user.id, idle_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert (await user.get("/v1/auth/session")).status_code == 401


async def test_absolute_expiry(api: ApiHarness) -> None:
    user = await api.user()
    await _db_update_session(api, user.id, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert (await user.get("/v1/auth/session")).status_code == 401


async def test_rotation_with_grace_period(api: ApiHarness) -> None:
    user = await api.user()
    old = user.client.cookies.get("ar_session") or ""
    await _db_update_session(api, user.id, rotated_at=datetime.now(UTC) - timedelta(hours=2))

    r = await user.get("/v1/auth/session")
    assert r.status_code == 200
    new = user.client.cookies.get("ar_session")
    assert new and new != old
    # In-flight requests with the previous token still work during the grace period...
    assert (await api.session_status(old)) == 200
    # ...and stop once it has passed.
    await _db_update_session(
        api, user.id, previous_token_valid_until=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert (await api.session_status(old)) == 401
    assert (await user.get("/v1/auth/session")).status_code == 200


# --- Password reset and change ---------------------------------------------------------


async def test_password_reset_flow(api: ApiHarness) -> None:
    user = await api.user()
    r = await api.client.post("/v1/auth/password-reset/request", json={"email": user.email})
    assert r.status_code == 202
    token = api.token_from(api.last_email(user.email, "auth.password_reset"), "reset")

    new_password = "a completely new passphrase"
    r = await api.client.post(
        "/v1/auth/password-reset/confirm", json={"token": token, "password": new_password}
    )
    assert r.status_code == 200
    assert api.last_email(user.email).kind == "auth.password_changed"
    # Every existing session is signed out.
    assert (await user.get("/v1/auth/session")).status_code == 401
    # The link is single use.
    again = await api.client.post(
        "/v1/auth/password-reset/confirm", json={"token": token, "password": "yet another one!!"}
    )
    assert again.status_code == 400
    # Old password no longer works; the new one does.
    old = await api.client.post("/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert old.status_code == 401
    await api.login(user.email, new_password)


async def test_password_reset_for_unknown_email_looks_the_same(api: ApiHarness) -> None:
    email = unique_email()
    r = await api.client.post("/v1/auth/password-reset/request", json={"email": email})
    assert r.status_code == 202
    assert r.json() == {"status": "accepted"}
    assert api.emails_to(email) == []


async def test_expired_reset_token_rejected(api: ApiHarness) -> None:
    from app.modules.identity.models import OneTimeToken

    user = await api.user()
    await api.client.post("/v1/auth/password-reset/request", json={"email": user.email})
    token = api.token_from(api.last_email(user.email, "auth.password_reset"), "reset")
    async with api.app.state.resources.session_factory() as db:
        await db.execute(
            update(OneTimeToken)
            .where(OneTimeToken.token_hash == hash_token(token))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
    r = await api.client.post(
        "/v1/auth/password-reset/confirm", json={"token": token, "password": "new long passphrase"}
    )
    assert r.status_code == 400


async def test_change_password_rotates_and_signs_out_others(api: ApiHarness) -> None:
    user = await api.user()
    other = await api.login(user.email)
    old_token = user.client.cookies.get("ar_session")

    bad = await user.post(
        "/v1/auth/password",
        json={"current_password": "wrong", "new_password": "another long passphrase"},
    )
    assert bad.status_code == 400

    r = await user.post(
        "/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "another long passphrase"},
    )
    assert r.status_code == 200, r.text
    assert user.client.cookies.get("ar_session") != old_token
    assert (await user.get("/v1/auth/session")).status_code == 200
    assert (await other.get("/v1/auth/session")).status_code == 401
    assert await api.session_status(old_token) == 401


# --- Configuration ---------------------------------------------------------------------


def test_production_requires_secure_cookies() -> None:
    from pydantic import ValidationError

    from tests.conftest import make_settings

    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        make_settings(
            app_env=Environment.PRODUCTION,
            secret_key=SecretStr("z" * 48),
            cors_origins=["https://app.approvalready.com.au"],
            cookie_secure=False,
        )
