"""What applying for a development application looks like across each state or territory.

``states.json`` has one entry per state we cover: the general steps (shown with each
council's own steps, which take precedence), the state's application forms every council
uses, fees the state sets for every council (New South Wales and South Australia set
development application fees by regulation, for example), what the state calls a
council's planning rules, and where to look up the zone. Gathered from state government
websites like the council directory.
"""

from __future__ import annotations

import json
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.councils.directory import CouncilFees, CouncilSource, Line, StateCode, Url
from app.modules.guidance import forms as official_forms
from app.modules.guidance.forms import FormId

STATES_FILE = Path(__file__).parent / "states.json"


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )


class StatePlanning(_Strict):
    state: StateCode
    name: Line
    checked_on: date
    general_steps: list[Annotated[str, StringConstraints(min_length=1, max_length=600)]] = Field(
        min_length=1, max_length=10
    )
    # The state's application forms (``guidance/official_forms.json``) every council uses.
    forms: list[FormId] = Field(default_factory=list)
    source: CouncilSource
    # Fees the state sets for every council, shown when a council's own fees aren't listed.
    fees: CouncilFees | None = None
    # What the state calls a council's planning rules ("planning scheme", "Local
    # Environmental Plan").
    planning_scheme_label: Line = "planning scheme"
    # Where anyone can look up a site's zone and overlays on a map.
    zoning_lookup_url: Url | None = None
    # Where development applications are lodged when the state runs one portal for every
    # council (New South Wales, South Australia, the ACT).
    portal: CouncilSource | None = None
    gaps: list[Line] = Field(default_factory=list)


class States(_Strict):
    states: list[StatePlanning]

    @model_validator(mode="after")
    def _check(self) -> States:
        codes = [s.state for s in self.states]
        if len(set(codes)) != len(codes):
            raise ValueError("duplicate state")
        for s in self.states:
            missing = official_forms.unknown(s.forms)
            if missing:
                raise ValueError(f"{s.state}: unknown forms {missing}")
        return self


@cache
def _states() -> dict[str, StatePlanning]:
    parsed = States.model_validate(json.loads(STATES_FILE.read_text(encoding="utf-8")))
    return {s.state: s for s in parsed.states}


def for_state(state: str) -> StatePlanning | None:
    return _states().get(state)


def all_states() -> list[StatePlanning]:
    return list(_states().values())
