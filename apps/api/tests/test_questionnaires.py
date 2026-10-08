"""Questionnaire versioning and immutability, and the answer/branching/submit flow via the API."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.questionnaires import service
from app.modules.questionnaires.definition import QuestionnaireDef
from tests.harness import ApiHarness, User

pytestmark = pytest.mark.integration

ADDRESS = {"line1": "1 Esplanade", "suburb": "Cairns City", "state": "QLD", "postcode": "4870"}


def base(org_id: str) -> str:
    return f"/v1/organisations/{org_id}"


async def start(user: User, vertical: str = "PLANNING", key: str | None = None) -> dict[str, Any]:
    org = base(user.personal_org_id)
    project = (await user.post(f"{org}/projects", json={"vertical": vertical, "title": "P"})).json()
    body = {"questionnaire_key": key} if key else {}
    r = await user.post(f"{org}/projects/{project['id']}/submissions", json=body)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def answer(user: User, submission: dict[str, Any], answers: dict[str, Any]) -> Any:
    return await user.put(
        f"{base(user.personal_org_id)}/submissions/{submission['id']}/answers",
        json={"answers": answers},
    )


# --- Published definitions -------------------------------------------------------------


async def test_bundled_questionnaires_are_published(api: ApiHarness) -> None:
    user = await api.user()
    listed = (await user.get("/v1/questionnaires")).json()
    keys = {q["key"] for q in listed}
    assert {
        f"{v}.general" for v in ("planning", "vessel", "business", "grant", "sell", "rent")
    } <= keys
    planning = (await user.get("/v1/questionnaires/planning.general")).json()
    assert planning["vertical"] == "PLANNING"
    assert planning["sections"][0]["questions"][0]["key"] == "property.address"
    lots = next(
        q
        for s in planning["sections"]
        for q in s["questions"]
        if q["key"] == "planning.proposed_lots"
    )
    assert lots["visible_when"] == {
        "fact": "planning.development_type",
        "op": "equals",
        "value": "subdivision",
    }
    assert (await user.get("/v1/questionnaires/nope.nope")).status_code == 404
    assert (await api.client.get("/v1/questionnaires")).status_code == 401


# --- Versioning ------------------------------------------------------------------------


def _versioned(*extra: dict[str, Any]) -> QuestionnaireDef:
    # GRANT vertical with an explicit key: tests that start GRANT submissions must name it.
    return QuestionnaireDef.model_validate(
        {
            "key": "test.versioning",
            "vertical": "GRANT",
            "title": "Versioning test",
            "sections": [
                {
                    "title": "Only",
                    "questions": [
                        {"key": "test.name", "type": "TEXT", "label": "Name", "required": True},
                        *extra,
                    ],
                }
            ],
        }
    )


async def test_versions_are_pinned_and_immutable(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    v1 = _versioned()
    async with owner_sessions() as db:
        first = await service.sync_definition(db, v1)
        again = await service.sync_definition(db, v1)
        await db.commit()
    assert again.version == first.version and not again.changed

    user = await api.user()
    old = await start(user, "GRANT", "test.versioning")
    assert old["questionnaire"]["version"] == first.version
    assert (await answer(user, old, {"test.name": "Ada"})).status_code == 200

    v2 = _versioned({"key": "test.extra", "type": "BOOLEAN", "label": "Extra?"})
    async with owner_sessions() as db:
        second = await service.sync_definition(db, v2)
        await db.commit()
        statuses = dict(
            (
                await db.execute(
                    text(
                        "SELECT v.version, v.status FROM questionnaire_version v "
                        "JOIN questionnaire q ON q.id = v.questionnaire_id "
                        "WHERE q.key = 'test.versioning'"
                    )
                )
            ).all()
        )
    assert second.changed and second.version == first.version + 1
    assert statuses[first.version] == "RETIRED" and statuses[second.version] == "PUBLISHED"

    # The open submission still uses the version it started on, answers intact.
    org = base(user.personal_org_id)
    pinned = (await user.get(f"{org}/submissions/{old['id']}")).json()
    assert pinned["questionnaire"]["version"] == first.version
    assert pinned["answers"] == {"test.name": "Ada"}
    r = await answer(user, old, {"test.extra": True})
    assert r.status_code == 422
    assert "test.extra" in r.json()["detail"]["fields"]
    # Starting again on the same project resumes it rather than switching version.
    resumed = await user.post(
        f"{org}/projects/{old['project_id']}/submissions",
        json={"questionnaire_key": "test.versioning"},
    )
    assert resumed.json()["id"] == old["id"]

    new = await start(user, "GRANT", "test.versioning")
    assert new["questionnaire"]["version"] == second.version
    assert new["visible"] == ["test.name", "test.extra"]

    # Published content cannot change, even for the owner.
    async with owner_sessions() as db:
        for statement in (
            "UPDATE question_version SET label = 'Changed' WHERE questionnaire_version_id = "
            "(SELECT id FROM questionnaire_version WHERE status = 'PUBLISHED' LIMIT 1)",
            "UPDATE questionnaire_version SET title = 'Changed' WHERE status = 'PUBLISHED'",
            "UPDATE questionnaire_version SET status = 'DRAFT' WHERE status = 'RETIRED'",
            "DELETE FROM questionnaire_version WHERE status = 'RETIRED'",
            "DELETE FROM question_option",
            "INSERT INTO question_option (id, question_version_id, value, label, ordinal) "
            "SELECT gen_random_uuid(), id, 'zz', 'ZZ', 99 FROM question_version LIMIT 1",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                await db.execute(text(statement))
            await db.rollback()
    # And the application role cannot write definitions at all.
    async with api.app.state.resources.session_factory() as db:
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text("UPDATE question SET key = key"))
        await db.rollback()


# --- Answering -------------------------------------------------------------------------


async def test_answer_branch_prune_submit_reopen(api: ApiHarness) -> None:
    user = await api.user()
    org = base(user.personal_org_id)
    submission = await start(user)
    assert submission["status"] == "IN_PROGRESS"
    assert submission["questionnaire"]["key"] == "planning.general"
    assert "planning.proposed_lots" not in submission["visible"]
    project = (await user.get(f"{org}/projects/{submission['project_id']}")).json()
    assert project["status"] == "IN_PROGRESS"  # starting the questionnaire started the project
    assert project["submissions"][0]["questionnaire_key"] == "planning.general"

    # Invalid answers: nothing saved, every problem reported against its question.
    r = await answer(
        user,
        submission,
        {
            "property.address": {**ADDRESS, "postcode": "48"},
            "property.land_area_m2": "lots",
            "planning.development_type": "skyscraper",
            "no.such.question": 1,
        },
    )
    assert r.status_code == 422
    fields = r.json()["detail"]["fields"]
    assert set(fields) == {
        "property.address",
        "property.land_area_m2",
        "planning.development_type",
        "no.such.question",
    }
    assert fields["property.address"] == "Enter a 4-digit postcode."
    assert (await user.get(f"{org}/submissions/{submission['id']}")).json()["answers"] == {}

    r = await answer(
        user,
        submission,
        {
            "property.address": ADDRESS,
            "property.land_area_m2": 812.25,
            "property.has_existing_dwelling": True,
            "planning.development_type": "subdivision",
            "planning.proposed_lots": "3",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answers"]["planning.proposed_lots"] == 3
    assert body["answers"]["property.land_area_m2"] == "812.25"
    assert "planning.proposed_lots" in body["visible"]
    assert body["missing_required"] == []
    assert body["progress"]["answered"] == 5

    # Changing the controlling answer hides and removes the dependent answer.
    r = await answer(user, submission, {"planning.development_type": "secondary_dwelling"})
    body = r.json()
    assert body["pruned"] == ["planning.proposed_lots"]
    assert "planning.proposed_lots" not in body["answers"]
    assert body["missing_required"] == [
        "planning.secondary_dwelling_bedrooms",
        "planning.storeys",
    ]

    url = f"{org}/submissions/{submission['id']}"
    r = await user.post(f"{url}/submit")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "answers_incomplete"
    assert set(r.json()["detail"]["fields"]) == {
        "planning.secondary_dwelling_bedrooms",
        "planning.storeys",
    }

    # null clears an optional answer.
    r = await answer(
        user,
        submission,
        {
            "planning.secondary_dwelling_bedrooms": 2,
            "planning.storeys": 1,
            "property.land_area_m2": None,
        },
    )
    assert "property.land_area_m2" not in r.json()["answers"]
    r = await user.post(f"{url}/submit")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SUBMITTED" and r.json()["submitted_at"]

    r = await answer(user, submission, {"planning.storeys": 2})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "submission_closed"
    assert (await user.post(f"{url}/submit")).status_code == 409

    r = await user.post(f"{url}/reopen")
    assert r.status_code == 200 and r.json()["status"] == "IN_PROGRESS"
    assert (await answer(user, submission, {"planning.storeys": 2})).status_code == 200

    actions = [e["action"] for e in (await user.get(f"{org}/audit-events")).json()]
    for action in ("questionnaire.started", "questionnaire.submitted", "questionnaire.reopened"):
        assert action in actions


async def test_start_requires_a_matching_questionnaire(api: ApiHarness) -> None:
    user = await api.user()
    org = base(user.personal_org_id)
    project = (await user.post(f"{org}/projects", json={"vertical": "SELL", "title": "P"})).json()
    url = f"{org}/projects/{project['id']}/submissions"
    r = await user.post(url, json={"questionnaire_key": "planning.general"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "wrong_vertical"
    assert (await user.post(url, json={"questionnaire_key": "nope.nope"})).status_code == 404
    r = await user.post(url, json={})
    assert r.status_code == 200
    assert r.json()["questionnaire"]["key"] == "sell.general"
