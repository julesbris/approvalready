"""Answer suggestions for a questionnaire from what we already know about the site.

Suggestions are offered, never saved: the customer chooses to use them, and they are then
saved through the normal answers endpoint with the normal validation. Two places they come
from:

* the property linked to the project (address, lot and plan, land area), the business
  profile linked to a business project (ABN, structure, size, address) or the vessel linked
  to a vessel project (name, type, length, propulsion, UVI, passengers, crew), which the
  customer entered themselves;
* the configured property facts provider (``provider.py``), with its source shown.

Only questions that are part of the questionnaire and for which the value is a valid answer
are suggested, and only when they aren't answered yet, with two exceptions so the answers
follow the site: when the project's property is a different address from the one answered,
the site answers (address, lot and plan, land area, council) are suggested again from the
property; and mapped constraints are suggested when they add to the ones already ticked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.entities import service as entities
from app.modules.entities.models import BusinessProfile, Property, Vessel
from app.modules.grants.service import today
from app.modules.projects.models import Project
from app.modules.property_facts.provider import AddressQuery, PropertyFactsProvider
from app.modules.questionnaires.engine import AnswerInvalid, normalise_answer
from app.modules.questionnaires.service import SubmissionView

PROPERTY_SOURCE = "Your property details"
# Answers that describe the site itself: replaced when the project's property changes.
SITE_KEYS = frozenset(
    {"property.address", "property.lot_plan", "property.land_area_m2", "property.lga"}
)
CONSTRAINTS_KEY = "planning.known_constraints"
BUSINESS_SOURCE = "Your business details"
VESSEL_SOURCE = "Your vessel details"


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


async def _business_answers(db: AsyncSession, project: Project) -> dict[str, Any]:
    if project.business_profile_id is None:
        return {}
    profile = await entities.get_entity(
        db, BusinessProfile, project.organisation_id, project.business_profile_id
    )
    address_postcode: str | None = None
    answers: dict[str, Any] = {
        "business.has_abn": profile.abn is not None,
        "business.entity_type": profile.entity_type,
    }
    if profile.abn:
        answers["business.abn"] = profile.abn
    if profile.employee_band:
        answers["business.employee_band"] = profile.employee_band
    if profile.turnover_band:
        answers["business.turnover_band"] = profile.turnover_band
    if profile.address_id is not None:
        address = (await entities.addresses(db, [profile.address_id]))[profile.address_id]
        address_postcode = address.postcode
        answers["business.state"] = address.state
        answers["business.premises_address"] = {
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
    answers.update(_grant_answers(profile, answers.get("business.state"), address_postcode))
    answers.update(_trade_answers(profile, answers.get("business.state")))
    return answers


def _trading_age(established_on: date | None, on: date) -> str | None:
    if established_on is None:
        return None
    if established_on > on:
        return "not_yet"
    years = (
        on.year
        - established_on.year
        - ((on.month, on.day) < (established_on.month, established_on.day))
    )
    return "under_1" if years < 1 else "1_to_3" if years < 3 else "over_3"


def _grant_answers(
    profile: BusinessProfile, state: str | None, postcode: str | None
) -> dict[str, Any]:
    """The same business profile, phrased for the grant questionnaire (``grant.*``)."""
    answers: dict[str, Any] = {
        "grant.has_abn": profile.abn is not None,
        "grant.entity_type": profile.entity_type,
    }
    if profile.entity_type != "INCORPORATED_ASSOCIATION":
        answers["grant.applicant_type"] = "business"
    if profile.abn and profile.gst_registered is not None:
        answers["grant.gst_registered"] = profile.gst_registered
    if profile.employee_band:
        answers["grant.employee_band"] = profile.employee_band
    if profile.turnover_band:
        answers["grant.turnover_band"] = profile.turnover_band
    age = _trading_age(profile.established_on, today())
    if age:
        answers["grant.trading_age"] = age
    if state:
        answers["grant.state"] = state
    if postcode:
        answers["grant.postcode"] = postcode
    return answers


def _trade_answers(profile: BusinessProfile, state: str | None) -> dict[str, Any]:
    """The same business profile, phrased for the import and export questionnaire."""
    answers: dict[str, Any] = {"trade.has_abn": profile.abn is not None}
    if profile.abn and profile.gst_registered is not None:
        answers["trade.gst_registered"] = profile.gst_registered
    if state:
        answers["trade.state"] = state
    return answers


async def _vessel_answers(db: AsyncSession, project: Project) -> dict[str, Any]:
    if project.vessel_id is None:
        return {}
    vessel = await entities.get_entity(db, Vessel, project.organisation_id, project.vessel_id)
    answers: dict[str, Any] = {
        "vessel.name": vessel.name,
        "vessel.type": vessel.vessel_type.lower(),
        "vessel.has_uvi": vessel.uvi is not None,
    }
    if vessel.length_m is not None:
        answers["vessel.length_m"] = str(vessel.length_m)
    if vessel.propulsion:
        answers["vessel.propulsion"] = vessel.propulsion.lower()
    if vessel.uvi:
        answers["vessel.uvi"] = vessel.uvi
    if vessel.max_passengers is not None:
        answers["vessel.max_passengers"] = vessel.max_passengers
    if vessel.crew is not None:
        answers["vessel.crew"] = vessel.crew
    return answers


def _address_from_answer(value: Any) -> AddressQuery | None:
    if not isinstance(value, dict):
        return None
    try:
        return AddressQuery(value["line1"], value["suburb"], value["state"], value["postcode"])
    except KeyError:
        return None


def _same_address(a: Any, b: Any) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False

    def norm(v: Any) -> str:
        return " ".join(str(v or "").upper().split())

    return all(norm(a.get(k)) == norm(b.get(k)) for k in ("line1", "suburb", "state"))


async def suggestions(
    db: AsyncSession, project: Project, view: SubmissionView, provider: PropertyFactsProvider
) -> list[Suggestion]:
    known, query = await _property_answers(db, project)
    candidates = [Suggestion(k, "", v, PROPERTY_SOURCE) for k, v in known.items()]
    candidates += [
        Suggestion(k, "", v, BUSINESS_SOURCE)
        for k, v in (await _business_answers(db, project)).items()
    ]
    candidates += [
        Suggestion(k, "", v, VESSEL_SOURCE) for k, v in (await _vessel_answers(db, project)).items()
    ]
    answered_address = view.answers.get("property.address")
    # The project's property is a different site from the one answered: redo the site.
    site_changed = "property.address" in known and (
        answered_address is not None
        and not _same_address(known["property.address"], answered_address)
    )
    query = query or _address_from_answer(answered_address)
    if query is not None:
        candidates += [
            Suggestion(f.key, "", f.value, f.source, f.source_url, f.is_mock)
            for f in await provider.lookup(query)
        ]
    out: list[Suggestion] = []
    seen: set[str] = set()
    for c in candidates:
        question = view.spec.by_key.get(c.key)
        if question is None or c.key in seen:
            continue
        current = view.answers.get(c.key)
        replace = site_changed and c.key in SITE_KEYS
        if current is not None and not replace and c.key != CONSTRAINTS_KEY:
            continue
        try:
            value = normalise_answer(question, c.value)
        except AnswerInvalid:
            continue
        if value is None:
            continue
        if c.key == CONSTRAINTS_KEY and isinstance(current, list):
            # Add what the mapping shows to what was ticked; never untick anything.
            if set(value) <= set(current):
                continue
            value = sorted(set(current) | set(value))
        if value == current:
            continue
        seen.add(c.key)
        out.append(Suggestion(c.key, question.label, value, c.source, c.source_url, c.is_mock))
    return out
