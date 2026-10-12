"""Official forms: the direct link to every government form our guidance names.

Whenever a guide, checklist, finding or council page says "lodge Form 36" or "complete a
B650", the customer should be one click from that form. ``official_forms.json`` lists each
form once with its number, official name, publisher and a link to it on the publisher's own
site (gathered and checked on ``checked_on``).

Form numbers repeat between publishers ("Form 2" is the RTA's bond lodgement, the seller
disclosure statement and a building application), so a mention is only linked within a
known scope:

* a step-by-step guide lists the forms it names (``forms`` in ``approval_guides.json``);
* everything else in one product (findings, checklists, plan steps) links the forms whose
  ``verticals`` include that product, and a test makes sure no two forms in one product
  share a mention.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.projects.models import Vertical

FORMS_FILE = Path(__file__).parent / "official_forms.json"

FormId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)]
Url = Annotated[str, StringConstraints(pattern=r"^https://[^\s]+$", max_length=2000)]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class OfficialForm(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )

    id: FormId
    # The number people write, e.g. "Form 18a", "B650", "NAT 75136"; None for online forms
    # that have no number.
    code: Line | None = None
    name: Line
    publisher: Line
    url: Url
    # Words in our text that refer to this form and become a link to it. Defaults to the code.
    mentions: list[Line] = Field(default_factory=list)
    # Products whose findings, checklists and plan steps link this form's mentions.
    verticals: list[Vertical] = Field(default_factory=list)
    note: Line | None = None

    @property
    def label(self) -> str:
        """How the form is named in a list: number and name."""
        if self.code and self.code.lower() not in self.name.lower():
            return f"{self.code} {self.name}"
        return self.name

    @property
    def phrases(self) -> list[str]:
        return list(self.mentions) or ([self.code] if self.code else [])


class FormLibrary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checked_on: date
    forms: list[OfficialForm]

    @model_validator(mode="after")
    def _consistent(self) -> FormLibrary:
        ids = [f.id for f in self.forms]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate form id")
        for vertical in Vertical:
            seen: dict[str, str] = {}
            for f in self.forms:
                if vertical not in f.verticals:
                    continue
                for phrase in f.phrases:
                    other = seen.setdefault(phrase, f.id)
                    if other != f.id:
                        raise ValueError(
                            f"{vertical}: '{phrase}' could mean {other} or {f.id}; "
                            "give one of them a more specific mention"
                        )
        return self


@cache
def library() -> FormLibrary:
    return FormLibrary.model_validate(json.loads(FORMS_FILE.read_text(encoding="utf-8")))


@cache
def _by_id() -> dict[str, OfficialForm]:
    return {f.id: f for f in library().forms}


def get(form_id: str) -> OfficialForm:
    return _by_id()[form_id]


def unknown(ids: Iterable[str]) -> list[str]:
    known = _by_id()
    return [i for i in ids if i not in known]


def by_ids(ids: Iterable[str]) -> list[OfficialForm]:
    known = _by_id()
    return [known[i] for i in ids if i in known]


def for_vertical(vertical: Vertical | str) -> list[OfficialForm]:
    return [f for f in library().forms if vertical in f.verticals]


def _pattern(phrase: str) -> str:
    # "Form 1" must not match inside "Form 1a" or "Form 18", nor "B650" inside "B6500".
    return rf"(?<![\w]){re.escape(phrase)}(?![\w])"


def mentioned(text: str | None, forms: Iterable[OfficialForm]) -> list[OfficialForm]:
    """The forms this text mentions, in the order they first appear."""
    if not text:
        return []
    hits: list[tuple[int, OfficialForm]] = []
    for f in forms:
        positions = [m.start() for p in f.phrases for m in re.finditer(_pattern(p), text)]
        if positions:
            hits.append((min(positions), f))
    return [f for _, f in sorted(hits, key=lambda h: h[0])]
