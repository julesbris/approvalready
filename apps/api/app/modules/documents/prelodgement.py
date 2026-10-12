"""The pre-lodgement pack: one document to take to a meeting (or send) to the council's
planning team before lodging a development application.

It brings together what the council will ask about: the site (address, lot and plan,
zone, area and the constraints known or mapped), what is proposed, the approvals the
assessment found, the documents to bring, how the council takes pre-lodgement enquiries,
and a list of questions with room to write the council's answers. Everything comes from
the assessment's facts and findings and the council directory; nothing new is claimed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.modules.councils import directory

QLD_GLOBE = "https://qldglobe.information.qld.gov.au/"
SARA_MAPPING = "https://planning.statedevelopment.qld.gov.au/planning-framework/mapping"

# What each known constraint usually means for the application, to ask the council about.
CONSTRAINT_QUESTIONS = {
    "heritage": "The site may be heritage listed or near a heritage place. What heritage "
    "assessment or report will the application need?",
    "flooding": "The site may be flood affected. What floor levels, flood report or design "
    "measures will the council expect?",
    "bushfire": "The site may be in a bushfire hazard area. Will a bushfire management plan "
    "or a bushfire attack level (BAL) assessment be needed?",
    "vegetation": "There may be protected vegetation on the site. Can any of it be cleared, "
    "and will an ecological or arborist report be needed?",
    "easement": "There is an easement on the site. What can be built over or near it, and do "
    "we need the easement holder's consent?",
    "steep_slope": "The site may be steep. Will a geotechnical report or slope stability "
    "assessment be needed?",
    "wet_tropics_world_heritage": "The site may be in or near the Wet Tropics World Heritage "
    "Area. Do any extra requirements or referrals apply?",
}


def _text(value: Any) -> str | None:
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value).strip() or None


def _address(value: Any) -> str | None:
    if isinstance(value, dict):
        place = " ".join(
            p for p in (_text(value.get(k)) for k in ("suburb", "state", "postcode")) if p
        )
        parts = [_text(value.get("line1")), _text(value.get("line2")), place or None]
        return ", ".join(p for p in parts if p) or None
    return _text(value)


def _choice(options: dict[str, dict[str, str]], key: str, value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    label = options.get(key, {}).get(value)
    return label or value.replace("_", " ").capitalize()


def build(
    facts: dict[str, Any],
    options: dict[str, dict[str, str]],
    approvals: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    missing: list[str],
) -> dict[str, Any]:
    """The pack's own sections, from the report context's approvals, evidence and missing
    information and the assessment's facts (with the questionnaire's option wording)."""
    council = directory.by_key(facts["property.lga"]) if facts.get("property.lga") else None
    address = _address(facts.get("property.address"))
    lot_plan = _text(facts.get("property.lot_plan"))
    zone = _choice(options, "property.zone", facts.get("property.zone"))
    if facts.get("property.zone") == "another_zone":
        zone = None

    land = facts.get("property.land_area_m2")
    site = [
        ("Address", address),
        ("Lot and plan", lot_plan),
        ("Council", council.name if council else None),
        ("Zone", zone),
        ("Land area", f"{_text(land)} m²" if land is not None else None),
        ("Existing house on the land", _text(facts.get("property.has_existing_dwelling"))),
    ]

    development = _choice(
        options, "planning.development_type", facts.get("planning.development_type")
    )
    proposal = [
        ("What is proposed", development),
        ("Description", _text(facts.get("planning.other_description"))),
        ("Bedrooms", _text(facts.get("planning.secondary_dwelling_bedrooms"))),
        ("Floor area (m²)", _text(facts.get("planning.secondary_dwelling_floor_area_m2"))),
        ("Storeys", _text(facts.get("planning.storeys"))),
        ("Lots after subdividing", _text(facts.get("planning.proposed_lots"))),
        ("Smallest new lot (m²)", _text(facts.get("planning.smallest_lot_m2"))),
        ("Narrowest frontage (m)", _text(facts.get("planning.smallest_lot_frontage_m"))),
        ("Current use", _text(facts.get("planning.current_use"))),
        ("Proposed use", _text(facts.get("planning.proposed_use"))),
        ("Hoping to start", _text(facts.get("planning.target_start_date"))),
        ("Designer, builder or planner involved", _text(facts.get("planning.has_professional"))),
    ]

    raw_constraints = facts.get("planning.known_constraints") or []
    constraint_keys = [c for c in raw_constraints if isinstance(c, str)]
    constraints = [_choice(options, "planning.known_constraints", c) or c for c in constraint_keys]

    where = f" in the {zone} zone" if zone else " on this site"
    questions = [
        f"Does this proposal need a development application{where}, and would it be "
        "accepted, code or impact assessable?",
        "Which parts of the planning scheme (zone code, overlay codes, development codes) "
        "will the council assess it against?",
    ]
    for a in approvals:
        if a["certainty_label"] != "Required":
            questions.append(f"Is this approval needed: {a['title']}?")
    questions += [CONSTRAINT_QUESTIONS[c] for c in constraint_keys if c in CONSTRAINT_QUESTIONS]
    questions += [
        "Will the application be referred to the State Assessment and Referral Agency (SARA) "
        "or any other agency?",
        "What plans and reports should the application include, and at what level of detail?",
        "What is the application fee, and will infrastructure charges apply?",
        "How long does the council usually take to decide an application like this?",
    ]

    bring = [
        "This pack, printed or on screen.",
        "A site plan showing the boundaries, existing buildings and what you want to build.",
        "Photos of the site and the street.",
        "A copy of the title search or rates notice showing the lot and plan, if you have it.",
    ] + [e["title"] + (f" ({e['detail']})" if e.get("detail") else "") for e in evidence]

    contact = None
    if council is not None:
        c = council.contact
        email = c.planning_email or c.email
        pre = council.pre_lodgement
        contact = {
            "name": council.name,
            "email": email,
            "email_general": bool(email) and (c.planning_email_general or not c.planning_email),
            "phone": c.planning_phone or c.phone,
            "pre_lodgement": (
                "The council offers pre-lodgement meetings."
                if pre and pre.available
                else "The council says it doesn't offer pre-lodgement meetings at the moment."
                if pre and pre.available is False
                else "Ask the council whether it offers pre-lodgement meetings."
            )
            + (f" {pre.note}" if pre and pre.note else ""),
            "pre_lodgement_url": pre.url if pre else None,
            "planning_scheme": council.planning_scheme.name if council.planning_scheme else None,
            "planning_scheme_url": council.planning_scheme.url if council.planning_scheme else None,
            "fees": [
                {"label": f.label, "amount": f.amount}
                for f in (council.fees.items if council.fees else [])
            ],
            "fee_year": council.fees.fee_year if council.fees else None,
            "checked_on": council.checked_on.strftime("%-d %B %Y"),
        }

    return {
        "site": [{"label": k, "value": v} for k, v in site if v],
        "proposal": [{"label": k, "value": v} for k, v in proposal if v],
        "constraints": constraints,
        "council": contact,
        "questions": questions,
        "bring": bring,
        "to_confirm": missing,
        "map_links": [
            {
                "title": "Queensland Globe (search the lot and plan, then print the map)",
                "url": QLD_GLOBE,
            },
            {
                "title": "State planning maps, including the development assessment mapping "
                "system (DAMS) for state referrals",
                "url": SARA_MAPPING,
            },
        ],
    }
