"""How to apply to each Queensland council for a development application.

``qld_councils.json`` is a reviewed file with one entry per council area in the state's
address data (the 77 local government areas, plus the Weipa Town Authority): how the
council takes applications, the steps it publishes, its contact details, pre-lodgement
meetings and the application fees it publishes, with the pages each came from.

The entries were gathered from council and Queensland Government websites. They are
shown as "gathered from the council's website" until a person checks them: the content
pack ``councils_qld`` (built from this file by ``pack.py``) puts one source reference per
council into the admin sources screens, and an entry reads as checked only once its
reference there is verified. Where something wasn't published or couldn't be read, the
entry says so in ``gaps`` rather than guessing, and a missing fee reads "check with
council".
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

DIRECTORY_FILE = Path(__file__).parent / "qld_councils.json"

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
        """The section of this council's source reference in the ``councils_qld`` pack."""
        return f"Council directory: {self.key}"


class Directory(_Strict):
    councils: list[Council]

    @model_validator(mode="after")
    def _unique(self) -> Directory:
        for field in ("key", "spatial_name"):
            values = [getattr(c, field) for c in self.councils]
            if len(set(values)) != len(values):
                raise ValueError(f"duplicate council {field}")
        return self


def _normalise(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", name.lower())
    text = re.sub(r"\b(council|of|the)\b", " ", text)
    return " ".join(text.split())


@cache
def directory() -> Directory:
    return Directory.model_validate(json.loads(DIRECTORY_FILE.read_text(encoding="utf-8")))


def councils() -> list[Council]:
    """Every council, by name."""
    return sorted(directory().councils, key=lambda c: c.name)


def by_key(key: str) -> Council | None:
    return next((c for c in directory().councils if c.key == key), None)


def for_local_authority(name: str | None) -> Council | None:
    """The council for a name from the state's address data ("Cairns Regional"), or for
    its full name ("Cairns Regional Council"); None when it isn't a Queensland council."""
    if not name:
        return None
    wanted = _normalise(name)
    for council in directory().councils:
        if wanted in (_normalise(council.spatial_name), _normalise(council.name)):
            return council
    return None


# What applying for a development application in Queensland looks like everywhere, under
# the Planning Act 2016. Shown with each council's own steps, which take precedence.
GENERAL_STEPS: tuple[str, ...] = (
    "Check what the council's planning scheme says about your project: some work needs no "
    "planning approval, some is code assessable and some is impact assessable.",
    "Talk to the council's planning team before you lodge, especially if the project is "
    "unusual. Many councils offer pre-lodgement meetings.",
    "Prepare the application: the state's DA Form 1 (DA Form 2 if it includes building "
    "work), owner's consent if you don't own the "
    "land, plans, and a report showing how the project meets the planning scheme.",
    "Lodge it with the council and pay the application fee.",
    "Answer any information request from the council by the date it gives.",
    "Impact assessable applications are publicly notified before the council decides.",
    "Building work usually also needs a building approval, normally from a private "
    "building certifier.",
)
# The state's development application forms (``guidance/official_forms.json``), used by
# every council: DA Form 1 for most applications, DA Form 2 when it includes building work.
STATE_FORMS: tuple[str, ...] = ("qld-da-form-1", "qld-da-form-2")
GENERAL_SOURCE = CouncilSource(
    url="https://planning.statedevelopment.qld.gov.au/planning-framework/development-assessment/"
    "development-assessment-process",
    title="Development assessment process (Queensland Government)",
)
