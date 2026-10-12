"""Build each state's ``councils_<state>`` content pack from the council directory.

The pack gives staff one source organisation per council, a source document for every
page an entry was gathered from (read weekly for changes, like any other source) and one
source reference per council summarising the entry. Verifying that reference in the admin
sources screens is what marks the council's entry as checked for customers.

Regenerate the packs after editing a ``<state>_councils.json``::

    python -m app.modules.councils.pack

A test fails if a committed pack and the directory disagree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.councils.directory import Council, councils, states
from app.modules.lookups.spatial import STATES

PACKS_DIR = Path(__file__).parents[1] / "rules" / "packs"
PACK_KEY = "councils_qld"
PACK_FILE = PACKS_DIR / f"{PACK_KEY}.json"


def pack_key(state: str) -> str:
    return f"councils_{state.lower()}"


def pack_file(state: str) -> Path:
    return PACKS_DIR / f"{pack_key(state)}.json"


def jurisdiction(council: Council) -> str:
    """``LGA:QLD_CAIRNS``, ``LGA:NSW_SYDNEY``: the key without its state prefix."""
    bare = council.key.removeprefix(council.state.lower() + "_")
    return f"LGA:{council.state}_{bare.upper()}"


def _doc_ref(council: Council, index: int) -> str:
    return f"{council.key}_doc{index}"


def summary(council: Council) -> str:
    """The entry in words, as the reference's extracted text."""
    lines = [
        f"[Gathered by ApprovalReady from official websites on {council.checked_on.isoformat()}; "
        "a summary, not the source's wording] How to apply to "
        f"{council.name} for a development application."
    ]
    if council.planning_scheme and council.planning_scheme.name:
        lines.append(f"Planning scheme: {council.planning_scheme.name}.")
    for way in council.lodgement:
        detail = way.url or way.email or way.address or ""
        method = way.method.lower().replace("_", " ")
        lines.append(f"Lodge ({method}): {way.label} {detail}".strip())
    lines += [f"Step {i}: {step}" for i, step in enumerate(council.steps, start=1)]
    if council.pre_lodgement and council.pre_lodgement.available is not None:
        offered = "offered" if council.pre_lodgement.available else "not offered"
        note = f" ({council.pre_lodgement.note})" if council.pre_lodgement.note else ""
        lines.append(f"Pre-lodgement meetings: {offered}{note}.")
    contact = council.contact
    for label, value in (
        ("Phone", contact.phone),
        ("Email", contact.email),
        ("Address", contact.address),
        ("Hours", contact.hours),
        ("Planning enquiries email", contact.planning_email),
        ("Planning enquiries phone", contact.planning_phone),
    ):
        if value:
            lines.append(f"{label}: {value}")
    if council.fees:
        year = f" ({council.fees.fee_year})" if council.fees.fee_year else ""
        lines += [
            f"Fee{year}: {item.label}: {item.amount}" + (f" ({item.note})" if item.note else "")
            for item in council.fees.items
        ]
    return "\n".join(lines)


def build(state: str = "QLD") -> dict[str, Any]:
    organisations: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for council in councils(state):
        organisations.append(
            {
                "ref": council.key,
                "name": council.name,
                "kind": "COUNCIL",
                "jurisdiction": jurisdiction(council),
                "website": council.website,
            }
        )
        first_ref: str | None = None
        fee_url = council.fees.schedule_url if council.fees else None
        for index, source in enumerate(council.sources, start=1):
            if source.url in seen_urls:
                continue
            seen_urls.add(source.url)
            ref = _doc_ref(council, index)
            first_ref = first_ref or ref
            documents.append(
                {
                    "ref": ref,
                    "organisation": council.key,
                    "jurisdiction": jurisdiction(council),
                    "title": source.title[:300],
                    "url": source.url,
                    "source_type": "FEE_SCHEDULE" if source.url == fee_url else "WEBPAGE",
                }
            )
        if first_ref is None:
            raise ValueError(f"{council.key}: every source page is shared with another council")
        references.append(
            {
                "ref": f"{council.key}_how_to_apply",
                "document": first_ref,
                "section": council.reference_section,
                "extracted_text": summary(council)[:10000],
                "interpretation": (
                    "Check each line against the source pages (this council's documents) and "
                    f"correct {state.lower()}_councils.json if anything is wrong before "
                    "verifying."
                    + (" Gaps found: " + " ".join(council.gaps) if council.gaps else "")
                )[:2000],
            }
        )
    return {
        "key": pack_key(state),
        "title": f"{STATES[state]} councils: how to apply for a development application",
        "notes": (
            f"Generated from app/modules/councils/{state.lower()}_councils.json by "
            "`python -m app.modules.councils.pack`; edit the directory, not this file. One "
            "reference per council: verifying it marks that council's details as checked."
        ),
        "organisations": organisations,
        "documents": documents,
        "references": references,
        "rule_sets": [],
    }


PLANNING_FILE = Path(__file__).parents[1] / "questionnaires" / "definitions" / "planning.json"
OTHER_COUNCIL = {"value": "other", "label": "A council not listed here"}
QLD_ONLY_OTHER = "A council outside Queensland"


def lga_options() -> list[dict[str, str]]:
    """The planning questionnaire's ``property.lga`` options: every council, Queensland
    first then by state (the API shows each state's councils under a heading), then
    "other"."""
    grouped = len(states()) > 1
    options = [{"value": c.key, "label": c.name} for c in councils()]
    other = OTHER_COUNCIL if grouped else {"value": "other", "label": QLD_ONLY_OTHER}
    return [*options, other]


def render_planning(text: str) -> str:
    """planning.json with the council options replaced (one option per line, as written)."""
    start = text.index('"key": "property.lga"')
    open_at = text.index('"options": [', start) + len('"options": [')
    close_at = text.index("\n          ]", open_at)
    lines = ",\n".join("            " + json.dumps(o, ensure_ascii=False) for o in lga_options())
    return text[:open_at] + "\n" + lines + text[close_at:]


def render(state: str = "QLD") -> str:
    return json.dumps(build(state), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    for code in states():
        pack_file(code).write_text(render(code), encoding="utf-8")
        print(f"wrote {pack_file(code)}")
    PLANNING_FILE.write_text(
        render_planning(PLANNING_FILE.read_text(encoding="utf-8")), encoding="utf-8"
    )
    print(f"wrote {PLANNING_FILE}")
