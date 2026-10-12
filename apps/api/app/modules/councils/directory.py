"""How to apply to each council for a development application, in every state we cover.

``<state>_councils.json`` (``qld_councils.json``, ``nsw_councils.json``, ...) is a reviewed
file per state or territory with one entry per council area in that state's address data:
how the council takes applications, the steps it publishes, its contact details,
pre-lodgement meetings and the application fees it publishes, with the pages each came
from. Queensland's keys are bare (``cairns``); every other state's keys start with the
state (``nsw_sydney``), so a key names one council in Australia.

The entries were gathered from council and state government websites. They are shown as
"gathered from the council's website" until a person checks them: the content pack
``councils_<state>`` (built from the file by ``pack.py``) puts one source reference per
council into the admin sources screens, and an entry reads as checked only once its
reference there is verified. Where something wasn't published or couldn't be read, the
entry says so in ``gaps`` rather than guessing, and a missing fee reads "check with
council".

``states.py`` holds what applying looks like across each state (the general steps, the
state's forms and fees set by the state), shown with every council's own details.
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

DIRECTORY_DIR = Path(__file__).parent
DIRECTORY_FILE = DIRECTORY_DIR / "qld_councils.json"
StateCode = Literal["QLD", "NSW", "VIC", "WA", "SA", "TAS", "ACT", "NT"]

Url = Annotated[str, StringConstraints(pattern=r"^https?://[^\s]+$", max_length=2000)]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )


class CouncilLodgement(_Strict):
    method: Literal["ONLINE", "EMAIL", "POST", "IN_PERSON"]
    label: Line
    url: Url | None = None
    email: Line | None = None
    address: Line | None = None


class CouncilPlanningScheme(_Strict):
    name: Line | None = None
    url: Url | None = None


class CouncilPreLodgement(_Strict):
    available: bool | None = None
    url: Url | None = None
    note: Line | None = None


class CouncilContact(_Strict):
    phone: Line | None = None
    email: Line | None = None
    address: Line | None = None
    hours: Line | None = None
    # Where planning and development enquiries go, when the council publishes it. The
    # email may be the council's general address when that is what the council says to
    # use for planning questions (``planning_email_general``), and ``planning_source`` is
    # the page it was published on.
    planning_email: Line | None = None
    planning_email_general: bool = False
    planning_phone: Line | None = None
    planning_source: Url | None = None


class CouncilFeeItem(_Strict):
    label: Line
    amount: Line
    note: Line | None = None


class CouncilFees(_Strict):
    schedule_url: Url | None = None
    fee_year: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}$")] | None = None
    items: list[CouncilFeeItem] = Field(default_factory=list, max_length=8)


class CouncilSource(_Strict):
    url: Url
    title: Line


class Council(_Strict):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,40}$")]
    name: Line
    # Set from the file the entry is in.
    state: StateCode = "QLD"
    # The council's name in the state's address and cadastre data (``local_authority`` /
    # ``shire_name``), e.g. "Cairns Regional".
    spatial_name: Line
    checked_on: date
    website: Url | None = None
    planning_url: Url | None = None
    planning_scheme: CouncilPlanningScheme | None = None
    lodgement: list[CouncilLodgement] = Field(default_factory=list)
    steps: list[Line] = Field(default_factory=list, max_length=10)
    pre_lodgement: CouncilPreLodgement | None = None
    contact: CouncilContact = Field(default_factory=CouncilContact)
    fees: CouncilFees | None = None
    sources: list[CouncilSource] = Field(min_length=1)
    gaps: list[Line] = Field(default_factory=list)

    @property
    def reference_section(self) -> str:
        """The section of this council's source reference in its state's councils pack."""
        return f"Council directory: {self.key}"

    @property
    def label(self) -> str:
        """The name with the state, for lists that hold more than one state."""
        return self.name if self.state == "QLD" else f"{self.name} ({self.state})"


class Directory(_Strict):
    councils: list[Council]

    @model_validator(mode="after")
    def _unique(self) -> Directory:
        keys = [c.key for c in self.councils]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate council key")
        names = [(c.state, c.spatial_name) for c in self.councils]
        if len(set(names)) != len(names):
            raise ValueError("duplicate council spatial_name")
        for c in self.councils:
            if c.state != "QLD" and not c.key.startswith(c.state.lower() + "_"):
                raise ValueError(f"{c.key}: keys outside Queensland start with the state")
        return self


def _normalise(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", name.lower())
    text = re.sub(r"\b(council|of|the)\b", " ", text)
    return " ".join(text.split())


def state_files() -> dict[str, Path]:
    """Each state's directory file, by state code."""
    return {
        path.name.split("_", 1)[0].upper(): path
        for path in sorted(DIRECTORY_DIR.glob("*_councils.json"))
    }


@cache
def directory() -> Directory:
    entries: list[dict[str, object]] = []
    for state, path in state_files().items():
        for entry in json.loads(path.read_text(encoding="utf-8"))["councils"]:
            entries.append({**entry, "state": state})
    return Directory.model_validate({"councils": entries})


def states() -> list[str]:
    """The states and territories with a council directory, Queensland first."""
    return sorted({c.state for c in directory().councils}, key=lambda s: (s != "QLD", s))


def councils(state: str | None = None) -> list[Council]:
    """Every council (in one state, if given), by state then name, Queensland first."""
    return sorted(
        (c for c in directory().councils if state is None or c.state == state),
        key=lambda c: (c.state != "QLD", c.state, c.name),
    )


def by_key(key: str) -> Council | None:
    return next((c for c in directory().councils if c.key == key), None)


def for_local_authority(name: str | None, state: str | None = None) -> Council | None:
    """The council for a name from a state's address data ("Cairns Regional"), or for its
    full name ("Cairns Regional Council"), in that state when given (names repeat between
    states: there is a Campbelltown in New South Wales and South Australia); None when it
    isn't a council we know."""
    if not name:
        return None
    wanted = _normalise(name)
    for council in councils(state):
        if wanted in (_normalise(council.spatial_name), _normalise(council.name)):
            return council
    return None
