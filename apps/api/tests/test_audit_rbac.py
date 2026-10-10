"""Audit log (append-only, hash chain, visibility) and the seeded role catalogue."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import cli
from app.modules.audit import service as audit
from app.modules.audit.models import AuditEvent
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation, OrganisationMember, Role
from app.modules.tenancy.rbac import PERMISSION_DESCRIPTIONS, ROLES
from tests.harness import ApiHarness, enable_mfa

pytestmark = pytest.mark.integration


async def test_actions_are_audited_and_visible_to_org_admins(api: ApiHarness) -> None:
    owner = await api.user()
    r = await owner.post("/v1/organisations", json={"name": "Audited Co", "kind": "BUSINESS"})
    org_id = r.json()["id"]
    await owner.patch(f"/v1/organisations/{org_id}", json={"name": "Audited Co Pty Ltd"})

    events = (await owner.get(f"/v1/organisations/{org_id}/audit-events")).json()
    assert [e["action"] for e in events] == ["org.updated", "org.created"]
    assert events[0]["actor_user_id"] == owner.id
    assert events[0]["details"] == {"fields": ["name"]}

    async with api.app.state.resources.session_factory() as db:
        actions = (
            (
                await db.execute(
                    select(AuditEvent.action).where(AuditEvent.actor_user_id == owner.id)
                )
            )
            .scalars()
            .all()
        )
    assert {"auth.registered", "auth.email_verified", "auth.login.succeeded"} <= set(actions)


async def test_failed_logins_are_audited_without_the_address(api: ApiHarness) -> None:
    email = "nobody-audit@example.com"
    await api.client.post("/v1/auth/login", json={"email": email, "password": "x"})
    async with api.app.state.resources.session_factory() as db:
        event = (
            await db.execute(
                select(AuditEvent)
                .where(AuditEvent.action == "auth.login.failed")
                .order_by(AuditEvent.seq.desc())
                .limit(1)
            )
        ).scalar_one()
    assert email not in str(event.details)
    assert "email_digest" in event.details


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_event SET action = 'tampered'",
        "DELETE FROM audit_event",
        "TRUNCATE audit_event",
    ],
)
async def test_audit_log_is_append_only(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession], statement: str
) -> None:
    await api.user()  # make sure there is at least one row
    # The application role has no UPDATE/DELETE/TRUNCATE privilege on the table at all...
    async with api.app.state.resources.session_factory() as db:
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text(statement))
        await db.rollback()
    # ...and the triggers stop even the owner.
    async with owner_sessions() as db:
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text(statement))
        await db.rollback()


async def test_hash_chain_verifies_and_detects_tampering(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    await api.user()
    factory = owner_sessions
    async with factory() as db:
        assert (await audit.verify_chain(db)).ok

    async with factory() as db:
        victim = (
            await db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1))
        ).scalar_one()
        seq, original = victim.seq, victim.action
    # Simulate someone with superuser access bypassing the triggers.
    async with factory() as db:
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        await db.execute(
            text("UPDATE audit_event SET action = 'auth.nothing_to_see' WHERE seq = :s"),
            {"s": seq},
        )
        await db.commit()
    try:
        async with factory() as db:
            result = await audit.verify_chain(db)
        assert not result.ok
        assert result.first_bad_seq == seq
    finally:
        async with factory() as db:
            await db.execute(text("SET LOCAL session_replication_role = replica"))
            await db.execute(
                text("UPDATE audit_event SET action = :a WHERE seq = :s"),
                {"a": original, "s": seq},
            )
            await db.commit()
    async with factory() as db:
        assert (await audit.verify_chain(db)).ok


async def test_platform_admin_bootstrap_and_audit_verification(
    api: ApiHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ops = await api.user(name="Ops")
    customer = await api.user()
    monkeypatch.setattr(cli, "get_settings", lambda: api.app.state.settings)

    async with api.app.state.resources.session_factory() as db:
        platform = (
            await db.execute(select(Organisation).where(Organisation.kind == "PLATFORM_ADMIN"))
        ).scalar_one_or_none()
    if platform is None:
        assert await cli.grant_platform_role(ops.email, cli.RoleKey.STAFF) == 1  # must bootstrap
        assert await cli.grant_platform_role(ops.email, cli.RoleKey.SUPERADMIN) == 0
    else:
        assert await cli.grant_platform_role(ops.email, cli.RoleKey.ADMIN) == 0

    assert await cli.platform_access(ops.email) == 0
    assert await cli.platform_access(customer.email) == 1  # no platform role
    assert await cli.platform_access("nobody@example.com") == 1
    assert await cli.platform_access(None) == 0
    out = capsys.readouterr().out
    assert "/admin/ops: yes" in out
    assert f"grant-platform-role --email {customer.email}" in out

    async with api.app.state.resources.session_factory() as db:
        platform_id = (
            await db.execute(select(Organisation.id).where(Organisation.kind == "PLATFORM_ADMIN"))
        ).scalar_one()

    # Platform permissions only apply with the platform organisation active.
    assert (await ops.get("/v1/admin/audit/verify")).status_code == 403
    r = await ops.put("/v1/auth/session/organisation", json={"organisation_id": str(platform_id)})
    assert r.status_code == 200
    # ...and only for a session that passed two-step sign-in (Milestone 18).
    assert r.json()["staff_mfa_required"] is True
    assert r.json()["permissions"] == []
    r = await ops.get("/v1/admin/audit/verify")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "mfa_required"
    await enable_mfa(ops)
    assert ops.session["staff_mfa_required"] is False
    assert "platform.audit.read" in ops.session["permissions"]
    r = await ops.get("/v1/admin/audit/verify")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["checked"] > 0

    assert (await customer.get("/v1/admin/audit/verify")).status_code == 403


# --- Role catalogue --------------------------------------------------------------------


async def test_seeded_roles_match_catalogue(api: ApiHarness) -> None:
    async with api.app.state.resources.session_factory() as db:
        seeded = {
            r.key: (r.scope, sorted(r.allowed_org_kinds))
            for r in (await db.execute(select(Role))).scalars()
        }
        for key, (scope, _, kinds, permissions) in ROLES.items():
            assert seeded[key] == (scope, sorted(kinds)), key
            assert await tenancy.permissions_of_roles(db, [key]) == {str(p) for p in permissions}
        permission_keys = (await db.execute(text("SELECT key FROM permission"))).scalars().all()
    assert set(seeded) == set(ROLES)
    assert set(permission_keys) == {str(p) for p in PERMISSION_DESCRIPTIONS}


async def test_database_rejects_platform_role_in_customer_org(api: ApiHarness) -> None:
    user = await api.user()
    async with api.app.state.resources.session_factory() as db:
        member_id = (
            await db.execute(
                select(OrganisationMember.id).where(
                    OrganisationMember.organisation_id == user.personal_org_id
                )
            )
        ).scalar_one()
        with pytest.raises(DBAPIError, match="cannot be granted"):
            await db.execute(
                text(
                    "INSERT INTO member_role (organisation_member_id, role_id) "
                    "SELECT :m, id FROM role WHERE key = 'SUPERADMIN'"
                ),
                {"m": member_id},
            )
        await db.rollback()
