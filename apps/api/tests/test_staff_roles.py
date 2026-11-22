"""Giving and taking away staff roles from Admin > Accounts."""

from __future__ import annotations

import pytest
from httpx import Response

from tests.harness import ApiHarness, User, platform_user

pytestmark = pytest.mark.integration


async def _set(
    staff: User, account_id: str, role: str | None, reason: str = "New hire"
) -> Response:
    return await staff.put(
        f"/v1/admin/accounts/{account_id}/staff-role", json={"role": role, "reason": reason}
    )


async def test_only_super_administrators_change_roles(api: ApiHarness) -> None:
    customer = await api.user()
    admin = await platform_user(api, role="ADMIN", name="Admin")
    assert (await _set(admin, customer.id, "STAFF")).status_code == 403
    detail = (await admin.get(f"/v1/admin/accounts/{customer.id}")).json()
    assert detail["can_change_role"] is False

    boss = await platform_user(api, role="SUPERADMIN", name="Boss")
    detail = (await boss.get(f"/v1/admin/accounts/{customer.id}")).json()
    assert detail["can_change_role"] is True
    own = (await boss.get(f"/v1/admin/accounts/{boss.id}")).json()
    assert own["can_change_role"] is False
    assert (await _set(boss, boss.id, None)).status_code == 403


async def test_give_change_and_take_away_a_role(api: ApiHarness) -> None:
    customer = await api.user(name="New Starter")
    boss = await platform_user(api, role="SUPERADMIN", name="Boss")

    r = await _set(boss, customer.id, "STAFF", reason=" ")
    assert r.status_code == 422, r.text
    r = await _set(boss, customer.id, "STAFF")
    assert r.status_code == 200, r.text
    assert r.json()["account"]["platform_role"] == "STAFF"
    [email] = api.emails_to(customer.email, "admin.staff_role_granted")
    assert "Staff" in email.subject and "organisation menu" in email.text
    assert (await _set(boss, customer.id, "STAFF")).status_code == 409

    # The platform organisation appears in their organisation menu.
    kinds = [o["kind"] for o in (await customer.get("/v1/auth/session")).json()["organisations"]]
    assert "PLATFORM_ADMIN" in kinds

    r = await _set(boss, customer.id, "ADMIN")
    assert r.status_code == 200, r.text
    assert r.json()["account"]["platform_role"] == "ADMIN"

    r = await _set(boss, customer.id, None, reason="Left the company")
    assert r.status_code == 200, r.text
    detail = r.json()["account"]
    assert detail["platform_role"] is None
    actions = [e["action"] for e in detail["events"]]
    assert "platform.role_removed" in actions and "platform.role_granted" in actions
    kinds = [o["kind"] for o in (await customer.get("/v1/auth/session")).json()["organisations"]]
    assert "PLATFORM_ADMIN" not in kinds
    assert (await _set(boss, customer.id, None)).status_code == 409


async def test_unconfirmed_accounts_cant_be_given_a_role(api: ApiHarness) -> None:
    boss = await platform_user(api, role="SUPERADMIN", name="Boss")
    email = await api.register(name="Not Confirmed")
    found = (await boss.post("/v1/admin/accounts/search", json={"query": email})).json()
    r = await _set(boss, found[0]["id"], "STAFF")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "account_not_ready"
