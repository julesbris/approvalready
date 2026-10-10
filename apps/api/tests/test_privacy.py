"""Milestone 19: policy acceptance, download my data, close my account, privacy requests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.identity.models import AppUser, UserStatus
from app.modules.ops.checks import CheckState, privacy_check
from app.modules.privacy import policies
from app.modules.privacy.models import PolicyAcceptance, PrivacyRequest
from tests.harness import PASSWORD, ApiHarness, platform_user, totp_code, unique_email
from tests.test_projects import create_project

Owner = async_sessionmaker[AsyncSession]


# --- Policy acceptance -----------------------------------------------------------------


async def test_registration_needs_agreement_to_the_policies(api: ApiHarness) -> None:
    r = await api.client.post(
        "/v1/auth/register",
        json={"email": unique_email(), "password": PASSWORD, "display_name": "No Terms"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "terms_not_accepted"


async def test_registration_records_the_current_versions(
    api: ApiHarness, owner_sessions: Owner
) -> None:
    user = await api.user()
    assert user.session["policies_to_accept"] == []
    async with owner_sessions() as db:
        rows = (
            await db.execute(
                select(PolicyAcceptance.document, PolicyAcceptance.version).where(
                    PolicyAcceptance.user_id == user.id
                )
            )
        ).all()
    assert sorted(rows) == sorted((p.document.value, p.version) for p in policies.current())


async def test_existing_users_are_asked_to_agree_again(
    api: ApiHarness, owner_sessions: Owner
) -> None:
    user = await api.user()
    async with owner_sessions() as db:  # as if they registered before Milestone 19
        await db.execute(delete(PolicyAcceptance).where(PolicyAcceptance.user_id == user.id))
        await db.commit()
    session = (await user.get("/v1/auth/session")).json()
    assert {p["document"] for p in session["policies_to_accept"]} == {"terms", "privacy"}
    assert session["policies_to_accept"][0]["path"].startswith("/")

    r = await user.post("/v1/auth/policies/accept", json={"documents": ["terms"]})
    assert r.status_code == 200, r.text
    assert [p["document"] for p in r.json()] == ["privacy"]
    r = await user.post("/v1/auth/policies/accept", json={"documents": ["terms", "privacy"]})
    assert r.json() == []
    # Agreeing again records nothing new.
    r = await user.post("/v1/auth/policies/accept", json={"documents": ["terms"]})
    assert r.status_code == 200
    async with owner_sessions() as db:
        count = len(
            (
                await db.execute(
                    select(PolicyAcceptance).where(PolicyAcceptance.user_id == user.id)
                )
            ).all()
        )
    assert count == 2
    assert (await user.get("/v1/auth/session")).json()["policies_to_accept"] == []


async def test_accepting_needs_a_signed_in_user_and_csrf(api: ApiHarness) -> None:
    r = await api.client.post("/v1/auth/policies/accept", json={"documents": ["terms"]})
    assert r.status_code == 401
    user = await api.user()
    r = await user.client.post("/v1/auth/policies/accept", json={"documents": ["terms"]})
    assert r.status_code == 403


# --- Download my data ------------------------------------------------------------------


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


async def test_export_has_the_account_and_personal_workspace(api: ApiHarness) -> None:
    user = await api.user(name="Exporter")
    await create_project(user, user.personal_org_id, title="My granny flat")
    r = await user.get("/v1/auth/account/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["cache-control"] == "no-store"
    data = json.loads(r.content)
    assert data["account"]["email"] == user.email
    assert data["account"]["display_name"] == "Exporter"
    assert [o["kind"] for o in data["organisations"]] == ["PERSONAL"]
    assert data["notification_settings"]["REMINDERS"] == "ALL"
    assert data["sign_ins"]
    assert {a["document"] for a in data["policy_acceptances"]} == {"terms", "privacy"}
    assert any(e["action"] == "auth.registered" for e in data["activity"])
    projects = data["personal_workspace"]["project"]
    assert [p["title"] for p in projects] == ["My granny flat"]
    # Credentials and token digests never leave the server.
    leaked = {k for k in _keys(data) if "hash" in k or "secret" in k or "token" in k}
    assert leaked == set()


async def test_export_only_covers_the_users_own_workspace(api: ApiHarness) -> None:
    alice = await api.user(name="Alice")
    bob = await api.user(name="Bob")
    await create_project(bob, bob.personal_org_id, title="Bob's project")
    data = (await alice.get("/v1/auth/account/export")).json()
    assert "project" not in data["personal_workspace"]
    assert "Bob" not in json.dumps(data)


async def test_export_is_rate_limited(api: ApiHarness) -> None:
    user = await api.user()
    for _ in range(10):
        assert (await user.get("/v1/auth/account/export")).status_code == 200
    assert (await user.get("/v1/auth/account/export")).status_code == 429


# --- Close my account ------------------------------------------------------------------


async def test_closing_an_account(api: ApiHarness, owner_sessions: Owner) -> None:
    user = await api.user(name="Leaving")
    await create_project(user, user.personal_org_id)
    other_device = await api.login(user.email)

    r = await user.post("/v1/auth/account/close", json={"password": "wrong password!"})
    assert r.status_code == 400
    r = await user.post("/v1/auth/account/close", json={"password": PASSWORD})
    assert r.status_code == 204, r.text

    # Signed out everywhere and can't sign in again.
    assert (await user.get("/v1/auth/session")).status_code == 401
    assert (await other_device.get("/v1/auth/session")).status_code == 401
    r = await (await api.new_client()).post(
        "/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert r.status_code == 401
    assert api.last_email(user.email, "privacy.account_closed")

    async with owner_sessions() as db:
        row = await db.get(AppUser, user.id)
        assert row is not None
        assert row.email != user.email and row.email.endswith(".invalid")
        assert row.display_name == "Closed account"
        assert row.status == UserStatus.DELETION_REQUESTED
        assert row.deleted_at is not None
        request = (
            await db.execute(select(PrivacyRequest).where(PrivacyRequest.user_id == user.id))
        ).scalar_one()
        assert request.kind == "DELETION" and request.source == "ACCOUNT_CLOSED"
        assert request.email == user.email
        assert request.due_at > datetime.now(UTC) + timedelta(days=29)

    # The address is free to register again.
    await api.user(email=user.email)


async def test_closing_needs_the_code_when_two_step_sign_in_is_on(api: ApiHarness) -> None:
    from tests.harness import enable_mfa

    user = await api.user()
    secret = await enable_mfa(user)
    r = await user.post("/v1/auth/account/close", json={"password": PASSWORD})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "mfa_code_required"
    r = await user.post("/v1/auth/account/close", json={"password": PASSWORD, "code": "000000"})
    assert r.status_code == 400
    r = await user.post(
        "/v1/auth/account/close", json={"password": PASSWORD, "code": totp_code(secret, 1)}
    )
    assert r.status_code == 204, r.text


async def test_closing_is_refused_while_in_a_business(api: ApiHarness) -> None:
    user = await api.user()
    r = await user.post("/v1/organisations", json={"name": "Corner Shop", "kind": "BUSINESS"})
    assert r.status_code == 201, r.text
    r = await user.post("/v1/auth/account/close", json={"password": PASSWORD})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "account_has_organisations"
    assert "Corner Shop" in r.json()["detail"]["message"]
    assert (await user.get("/v1/auth/session")).status_code == 200


# --- Privacy requests ------------------------------------------------------------------


async def test_privacy_requests_reach_staff(api: ApiHarness) -> None:
    body = {
        "name": "Pat Citizen",
        "email": "pat@example.com",
        "kind": "ACCESS",
        "details": "Please tell me what you hold about me.",
    }
    r = await api.client.post("/v1/privacy/requests", json=body)
    assert r.status_code == 202, r.text
    reference = r.json()["reference"]
    assert len(reference) == 8

    customer = await api.user()
    assert (await customer.get("/v1/admin/privacy/requests")).status_code == 403
    staff = await platform_user(api, role="STAFF", name="Plain staff")
    assert (await staff.get("/v1/admin/privacy/requests")).status_code == 403

    admin = await platform_user(api)
    listed = (await admin.get("/v1/admin/privacy/requests", params={"status": "OPEN"})).json()
    mine = next(r for r in listed if r["id"].upper().endswith(reference))
    assert mine["details"] == body["details"] and mine["source"] == "CONTACT_FORM"

    ops = (await admin.get("/v1/admin/ops")).json()
    check = next(c for c in ops["checks"] if c["key"] == "privacy")
    assert check["state"] == "WARNING"

    r = await admin.patch(
        f"/v1/admin/privacy/requests/{mine['id']}",
        json={"status": "DONE", "note": "Sent the export by email."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DONE" and r.json()["resolved_at"] is not None


async def test_privacy_requests_are_validated_and_rate_limited(api: ApiHarness) -> None:
    body = {"name": "X", "email": "x@example.com", "kind": "OTHER", "details": "short"}
    assert (await api.client.post("/v1/privacy/requests", json=body)).status_code == 422
    body["details"] = "A long enough question about my data."
    codes = [
        (await api.client.post("/v1/privacy/requests", json=body)).status_code for _ in range(6)
    ]
    assert codes == [202] * 5 + [429]


def test_privacy_check_states() -> None:
    now = datetime.now(UTC)
    assert privacy_check(0, 0, None).state == CheckState.OK
    assert privacy_check(2, 0, now + timedelta(days=3)).state == CheckState.WARNING
    assert privacy_check(2, 1, now - timedelta(days=1)).state == CheckState.FAILING
