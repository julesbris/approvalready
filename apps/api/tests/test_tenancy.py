"""Organisations, invitations, roles, privilege rules and tenant isolation."""

from __future__ import annotations

import pytest

from tests.harness import ApiHarness, User

pytestmark = pytest.mark.integration

VALID_ABN = "51824753556"  # the ATO's published example ABN


async def _business(owner: User, name: str = "Acme Pty Ltd") -> str:
    r = await owner.post(
        "/v1/organisations", json={"name": name, "kind": "BUSINESS", "abn": "51 824 753 556"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["abn"] == VALID_ABN
    assert set(body["roles"]) == {"CUSTOMER", "ORG_ADMIN"}
    return str(body["id"])


async def _invite_and_join(
    api: ApiHarness, admin: User, org_id: str, roles: list[str], name: str = "Member"
) -> User:
    member_email = f"{name.lower()}-{org_id[:8]}@example.com"
    r = await admin.post(
        f"/v1/organisations/{org_id}/invitations", json={"email": member_email, "roles": roles}
    )
    assert r.status_code == 201, r.text
    token = api.token_from(api.last_email(member_email, "org.invitation"), "accept")
    member = await api.user(name=name, email=member_email)
    r = await member.post("/v1/invitations/accept", json={"token": token})
    assert r.status_code == 200, r.text
    return member


async def _member_id(user: User, org_id: str, email: str) -> str:
    members = (await user.get(f"/v1/organisations/{org_id}/members")).json()
    return str(next(m["id"] for m in members if m["email"] == email))


# --- Organisations ---------------------------------------------------------------------


async def test_create_and_update_business(api: ApiHarness) -> None:
    owner = await api.user()
    org_id = await _business(owner)
    listed = (await owner.get("/v1/organisations")).json()
    assert [o["kind"] for o in listed] == ["PERSONAL", "BUSINESS"]

    r = await owner.patch(f"/v1/organisations/{org_id}", json={"name": "Acme Holdings"})
    assert r.status_code == 200
    assert r.json()["name"] == "Acme Holdings"


@pytest.mark.parametrize("abn", ["51824753557", "1234", "abcdefghijk"])
async def test_invalid_abn_rejected(api: ApiHarness, abn: str) -> None:
    owner = await api.user()
    r = await owner.post("/v1/organisations", json={"name": "X", "kind": "BUSINESS", "abn": abn})
    assert r.status_code == 422


@pytest.mark.parametrize("kind", ["PARTNER", "PLATFORM_ADMIN", "PERSONAL"])
async def test_privileged_kinds_cannot_be_self_created(api: ApiHarness, kind: str) -> None:
    owner = await api.user()
    r = await owner.post("/v1/organisations", json={"name": "X", "kind": kind})
    assert r.status_code == 422


# --- Invitations -----------------------------------------------------------------------


async def test_invitation_flow_and_member_permissions(api: ApiHarness) -> None:
    admin = await api.user(name="Admin")
    org_id = await _business(admin)
    member = await _invite_and_join(api, admin, org_id, ["CUSTOMER"], name="Bob")

    orgs = {o["id"]: o for o in (await member.get("/v1/organisations")).json()}
    assert orgs[org_id]["roles"] == ["CUSTOMER"]
    members = (await member.get(f"/v1/organisations/{org_id}/members")).json()
    assert {m["display_name"] for m in members} == {"Admin", "Bob"}

    # A plain customer member can read but not manage.
    assert (await member.get(f"/v1/organisations/{org_id}/invitations")).status_code == 403
    r = await member.post(
        f"/v1/organisations/{org_id}/invitations",
        json={"email": "x@example.com", "roles": ["CUSTOMER"]},
    )
    assert r.status_code == 403
    r = await member.patch(f"/v1/organisations/{org_id}", json={"name": "Hijacked"})
    assert r.status_code == 403
    assert (await member.get(f"/v1/organisations/{org_id}/audit-events")).status_code == 403


async def test_invitation_token_bound_to_email(api: ApiHarness) -> None:
    admin = await api.user()
    org_id = await _business(admin)
    await admin.post(
        f"/v1/organisations/{org_id}/invitations",
        json={"email": "intended@example.com", "roles": ["CUSTOMER"]},
    )
    token = api.token_from(api.last_email("intended@example.com", "org.invitation"), "accept")
    stranger = await api.user()
    r = await stranger.post("/v1/invitations/accept", json={"token": token})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "invitation_email_mismatch"


async def test_reinvite_replaces_and_revoke_invalidates(api: ApiHarness) -> None:
    admin = await api.user()
    org_id = await _business(admin)
    email = f"re-{org_id[:8]}@example.com"
    for _ in range(2):
        await admin.post(
            f"/v1/organisations/{org_id}/invitations", json={"email": email, "roles": ["CUSTOMER"]}
        )
    first, second = (api.token_from(m, "accept") for m in api.emails_to(email, "org.invitation"))
    open_invites = (await admin.get(f"/v1/organisations/{org_id}/invitations")).json()
    assert len(open_invites) == 1

    invitee = await api.user(email=email)
    assert (await invitee.post("/v1/invitations/accept", json={"token": first})).status_code == 400
    r = await admin.delete(f"/v1/organisations/{org_id}/invitations/{open_invites[0]['id']}")
    assert r.status_code == 204
    assert (await invitee.post("/v1/invitations/accept", json={"token": second})).status_code == 400


async def test_personal_account_cannot_invite(api: ApiHarness) -> None:
    user = await api.user()
    r = await user.post(
        f"/v1/organisations/{user.personal_org_id}/invitations",
        json={"email": "friend@example.com", "roles": ["CUSTOMER"]},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "single_member_org"


# --- Role rules ------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["PARTNER_ADMIN", "SUPERADMIN", "STAFF", "NOT_A_ROLE"])
async def test_roles_outside_org_kind_cannot_be_granted(api: ApiHarness, role: str) -> None:
    admin = await api.user()
    org_id = await _business(admin)
    r = await admin.post(
        f"/v1/organisations/{org_id}/invitations",
        json={"email": "someone@example.com", "roles": [role]},
    )
    assert r.status_code == 422


async def test_member_without_manage_cannot_change_roles(api: ApiHarness) -> None:
    admin = await api.user(name="Admin")
    org_id = await _business(admin)
    member = await _invite_and_join(api, admin, org_id, ["CUSTOMER"], name="Mallory")
    admin_member_id = await _member_id(member, org_id, admin.email)
    own_id = await _member_id(member, org_id, member.email)
    for target in (admin_member_id, own_id):
        r = await member.put(
            f"/v1/organisations/{org_id}/members/{target}/roles", json={"roles": ["ORG_ADMIN"]}
        )
        assert r.status_code == 403


async def test_admin_can_promote_and_last_admin_is_protected(api: ApiHarness) -> None:
    admin = await api.user(name="Admin")
    org_id = await _business(admin)
    member = await _invite_and_join(api, admin, org_id, ["CUSTOMER"], name="Carol")
    admin_member_id = await _member_id(admin, org_id, admin.email)

    # Sole admin cannot demote themselves or leave.
    r = await admin.put(
        f"/v1/organisations/{org_id}/members/{admin_member_id}/roles", json={"roles": ["CUSTOMER"]}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "last_admin"
    assert (
        await admin.delete(f"/v1/organisations/{org_id}/members/{admin_member_id}")
    ).status_code == 409

    # Promote Carol; now the original admin can step down.
    carol_id = await _member_id(admin, org_id, member.email)
    r = await admin.put(
        f"/v1/organisations/{org_id}/members/{carol_id}/roles",
        json={"roles": ["CUSTOMER", "ORG_ADMIN"]},
    )
    assert r.status_code == 200
    assert set(r.json()["roles"]) == {"CUSTOMER", "ORG_ADMIN"}
    assert (
        await admin.delete(f"/v1/organisations/{org_id}/members/{admin_member_id}")
    ).status_code == 204
    assert (await admin.get(f"/v1/organisations/{org_id}")).status_code == 404


async def test_member_can_leave(api: ApiHarness) -> None:
    admin = await api.user()
    org_id = await _business(admin)
    member = await _invite_and_join(api, admin, org_id, ["CUSTOMER"], name="Dave")
    own_id = await _member_id(member, org_id, member.email)
    assert (await member.delete(f"/v1/organisations/{org_id}/members/{own_id}")).status_code == 204
    assert (await member.get(f"/v1/organisations/{org_id}")).status_code == 404


async def test_cannot_leave_personal_account(api: ApiHarness) -> None:
    user = await api.user()
    own_id = await _member_id(user, user.personal_org_id, user.email)
    r = await user.delete(f"/v1/organisations/{user.personal_org_id}/members/{own_id}")
    assert r.status_code == 409


# --- Tenant isolation ------------------------------------------------------------------


async def test_outsider_sees_nothing(api: ApiHarness) -> None:
    owner = await api.user()
    org_id = await _business(owner)
    outsider = await api.user()
    owner_member_id = await _member_id(owner, org_id, owner.email)

    base = f"/v1/organisations/{org_id}"
    reads = [base, f"{base}/members", f"{base}/invitations", f"{base}/audit-events"]
    for url in reads:
        r = await outsider.get(url)
        assert r.status_code == 404, url  # not 403: don't reveal the organisation exists
    writes = [
        ("patch", base, {"json": {"name": "Owned"}}),
        (
            "post",
            f"{base}/invitations",
            {"json": {"email": "x@example.com", "roles": ["CUSTOMER"]}},
        ),
        ("put", f"{base}/members/{owner_member_id}/roles", {"json": {"roles": ["CUSTOMER"]}}),
        ("delete", f"{base}/members/{owner_member_id}", {}),
    ]
    for method, url, kwargs in writes:
        r = await getattr(outsider, method)(url, **kwargs)
        assert r.status_code == 404, (method, url)
    # Personal accounts are tenants too.
    assert (await outsider.get(f"/v1/organisations/{owner.personal_org_id}")).status_code == 404
    assert org_id not in {o["id"] for o in (await outsider.get("/v1/organisations")).json()}


async def test_removed_member_loses_access_immediately(api: ApiHarness) -> None:
    admin = await api.user()
    org_id = await _business(admin)
    member = await _invite_and_join(api, admin, org_id, ["CUSTOMER"], name="Erin")
    assert (await member.get(f"/v1/organisations/{org_id}")).status_code == 200
    erin_id = await _member_id(admin, org_id, member.email)
    assert (await admin.delete(f"/v1/organisations/{org_id}/members/{erin_id}")).status_code == 204
    assert (await member.get(f"/v1/organisations/{org_id}")).status_code == 404


async def test_unknown_organisation_is_404(api: ApiHarness) -> None:
    user = await api.user()
    r = await user.get("/v1/organisations/00000000-0000-7000-8000-000000000000")
    assert r.status_code == 404


# --- Active organisation ---------------------------------------------------------------


async def test_switch_active_organisation_rotates_session(api: ApiHarness) -> None:
    user = await api.user()
    org_id = await _business(user)
    old_token = user.client.cookies.get("ar_session")
    r = await user.put("/v1/auth/session/organisation", json={"organisation_id": org_id})
    assert r.status_code == 200
    assert r.json()["active_organisation_id"] == org_id
    assert "org.audit.read" in r.json()["permissions"]
    assert user.client.cookies.get("ar_session") != old_token
    assert await api.session_status(old_token) == 401  # privilege change: no grace period

    stranger = await api.user()
    r = await stranger.put("/v1/auth/session/organisation", json={"organisation_id": org_id})
    assert r.status_code == 404
