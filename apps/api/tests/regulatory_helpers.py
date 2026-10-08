"""Building sources and rules through the admin API in tests.

Everything here is fictional test data (``example.com``, "Test Council"): no real
regulatory content is ever invented, in tests or anywhere else.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from tests.harness import User

ADMIN = "/v1/admin"


def unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def source_document(staff: User, **overrides: Any) -> dict[str, Any]:
    r = await staff.post(
        f"{ADMIN}/source-organisations",
        json={"name": unique("Test Council"), "kind": "COUNCIL", "jurisdiction": "QLD"},
    )
    assert r.status_code == 201, r.text
    body = {
        "source_organisation_id": r.json()["id"],
        "jurisdiction": "LGA:QLD_TEST",
        "title": unique("Test Planning Scheme"),
        "url": "https://example.com/planning-scheme",
        "source_type": "PLANNING_SCHEME",
        "effective_from": "2020-01-01",
        **overrides,
    }
    r = await staff.post(f"{ADMIN}/source-documents", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


async def snapshot(staff: User, document_id: str, text: str = "Clause 1. Example text.") -> Any:
    r = await staff.post(
        f"{ADMIN}/source-documents/{document_id}/snapshots",
        json={"content_text": text, "retrieved_at": datetime.now(UTC).isoformat()},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def reference(
    staff: User, *, verify: bool = True, document: dict[str, Any] | None = None
) -> dict[str, Any]:
    document = document or await source_document(staff)
    r = await staff.post(
        f"{ADMIN}/source-documents/{document['id']}/references",
        json={"section": "Part 1", "clause": "1.1", "extracted_text": "Example extract."},
    )
    assert r.status_code == 201, r.text
    ref = dict(r.json())
    if verify:
        await snapshot(staff, document["id"])
        r = await staff.post(
            f"{ADMIN}/source-references/{ref['id']}/review", json={"action": "VERIFY"}
        )
        assert r.status_code == 200, r.text
        ref = dict(r.json())
    return ref


async def rule_set(
    staff: User, *, vertical: str = "VESSEL", applies_when: dict[str, Any] | None = None
) -> dict[str, Any]:
    r = await staff.post(
        f"{ADMIN}/rule-sets",
        json={
            "key": f"test.{unique('set')}",
            "vertical": vertical,
            "jurisdiction": "QLD",
            "title": "Test rules",
            "applies_when": applies_when,
        },
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def content(
    condition: dict[str, Any],
    ref_ids: list[str],
    *,
    test_cases: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    return {
        "condition": condition,
        "effective_from": "2026-01-01",
        "outcomes": [
            {"on_result": "MATCH", "outcome_type": "APPROVAL_REQUIRED", "title": "Approval needed"},
            {"on_result": "NO_MATCH", "outcome_type": "NOT_REQUIRED", "title": "Not needed"},
        ],
        "sources": [{"source_reference_id": r, "relationship": "BASIS"} for r in ref_ids],
        "test_cases": test_cases
        if test_cases is not None
        else [{"name": "missing", "facts": {}, "expected_result": "UNKNOWN"}],
        **overrides,
    }


async def published_rule(
    admin: User,
    rule_set_id: str,
    condition: dict[str, Any],
    ref_ids: list[str],
    **content_overrides: Any,
) -> dict[str, Any]:
    """Create a rule, save its first draft and publish it. Returns the published version."""
    r = await admin.post(
        f"{ADMIN}/rule-sets/{rule_set_id}/rules",
        json={"key": unique("rule"), "title": "Test rule", "condition": condition},
    )
    assert r.status_code == 201, r.text
    version_id = r.json()["versions"][0]["id"]
    r = await admin.put(
        f"{ADMIN}/rule-versions/{version_id}", json=content(condition, ref_ids, **content_overrides)
    )
    assert r.status_code == 200, r.text
    r = await admin.post(f"{ADMIN}/rule-versions/{version_id}/publish")
    assert r.status_code == 200, r.text
    return dict(r.json())
