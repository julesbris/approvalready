"""Build the ``councils_qld`` content pack from the council directory.

The pack gives staff one source organisation per council, a source document for every
page an entry was gathered from (read weekly for changes, like any other source) and one
source reference per council summarising the entry. Verifying that reference in the admin
sources screens is what marks the council's entry as checked for customers.

Regenerate the pack after editing ``qld_councils.json``::

    python -m app.modules.councils.pack

A test fails if the committed pack and the directory disagree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.councils.directory import Council, councils

PACK_FILE = Path(__file__).parents[1] / "rules" / "packs" / "councils_qld.json"
PACK_KEY = "councils_qld"


def jurisdiction(council: Council) -> str:
    return f"LGA:QLD_{council.key.upper()}"


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


def build() -> dict[str, Any]:
    organisations: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for council in councils():
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
                    "correct qld_councils.json if anything is wrong before verifying."
                    + (" Gaps found: " + " ".join(council.gaps) if council.gaps else "")
                )[:2000],
            }
        )
    return {
        "key": PACK_KEY,
        "title": "Queensland councils: how to apply for a development application",
        "notes": (
            "Generated from app/modules/councils/qld_councils.json by "
            "`python -m app.modules.councils.pack`; edit the directory, not this file. One "
            "reference per council: verifying it marks that council's details as checked."
        ),
        "organisations": organisations,
        "documents": documents,
        "references": references,
        "rule_sets": [],
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    PACK_FILE.write_text(render(), encoding="utf-8")
    print(f"wrote {PACK_FILE}")
