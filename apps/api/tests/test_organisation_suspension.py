"""Suspending and restoring a business workspace from Admin > Accounts."""

from __future__ import annotations

import pytest
from httpx import Response

from tests.harness import ApiHarness, User, platform_user

pytestmark = pytest.mark.integration


async def _set(staff: User, user_id: str, org_id: str, status: str, reason: str = "") -> Response:
    return await staff.put(
        f"/v1/admin/accounts/{user_id}/organisations/{org_id}/status",
        json={"status": status, "reason": reason},
    )


async def test_suspend_and_restore_a_business(api: ApiHarness) -> None:
    owner = await api.user(name="Owner")
    r = await owner.post("/v1/organisations", json={"name": "Shady Co", "kind": "BUSINESS"})
    assert r.status_code == 201, r.text
    org_id = r.json()["id"]
    admin = await platform_user(api)
    staff = await platform_user(api, role="STAFF", name="Plain staff")

    detail = (await admin.get(f"/v1/admin/accounts/{owner.id}")).json()
    by_kind = {m["kind"]: m["can_suspend"] for m in detail["memberships"]}
    assert by_kind == {"PERSONAL": False, "BUSINESS": True}
    plain = (await staff.get(f"/v1/admin/accounts/{owner.id}")).json()
    assert not any(m["can_suspend"] for m in plain["memberships"])
    assert (await _set(staff, owner.id, org_id, "SUSPENDED", "spam")).status_code == 403

    r = await _set(admin, owner.id, org_id, "SUSPENDED")
    assert r.status_code == 422, r.text
    r = await _set(admin, owner.id, org_id, "SUSPENDED", "Sending spam to councils")
    assert r.status_code == 200, r.text
    assert "1 member" in r.json()["message"]
    business = next(m for m in r.json()["account"]["memberships"] if m["kind"] == "BUSINESS")
    assert business["organisation_status"] == "SUSPENDED"
    assert api.emails_to(owner.email, "admin.organisation_suspended")
    # The members can't open it any more.
    assert (await owner.get(f"/v1/organisations/{org_id}")).status_code == 404
    assert (await _set(admin, owner.id, org_id, "SUSPENDED", "again")).status_code == 409

    r = await _set(admin, owner.id, org_id, "ACTIVE")
    assert r.status_code == 200, r.text
    assert api.emails_to(owner.email, "admin.organisation_restored")
    assert (await owner.get(f"/v1/organisations/{org_id}")).status_code == 200


async def test_only_business_workspaces_of_that_account(api: ApiHarness) -> None:
    owner = await api.user()
    other = await api.user()
    admin = await platform_user(api)
    personal = next(
        m for m in (await admin.get(f"/v1/admin/accounts/{owner.id}")).json()["memberships"]
    )
    r = await _set(admin, owner.id, personal["organisation_id"], "SUSPENDED", "no")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_suspendable"
    # Someone else's account page can't be used for an organisation they aren't in.
    r = await _set(admin, other.id, personal["organisation_id"], "SUSPENDED", "no")
    assert r.status_code == 404
