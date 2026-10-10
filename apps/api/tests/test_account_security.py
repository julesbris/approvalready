"""Account security (Milestone 18): two-step sign-in, breached passwords, API rate limits."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from app import cli
from app.core import totp
from app.core.crypto import SealedValueError, seal, unseal
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.identity.models import MfaTotp
from tests.conftest import _client_for, make_settings
from tests.harness import PASSWORD, ApiHarness, User, enable_mfa, platform_user, totp_code

pytestmark = pytest.mark.integration

# --- TOTP and sealing (no database) ------------------------------------------------------


def test_totp_matches_rfc_6238() -> None:
    # RFC 6238 appendix B, SHA-1 secret "12345678901234567890": T=59 gives 94287082 (8
    # digits); authenticator apps show the last 6.
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert totp.code_at(secret, 59 // 30) == "287082"
    assert totp.code_at(secret, 1111111109 // 30) == "081804"


def test_totp_drift_window_and_replay() -> None:
    secret = totp.new_secret()
    now = 1_800_000_000.0
    step = totp.current_step(now)
    for offset in (-1, 0, 1):
        code = totp.code_at(secret, step + offset)
        assert totp.matching_step(secret, code, now=now) == step + offset
    assert totp.matching_step(secret, totp.code_at(secret, step + 2), now=now) is None
    assert totp.matching_step(secret, totp.code_at(secret, step - 2), now=now) is None
    # A used step (and anything before it) never matches again.
    code = totp.code_at(secret, step)
    assert totp.matching_step(secret, code, after_step=step, now=now) is None
    assert totp.matching_step(secret, "12345", now=now) is None
    assert totp.matching_step(secret, "abcdef", now=now) is None
    spaced = code[:3] + " " + code[3:]
    assert totp.matching_step(secret, spaced, now=now) == step


def test_provisioning_uri_and_qr() -> None:
    uri = totp.provisioning_uri("ABCDEF", "jo@example.com", "ApprovalReady")
    assert uri.startswith("otpauth://totp/ApprovalReady:jo@example.com?")
    assert "secret=ABCDEF" in uri and "issuer=ApprovalReady" in uri
    svg = totp.qr_svg(uri)
    assert svg.startswith("<svg") and "<script" not in svg


def test_sealed_secrets_are_bound_to_key_and_purpose() -> None:
    key = "k" * 40
    sealed = seal(key, "mfa-totp", b"secret")
    assert b"secret" not in sealed
    assert unseal(key, "mfa-totp", sealed) == b"secret"
    with pytest.raises(SealedValueError):
        unseal("x" * 40, "mfa-totp", sealed)
    with pytest.raises(SealedValueError):
        unseal(key, "other", sealed)
    with pytest.raises(SealedValueError):
        unseal(key, "mfa-totp", sealed[:-1] + bytes([sealed[-1] ^ 1]))


# --- Two-step sign-in --------------------------------------------------------------------


async def _login(api: ApiHarness, email: str, password: str = PASSWORD) -> httpx.AsyncClient:
    client = await api.new_client()
    r = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    assert r.json() == {"mfa_required": True}
    assert "ar_session" not in client.cookies
    assert client.cookies.get("ar_mfa")
    return client


async def test_setup_confirm_and_sign_in_with_a_code(api: ApiHarness) -> None:
    user = await api.user()
    other = await api.login(user.email)
    assert user.session["user"]["mfa_enabled"] is False

    r = await user.post("/v1/auth/mfa/totp/setup", json={"password": "wrong password!!"})
    assert r.status_code == 400
    r = await user.post("/v1/auth/mfa/totp/setup", json={"password": PASSWORD})
    assert r.status_code == 200
    setup = r.json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    assert setup["qr_svg"].startswith("<svg")
    # Not on until confirmed: sign-in still takes just the password.
    assert (await api.login(user.email)).session["user"]["mfa_enabled"] is False

    r = await user.post("/v1/auth/mfa/totp/confirm", json={"code": "000000"})
    if r.status_code == 200:  # pragma: no cover - one in a million
        pytest.skip("the made-up code happened to be right")
    assert r.json()["detail"]["code"] == "invalid_code"
    secret = setup["secret"]
    r = await user.post("/v1/auth/mfa/totp/confirm", json={"code": totp_code(secret)})
    assert r.status_code == 200, r.text
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert api.last_email(user.email, "auth.mfa_enabled")
    # Other sessions are signed out; this one carries on with a new token.
    assert (await other.get("/v1/auth/session")).status_code == 401
    session = (await user.get("/v1/auth/session")).json()
    assert session["user"]["mfa_enabled"] is True
    status = (await user.get("/v1/auth/mfa")).json()
    assert status["enabled"] is True and status["recovery_codes_left"] == 10

    # The secret is stored sealed, never in clear.
    async with api.app.state.resources.session_factory() as db:
        row = (await db.execute(select(MfaTotp))).scalars().all()
        assert all(secret.encode() not in r.secret_sealed for r in row)

    # Signing in now takes the password, then a code.
    client = await _login(api, user.email)
    r = await client.post("/v1/auth/login/mfa", json={"code": "999999"})
    assert r.status_code == 400
    r = await client.post("/v1/auth/login/mfa", json={"code": totp_code(secret, 1)})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["mfa_enabled"] is True
    assert client.cookies.get("ar_session")
    assert not client.cookies.get("ar_mfa")
    # The same code can't be used again.
    again = await _login(api, user.email)
    r = await again.post("/v1/auth/login/mfa", json={"code": totp_code(secret, 1)})
    assert r.status_code == 400

    async with api.app.state.resources.session_factory() as db:
        actions = (
            (await db.execute(select(AuditEvent.action).where(AuditEvent.actor_user_id == user.id)))
            .scalars()
            .all()
        )
    assert {"auth.mfa.enabled", "auth.mfa.failed", "auth.login.mfa_challenged"} <= set(actions)


async def test_recovery_codes_work_once_and_can_be_replaced(api: ApiHarness) -> None:
    user = await api.user()
    secret = await enable_mfa(user)
    first, second = user.recovery_codes[0], user.recovery_codes[1]

    client = await _login(api, user.email)
    r = await client.post("/v1/auth/login/mfa", json={"code": first.upper().replace("-", " ")})
    assert r.status_code == 200, r.text
    assert "9 left" in api.last_email(user.email, "auth.mfa_recovery_code_used").text
    client = await _login(api, user.email)
    assert (await client.post("/v1/auth/login/mfa", json={"code": first})).status_code == 400

    r = await user.post("/v1/auth/mfa/recovery-codes", json={"code": totp_code(secret, 1)})
    assert r.status_code == 200
    fresh = r.json()["recovery_codes"]
    assert second not in fresh
    client = await _login(api, user.email)
    assert (await client.post("/v1/auth/login/mfa", json={"code": second})).status_code == 400
    assert (await client.post("/v1/auth/login/mfa", json={"code": fresh[0]})).status_code == 200


async def test_challenge_limits(api: ApiHarness) -> None:
    user = await api.user()
    secret = await enable_mfa(user)
    # No challenge cookie: the password step is needed first.
    stranger = await api.new_client()
    r = await stranger.post("/v1/auth/login/mfa", json={"code": totp_code(secret)})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "mfa_challenge_expired"

    client = await _login(api, user.email)
    for _ in range(5):
        assert (await client.post("/v1/auth/login/mfa", json={"code": "000000"})).status_code == 400
    # Out of attempts: even the right code needs the password again.
    r = await client.post("/v1/auth/login/mfa", json={"code": totp_code(secret, 1)})
    assert r.status_code == 401

    # Wrong codes also count against the account (10 per window), across challenges.
    for _ in range(2):
        client = await _login(api, user.email)
        for _ in range(3):
            await client.post("/v1/auth/login/mfa", json={"code": "000000"})
    client = await _login(api, user.email)
    r = await client.post("/v1/auth/login/mfa", json={"code": totp_code(secret, 1)})
    assert r.status_code == 429


async def test_turning_off_needs_password_and_code(api: ApiHarness) -> None:
    user = await api.user()
    secret = await enable_mfa(user)
    r = await user.post("/v1/auth/mfa/totp/setup", json={"password": PASSWORD})
    assert r.status_code == 409
    body = {"password": "not my password", "code": totp_code(secret, 1)}
    assert (await user.post("/v1/auth/mfa/disable", json=body)).status_code == 400
    body = {"password": PASSWORD, "code": "000000"}
    assert (await user.post("/v1/auth/mfa/disable", json=body)).status_code == 400
    body = {"password": PASSWORD, "code": user.recovery_codes[0]}
    r = await user.post("/v1/auth/mfa/disable", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False
    assert api.last_email(user.email, "auth.mfa_disabled")
    # Back to password-only sign-in.
    assert (await api.login(user.email)).session["user"]["mfa_enabled"] is False


async def test_staff_need_two_step_sign_in(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    assert staff.session["staff_mfa_required"] is False
    assert (await staff.get("/v1/admin/source-references")).status_code == 200

    # A password-only session can't reach staff routes even with the platform org active:
    # remove the factor behind the session's back (as a reset would).
    async with api.app.state.resources.session_factory() as db:
        row = (await db.execute(select(MfaTotp).where(MfaTotp.user_id == staff.id))).scalar_one()
        await db.delete(row)
        await db.commit()
    r = await staff.get("/v1/admin/source-references")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "mfa_required"
    session = (await staff.get("/v1/auth/session")).json()
    assert session["staff_mfa_required"] is True and session["permissions"] == []

    # STAFF_MFA_REQUIRED=false (not recommended) lifts the requirement.
    settings = api.app.state.settings
    api.app.state.settings = settings.model_copy(update={"staff_mfa_required": False})
    try:
        assert (await staff.get("/v1/admin/source-references")).status_code == 200
    finally:
        api.app.state.settings = settings


async def test_cli_reset_mfa(api: ApiHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: api.app.state.settings)
    user = await api.user()
    await enable_mfa(user)
    assert await cli.reset_mfa(user.email) == 0
    assert (await user.get("/v1/auth/session")).status_code == 401
    assert (await api.login(user.email)).session["user"]["mfa_enabled"] is False
    assert await cli.reset_mfa("nobody@example.com") == 1


# --- Breached passwords ------------------------------------------------------------------


def _pwned_api(breached: set[str], *, fail: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(503)
        assert request.headers["add-padding"] == "true"
        prefix = request.url.path.rsplit("/", 1)[-1]
        assert len(prefix) == 5  # only the first five characters of the hash leave
        lines = ["0000000000000000000000000000000000A:0"]  # padding entry
        for password in breached:
            digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
            if digest.startswith(prefix):
                lines.append(f"{digest[5:]}:4210")
        return httpx.Response(200, text="\r\n".join(lines))

    return httpx.MockTransport(handler)


@pytest.fixture
async def pwned_client(migrated: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        make_settings(password_breach_check=True),
        breach_transport=_pwned_api({"password123456", "correct horse battery staple"}),
    )
    async for client in _client_for(app):
        await app.state.resources.redis.flushdb()
        yield client


async def test_breached_passwords_are_refused(pwned_client: httpx.AsyncClient) -> None:
    body = {
        "email": "pwned@example.com",
        "password": "password123456",
        "display_name": "P",
        "accept_terms": True,
    }
    r = await pwned_client.post("/v1/auth/register", json=body)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "breached_password"
    body["password"] = "a fine unbreached passphrase 7"
    assert (await pwned_client.post("/v1/auth/register", json=body)).status_code == 202


async def test_breach_check_fails_open(migrated: None) -> None:
    app = create_app(
        make_settings(password_breach_check=True), breach_transport=_pwned_api(set(), fail=True)
    )
    async for client in _client_for(app):
        body = {
            "email": "open@example.com",
            "password": "password123456",
            "display_name": "O",
            "accept_terms": True,
        }
        assert (await client.post("/v1/auth/register", json=body)).status_code == 202


async def test_breach_check_on_password_change(api: ApiHarness) -> None:
    from app.core.breach import BreachChecker

    user: User = await api.user()
    original = api.app.state.breach
    api.app.state.breach = BreachChecker(
        make_settings(password_breach_check=True), _pwned_api({"password123456"})
    )
    try:
        body = {"current_password": PASSWORD, "new_password": "password123456"}
        r = await user.post("/v1/auth/password", json=body)
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "breached_password"
    finally:
        await api.app.state.breach.aclose()
        api.app.state.breach = original


# --- API rate limits ---------------------------------------------------------------------


async def test_api_rate_limits(client_factory) -> None:  # type: ignore[no-untyped-def]
    async with client_factory(
        api_requests_per_ip_per_minute=4, api_writes_per_ip_per_minute=2
    ) as client:
        await client._transport.app.state.resources.redis.flushdb()  # type: ignore[attr-defined]
        for _ in range(2):
            assert (await client.post("/v1/auth/logout")).status_code == 401
        r = await client.post("/v1/auth/logout")
        assert r.status_code == 429
        assert r.json()["detail"]["code"] == "rate_limited"
        assert int(r.headers["retry-after"]) >= 1
        assert (await client.get("/v1/auth/session")).status_code == 401  # 4th request
        assert (await client.get("/v1/auth/session")).status_code == 429
        # Health checks are not limited.
        assert (await client.get("/health/live")).status_code == 200
