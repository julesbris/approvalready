"""Milestone 29: a closed account's personal workspace is deleted, keeping payment records,
the security log and the referrals partners received.

Reuses the lead engine's fixtures (``tests/test_leads.py``) for a customer whose referral a
partner accepted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.models import AuditEvent
from app.modules.documents.models import UploadedDocument
from app.modules.identity.models import AuthSession
from app.modules.leads.models import Lead, LeadContact, LeadMessage, LeadStatus, ReferralConsent
from app.modules.privacy import purge
from app.modules.privacy.models import PrivacyRequest
from app.modules.projects.models import Project
from app.modules.questionnaires.models import QuestionResponse
from tests.harness import PASSWORD, ApiHarness, User, platform_user
from tests.test_documents import read_stored, upload
from tests.test_leads import (  # noqa: F401 - fixtures used by name
    app,
    leads_url,
    only_new_partners,
    settings,
    stripe_api,
)
from tests.test_projects import create_project
from tests.test_quotes import claimed, send

pytestmark = pytest.mark.integration

Owner = async_sessionmaker[AsyncSession]


async def close(user: User) -> None:
    r = await user.post("/v1/auth/account/close", json={"password": PASSWORD})
    assert r.status_code == 204, r.text


async def request_for(owner: Owner, user: User) -> PrivacyRequest:
    async with owner() as db:
        return (
            await db.execute(select(PrivacyRequest).where(PrivacyRequest.user_id == user.id))
        ).scalar_one()


async def count(owner: Owner, model: type, org_id: str) -> int:
    async with owner() as db:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(model)
                    .where(model.organisation_id == uuid.UUID(org_id))  # type: ignore[attr-defined]
                )
            ).scalar_one()
        )


async def purge_now(api: ApiHarness, request_id: uuid.UUID) -> purge.PurgeResult:
    resources = api.app.state.resources
    async with resources.session_factory() as db:
        result = await purge.purge_workspace(db, resources.storage, request_id, staff_user_id=None)
        await db.commit()
    return result


async def test_closed_workspace_is_deleted(api: ApiHarness, owner_sessions: Owner) -> None:
    customer, project, [(partner_user, p, match_id)] = await claimed(api, ["Reef Planning"])
    org_id = customer.personal_org_id
    r = await upload(customer, str(project["id"]))
    assert r.status_code == 201, r.text
    async with owner_sessions() as db:
        key = (
            await db.execute(
                select(UploadedDocument.storage_key).where(
                    UploadedDocument.organisation_id == uuid.UUID(org_id)
                )
            )
        ).scalar_one()
    assert read_stored(key) is not None
    await send(partner_user, p, match_id)
    r = await partner_user.post(f"{leads_url(p)}/{match_id}/messages", json={"body": "Hello"})
    assert r.status_code == 201, r.text
    assert await count(owner_sessions, QuestionResponse, org_id) > 0

    # Closing links the workspace to the request and stops the referral.
    await close(customer)
    request = await request_for(owner_sessions, customer)
    assert str(request.organisation_id) == org_id
    assert request.purged_at is None
    async with owner_sessions() as db:
        consent = (
            await db.execute(
                select(ReferralConsent).where(
                    ReferralConsent.organisation_id == request.organisation_id
                )
            )
        ).scalar_one()
        assert consent.withdrawn_at is not None

    # The partner can't write to a closed account any more.
    r = await partner_user.post(
        f"{leads_url(p)}/{match_id}/messages", json={"body": "Still there?"}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "customer_closed_account"
    r = await partner_user.post(f"{leads_url(p)}/{match_id}/quotes", json={})
    assert r.status_code in (409, 422)

    result = await purge_now(api, request.id)
    assert result.files == 1 and result.rows["project"] == 1
    assert "payment" not in result.rows

    # The workspace is gone, files included.
    assert read_stored(key) is None
    for model in (Project, QuestionResponse, UploadedDocument, ReferralConsent):
        assert await count(owner_sessions, model, org_id) == 0, model
    async with owner_sessions() as db:
        assert (
            await db.execute(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.user_id == customer.id)
            )
        ).scalar_one() == 0
        # The partner keeps the referral, its quote and messages, without the link back.
        lead = (
            await db.execute(select(Lead).where(Lead.organisation_id == uuid.UUID(org_id)))
        ).scalar_one()
        assert lead.project_id is None and lead.referral_consent_id is None
        assert lead.summary is None and lead.status != LeadStatus.OPEN
        assert (
            await db.execute(
                select(func.count()).select_from(LeadContact).where(LeadContact.lead_id == lead.id)
            )
        ).scalar_one() == 0
        assert (
            await db.execute(
                select(func.count()).select_from(LeadMessage).where(LeadMessage.lead_id == lead.id)
            )
        ).scalar_one() == 1
        done = await db.get(PrivacyRequest, request.id)
        assert done is not None
        assert done.status == "DONE" and done.purged_at is not None
        assert done.resolution_note and "1 project" in done.resolution_note
        assert "1 uploaded file" in done.resolution_note
        event = (
            await db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "privacy.workspace.deleted",
                    AuditEvent.target_id == str(request.id),
                )
            )
        ).scalar_one()
        assert event.details["files"] == 1

    # The partner's page still works.
    r = await partner_user.get(f"{leads_url(p)}/{match_id}")
    assert r.status_code == 200, r.text

    # Once only.
    with pytest.raises(Exception, match="already been deleted"):
        await purge_now(api, request.id)


async def test_nightly_job_waits_and_skips_kept_workspaces(
    api: ApiHarness, owner_sessions: Owner
) -> None:
    # One closed just now, one closed 8 days ago but kept, one closed 8 days ago.
    users = [await api.user() for _ in range(3)]
    for user in users:
        await create_project(user, user.personal_org_id)
        await close(user)
    requests = [await request_for(owner_sessions, u) for u in users]
    old = datetime.now(UTC) - timedelta(days=8)
    async with owner_sessions() as db:
        await db.execute(
            update(PrivacyRequest)
            .where(PrivacyRequest.id.in_([requests[1].id, requests[2].id]))
            .values(created_at=old)
        )
        await db.commit()

    # Staff keep the second one (a legal hold) by declining the request.
    admin = await platform_user(api)
    r = await admin.patch(
        f"/v1/admin/privacy/requests/{requests[1].id}",
        json={"status": "DECLINED", "note": "Disputed payment: keep for now."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deletes_on"] is None
    listed = {x["id"]: x for x in (await admin.get("/v1/admin/privacy/requests")).json()}
    assert listed[str(requests[0].id)]["deletes_on"] is not None

    resources = api.app.state.resources
    async with resources.session_factory() as db:
        due_ids = await purge.due_requests(db, datetime.now(UTC), 7)
    assert requests[2].id in due_ids
    assert requests[0].id not in due_ids and requests[1].id not in due_ids

    await purge_now(api, requests[2].id)
    assert await count(owner_sessions, Project, users[2].personal_org_id) == 0
    assert await count(owner_sessions, Project, users[1].personal_org_id) == 1


async def test_staff_can_delete_a_workspace_now(api: ApiHarness, owner_sessions: Owner) -> None:
    user = await api.user()
    await create_project(user, user.personal_org_id)
    await close(user)
    request = await request_for(owner_sessions, user)
    url = f"/v1/admin/privacy/requests/{request.id}/delete-workspace"

    staff = await platform_user(api, role="STAFF", name="Plain staff")
    assert (await staff.post(url)).status_code == 403
    admin = await platform_user(api)
    r = await admin.post(url)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DONE" and body["purged_at"] and body["deletes_on"] is None
    assert "deleted by staff" in body["resolution_note"]
    assert await count(owner_sessions, Project, user.personal_org_id) == 0
    r = await admin.post(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_deleted"

    # A contact-form request has no workspace to delete.
    r = await api.client.post(
        "/v1/privacy/requests",
        json={
            "name": "Pat",
            "email": "pat@example.com",
            "kind": "DELETION",
            "details": "Please delete everything about me.",
        },
    )
    assert r.status_code == 202
    other = next(
        x
        for x in (await admin.get("/v1/admin/privacy/requests")).json()
        if x["source"] == "CONTACT_FORM" and x["status"] == "OPEN"
    )
    r = await admin.post(f"/v1/admin/privacy/requests/{other['id']}/delete-workspace")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_workspace"


async def test_the_database_function_only_deletes_closed_workspaces(api: ApiHarness) -> None:
    user = await api.user()
    await create_project(user, user.personal_org_id)
    factory = api.app.state.resources.session_factory

    async def call(org_id: str, tables: list[str]) -> None:
        async with factory() as db:
            await db.execute(
                text("SELECT purge_closed_workspace(:org, :tables)"),
                {"org": uuid.UUID(org_id), "tables": tables},
            )

    # An open account can't be emptied, even by the application itself.
    with pytest.raises(DBAPIError, match="only a closed personal workspace"):
        await call(user.personal_org_id, ["project"])
    await close(user)
    with pytest.raises(DBAPIError, match="is kept"):
        await call(user.personal_org_id, ["payment"])
    with pytest.raises(DBAPIError, match="not workspace data"):
        await call(user.personal_org_id, ["audit_event"])
    # Consents stay undeletable outside the function.
    async with factory() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("DELETE FROM referral_consent"))


async def test_every_workspace_table_is_deleted_or_deliberately_kept(api: ApiHarness) -> None:
    async with api.app.state.resources.session_factory() as db:
        tables = await purge.workspace_tables(db)
        tenant = set(
            (
                await db.execute(
                    text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")
                )
            ).scalars()
        )
    assert tenant >= purge.KEPT_TABLES
    assert set(tables) | purge.KEPT_TABLES == tenant
    # Children come before parents.
    assert tables.index("question_response") < tables.index("questionnaire_submission")
    assert tables.index("business_profile") < tables.index("address")
