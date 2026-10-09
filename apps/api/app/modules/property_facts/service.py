"""Answer suggestions for a questionnaire from what we already know about the site.

Suggestions are offered, never saved: the customer chooses to use them, and they are then
saved through the normal answers endpoint with the normal validation. Two places they come
from:

* the property linked to the project (address, lot and plan, land area), which the
  customer entered themselves;
* the configured property facts provider (``provider.py``), with its source shown.

Only questions that are part of the questionnaire, not answered yet, and for which the
value is a valid answer are suggested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.entities import service as entities
from app.modules.entities.models import Property
from app.modules.projects.models import Project
from app.modules.property_facts.provider import AddressQuery, PropertyFactsProvider
from app.modules.questionnaires.engine import AnswerInvalid, normalise_answer
from app.modules.questionnaires.service import SubmissionView

PROPERTY_SOURCE = "Your property details"


@dataclass(frozen=True)
class Suggestion:
    key: str
    label: str
    value: Any
    source: str
    source_url: str | None = None
    is_mock: bool = False


async def _property_answers(
    db: AsyncSession, project: Project
) -> tuple[dict[str, Any], AddressQuery | None]:
    if project.property_id is None:
        return {}, None
    prop = await entities.get_entity(db, Property, project.organisation_id, project.property_id)
    address = (await entities.addresses(db, [prop.address_id]))[prop.address_id]
    answers: dict[str, Any] = {
        "property.address": {
            k: v
            for k, v in {
                "line1": address.line1,
                "line2": address.line2,
                "suburb": address.suburb,
                "state": address.state,
                "postcode": address.postcode,
            }.items()
            if v
        }
    }
    if prop.lot_plan:
        answers["property.lot_plan"] = prop.lot_plan
    if prop.land_area_m2 is not None:
        answers["property.land_area_m2"] = str(prop.land_area_m2)
    query = AddressQuery(address.line1, address.suburb, address.state, address.postcode)
    return answers, query


def _address_from_answer(value: Any) -> AddressQuery | None:
    if not isinstance(value, dict):
        return None
    try:
        return AddressQuery(value["line1"], value["suburb"], value["state"], value["postcode"])
    except KeyError:
        return None


async def suggestions(
    db: AsyncSession, project: Project, view: SubmissionView, provider: PropertyFactsProvider
) -> list[Suggestion]:
    known, query = await _property_answers(db, project)
    candidates = [Suggestion(k, "", v, PROPERTY_SOURCE) for k, v in known.items()]
    query = query or _address_from_answer(view.answers.get("property.address"))
    if query is not None:
        candidates += [
            Suggestion(f.key, "", f.value, f.source, f.source_url, f.is_mock)
            for f in await provider.lookup(query)
        ]
    out: list[Suggestion] = []
    seen: set[str] = set()
    for c in candidates:
        question = view.spec.by_key.get(c.key)
        if question is None or c.key in view.answers or c.key in seen:
            continue
        try:
            value = normalise_answer(question, c.value)
        except AnswerInvalid:
            continue
        if value is None:
            continue
        seen.add(c.key)
        out.append(Suggestion(c.key, question.label, value, c.source, c.source_url, c.is_mock))
    return out
