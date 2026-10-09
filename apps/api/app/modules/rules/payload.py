"""Structured consequences of a rule outcome.

An outcome's ``title`` and ``detail`` are what the customer reads. Its optional payload says
what the outcome means in data, so an assessment can turn findings into approval and
evidence requirements, "who can help" referral categories and project tasks without parsing
prose:

```json
{
  "approval": {"kind": "PLANNING_MATERIAL_CHANGE_OF_USE", "authority": "Cairns Regional
               Council", "pathway": "Check the zone's table of assessment",
               "certainty": "MAY_APPLY"},
  "evidence": [{"kind": "SITE_PLAN", "title": "Site plan showing 3 car parks"}],
  "referral_categories": ["town_planner"],
  "task": "Confirm the level of assessment with council",
  "checklists": ["vessel.initial_survey"],
  "cross_sell": ["RENT"]
}
```

``cross_sell`` names other products the customer may need next (a seller with a tenant may
need RentReady until settlement); the outcome's title and detail say why. It is only allowed
on ``CROSS_SELL`` outcomes, so an offer is always a finding of its own, with its own sources.

An approval's certainty defaults from the outcome type (``APPROVAL_REQUIRED`` → required,
``APPROVAL_LIKELY`` → likely required, ``NOT_REQUIRED`` → not identified) and may only be
lowered from there, never raised: the payload cannot claim more than the outcome does.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.modules.checklists.definition import CHECKLIST_KEY_PATTERN
from app.modules.projects.models import Vertical
from app.modules.rules.models import KEY_PATTERN, OutcomeType

CODE_PATTERN = r"^[A-Z][A-Z0-9_]{1,59}$"

Code = Annotated[str, StringConstraints(strip_whitespace=True, pattern=CODE_PATTERN)]
Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text2000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ChecklistKey = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=CHECKLIST_KEY_PATTERN)
]
CategoryKey = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=60, pattern=KEY_PATTERN)
]


class Certainty(StrEnum):
    """How sure we are that an approval applies, strongest first (BusinessReady's approval
    map uses the same scale)."""

    REQUIRED = "REQUIRED"
    LIKELY_REQUIRED = "LIKELY_REQUIRED"
    MAY_APPLY = "MAY_APPLY"
    NOT_IDENTIFIED = "NOT_IDENTIFIED"


_CERTAINTY_RANK = {
    Certainty.NOT_IDENTIFIED: 0,
    Certainty.MAY_APPLY: 1,
    Certainty.LIKELY_REQUIRED: 2,
    Certainty.REQUIRED: 3,
}

# The strongest certainty an outcome type can carry, and its default.
_MAX_CERTAINTY = {
    OutcomeType.APPROVAL_REQUIRED: Certainty.REQUIRED,
    OutcomeType.APPROVAL_LIKELY: Certainty.LIKELY_REQUIRED,
    OutcomeType.NOT_REQUIRED: Certainty.NOT_IDENTIFIED,
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApprovalSpec(_Strict):
    kind: Code = Field(description="e.g. PLANNING_MATERIAL_CHANGE_OF_USE, BUILDING_WORKS.")
    authority: Text200 | None = Field(default=None, description="Who decides, if known.")
    pathway: Text200 | None = Field(default=None, description="How, in a few words.")
    certainty: Certainty | None = Field(
        default=None, description="Defaults from the outcome type; can only be lowered."
    )


class EvidenceSpec(_Strict):
    kind: Code = Field(description="e.g. SITE_PLAN, FLOOR_PLAN, GEOTECHNICAL_REPORT.")
    title: Text200
    detail: Text2000 | None = None


class OutcomePayload(_Strict):
    approval: ApprovalSpec | None = None
    evidence: list[EvidenceSpec] = Field(default_factory=list, max_length=10)
    referral_categories: list[CategoryKey] = Field(
        default_factory=list,
        max_length=5,
        description="Kinds of professional who can help, e.g. town_planner.",
    )
    task: Text200 | None = Field(
        default=None, description="A task added to the customer's project."
    )
    checklists: list[ChecklistKey] = Field(
        default_factory=list,
        max_length=5,
        description="Reviewed checklists added to the project, e.g. vessel.initial_survey.",
    )
    cross_sell: list[Vertical] = Field(
        default_factory=list,
        max_length=3,
        description="Other products to suggest (CROSS_SELL outcomes only), e.g. RENT.",
    )


def certainty_for(outcome_type: str, spec: ApprovalSpec) -> Certainty:
    ceiling = _MAX_CERTAINTY.get(OutcomeType(outcome_type), Certainty.MAY_APPLY)
    if spec.certainty is None:
        return ceiling
    return min(spec.certainty, ceiling, key=_CERTAINTY_RANK.__getitem__)


def validate_payload(outcome_type: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalised payload JSON, or ``ValueError`` with a message for the author."""
    if payload is None:
        return None
    try:
        parsed = OutcomePayload.model_validate(payload)
    except ValidationError as exc:
        error = exc.errors()[0]
        where = ".".join(str(p) for p in error["loc"])
        raise ValueError(f"{where}: {error['msg']}" if where else error["msg"]) from exc
    if parsed.approval is not None and parsed.approval.certainty is not None:
        allowed = certainty_for(outcome_type, parsed.approval)
        if allowed != parsed.approval.certainty:
            raise ValueError(
                f"approval.certainty: a {outcome_type.lower()} outcome can't be "
                f"{parsed.approval.certainty.lower()}."
            )
    if len(set(parsed.referral_categories)) != len(parsed.referral_categories):
        raise ValueError("referral_categories: list each category once.")
    if len(set(parsed.checklists)) != len(parsed.checklists):
        raise ValueError("checklists: list each checklist once.")
    if parsed.cross_sell and outcome_type != OutcomeType.CROSS_SELL:
        raise ValueError("cross_sell: only a cross_sell outcome can suggest another product.")
    if len(set(parsed.cross_sell)) != len(parsed.cross_sell):
        raise ValueError("cross_sell: list each product once.")
    dumped = parsed.model_dump(mode="json", exclude_defaults=True)
    return dumped or None


def parse_payload(payload: dict[str, Any] | None) -> OutcomePayload:
    return OutcomePayload.model_validate(payload or {})
