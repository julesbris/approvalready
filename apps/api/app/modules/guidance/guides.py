"""How to get each kind of approval an assessment can name.

A finding says *that* an approval applies (``payload.approval.kind``, e.g.
``VEHICLE_IMPORT_APPROVAL``). ``approval_guides.json`` says *how to get it*: what to have
ready, the steps in order with the form, timeframe and cost of each, the fees, who to
contact, what commonly goes wrong, and the official pages each came from. Assessments show
the guide for every approval they name, in the order the guides give (``order``), so a
customer sees one plan from first step to last.

The guides were gathered from official websites and are shown as "gathered from official
websites" until a person checks them: the content pack ``guides_au`` (built from this file
by ``pack.py``) puts one source reference per guide into the admin sources screens, and a
guide reads as checked only once its reference there is verified. Where something wasn't
published or couldn't be read, the guide says so in ``gaps`` rather than guessing.

Guides live in code rather than in rules so they can be improved on any deploy without
reloading a pack: loading a pack never changes a rule that already exists.
"""

from __future__ import annotations

import json
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.guidance import forms as official_forms
from app.modules.guidance.forms import FormId
from app.modules.projects.models import Vertical
from app.modules.rules.payload import CODE_PATTERN

GUIDES_FILE = Path(__file__).parent / "approval_guides.json"
# Commonwealth, a state or territory, or one council area ("LGA:QLD_CAIRNS").
JURISDICTION_PATTERN = r"^(CTH|QLD|NSW|VIC|WA|SA|TAS|ACT|NT|LGA:[A-Z]{2,3}_[A-Z0-9_]+)$"

Url = Annotated[str, StringConstraints(pattern=r"^https?://[^\s]+$", max_length=2000)]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Para = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)]
Kind = Annotated[str, StringConstraints(pattern=CODE_PATTERN)]


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )


class GuideLink(_Strict):
    name: Line
    url: Url


class GuideStep(_Strict):
    title: Line
    detail: Para
    timeframe: Line | None = None
    cost: Line | None = None
    form: GuideLink | None = None
    url: Url | None = None


class GuideFee(_Strict):
    label: Line
    amount: Line
    note: Line | None = None


class GuideContact(_Strict):
    name: Line
    phone: Line | None = None
    email: Line | None = None
    url: Url | None = None
    hours: Line | None = None
    note: Line | None = None


class GuideSource(_Strict):
    url: Url
    title: Line


class ApprovalGuide(_Strict):
    kind: Kind
    title: Line
    summary: Para
    authority: Line
    # The source organisation the guide's pages are filed under in the admin sources screens.
    publisher: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    # Which products show it: the same kind can mean different things elsewhere (a home
    # based business check in BusinessReady is a full planning application in PlanningReady).
    verticals: list[Vertical] = Field(min_length=1)
    jurisdiction: Annotated[str, StringConstraints(pattern=JURISDICTION_PATTERN)]
    # Where this sits in a customer's plan: lower comes first (before you buy or ship,
    # then at the border, then after arrival or before opening).
    order: int = Field(ge=0, le=1000)
    checked_on: date
    timeframe: Line | None = None
    cost_summary: Line | None = None
    before_you_start: list[Line] = Field(default_factory=list, max_length=12)
    steps: list[GuideStep] = Field(min_length=1, max_length=16)
    fees: list[GuideFee] = Field(default_factory=list, max_length=20)
    contacts: list[GuideContact] = Field(default_factory=list, max_length=10)
    watch_out: list[Line] = Field(default_factory=list, max_length=12)
    sources: list[GuideSource] = Field(min_length=1)
    gaps: list[Line] = Field(default_factory=list)
    # Every official form the guide names (``official_forms.json``), in the order to use them.
    # Mentions of these forms anywhere in the guide become links to them.
    forms: list[FormId] = Field(default_factory=list, max_length=30)

    @property
    def reference_section(self) -> str:
        """The section of this guide's source reference in the ``guides_au`` pack."""
        return f"Approval guide: {self.kind}"


class Guides(_Strict):
    guides: list[ApprovalGuide]

    @model_validator(mode="after")
    def _unique(self) -> Guides:
        kinds = [g.kind for g in self.guides]
        if len(set(kinds)) != len(kinds):
            raise ValueError("duplicate guide kind")
        for g in self.guides:
            missing = official_forms.unknown(g.forms)
            if missing:
                raise ValueError(f"{g.kind}: unknown forms {missing}")
        return self


@cache
def library() -> Guides:
    return Guides.model_validate(json.loads(GUIDES_FILE.read_text(encoding="utf-8")))


def guides() -> list[ApprovalGuide]:
    """Every guide, in plan order."""
    return sorted(library().guides, key=lambda g: (g.order, g.title))


def for_kinds(kinds: list[str], vertical: Vertical | None = None) -> list[ApprovalGuide]:
    """The guides for these approval kinds (in one product, if given), in plan order; kinds
    without a guide are left out."""
    wanted = set(kinds)
    return [
        g for g in guides() if g.kind in wanted and (vertical is None or vertical in g.verticals)
    ]
