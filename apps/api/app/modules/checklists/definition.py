"""Checklist definitions: reviewed JSON files in ``definitions/``, one per checklist.

A checklist is a list of things to gather or do before an approval step (a vessel's initial
survey, a registration application). Like questionnaires and templates, definitions are
reviewed in the repository; unlike them they are not synced to the database: adding a
checklist to a project copies its items into the project, so later edits to the file never
change a checklist a customer is already working through.

Every definition cites the sources its items come from. Items describe what to prepare;
they never state that an approval is or is not needed (that is the rules' job).
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

from app.modules.projects.models import Vertical

DEFINITIONS_DIR = Path(__file__).parent / "definitions"

CHECKLIST_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,30}\.[a-z][a-z0-9_]{1,40}$"
ChecklistKey = Annotated[str, StringConstraints(pattern=CHECKLIST_KEY_PATTERN)]
ItemKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,59}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChecklistSource(_Strict):
    title: str = Field(min_length=1, max_length=300)
    organisation: str = Field(min_length=1, max_length=200)
    url: HttpUrl


class ChecklistItemDef(_Strict):
    key: ItemKey
    title: str = Field(min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=1000)
    required: bool = True


class ChecklistDef(_Strict):
    key: ChecklistKey
    vertical: Vertical
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    sources: list[ChecklistSource] = Field(min_length=1)
    items: list[ChecklistItemDef] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def _unique_items(self) -> ChecklistDef:
        keys = [i.key for i in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.key}: each item key must appear once")
        return self

    def content_hash(self) -> bytes:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        ).digest()


def load_file(path: Path) -> ChecklistDef:
    definition = ChecklistDef.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if path.stem != definition.key:
        raise ValueError(f"{path.name}: the file name must be the checklist key")
    return definition


@cache
def bundled() -> dict[str, ChecklistDef]:
    return {d.key: d for d in (load_file(p) for p in sorted(DEFINITIONS_DIR.glob("*.json")))}


def for_vertical(vertical: str) -> list[ChecklistDef]:
    return [d for d in bundled().values() if d.vertical == vertical]


def unknown_keys(keys: list[str]) -> list[str]:
    known = bundled()
    return [k for k in keys if k not in known]
