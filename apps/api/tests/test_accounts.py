"""Staff accounts page (Milestone 27): find accounts, see them, and the support actions."""

from __future__ import annotations

import pytest
from httpx import Response
from sqlalchemy import select

from app.modules.audit.models import AuditEvent
from tests.harness import (
    PASSWORD,
    ApiHarness,
    User,
    enable_mfa,
    platform_user,
    unique_email,
)

pytestmark = pytest.mark.integration


async def _action(staff: User, account_id: str, action: str, reason: str = "") -> Response:
    return await staff.post(
        f"/v1/admin/accounts/{account_id}/actions", json={"action": action, "reason": reason}
    )


async def test_reading_needs_a_platform_role(api: ApiHarness) -> None:
    customer = await api.user()
    assert (await customer.get("/v1/admin/accounts")).status_code == 403
    r = await customer.post("/v1/admin/accounts/search", json={"query": customer.email})
    assert r.status_code == 403
    assert (await customer.get(f"/v1/admin/accounts/{customer.id}")).status_code == 403

    staff = await platform_user(api, role="STAFF", name="Plain staff")
    assert (await staff.get("/v1/admin/accounts")).status_code == 200
    detail = (await staff.get(f"/v1/admin/accounts/{customer.id}")).json()
    assert detail["email"] == customer.email
    # Plain staff can look but not change anything.
    assert detail["allowed_actions"] == []
    assert (await _action(staff, customer.id, "sign_out_everywhere")).status_code == 403


async def test_search_by_email_name_business_and_abn(api: ApiHarness) -> None:
    admin = await platform_user(api)
    tag = unique_email("findme").split("@")[0]
    customer = await api.user(name=f"Robin {tag}")
    r = await customer.post(
        "/v1/organisations",
        json={"name": f"Reef Tours {tag}", "kind": "BUSINESS", "abn": "51824753556"},
    )
    assert r.status_code == 201, r.text

    async def found(query: str, status: str | None = None) -> list[str]:
        r = await admin.post("/v1/admin/accounts/search", json={"query": query, "status": status})
        assert r.status_code == 200, r.text
        return [a["id"] for a in r.json()]

    assert customer.id in await found(customer.email.upper())
    assert customer.id in await found(f"robin {tag}")
    assert customer.id in await found(f"reef tours {tag}")
    assert customer.id in await found("518 247 535 56")
    assert customer.id in await found(customer.id)
    assert customer.id not in await found(f"{tag}-nobody")
    # LIKE wildcards are matched literally.
    assert customer.id not in await found("%")
    assert customer.id in await found(customer.email, "ACTIVE")
    assert customer.id not in await found(customer.email, "SUSPENDED")
    assert admin.id in await found(admin.email, "STAFF")

    summary = next(
        a
        for a in (
            await admin.post("/v1/admin/accounts/search", json={"query": customer.email})
        ).json()
        if a["id"] == customer.id
    )
    assert summary["organisations"] == 2  # personal workspace and the business
    assert summary["email_verified"] and not summary["mfa_enabled"]
    assert summary["platform_role"] is None
    newest = (await admin.get("/v1/admin/accounts")).json()
    assert customer.id in [a["id"] for a in newest]


async def test_detail_shows_organisations_sessions_and_history(api: ApiHarness) -> None:
    admin = await platform_user(api)
    customer = await api.user(name="Detail Person")
    await customer.post("/v1/organisations", json={"name": "Detail Co", "kind": "BUSINESS"})

    r = await admin.get(f"/v1/admin/accounts/{customer.id}")
    assert r.status_code == 200, r.text
    detail = r.json()
    assert {m["name"] for m in detail["memberships"]} >= {"Detail Co"}
    business = next(m for m in detail["memberships"] if m["name"] == "Detail Co")
    assert business["kind"] == "BUSINESS" and "ORG_ADMIN" in business["roles"]
    assert len(detail["sessions"]) >= 1 and detail["password_set"]
    actions = [e["action"] for e in detail["events"]]
    assert "auth.registered" in actions and "auth.login.succeeded" in actions
    assert all(e["by"] in ("self", "other", "system") for e in detail["events"])
    assert detail["allowed_actions"] == ["send_password_reset", "sign_out_everywhere", "suspend"]

    # Opening an account is audited, once per half hour per staff member.
    await admin.get(f"/v1/admin/accounts/{customer.id}")
    async with api.app.state.resources.session_factory() as db:
        views = (
            (
                await db.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "admin.account.viewed",
                        AuditEvent.target_id == customer.id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(views) == 1 and str(views[0].actor_user_id) == admin.id
    assert (await admin.get(f"/v1/admin/accounts/{admin.id}x")).status_code == 422
    missing = "00000000-0000-7000-8000-000000000000"
    assert (await admin.get(f"/v1/admin/accounts/{missing}")).status_code == 404


async def test_resend_verification_and_password_reset(api: ApiHarness) -> None:
    admin = await platform_user(api)
    email = await api.register(name="Not Yet Verified")
    found = (await admin.post("/v1/admin/accounts/search", json={"query": email})).json()
    account_id = found[0]["id"]
    assert found[0]["email_verified"] is False
    detail = (await admin.get(f"/v1/admin/accounts/{account_id}")).json()
    assert detail["allowed_actions"][0] == "resend_verification"

    before = len(api.emails_to(email, "auth.verify_email"))
    r = await _action(admin, account_id, "resend_verification")
    assert r.status_code == 200, r.text
    assert email in r.json()["message"]
    assert len(api.emails_to(email, "auth.verify_email")) == before + 1
    await api.verify(email)  # the new link works
    after = (await admin.get(f"/v1/admin/accounts/{account_id}")).json()
    assert after["email_verified"] is True
    assert (await _action(admin, account_id, "resend_verification")).status_code == 409

    r = await _action(admin, account_id, "send_password_reset")
    assert r.status_code == 200, r.text
    token = api.token_from(api.last_email(email, "auth.password_reset"), "reset")
    r = await api.client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "password": "a brand new long passphrase"},
    )
    assert r.status_code == 200, r.text
    await api.login(email, "a brand new long passphrase")

    events = (await admin.get(f"/v1/admin/accounts/{account_id}")).json()["events"]
    sent = next(e for e in events if e["action"] == "admin.account.password_reset_sent")
    assert sent["by"] == "other" and sent["actor_email"] == admin.email


async def test_sign_out_everywhere(api: ApiHarness) -> None:
    admin = await platform_user(api)
    customer = await api.user()
    r = await _action(admin, customer.id, "sign_out_everywhere")
    assert r.status_code == 200, r.text
    assert r.json()["account"]["sessions"] == []
    assert (await customer.get("/v1/auth/session")).status_code == 401
    # Nothing left to sign out of.
    assert (await _action(admin, customer.id, "sign_out_everywhere")).status_code == 409


async def test_reset_two_step_needs_a_reason(api: ApiHarness) -> None:
    admin = await platform_user(api)
    customer = await api.user()
    await enable_mfa(customer)
    detail = (await admin.get(f"/v1/admin/accounts/{customer.id}")).json()
    assert detail["mfa_enabled"] and detail["recovery_codes_left"] == 10
    assert "reset_two_step" in detail["allowed_actions"]

    r = await _action(admin, customer.id, "reset_two_step", "  ")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reason_required"
    r = await _action(admin, customer.id, "reset_two_step", "Lost phone; checked ID on a call")
    assert r.status_code == 200, r.text
    account = r.json()["account"]
    assert account["mfa_enabled"] is False and account["sessions"] == []
    assert api.last_email(customer.email, "auth.mfa_disabled")
    # Signs in with the password alone again.
    await api.login(customer.email)
    reset = next(e for e in account["events"] if e["action"] == "auth.mfa.reset")
    assert reset["details"]["reason"] == "Lost phone; checked ID on a call"
    assert reset["actor_email"] == admin.email


async def test_suspend_and_restore(api: ApiHarness) -> None:
    admin = await platform_user(api)
    customer = await api.user()
    assert (await _action(admin, customer.id, "suspend")).status_code == 422
    r = await _action(admin, customer.id, "suspend", "Chargeback fraud report")
    assert r.status_code == 200, r.text
    assert r.json()["account"]["status"] == "SUSPENDED"
    assert r.json()["account"]["allowed_actions"] == ["restore"]
    assert (await customer.get("/v1/auth/session")).status_code == 401
    c = await api.new_client()
    r = await c.post("/v1/auth/login", json={"email": customer.email, "password": PASSWORD})
    assert r.status_code != 200
    found = (
        await admin.post(
            "/v1/admin/accounts/search", json={"query": customer.email, "status": "SUSPENDED"}
        )
    ).json()
    assert [a["id"] for a in found] == [customer.id]

    r = await _action(admin, customer.id, "restore")
    assert r.status_code == 200, r.text
    assert r.json()["account"]["status"] == "ACTIVE"
    await api.login(customer.email)


async def test_no_acting_on_yourself_or_on_higher_staff(api: ApiHarness) -> None:
    admin = await platform_user(api, name="Admin")
    me = (await admin.get(f"/v1/admin/accounts/{admin.id}")).json()
    assert me["allowed_actions"] == [] and me["platform_role"] == "ADMIN"
    assert (await _action(admin, admin.id, "sign_out_everywhere")).status_code == 403

    # An administrator can't touch another staff member's account; a super admin can.
    other_staff = await platform_user(api, role="STAFF", name="Other staff")
    other = (await admin.get(f"/v1/admin/accounts/{other_staff.id}")).json()
    assert other["allowed_actions"] == []
    r = await _action(admin, other_staff.id, "suspend", "testing")
    assert r.status_code == 403
    superadmin = await platform_user(api, role="SUPERADMIN", name="Super")
    other = (await superadmin.get(f"/v1/admin/accounts/{other_staff.id}")).json()
    assert "sign_out_everywhere" in other["allowed_actions"]
    r = await _action(superadmin, other_staff.id, "sign_out_everywhere")
    assert r.status_code == 200, r.text


async def test_closed_accounts_are_read_only(api: ApiHarness) -> None:
    admin = await platform_user(api)
    customer = await api.user()
    r = await customer.post("/v1/auth/account/close", json={"password": PASSWORD})
    assert r.status_code == 204, r.text
    detail = (await admin.get(f"/v1/admin/accounts/{customer.id}")).json()
    assert detail["closed"] is True and detail["allowed_actions"] == []
    found = (
        await admin.post("/v1/admin/accounts/search", json={"query": "", "status": "CLOSED"})
    ).json()
    assert customer.id in [a["id"] for a in found]
