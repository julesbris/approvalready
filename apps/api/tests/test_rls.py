"""Row-level security and the application's database role.

The application connects as a non-owner role without BYPASSRLS. These tests talk to the
database directly (not through the API) to prove the database itself refuses cross-tenant
access, i.e. that RLS still holds when application code forgets a tenant filter.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import models  # noqa: F401 - registers every table
from app.db.base import Base, TenantMixin
from app.db.tenant import bind_tenant
from app.modules.projects.models import Project, Task
from tests.harness import ApiHarness, User

pytestmark = pytest.mark.integration

APP_GROUP = "approvalready_rw"
CRUD = {"SELECT", "INSERT", "UPDATE", "DELETE"}
WRITE = {"SELECT", "INSERT", "UPDATE"}
APPEND = {"SELECT", "INSERT"}
READ = {"SELECT"}

# The application's privileges, table by table. A new table must be added here on purpose.
EXPECTED_PRIVILEGES: dict[str, set[str]] = {
    "app_user": CRUD,
    "password_credential": CRUD,
    "auth_identity": CRUD,
    "auth_session": CRUD,
    "one_time_token": CRUD,
    "mfa_totp": CRUD,
    "mfa_recovery_code": CRUD,
    "policy_acceptance": APPEND,
    "privacy_request": {"SELECT", "INSERT", "UPDATE"},
    "organisation": CRUD,
    "organisation_member": CRUD,
    "organisation_invitation": CRUD,
    "member_role": CRUD,
    "role": READ,
    "permission": READ,
    "role_permission": READ,
    "audit_event": APPEND,
    "address": CRUD,
    "property": CRUD,
    "property_ownership": CRUD,
    "vessel": CRUD,
    "business_profile": CRUD,
    "project": CRUD,
    "project_status_event": APPEND,
    "task": CRUD,
    "reminder": CRUD,
    "questionnaire": READ,
    "questionnaire_version": READ,
    "question": READ,
    "question_version": READ,
    "question_option": READ,
    "questionnaire_submission": CRUD,
    "question_response": CRUD,
    "source_organisation": WRITE,
    "source_document": WRITE,
    "source_snapshot": APPEND,
    "source_reference": WRITE,
    "source_review_event": APPEND,
    "rule_set": WRITE,
    "rule": WRITE,
    "rule_version": CRUD,
    "rule_outcome": CRUD,
    "rule_source": CRUD,
    "rule_test_case": CRUD,
    "rule_fact_dependency": CRUD,
    "assessment": APPEND,
    "assessment_finding": APPEND,
    "approval_requirement": APPEND,
    "evidence_requirement": APPEND,
    "uploaded_document": WRITE,
    "evidence": CRUD,
    "document_template": READ,
    "document_template_version": READ,
    "generated_document": WRITE,
    "professional": WRITE,
    "professional_credential": CRUD,
    "professional_service": CRUD,
    "review_request": WRITE,
    "review_comment": APPEND,
    "finding_override": APPEND,
    "review_decision": APPEND,
    "marketplace_category": READ,
    # Milestone 9
    "vessel_certificate": WRITE,
    "safety_management_system": WRITE,
    "project_checklist": CRUD,
    "checklist_item": CRUD,
    # Milestone 10
    "grant_program": WRITE,
    "grant_round": WRITE,
    "grant_match": APPEND,
    # Milestone 12
    "prompt_version": READ,
    "ai_job": WRITE,
    "ai_provider_log": APPEND,
    # Milestone 13: the catalogue is reviewed data; prices and webhook events are platform
    # rows whose fixed columns triggers protect; billing customers are never edited.
    "product": READ,
    "feature": READ,
    "product_feature": READ,
    "price": WRITE,
    "stripe_event": WRITE,
    "billing_customer": APPEND,
    "payment": WRITE,
    "subscription": WRITE,
    "invoice_reference": WRITE,
    # Milestone 14: platform tables (staff verify across partners); credentials, categories
    # and service areas can be removed by the partner, service areas are never edited.
    "partner_organisation": WRITE,
    "partner_application": WRITE,
    "partner_credential": CRUD,
    "partner_category": CRUD,
    "partner_service_area": {"SELECT", "INSERT", "DELETE"},
    # Milestone 15: consent texts are synced by the owner; a consent only gains its
    # withdrawal (trigger); leads are platform rows; the released contact is deleted when a
    # lead closes; lead prices are replaced, never edited (trigger); events and the credit
    # ledger are append-only.
    "consent_text_version": READ,
    "referral_consent": WRITE,
    "lead": WRITE,
    "lead_contact": {"SELECT", "INSERT", "DELETE"},
    "lead_match": WRITE,
    "lead_claim": WRITE,
    "lead_status_event": APPEND,
    "lead_price": WRITE,
    "credit_ledger_entry": APPEND,
    # Milestone 17: the backup service writes backup runs as the owner; the worker may only
    # record the off-site copy (a column grant, which this table-level map doesn't list).
    "backup_run": READ,
    # Milestone 20: the API queues emails, the worker sends them and removes old rows.
    "email_outbox": CRUD,
    "notification_preference": CRUD,
    # Milestone 22: what a refund is never changes (trigger); only its sending progress does.
    "refund": WRITE,
    # Milestone 11
    "sale_project": WRITE,
    "sale_document": CRUD,
    "sale_offer": WRITE,
    "sale_enquiry": WRITE,
    "rental_property": WRITE,
    "tenant_application": WRITE,
    "tenancy": WRITE,
    "inspection": WRITE,
    "inspection_item": CRUD,
    "maintenance_item": WRITE,
    "notification": WRITE,
}

TENANT_TABLES = sorted(
    mapper.local_table.name  # type: ignore[union-attr]
    for mapper in Base.registry.mappers
    if issubclass(mapper.class_, TenantMixin)
)


async def _project(user: User, org_id: str, title: str = "Granny flat") -> str:
    r = await user.post(
        f"/v1/organisations/{org_id}/projects", json={"vertical": "PLANNING", "title": title}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _two_tenants(api: ApiHarness) -> tuple[User, User, str, str]:
    alice, bob = await api.user(name="Alice"), await api.user(name="Bob")
    await _project(alice, alice.personal_org_id)
    await _project(bob, bob.personal_org_id, "Bob's project")
    return alice, bob, alice.personal_org_id, bob.personal_org_id


# --- Role and catalogue ----------------------------------------------------------------


async def test_app_role_is_not_privileged(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with api.app.state.resources.session_factory() as db:
        me = (await db.execute(text("SELECT current_user"))).scalar_one()
    async with owner_sessions() as db:
        row = (
            await db.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, "
                    "pg_has_role(rolname, :g, 'MEMBER') FROM pg_roles WHERE rolname = :r"
                ),
                {"r": me, "g": APP_GROUP},
            )
        ).one()
        owned = (
            await db.execute(
                text("SELECT count(*) FROM pg_tables WHERE tableowner = :r"), {"r": me}
            )
        ).scalar_one()
    assert tuple(row) == (False, False, False, False, True)
    assert owned == 0


async def test_privileges_match_the_reviewed_map(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with owner_sessions() as db:
        grants = (
            await db.execute(
                text(
                    "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = :g AND table_schema = 'public'"
                ),
                {"g": APP_GROUP},
            )
        ).all()
        tables = set(
            (
                await db.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                        "AND tablename <> 'alembic_version'"
                    )
                )
            ).scalars()
        )
    actual: dict[str, set[str]] = {}
    for table, privilege in grants:
        actual.setdefault(table, set()).add(privilege)
    assert actual == EXPECTED_PRIVILEGES
    assert tables == set(EXPECTED_PRIVILEGES), "every table needs a deliberate privilege decision"


async def test_every_tenant_table_has_forced_rls(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    assert {"project", "question_response", "assessment", "assessment_finding"} <= set(
        TENANT_TABLES
    )
    async with owner_sessions() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid "
                    " AND p.polname = 'tenant_isolation') "
                    "FROM pg_class c WHERE c.relname = ANY(:t) AND c.relkind = 'r'"
                ),
                {"t": TENANT_TABLES},
            )
        ).all()
    assert {r[0]: tuple(r[1:]) for r in rows} == {t: (True, True, 1) for t in TENANT_TABLES}


# --- Behaviour -------------------------------------------------------------------------


async def test_nothing_is_visible_without_a_tenant(api: ApiHarness) -> None:
    await _two_tenants(api)
    async with api.app.state.resources.session_factory() as db:
        assert (await db.execute(select(func.count(Project.id)))).scalar_one() == 0


async def test_bound_tenant_sees_only_its_rows(api: ApiHarness) -> None:
    _, _, org_a, org_b = await _two_tenants(api)
    async with api.app.state.resources.session_factory() as db:
        await bind_tenant(db, uuid.UUID(org_a))
        # Deliberately no WHERE clause: the database applies the tenant filter.
        orgs = set((await db.execute(select(Project.organisation_id))).scalars())
        assert orgs == {uuid.UUID(org_a)}
        # The binding survives a commit (re-applied at the start of each transaction).
        await db.commit()
        orgs = set((await db.execute(select(Project.organisation_id))).scalars())
        assert orgs == {uuid.UUID(org_a)}
        assert uuid.UUID(org_b) not in orgs


async def test_binding_does_not_leak_to_the_next_session(api: ApiHarness) -> None:
    _, _, org_a, _ = await _two_tenants(api)
    factory = api.app.state.resources.session_factory
    for _ in range(3):  # pooled connections get reused
        async with factory() as db:
            await bind_tenant(db, uuid.UUID(org_a))
            assert (await db.execute(select(func.count(Project.id)))).scalar_one() >= 1
            await db.commit()
        async with factory() as db:
            assert (await db.execute(select(func.count(Project.id)))).scalar_one() == 0


async def test_cannot_write_rows_for_another_tenant(api: ApiHarness) -> None:
    alice, _, org_a, org_b = await _two_tenants(api)
    factory = api.app.state.resources.session_factory
    async with factory() as db:
        await bind_tenant(db, uuid.UUID(org_a))
        db.add(
            Project(
                organisation_id=uuid.UUID(org_b),
                vertical="PLANNING",
                title="Smuggled",
                reference_code=f"PLN-{uuid.uuid4().hex[:6].upper()}",
            )
        )
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.flush()
        await db.rollback()

    async with factory() as db:
        await bind_tenant(db, uuid.UUID(org_a))
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(
                text("UPDATE project SET organisation_id = :b"), {"b": uuid.UUID(org_b)}
            )
        await db.rollback()

    async with factory() as db:
        await bind_tenant(db, uuid.UUID(org_b))
        # Another tenant's rows can't be changed or deleted: they are simply not there.
        updated = await db.execute(
            text("UPDATE project SET title = 'pwned' WHERE organisation_id = :a"),
            {"a": uuid.UUID(org_a)},
        )
        deleted = await db.execute(
            text("DELETE FROM project WHERE organisation_id = :a"), {"a": uuid.UUID(org_a)}
        )
        assert updated.rowcount == 0  # type: ignore[attr-defined]
        assert deleted.rowcount == 0  # type: ignore[attr-defined]
        await db.commit()
    projects = (await alice.get(f"/v1/organisations/{org_a}/projects")).json()
    assert [p["title"] for p in projects] == ["Granny flat"]


async def test_cross_tenant_references_are_impossible(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Foreign-key checks bypass RLS, so tenant FKs include organisation_id. Even the owner
    (who bypasses RLS entirely) cannot attach a row to another tenant's project."""
    alice, _, org_a, org_b = await _two_tenants(api)
    project_a = (await alice.get(f"/v1/organisations/{org_a}/projects")).json()[0]["id"]
    async with owner_sessions() as db:
        db.add(Task(organisation_id=uuid.UUID(org_b), project_id=uuid.UUID(project_a), title="x"))
        with pytest.raises(IntegrityError, match="fk_task_organisation_id_project"):
            await db.flush()
        await db.rollback()
