"""BusinessReady's approval map: every approval an assessment considered, once, sorted
into Required, Likely required, May apply and Not identified.

Built from the stored approval requirements, so it says nothing the findings did not.
Several findings can name the same kind of approval (a liquor licence from a general rule
and a venue rule, say): the map shows it once, at the strongest certainty any of them gave
(a later "not identified" never hides an earlier "required"), and lists every finding.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.modules.assessments.models import ApprovalRequirement
from app.modules.rules.payload import Certainty

COLUMNS = (
    Certainty.REQUIRED,
    Certainty.LIKELY_REQUIRED,
    Certainty.MAY_APPLY,
    Certainty.NOT_IDENTIFIED,
)
_RANK = {c: i for i, c in enumerate(COLUMNS)}


@dataclass
class MapEntry:
    kind: str
    title: str
    certainty: Certainty
    confidence: str
    authority: str | None
    pathway: str | None
    requirement_ids: list[uuid.UUID] = field(default_factory=list)
    finding_ids: list[uuid.UUID] = field(default_factory=list)


def build(approvals: list[ApprovalRequirement]) -> list[MapEntry]:
    entries: dict[str, MapEntry] = {}
    first_seen: dict[str, int] = {}
    for a in sorted(approvals, key=lambda r: r.ordinal):
        certainty = Certainty(a.certainty)
        entry = entries.get(a.kind)
        if entry is None or _RANK[certainty] < _RANK[entry.certainty]:
            replacement = MapEntry(
                kind=a.kind,
                title=a.title,
                certainty=certainty,
                confidence=a.confidence,
                authority=a.authority,
                pathway=a.pathway,
            )
            if entry is not None:
                replacement.requirement_ids = entry.requirement_ids
                replacement.finding_ids = entry.finding_ids
            entries[a.kind] = entry = replacement
            first_seen.setdefault(a.kind, a.ordinal)
        entry.requirement_ids.append(a.id)
        entry.finding_ids.append(a.finding_id)
    return sorted(entries.values(), key=lambda e: (_RANK[e.certainty], first_seen[e.kind]))
