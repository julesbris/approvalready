"""Regulatory sources: access, capture with provenance, snapshots, verification workflow."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.harness import ApiHarness, platform_user
from tests.regulatory_helpers import ADMIN, reference, snapshot, source_document

pytestmark = pytest.mark.integration


async def test_only_platform_staff_reach_sources(api: ApiHarness) -> None:
    customer = await api.user()
    assert (await customer.get(f"{ADMIN}/source-documents")).status_code == 403
    r = await customer.post(
        f"{ADMIN}/source-organisations",
        json={"name": "Nope", "kind": "COUNCIL", "jurisdiction": "QLD"},
    )
    assert r.status_code == 403

    staff = await platform_user(api, "STAFF")
    assert (await staff.get(f"{ADMIN}/source-documents")).status_code == 200
    # Platform roles only count while the platform organisation is active.
    r = await staff.put(
        "/v1/auth/session/organisation", json={"organisation_id": staff.personal_org_id}
    )
    assert r.status_code == 200
    assert (await staff.get(f"{ADMIN}/source-documents")).status_code == 403


async def test_capture_document_with_provenance(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    document = await source_document(
        staff, version_label="v12", effective_to="2030-01-01", licence="CC BY 4.0"
    )
    assert document["latest_snapshot"] is None
    assert document["reference_counts"] == {}

    r = await staff.post(
        f"{ADMIN}/source-organisations",
        json={
            "name": document["organisation_name"].upper(),
            "kind": "COUNCIL",
            "jurisdiction": "QLD",
        },
    )
    assert r.status_code == 409  # names are unique, ignoring case

    bad = {
        "jurisdiction": "Queensland",  # not a jurisdiction code
        "url": "ftp://example.com",
        "effective_from": "2030-01-01",  # after effective_to
    }
    for field, value in bad.items():
        r = await staff.patch(f"{ADMIN}/source-documents/{document['id']}", json={field: value})
        assert r.status_code == 422, (field, r.text)

    r = await staff.patch(
        f"{ADMIN}/source-documents/{document['id']}", json={"supersedes_id": document["id"]}
    )
    assert r.status_code == 422


async def test_snapshots_detect_changes(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    document = await source_document(staff)
    first = await snapshot(staff, document["id"], "Version one.")
    assert first["changed"] is True
    again = await snapshot(staff, document["id"], "Version one.")
    assert again["changed"] is False and again["id"] == first["id"]
    second = await snapshot(staff, document["id"], "Version two.")
    assert second["changed"] is True and second["content_hash"] != first["content_hash"]

    listed = (await staff.get(f"{ADMIN}/source-documents/{document['id']}/snapshots")).json()
    assert [s["id"] for s in listed] == [second["id"], first["id"]]
    detail = await staff.get(f"{ADMIN}/source-documents/{document['id']}/snapshots/{first['id']}")
    assert detail.json()["content_text"] == "Version one."

    r = await staff.post(
        f"{ADMIN}/source-documents/{document['id']}/snapshots",
        json={
            "content_text": "x",
            "retrieved_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 422


async def test_verification_workflow(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    document = await source_document(staff)
    ref = await reference(staff, verify=False, document=document)
    assert ref["verification_status"] == "UNVERIFIED"
    assert ref["attention"] == ["Not verified yet."]
    assert ref["citation"].endswith("Part 1, cl. 1.1")
    url = f"{ADMIN}/source-references/{ref['id']}"

    # Verification is against a captured snapshot.
    r = await staff.post(f"{url}/review", json={"action": "VERIFY"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "snapshot_required"
    snap = await snapshot(staff, document["id"])
    r = await staff.post(f"{url}/review", json={"action": "VERIFY"})
    assert r.status_code == 200, r.text
    verified = r.json()
    assert verified["verification_status"] == "VERIFIED"
    assert verified["verified_snapshot_id"] == snap["id"]
    assert verified["verified_by"] == staff.id
    assert date.fromisoformat(verified["next_review_due"]) > date.today() + timedelta(days=360)
    assert verified["attention"] == []
    assert verified["allowed_actions"] == ["VERIFY", "DISPUTE", "SUPERSEDE", "REOPEN"]

    # The document changing is flagged until someone re-verifies against the new snapshot.
    await snapshot(staff, document["id"], "Amended text.")
    changed = (await staff.get(url)).json()
    assert changed["attention"] == ["The document has changed since this was verified."]
    queue = (await staff.get(f"{ADMIN}/source-references?needs_attention=true")).json()
    assert ref["id"] in {q["id"] for q in queue}
    due = (date.today() + timedelta(days=30)).isoformat()
    r = await staff.post(f"{url}/review", json={"action": "VERIFY", "next_review_due": due})
    assert r.json()["attention"] == [] and r.json()["next_review_due"] == due

    # Disputing needs a reason; editing the citation undoes verification.
    r = await staff.post(f"{url}/review", json={"action": "DISPUTE"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "notes_required"
    r = await staff.patch(url, json={"clause": "1.2"})
    assert r.json()["verification_status"] == "UNVERIFIED"
    assert r.json()["verified_snapshot_id"] is None
    r = await staff.post(f"{url}/review", json={"action": "REOPEN"})
    assert r.status_code == 409  # already unverified
    r = await staff.post(f"{url}/review", json={"action": "DISPUTE", "notes": "Clause renumbered"})
    assert r.json()["verification_status"] == "DISPUTED"
    r = await staff.post(f"{url}/review", json={"action": "SUPERSEDE", "notes": "Replaced"})
    assert r.json()["verification_status"] == "SUPERSEDED"
    assert r.json()["allowed_actions"] == []
    assert (await staff.patch(url, json={"page": "3"})).status_code == 409

    events = (await staff.get(f"{url}/events")).json()
    assert [e["action"] for e in events] == [
        "CREATED",
        "VERIFIED",
        "VERIFIED",
        "EDITED",
        "DISPUTED",
        "SUPERSEDED",
    ]
    assert events[4]["notes"] == "Clause renumbered"
    assert events[4]["reviewer_name"] == "Staff"

    document_now = (await staff.get(f"{ADMIN}/source-documents/{document['id']}")).json()
    assert document_now["reference_counts"] == {"SUPERSEDED": 1}


async def test_overdue_review_needs_attention(api: ApiHarness, owner_sessions: object) -> None:
    staff = await platform_user(api, "STAFF")
    ref = await reference(staff)
    async with owner_sessions() as db:  # type: ignore[operator]
        await db.execute(
            text("UPDATE source_reference SET next_review_due = :d WHERE id = :id"),
            {"d": date.today() - timedelta(days=1), "id": uuid.UUID(ref["id"])},
        )
        await db.commit()
    assert (await staff.get(f"{ADMIN}/source-references/{ref['id']}")).json()["attention"] == [
        "Overdue for review."
    ]


async def test_snapshots_and_review_history_are_append_only(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    ref = await reference(staff)
    factory = api.app.state.resources.session_factory
    for statement in (
        "UPDATE source_snapshot SET content_text = 'forged'",
        "DELETE FROM source_snapshot",
        "UPDATE source_review_event SET notes = 'forged'",
        "DELETE FROM source_review_event",
        "DELETE FROM source_reference",
    ):
        async with factory() as db:
            with pytest.raises(DBAPIError, match="permission denied"):
                await db.execute(text(statement))
            await db.rollback()
    assert (await staff.get(f"{ADMIN}/source-references/{ref['id']}")).status_code == 200
