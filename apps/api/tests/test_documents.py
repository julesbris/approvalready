"""Uploads, scanning, downloads, FILE answers, evidence and generated reports (Milestone 6).

Jobs run inline in tests (JOBS_MODE=inline) with the EICAR-only scanner, so an upload is
scanned before its request returns.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.documents import jobs
from app.modules.documents.models import DocumentTemplateVersion
from app.modules.documents.scanner import EICAR, ScannerUnavailable, ScanResult
from tests.conftest import TEST_STORAGE_ROOT
from tests.harness import ApiHarness, User, platform_user
from tests.regulatory_helpers import ADMIN, content, reference, rule_set, unique
from tests.test_assessments import FLOOR_OVER_80, org_url, run, scoped, submitted_project
from tests.test_document_files import PDF
from tests.test_requirements import APPROVAL_PAYLOAD

pytestmark = pytest.mark.integration


async def new_project(user: User, vertical: str = "PLANNING") -> str:
    r = await user.post(
        f"{org_url(user)}/projects", json={"vertical": vertical, "title": "Granny flat"}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def upload(
    user: User,
    project_id: str,
    data: bytes = PDF,
    name: str = "site plan.pdf",
    mime: str = "application/pdf",
) -> Any:
    return await user.post(
        f"{org_url(user)}/projects/{project_id}/documents", files={"file": (name, data, mime)}
    )


def stored(*parts: str) -> Path:
    return Path(TEST_STORAGE_ROOT, *parts)


def read_stored(*parts: str) -> bytes | None:
    path = stored(*parts)
    return path.read_bytes() if path.exists() else None


def write_stored(data: bytes, *parts: str) -> None:
    stored(*parts).write_bytes(data)


class NoJobs:
    """Leaves work queued (PENDING), as if the worker had not picked it up yet."""

    async def scan(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> None:
        return None

    async def generate(self, organisation_id: uuid.UUID, generated_id: uuid.UUID) -> None:
        return None


class DownScanner:
    name = "clamav"

    async def scan(self, data: bytes) -> ScanResult:
        raise ScannerUnavailable("clamd unreachable")


# --- Uploads and downloads -------------------------------------------------------------


async def test_upload_scan_download_and_delete(api: ApiHarness) -> None:
    user = await api.user()
    org = org_url(user)
    project_id = await new_project(user)

    r = await upload(user, project_id)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc | {"id": None, "created_at": None} == {
        "id": None,
        "project_id": project_id,
        "filename": "site plan.pdf",
        "content_type": "application/pdf",
        "size_bytes": len(PDF),
        "scan_status": "CLEAN",
        "created_at": None,
        "created_by": user.id,
    }
    key = ("uploads", user.personal_org_id, doc["id"])
    assert read_stored(*key) == PDF

    listed = (await user.get(f"{org}/projects/{project_id}/documents")).json()
    assert [d["id"] for d in listed] == [doc["id"]]

    r = await user.get(f"{org}/documents/{doc['id']}/content")
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith('attachment; filename="site plan.pdf"')
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in r.headers["cache-control"]

    r = await user.delete(f"{org}/documents/{doc['id']}")
    assert r.status_code == 204
    assert read_stored(*key) is None
    assert (await user.get(f"{org}/documents/{doc['id']}")).status_code == 404
    assert (await user.get(f"{org}/projects/{project_id}/documents")).json() == []

    async with api.app.state.resources.session_factory() as db:
        actions = (
            await db.execute(
                select(AuditEvent.action)
                .where(AuditEvent.target_id == doc["id"])
                .order_by(AuditEvent.seq)
            )
        ).scalars()
        assert list(actions) == ["document.uploaded", "document.downloaded", "document.deleted"]


async def test_infected_files_are_quarantined_and_never_served(api: ApiHarness) -> None:
    user = await api.user()
    org = org_url(user)
    project_id = await new_project(user)
    r = await upload(user, project_id, EICAR, "readme.txt", "text/plain")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["scan_status"] == "INFECTED"
    assert read_stored("uploads", user.personal_org_id, doc["id"]) is None
    assert read_stored("quarantine", user.personal_org_id, doc["id"]) == EICAR
    r = await user.get(f"{org}/documents/{doc['id']}/content")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "document_infected"


@pytest.mark.parametrize(
    ("data", "name", "mime", "code"),
    [
        (b"MZ\x90\x00", "tool.exe", "application/octet-stream", "file_rejected"),
        (PDF, "photo.jpg", "image/jpeg", "file_rejected"),
        (b"<svg/>", "logo.svg", "image/svg+xml", "file_rejected"),
    ],
)
async def test_unacceptable_files_are_refused(
    api: ApiHarness, data: bytes, name: str, mime: str, code: str
) -> None:
    user = await api.user()
    project_id = await new_project(user)
    r = await upload(user, project_id, data, name, mime)
    assert r.status_code == 415
    assert r.json()["detail"]["code"] == code
    assert (await user.get(f"{org_url(user)}/projects/{project_id}/documents")).json() == []


async def test_size_and_count_limits(api: ApiHarness, settings: Settings) -> None:
    user = await api.user()
    project_id = await new_project(user)
    settings.upload_max_mb = 1
    settings.upload_max_files_per_project = 1
    big = PDF + b"0" * (1024 * 1024)
    r = await upload(user, project_id, big)
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "file_too_large"
    assert (await upload(user, project_id)).status_code == 201
    r = await upload(user, project_id)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "too_many_files"


async def test_uploads_are_rate_limited(api: ApiHarness, settings: Settings) -> None:
    user = await api.user()
    project_id = await new_project(user)
    settings.uploads_per_user_per_hour = 2
    assert (await upload(user, project_id)).status_code == 201
    assert (await upload(user, project_id)).status_code == 201
    r = await upload(user, project_id)
    assert r.status_code == 429
    assert "retry-after" in r.headers


async def test_other_organisations_cannot_reach_documents(api: ApiHarness) -> None:
    owner = await api.user()
    outsider = await api.user()
    project_id = await new_project(owner)
    doc = (await upload(owner, project_id)).json()
    org = org_url(owner)
    for method, url in [
        ("get", f"{org}/projects/{project_id}/documents"),
        ("get", f"{org}/documents/{doc['id']}"),
        ("get", f"{org}/documents/{doc['id']}/content"),
        ("delete", f"{org}/documents/{doc['id']}"),
        ("get", f"{org}/upload-limits"),
    ]:
        r = await getattr(outsider, method)(url)
        assert r.status_code == 404, (method, url, r.status_code)
    r = await upload(outsider, project_id)
    assert r.status_code == 404
    # Their own organisation's URLs don't find someone else's document either.
    r = await outsider.get(f"{org_url(outsider)}/documents/{doc['id']}")
    assert r.status_code == 404


async def test_upload_limits_are_published(api: ApiHarness) -> None:
    user = await api.user()
    r = await user.get(f"{org_url(user)}/upload-limits")
    assert r.status_code == 200
    body = r.json()
    assert body["max_bytes"] == 20 * 1024 * 1024
    assert {"pdf", "docx", "jpg", "heic"} <= set(body["extensions"])
    assert ".pdf" in body["accept"].split(",")


# --- Scanning jobs ---------------------------------------------------------------------


async def test_scanner_outage_retries_then_marks_error(api: ApiHarness) -> None:
    resources = api.app.state.resources
    resources.jobs = NoJobs()
    user = await api.user()
    project_id = await new_project(user)
    doc = (await upload(user, project_id)).json()
    assert doc["scan_status"] == "PENDING"
    r = await user.get(f"{org_url(user)}/documents/{doc['id']}/content")
    assert r.json()["detail"]["code"] == "document_not_scanned"

    ctx = jobs.JobContext(resources.session_factory, resources.storage, DownScanner())
    org_id, doc_id = uuid.UUID(user.personal_org_id), uuid.UUID(doc["id"])
    with pytest.raises(jobs.RetryLater):
        await jobs.scan_job(ctx, org_id, doc_id, final_attempt=False)
    assert (await user.get(f"{org_url(user)}/documents/{doc['id']}")).json()[
        "scan_status"
    ] == "PENDING"
    assert await jobs.scan_job(ctx, org_id, doc_id, final_attempt=True) == "ERROR"
    assert (await user.get(f"{org_url(user)}/documents/{doc['id']}")).json()[
        "scan_status"
    ] == "ERROR"
    # A finished scan is never redone, even by a duplicate job.
    ok = jobs.JobContext(resources.session_factory, resources.storage, DownScanner())
    assert await jobs.scan_job(ok, org_id, doc_id, final_attempt=True) is None


async def test_tampered_content_is_not_passed_as_clean(api: ApiHarness) -> None:
    resources = api.app.state.resources
    resources.jobs = NoJobs()
    user = await api.user()
    doc = (await upload(user, await new_project(user))).json()
    write_stored(EICAR[:5], "uploads", user.personal_org_id, doc["id"])
    ctx = jobs.JobContext(resources.session_factory, resources.storage, DownScanner())
    status = await jobs.scan_job(
        ctx, uuid.UUID(user.personal_org_id), uuid.UUID(doc["id"]), final_attempt=True
    )
    assert status == "ERROR"


async def test_stalled_jobs_are_found_across_tenants_by_id_only(
    api: ApiHarness, settings: Settings
) -> None:
    api.app.state.resources.jobs = NoJobs()
    first, second = await api.user(), await api.user()
    a = (await upload(first, await new_project(first))).json()
    b = (await upload(second, await new_project(second))).json()
    found = {(kind, i) for kind, i, _ in await jobs.stalled_jobs(settings, 0)}
    assert {("scan", a["id"]), ("scan", b["id"])} <= found
    # The application role still cannot read the rows themselves without a tenant.
    async with api.app.state.resources.session_factory() as db:
        assert (await db.execute(text("SELECT count(*) FROM uploaded_document"))).scalar() == 0


# --- FILE answers ----------------------------------------------------------------------


async def _submission(user: User, project_id: str) -> str:
    r = await user.post(f"{org_url(user)}/projects/{project_id}/submissions", json={})
    assert r.status_code == 200, r.text
    return str(r.json()["id"])


async def test_file_answers_use_the_projects_own_checked_uploads(api: ApiHarness) -> None:
    user = await api.user()
    org = org_url(user)
    project_id = await new_project(user)
    other_project = await new_project(user)
    submission = await _submission(user, project_id)
    answers = f"{org}/submissions/{submission}/answers"
    mine = (await upload(user, project_id)).json()
    elsewhere = (await upload(user, other_project)).json()

    for bad in ([elsewhere["id"]], [str(uuid.uuid4())]):
        r = await user.put(answers, json={"answers": {"planning.site_documents": bad}})
        assert r.status_code == 422, r.text
        assert "removed" in r.json()["detail"]["fields"]["planning.site_documents"]

    r = await user.put(answers, json={"answers": {"planning.site_documents": [mine["id"]]}})
    assert r.status_code == 200, r.text
    assert r.json()["answers"]["planning.site_documents"] == [mine["id"]]

    infected = (await upload(user, project_id, EICAR, "x.txt", "text/plain")).json()
    r = await user.put(answers, json={"answers": {"planning.site_documents": [infected["id"]]}})
    assert r.status_code == 422
    assert "blocked" in r.json()["detail"]["fields"]["planning.site_documents"]


async def test_submitting_waits_for_virus_checks(api: ApiHarness) -> None:
    user = await api.user()
    org = org_url(user)
    project = await submitted_project(user, unique("LOT"))
    detail = (await user.get(f"{org}/projects/{project['id']}")).json()
    submission = detail["submissions"][0]["id"]
    assert (await user.post(f"{org}/submissions/{submission}/reopen")).status_code == 200
    api.app.state.resources.jobs = NoJobs()
    pending = (await upload(user, project["id"])).json()
    r = await user.put(
        f"{org}/submissions/{submission}/answers",
        json={"answers": {"planning.site_documents": [pending["id"]]}},
    )
    assert r.status_code == 200, r.text
    r = await user.post(f"{org}/submissions/{submission}/submit")
    assert r.status_code == 422
    assert "Wait until" in r.json()["detail"]["fields"]["planning.site_documents"]

    resources = api.app.state.resources
    ctx = jobs.JobContext(resources.session_factory, resources.storage, _CleanScanner())
    await jobs.scan_job(
        ctx, uuid.UUID(user.personal_org_id), uuid.UUID(pending["id"]), final_attempt=True
    )
    r = await user.post(f"{org}/submissions/{submission}/submit")
    assert r.status_code == 200, r.text


class _CleanScanner:
    name = "clamav"

    async def scan(self, data: bytes) -> ScanResult:
        return ScanResult(infected=False)


# --- Evidence and generated reports ----------------------------------------------------


async def _assessed(api: ApiHarness) -> tuple[User, dict[str, Any], dict[str, Any]]:
    """A customer with an assessment that has one evidence requirement."""
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    lot = unique("LOT")
    rs = await rule_set(staff, vertical="PLANNING", applies_when=scoped(lot))
    ref = await reference(staff)
    body = content(FLOOR_OVER_80, [ref["id"]])
    body["outcomes"][0] = {
        "on_result": "MATCH",
        "outcome_type": "APPROVAL_LIKELY",
        "title": "A development application is likely",
        "payload": APPROVAL_PAYLOAD,
    }
    r = await admin.post(
        f"{ADMIN}/rule-sets/{rs['id']}/rules",
        json={"key": unique("rule"), "title": "Size rule", "condition": FLOOR_OVER_80},
    )
    version_id = r.json()["versions"][0]["id"]
    assert (await admin.put(f"{ADMIN}/rule-versions/{version_id}", json=body)).status_code == 200
    assert (await admin.post(f"{ADMIN}/rule-versions/{version_id}/publish")).status_code == 200
    customer = await api.user()
    project = await submitted_project(customer, lot)
    r = await run(customer, project["id"])
    assert r.status_code == 201, r.text
    return customer, project, r.json()


async def test_evidence_attach_list_and_withdraw(api: ApiHarness) -> None:
    customer, project, assessment = await _assessed(api)
    org = org_url(customer)
    [requirement] = assessment["evidence_requirements"]
    doc = (await upload(customer, project["id"])).json()
    body = {"evidence_requirement_id": requirement["id"], "uploaded_document_id": doc["id"]}

    r = await customer.post(f"{org}/evidence", json=body | {"note": "Drawn by our designer"})
    assert r.status_code == 201, r.text
    evidence = r.json()
    assert (evidence["status"], evidence["note"]) == ("SUBMITTED", "Drawn by our designer")
    assert evidence["document"]["id"] == doc["id"]
    assert (await customer.post(f"{org}/evidence", json=body)).status_code == 409

    listed = (await customer.get(f"{org}/assessments/{assessment['id']}/evidence")).json()
    assert [e["id"] for e in listed] == [evidence["id"]]

    # Only virus-checked files from the same project.
    other = (await upload(customer, await new_project(customer))).json()
    r = await customer.post(f"{org}/evidence", json=body | {"uploaded_document_id": other["id"]})
    assert r.status_code == 404
    infected = (await upload(customer, project["id"], EICAR, "x.txt", "text/plain")).json()
    r = await customer.post(f"{org}/evidence", json=body | {"uploaded_document_id": infected["id"]})
    assert r.status_code == 409

    outsider = await api.user()
    r = await outsider.post(f"{org_url(outsider)}/evidence", json=body)
    assert r.status_code == 404
    assert (await outsider.delete(f"{org}/evidence/{evidence['id']}")).status_code == 404

    assert (await customer.delete(f"{org}/evidence/{evidence['id']}")).status_code == 204
    assert (await customer.get(f"{org}/assessments/{assessment['id']}/evidence")).json() == []

    # Deleting a document withdraws it everywhere.
    await customer.post(f"{org}/evidence", json=body)
    await customer.delete(f"{org}/documents/{doc['id']}")
    assert (await customer.get(f"{org}/assessments/{assessment['id']}/evidence")).json() == []


async def test_reports_in_every_format_carry_the_required_metadata(api: ApiHarness) -> None:
    customer, project, assessment = await _assessed(api)
    org = org_url(customer)
    [requirement] = assessment["evidence_requirements"]
    doc = (await upload(customer, project["id"], name="Site plan v2.pdf")).json()
    await customer.post(
        f"{org}/evidence",
        json={"evidence_requirement_id": requirement["id"], "uploaded_document_id": doc["id"]},
    )
    reference_code = (await customer.get(f"{org}/projects/{project['id']}")).json()[
        "reference_code"
    ]

    outputs: dict[str, bytes] = {}
    for fmt in ("HTML", "PDF", "DOCX"):
        r = await customer.post(
            f"{org}/assessments/{assessment['id']}/documents", json={"format": fmt}
        )
        assert r.status_code == 202, r.text
        generated = r.json()
        assert (generated["status"], generated["review_status"]) == ("READY", "NOT_REVIEWED")
        assert generated["filename"].startswith(f"{reference_code}-assessment-")
        r = await customer.get(f"{org}/generated-documents/{generated['id']}/content")
        assert r.status_code == 200
        assert r.headers["content-disposition"].startswith("attachment;")
        outputs[fmt] = r.content

    html = outputs["HTML"].decode()
    for expected in (
        reference_code,
        "Granny flat",
        "Not reviewed by a professional",
        "A development application is likely",
        "Site plan v2.pdf",  # evidence already provided
        "Assumptions",
        "Missing information",
        "Sources",
        "Limitations",
        "not legal or planning advice",
    ):
        assert expected in html, expected
    assert outputs["PDF"].startswith(b"%PDF-")
    with zipfile.ZipFile(io.BytesIO(outputs["DOCX"])) as z:
        word = z.read("word/document.xml").decode()
    assert reference_code in word and "Not reviewed by a professional" in word

    listed = (await customer.get(f"{org}/projects/{project['id']}/generated-documents")).json()
    assert {g["format"] for g in listed} == {"HTML", "PDF", "DOCX"}

    outsider = await api.user()
    for url in (
        f"{org}/generated-documents/{listed[0]['id']}",
        f"{org}/generated-documents/{listed[0]['id']}/content",
        f"{org}/projects/{project['id']}/generated-documents",
    ):
        assert (await outsider.get(url)).status_code == 404
    r = await outsider.post(
        f"{org}/assessments/{assessment['id']}/documents", json={"format": "PDF"}
    )
    assert r.status_code == 404


async def test_reports_wait_until_generated(api: ApiHarness) -> None:
    customer, _, assessment = await _assessed(api)
    api.app.state.resources.jobs = NoJobs()
    org = org_url(customer)
    r = await customer.post(
        f"{org}/assessments/{assessment['id']}/documents", json={"format": "PDF"}
    )
    assert r.json()["status"] == "PENDING"
    r = await customer.get(f"{org}/generated-documents/{r.json()['id']}/content")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "not_ready"


# --- Templates -------------------------------------------------------------------------


async def test_template_versions_are_immutable(
    owner_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with owner_sessions() as db:
        version = (
            (
                await db.execute(
                    select(DocumentTemplateVersion).where(
                        DocumentTemplateVersion.status == "PUBLISHED"
                    )
                )
            )
            .scalars()
            .first()
        )
        assert version is not None
        version_id = version.id
        with pytest.raises(DBAPIError, match="immutable"):
            await db.execute(
                text("UPDATE document_template_version SET body = 'x' WHERE id = :id"),
                {"id": version_id},
            )
        await db.rollback()
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            await db.execute(
                text("DELETE FROM document_template_version WHERE id = :id"), {"id": version_id}
            )


async def test_template_sync_is_a_no_op_when_unchanged(
    settings: Settings, migrated: None, capsys: pytest.CaptureFixture[str]
) -> None:
    from app import cli

    assert await cli.sync_templates(settings) == 0
    assert "PLANNING_ASSESSMENT: version 1 unchanged" in capsys.readouterr().out
