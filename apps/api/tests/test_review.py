"""Professional review (Milestone 7): professionals and their verification, the review
workflow, overrides, evidence decisions, isolation and reports."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.modules.audit.models import AuditEvent
from tests.harness import ApiHarness, User, platform_user
from tests.regulatory_helpers import reference
from tests.test_assessments import org_url, run
from tests.test_documents import _assessed, upload

pytestmark = pytest.mark.integration

PRO = "/v1/professional"
ADMIN = "/v1/admin"


async def practice_user(api: ApiHarness, name: str = "Pat Planner") -> tuple[User, str]:
    """A user with a professional practice as their active organisation."""
    user = await api.user(name=name)
    r = await user.post(
        "/v1/organisations", json={"kind": "PROFESSIONAL_PRACTICE", "name": f"{name} Planning"}
    )
    assert r.status_code == 201, r.text
    practice_id = str(r.json()["id"])
    r = await user.put("/v1/auth/session/organisation", json={"organisation_id": practice_id})
    assert r.status_code == 200, r.text
    return user, practice_id


async def professional(
    api: ApiHarness, staff: User, name: str = "Pat Planner", *, activate: bool = True
) -> tuple[User, dict[str, Any]]:
    user, _ = await practice_user(api, name)
    r = await user.post(
        f"{PRO}/profile",
        json={"display_name": name, "discipline": "TOWN_PLANNER", "bio": "Planning in FNQ."},
    )
    assert r.status_code == 201, r.text
    r = await user.post(
        f"{PRO}/profile/credentials",
        json={"kind": "MEMBERSHIP", "issuer": "Planning Institute of Australia", "number": "123"},
    )
    assert r.status_code == 201, r.text
    r = await user.put(f"{PRO}/profile/services", json={"services": [{"vertical": "PLANNING"}]})
    assert r.status_code == 200, r.text
    profile = r.json()
    if activate:
        [credential] = profile["credentials"]
        r = await staff.post(
            f"{ADMIN}/professionals/{profile['id']}/credentials/{credential['id']}",
            json={"status": "VERIFIED", "notes": "Checked on the PIA register."},
        )
        assert r.status_code == 200, r.text
        r = await staff.post(
            f"{ADMIN}/professionals/{profile['id']}/status", json={"status": "ACTIVE"}
        )
        assert r.status_code == 200, r.text
        profile = r.json()
    return user, profile


async def requested(api: ApiHarness) -> tuple[User, dict[str, Any], dict[str, Any], dict[str, Any]]:
    customer, project, assessment = await _assessed(api)
    r = await customer.post(
        f"{org_url(customer)}/projects/{project['id']}/reviews",
        json={"assessment_id": assessment["id"], "message": "Is the floor area a problem?"},
    )
    assert r.status_code == 201, r.text
    return customer, project, assessment, r.json()


async def assigned(
    api: ApiHarness,
) -> tuple[User, dict[str, Any], dict[str, Any], dict[str, Any], User, dict[str, Any], User]:
    staff = await platform_user(api, "STAFF")
    customer, project, assessment, review = await requested(api)
    reviewer, profile = await professional(api, staff)
    r = await staff.post(
        f"{ADMIN}/reviews/{review['id']}/assign",
        json={"professional_id": profile["id"], "due_on": "2030-01-31"},
    )
    assert r.status_code == 200, r.text
    return customer, project, assessment, review, reviewer, profile, staff


# --- Professionals ---------------------------------------------------------------------


async def test_professional_onboarding_and_verification(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")

    # Reviewer routes act from a practice where the user is a reviewer.
    customer = await api.user()
    r = await customer.post(
        f"{PRO}/profile", json={"display_name": "Me", "discipline": "TOWN_PLANNER"}
    )
    assert r.status_code == 403

    user, profile = await professional(api, staff, activate=False)
    assert profile["status"] == "PENDING"
    assert profile["practice_name"] == "Pat Planner Planning"
    assert profile["problems"] == [
        "The profile is not active.",
        "No verified credential is current.",
    ]
    r = await user.post(
        f"{PRO}/profile", json={"display_name": "Again", "discipline": "TOWN_PLANNER"}
    )
    assert r.status_code == 409

    # Activation needs a verified, current credential.
    r = await staff.post(f"{ADMIN}/professionals/{profile['id']}/status", json={"status": "ACTIVE"})
    assert r.status_code == 409
    assert "No verified credential is current." in r.json()["detail"]["message"]

    # Professionals can't verify themselves, and customers can't reach staff routes.
    assert (await user.get(f"{ADMIN}/professionals")).status_code == 403
    assert (await customer.get(f"{ADMIN}/reviews")).status_code == 403

    [credential] = profile["credentials"]
    r = await staff.post(
        f"{ADMIN}/professionals/{profile['id']}/credentials/{credential['id']}",
        json={"status": "VERIFIED"},
    )
    assert r.json()["credentials"][0]["current"] is True
    r = await staff.post(f"{ADMIN}/professionals/{profile['id']}/status", json={"status": "ACTIVE"})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["problems"]) == ("ACTIVE", [])

    listed = (await staff.get(f"{ADMIN}/professionals?status=ACTIVE")).json()
    assert profile["id"] in {p["id"] for p in listed}

    # An expired credential makes them unassignable again.
    r = await user.post(
        f"{PRO}/profile/credentials",
        json={
            "kind": "INSURANCE",
            "issuer": "Insurer",
            "number": "PI-1",
            "expires_on": "2020-01-01",
        },
    )
    expired = next(c for c in r.json()["credentials"] if c["kind"] == "INSURANCE")
    r = await staff.post(
        f"{ADMIN}/professionals/{profile['id']}/credentials/{expired['id']}",
        json={"status": "VERIFIED"},
    )
    assert next(c for c in r.json()["credentials"] if c["id"] == expired["id"])["current"] is False

    async with api.app.state.resources.session_factory() as db:
        actions = set(
            (
                await db.execute(
                    select(AuditEvent.action).where(AuditEvent.target_id == profile["id"])
                )
            ).scalars()
        )
    assert {
        "professional.created",
        "professional.credential_added",
        "professional.credential_checked",
        "professional.services_changed",
        "professional.status_changed",
    } <= actions


# --- The workflow ----------------------------------------------------------------------


async def test_review_end_to_end(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    customer, project, assessment, review = await requested(api)
    org = org_url(customer)
    project_url = f"{org}/projects/{project['id']}"
    assert review["status"] == "REVIEW_REQUESTED"
    assert review["professional"] is None
    assert (await customer.get(project_url)).json()["status"] == "IN_REVIEW"

    # One open review per project.
    r = await customer.post(f"{project_url}/reviews", json={"assessment_id": assessment["id"]})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "review_open")

    reviewer, profile = await professional(api, staff)
    # Not assigned yet: the reviewer sees nothing.
    assert (await reviewer.get(f"{PRO}/reviews")).json() == []
    assert (await reviewer.get(f"{PRO}/reviews/{review['id']}")).status_code == 404

    queue = (await staff.get(f"{ADMIN}/reviews?status=REVIEW_REQUESTED")).json()
    assert review["id"] in {q["id"] for q in queue}
    detail = (await staff.get(f"{ADMIN}/reviews/{review['id']}")).json()
    assert profile["id"] in {c["id"] for c in detail["candidates"]}
    assert detail["project_title"] == "Granny flat"

    r = await staff.post(
        f"{ADMIN}/reviews/{review['id']}/assign", json={"professional_id": profile["id"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["review"]["status"] == "ASSIGNED"
    email = api.last_email(reviewer.email, "review.assigned")
    assert email.links["review"].endswith(f"/review/{review['id']}")
    assert "Granny flat" not in email.text  # notifications carry no project content

    [item] = (await reviewer.get(f"{PRO}/reviews")).json()
    assert (item["id"], item["status"]) == (review["id"], "ASSIGNED")

    # Files: only the ones shared or offered as evidence.
    private = (await upload(customer, project["id"], name="private.pdf")).json()
    shared = (await upload(customer, project["id"], name="survey.pdf")).json()
    r = await customer.patch(
        f"{org}/documents/{shared['id']}", json={"classification": "SHARED_WITH_REVIEWER"}
    )
    assert r.json()["classification"] == "SHARED_WITH_REVIEWER"
    [requirement] = assessment["evidence_requirements"]
    plan = (await upload(customer, project["id"], name="plan.pdf")).json()
    evidence = (
        await customer.post(
            f"{org}/evidence",
            json={"evidence_requirement_id": requirement["id"], "uploaded_document_id": plan["id"]},
        )
    ).json()

    workspace = (await reviewer.get(f"{PRO}/reviews/{review['id']}")).json()
    assert workspace["review"]["message"] == "Is the floor area a problem?"
    assert workspace["assessment"]["id"] == assessment["id"]
    assert [d["filename"] for d in workspace["shared_documents"]] == ["survey.pdf"]
    assert [e["document"]["filename"] for e in workspace["evidence"]] == ["plan.pdf"]
    base = f"{PRO}/reviews/{review['id']}"
    for doc, expected in ((shared, 200), (plan, 200), (private, 404)):
        r = await reviewer.get(f"{base}/documents/{doc['id']}/content")
        assert r.status_code == expected, doc["filename"]
    assert r.status_code == 404

    # Nothing can be changed before the review starts.
    [finding] = assessment["finding_list"]
    override = {
        "finding_id": finding["id"],
        "new_outcome_type": "APPROVAL_REQUIRED",
        "new_confidence": "LIKELY",
        "reason": "The proposal exceeds 80 m2, so it is assessable development.",
    }
    r = await reviewer.post(f"{base}/overrides", json=override)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "invalid_review_status")
    r = await reviewer.post(f"{base}/start")
    assert r.json()["review"]["status"] == "IN_REVIEW"

    # Overrides need a reason; VERIFIED needs a verified source.
    r = await reviewer.post(f"{base}/overrides", json=override | {"reason": "short"})
    assert r.status_code == 422
    r = await reviewer.post(f"{base}/overrides", json=override | {"new_confidence": "VERIFIED"})
    assert (r.status_code, r.json()["detail"]["code"]) == (422, "verified_needs_source")
    unverified = await reference(staff, verify=False)
    r = await reviewer.post(
        f"{base}/overrides",
        json=override | {"new_confidence": "VERIFIED", "source_reference_id": unverified["id"]},
    )
    assert r.status_code == 422
    r = await reviewer.post(f"{base}/overrides", json=override)
    assert r.status_code == 200, r.text
    [first] = r.json()["review"]["overrides"]
    assert (first["previous_outcome_type"], first["previous_confidence"]) == (
        finding["outcome_type"],
        finding["confidence"],
    )
    assert (first["new_outcome_type"], first["new_confidence"], first["current"]) == (
        "APPROVAL_REQUIRED",
        "LIKELY",
        True,
    )
    r = await reviewer.post(f"{base}/overrides", json=override)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "no_change")
    verified = await reference(staff)
    r = await reviewer.post(
        f"{base}/overrides",
        json=override
        | {
            "new_outcome_type": None,
            "new_confidence": "VERIFIED",
            "source_reference_id": verified["id"],
        },
    )
    first, second = r.json()["review"]["overrides"]
    assert (second["previous_confidence"], second["new_confidence"]) == ("LIKELY", "VERIFIED")
    assert second["new_outcome_type"] == "APPROVAL_REQUIRED"  # kept
    assert second["source"]["verification_status"] == "VERIFIED"
    assert (first["current"], second["current"]) == (False, True)

    # Evidence decisions; a rejection needs a reason.
    r = await reviewer.post(f"{base}/evidence/{evidence['id']}", json={"status": "REJECTED"})
    assert r.status_code == 422
    r = await reviewer.post(
        f"{base}/evidence/{evidence['id']}",
        json={"status": "REJECTED", "note": "The plan has no scale."},
    )
    [checked] = r.json()["evidence"]
    assert (checked["status"], checked["review_note"]) == ("REJECTED", "The plan has no scale.")
    # Reviewed evidence can't be withdrawn by the customer.
    assert (await customer.delete(f"{org}/evidence/{evidence['id']}")).status_code == 409

    # Comments both ways, a task on the project, then changes required.
    r = await reviewer.post(
        f"{base}/comments",
        json={"body": "Can you upload a scaled plan?", "finding_id": finding["id"]},
    )
    assert r.status_code == 200, r.text
    r = await reviewer.post(f"{base}/tasks", json={"title": "Upload a scaled site plan"})
    assert [t["source"] for t in r.json()["tasks"]] == ["REVIEWER"]
    tasks = (await customer.get(f"{project_url}/tasks")).json()
    assert "Upload a scaled site plan" in {t["title"] for t in tasks}
    r = await reviewer.post(f"{base}/decision", json={"decision": "CHANGES_REQUIRED"})
    assert (r.status_code, r.json()["detail"]["code"]) == (422, "notes_required")
    r = await reviewer.post(
        f"{base}/decision",
        json={"decision": "CHANGES_REQUIRED", "notes": "Please add a scaled plan."},
    )
    assert r.json()["review"]["status"] == "CHANGES_REQUIRED"
    email = api.last_email(customer.email, "review.decided")
    assert "asked for some changes" in email.text

    seen = (await customer.get(f"{org}/reviews/{review['id']}")).json()
    assert seen["professional"] == {
        "id": profile["id"],
        "display_name": "Pat Planner",
        "discipline": "TOWN_PLANNER",
        "practice_name": "Pat Planner Planning",
    }
    assert [c["author_role"] for c in seen["comments"]] == ["REVIEWER"]
    status = (await customer.get(f"{org}/assessments/{assessment['id']}/review")).json()
    assert status["review_status"] == "CHANGES_REQUIRED"
    assert [o["current"] for o in status["overrides"]] == [False, True]

    r = await customer.post(f"{org}/reviews/{review['id']}/comments", json={"body": "Added it."})
    assert r.status_code == 200, r.text
    r = await customer.post(f"{org}/reviews/{review['id']}/resubmit", json={})
    assert r.json()["status"] == "IN_REVIEW"
    assert api.last_email(reviewer.email, "review.resubmitted")
    assert (await customer.get(f"{org}/assessments/{assessment['id']}/review")).json()[
        "review_status"
    ] == "IN_REVIEW"

    r = await reviewer.post(
        f"{base}/decision", json={"decision": "APPROVED", "notes": "Checked against the scheme."}
    )
    assert r.json()["review"]["status"] == "APPROVED"
    assert r.json()["project_status"] == "ASSESSED"
    assert (await customer.get(project_url)).json()["status"] == "ASSESSED"
    # Closed: no more comments, and the reviewer keeps read access.
    r = await reviewer.post(f"{base}/comments", json={"body": "One more thing"})
    assert r.status_code == 409
    assert (await reviewer.get(base)).status_code == 200

    # The report says who reviewed it and what they changed.
    r = await customer.post(
        f"{org}/assessments/{assessment['id']}/documents", json={"format": "HTML"}
    )
    generated = r.json()
    assert generated["review_status"] == "APPROVED"
    html = (await customer.get(f"{org}/generated-documents/{generated['id']}/content")).text
    for expected in (
        "Reviewed and approved by a professional",
        "Pat Planner, Town planner, Pat Planner Planning",
        "Checked against the scheme.",
        "Changes made by the reviewer",
        "Approval required (Verified)",
        "Changed by the professional reviewer",
    ):
        assert expected in html, expected

    async with api.app.state.resources.session_factory() as db:
        actions = list(
            (
                await db.execute(
                    select(AuditEvent.action)
                    .where(AuditEvent.target_id == review["id"])
                    .order_by(AuditEvent.seq)
                )
            ).scalars()
        )
    assert actions == [
        "review.requested",
        "review.assigned",
        "review.started",
        "finding.overridden",
        "finding.overridden",
        "evidence.reviewed",
        "review.comment_added",
        "review.task_added",
        "review.decided",
        "review.comment_added",
        "review.resubmitted",
        "review.decided",
    ]


async def test_decline_cancel_and_resubmit_on_a_newer_assessment(api: ApiHarness) -> None:
    customer, project, assessment, review, reviewer, profile, staff = await assigned(api)
    org = org_url(customer)
    base = f"{PRO}/reviews/{review['id']}"

    # Declining hands it back to the queue; the reviewer loses access.
    r = await reviewer.post(f"{base}/decline", json={"reason": "Conflict of interest"})
    assert r.status_code == 200, r.text
    assert (await reviewer.get(base)).status_code == 404
    detail = (await staff.get(f"{ADMIN}/reviews/{review['id']}")).json()
    assert (detail["review"]["status"], detail["review"]["professional"]) == (
        "REVIEW_REQUESTED",
        None,
    )

    await staff.post(
        f"{ADMIN}/reviews/{review['id']}/assign", json={"professional_id": profile["id"]}
    )
    await reviewer.post(f"{base}/start")
    # Staff can only take back a review that hasn't started.
    r = await staff.post(f"{ADMIN}/reviews/{review['id']}/unassign", json={})
    assert r.status_code == 409
    await reviewer.post(f"{base}/decision", json={"decision": "CHANGES_REQUIRED", "notes": "x"})

    # Resubmitting can move the review to the project's latest assessment only.
    newer = (await run(customer, project["id"])).json()
    r = await customer.post(
        f"{org}/reviews/{review['id']}/resubmit", json={"assessment_id": assessment["id"]}
    )
    assert r.json()["assessment_id"] == assessment["id"]  # unchanged: fine
    await reviewer.post(f"{base}/decision", json={"decision": "CHANGES_REQUIRED", "notes": "x"})
    r = await customer.post(
        f"{org}/reviews/{review['id']}/resubmit", json={"assessment_id": newer["id"]}
    )
    assert (r.json()["status"], r.json()["assessment_id"]) == ("IN_REVIEW", newer["id"])
    workspace = (await reviewer.get(base)).json()
    assert workspace["assessment"]["id"] == newer["id"]

    # A newer assessment can't be reviewed separately while this one is open.
    r = await customer.post(
        f"{org}/projects/{project['id']}/reviews", json={"assessment_id": newer["id"]}
    )
    assert r.status_code == 409

    r = await customer.post(f"{org}/reviews/{review['id']}/cancel")
    assert r.json()["status"] == "CANCELLED"
    assert (await customer.get(f"{org}/projects/{project['id']}")).json()["status"] == "ASSESSED"
    assert (await reviewer.get(base)).status_code == 404
    r = await customer.post(f"{org}/reviews/{review['id']}/cancel")
    assert r.status_code == 409

    # Old assessments can't be sent for review.
    r = await customer.post(
        f"{org}/projects/{project['id']}/reviews", json={"assessment_id": assessment["id"]}
    )
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_latest_assessment")


async def test_reviews_are_isolated(api: ApiHarness) -> None:
    customer, project, assessment, review, reviewer, profile, staff = await assigned(api)
    org = org_url(customer)
    base = f"{PRO}/reviews/{review['id']}"

    # Another active professional, and the assigned one acting outside their practice.
    other, _ = await professional(api, staff, "Sam Surveyor")
    assert (await other.get(base)).status_code == 404
    assert (await other.post(f"{base}/start")).status_code == 404
    assert (await other.get(f"{PRO}/reviews")).json() == []
    personal = next(o for o in reviewer.session["organisations"] if o["kind"] == "PERSONAL")
    await reviewer.put(
        "/v1/auth/session/organisation", json={"organisation_id": personal["organisation_id"]}
    )
    assert (await reviewer.get(base)).status_code == 403

    # Another customer can't see or touch the review.
    outsider = await api.user()
    for url in (f"{org}/reviews/{review['id']}", f"{org}/projects/{project['id']}/reviews"):
        assert (await outsider.get(url)).status_code == 404
    r = await outsider.post(f"{org}/reviews/{review['id']}/comments", json={"body": "hi"})
    assert r.status_code == 404
    r = await outsider.post(
        f"{org_url(outsider)}/projects/{project['id']}/reviews",
        json={"assessment_id": assessment["id"]},
    )
    assert r.status_code == 404

    # Unknown ids look the same as other people's.
    assert (await other.get(f"{PRO}/reviews/{profile['id']}")).status_code == 404


async def test_review_records_are_append_only_and_tenant_bound(api: ApiHarness) -> None:
    customer, _, assessment, review, reviewer, _, _ = await assigned(api)
    base = f"{PRO}/reviews/{review['id']}"
    await reviewer.post(f"{base}/start")
    [finding] = assessment["finding_list"]
    r = await reviewer.post(
        f"{base}/overrides",
        json={
            "finding_id": finding["id"],
            "new_confidence": "REVIEW_REQUIRED",
            "reason": "The scheme changed last month.",
        },
    )
    assert r.status_code == 200, r.text
    factory = api.app.state.resources.session_factory
    async with factory() as db:
        await db.execute(
            text("SELECT set_config('app.current_org', :org, true)"),
            {"org": customer.personal_org_id},
        )
        for table in ("finding_override", "review_comment", "review_decision"):
            with pytest.raises(DBAPIError, match="permission denied"):
                await db.execute(text(f"DELETE FROM {table}"))  # noqa: S608
            await db.rollback()
            await db.execute(
                text("SELECT set_config('app.current_org', :org, true)"),
                {"org": customer.personal_org_id},
            )
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text("UPDATE finding_override SET reason = 'changed afterwards'"))
        await db.rollback()

    # Without a bound organisation the rows are invisible, and the definer functions return
    # ids and summaries only.
    async with factory() as db:
        assert (await db.execute(text("SELECT count(*) FROM review_request"))).scalar_one() == 0
        org_id = (
            await db.execute(text("SELECT review_request_organisation(:id)"), {"id": review["id"]})
        ).scalar_one()
        assert str(org_id) == customer.personal_org_id
