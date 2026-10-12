"""Where each approval guide lives on the public site, for search engines and social posts.

Every guide gets its own page at ``/guides/<state>/<slug>``: ``<state>`` is the state or
territory it applies in (``australia`` for Commonwealth guides, the state for a council's),
and ``<slug>`` comes from the guide's kind without its state prefix
(``NSW_BOAT_LICENCE`` is ``/guides/nsw/boat-licence``) unless the guide sets its own.

The web app builds its pages from ``public_paths.json``, which ``pack.py`` writes from this
module (a test keeps it in step), so the site and the marketing posts always agree on the
address of a guide.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.modules.guidance.guides import ApprovalGuide, guides

PATHS_FILE = Path(__file__).parent / "public_paths.json"


@dataclass(frozen=True)
class State:
    code: str
    segment: str
    name: str
    hashtag: str


STATES: tuple[State, ...] = (
    State("QLD", "qld", "Queensland", "#Queensland"),
    State("NSW", "nsw", "New South Wales", "#NSW"),
    State("VIC", "vic", "Victoria", "#Victoria"),
    State("WA", "wa", "Western Australia", "#WesternAustralia"),
    State("SA", "sa", "South Australia", "#SouthAustralia"),
    State("TAS", "tas", "Tasmania", "#Tasmania"),
    State("ACT", "act", "Australian Capital Territory", "#Canberra"),
    State("NT", "nt", "Northern Territory", "#NorthernTerritory"),
    State("CTH", "australia", "Australia-wide", "#Australia"),
)
_BY_CODE = {s.code: s for s in STATES}


def state_of(guide: ApprovalGuide) -> State:
    """The state a guide applies in: a council's guide belongs to its state."""
    code = guide.jurisdiction
    if code.startswith("LGA:"):
        code = code.removeprefix("LGA:").split("_", 1)[0]
    return _BY_CODE[code]


def slug_of(guide: ApprovalGuide) -> str:
    if guide.slug:
        return guide.slug
    kind = guide.kind
    prefix = state_of(guide).code + "_"
    if kind.startswith(prefix):
        kind = kind.removeprefix(prefix)
    return kind.lower().replace("_", "-")


def path_of(guide: ApprovalGuide) -> str:
    return f"/guides/{state_of(guide).segment}/{slug_of(guide)}"


def build() -> dict[str, object]:
    rows = [
        {
            "kind": g.kind,
            "state": state_of(g).segment,
            "slug": slug_of(g),
            "path": path_of(g),
        }
        for g in guides()
    ]
    paths = [r["path"] for r in rows]
    duplicates = sorted({p for p in paths if paths.count(p) > 1})
    if duplicates:
        raise ValueError(f"two guides share a page: {duplicates} (give one a `slug`)")
    return {
        "notes": (
            "Generated from approval_guides.json by `python -m app.modules.guidance.pack`; "
            "the web app's public guide pages live at these paths."
        ),
        "states": [{"code": s.code, "segment": s.segment, "name": s.name} for s in STATES],
        "guides": rows,
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def path_for_kind(kind: str) -> str | None:
    return next((path_of(g) for g in guides() if g.kind == kind), None)
