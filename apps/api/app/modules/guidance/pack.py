"""Build the ``guides_au`` content pack from the approval guides.

The pack gives staff one source organisation per guide publisher, a source document for
every official page a guide was gathered from (read weekly for changes, like any other
source) and one source reference per guide summarising it. Verifying that reference in the
admin sources screens is what marks the guide as checked for customers.

Regenerate the pack after editing ``approval_guides.json``::

    python -m app.modules.guidance.pack

which also writes ``public_paths.json`` (where each guide's public page lives). A test
fails if the committed pack and the guides disagree.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.modules.guidance.guides import ApprovalGuide, guides

PACK_FILE = Path(__file__).parents[1] / "rules" / "packs" / "guides_au.json"
PACK_KEY = "guides_au"


def _org_ref(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:50]


def _org_kind(jurisdiction: str) -> str:
    if jurisdiction.startswith("LGA:"):
        return "COUNCIL"
    return "CTH_AGENCY" if jurisdiction == "CTH" else "STATE_AGENCY"


def summary(guide: ApprovalGuide) -> str:
    """The guide in words, as the reference's extracted text."""
    lines = [
        f"[Gathered by ApprovalReady from official websites on {guide.checked_on.isoformat()}; "
        f"a summary, not the source's wording] How to get: {guide.title} ({guide.authority}).",
        guide.summary,
    ]
    if guide.timeframe:
        lines.append(f"Timeframe: {guide.timeframe}")
    if guide.cost_summary:
        lines.append(f"Cost: {guide.cost_summary}")
    lines += [f"Before you start: {item}" for item in guide.before_you_start]
    for i, step in enumerate(guide.steps, start=1):
        extra = "; ".join(
            x
            for x in (
                step.timeframe and f"time: {step.timeframe}",
                step.cost and f"cost: {step.cost}",
                step.form and f"form: {step.form.name}",
            )
            if x
        )
        lines.append(f"Step {i}: {step.title}. {step.detail}" + (f" ({extra})" if extra else ""))
    lines += [
        f"Fee: {fee.label}: {fee.amount}" + (f" ({fee.note})" if fee.note else "")
        for fee in guide.fees
    ]
    for contact in guide.contacts:
        detail = ", ".join(x for x in (contact.phone, contact.email, contact.url) if x)
        lines.append(f"Contact: {contact.name}" + (f": {detail}" if detail else ""))
    lines += [f"Watch out: {item}" for item in guide.watch_out]
    return "\n".join(lines)


def build() -> dict[str, Any]:
    organisations: dict[str, dict[str, Any]] = {}
    documents: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    seen_urls: dict[str, str] = {}
    for guide in guides():
        org = _org_ref(guide.publisher)
        organisations.setdefault(
            org,
            {
                "ref": org,
                "name": guide.publisher,
                "kind": _org_kind(guide.jurisdiction),
                "jurisdiction": guide.jurisdiction,
            },
        )
        first_ref: str | None = None
        shared_first: str | None = None
        for index, source in enumerate(guide.sources, start=1):
            if source.url in seen_urls:
                # Already a document of an earlier guide: the reference can point at it.
                shared_first = shared_first or seen_urls[source.url]
                continue
            ref = f"{guide.kind.lower()}_doc{index}"
            seen_urls[source.url] = ref
            first_ref = first_ref or ref
            documents.append(
                {
                    "ref": ref,
                    "organisation": org,
                    "jurisdiction": guide.jurisdiction,
                    "title": source.title[:300],
                    "url": source.url,
                    "source_type": "WEBPAGE",
                }
            )
        first_ref = first_ref or shared_first
        references.append(
            {
                "ref": f"{guide.kind.lower()}_guide",
                "document": first_ref,
                "section": guide.reference_section,
                "extracted_text": summary(guide)[:10000],
                "interpretation": (
                    "Check each line against the source pages (this guide's documents) and "
                    "correct approval_guides.json if anything is wrong before verifying."
                    + (" Gaps found: " + " ".join(guide.gaps) if guide.gaps else "")
                )[:2000],
            }
        )
    return {
        "key": PACK_KEY,
        "title": "Approval guides: how to get each approval (steps, fees, forms and contacts)",
        "notes": (
            "Generated from app/modules/guidance/approval_guides.json by "
            "`python -m app.modules.guidance.pack`; edit the guides, not this file. One "
            "reference per guide: verifying it marks that guide as checked."
        ),
        "organisations": list(organisations.values()),
        "documents": documents,
        "references": references,
        "rule_sets": [],
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    from app.modules.guidance import public

    PACK_FILE.write_text(render(), encoding="utf-8")
    print(f"wrote {PACK_FILE}")
    public.PATHS_FILE.write_text(public.render(), encoding="utf-8")
    print(f"wrote {public.PATHS_FILE}")
