"""The safety management system (SMS) structure: a reviewed file, ``sms_structure.json``.

The structure lists the parts an SMS for a domestic commercial vessel has to cover, from
the sources it cites, each with guidance on what to write. The builder stores the
customer's text per element. It does not write the SMS for them, and nothing here says an
SMS is adequate: that is for the operator, a marine safety professional and AMSA.
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

STRUCTURE_FILE = Path(__file__).parent / "sms_structure.json"

MAX_ELEMENT_CHARS = 20_000

ElementKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,59}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SmsSource(_Strict):
    title: str = Field(min_length=1, max_length=300)
    organisation: str = Field(min_length=1, max_length=200)
    url: HttpUrl


class SmsElement(_Strict):
    key: ElementKey
    title: str = Field(min_length=1, max_length=200)
    guidance: str = Field(min_length=1, max_length=2000)
    required: bool = True
    prefill: str | None = Field(
        default=None,
        pattern=r"^vessel_description$",
        description="Offer a starting text built from the vessel's details.",
    )


class SmsSection(_Strict):
    key: ElementKey
    title: str = Field(min_length=1, max_length=200)
    elements: list[SmsElement] = Field(min_length=1)


class SmsStructure(_Strict):
    title: str
    description: str
    disclaimer: str
    sources: list[SmsSource] = Field(min_length=1)
    sections: list[SmsSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> SmsStructure:
        keys = [e.key for s in self.sections for e in s.elements]
        if len(keys) != len(set(keys)):
            raise ValueError("each element key must appear once")
        return self

    @property
    def elements(self) -> dict[str, SmsElement]:
        return {e.key: e for s in self.sections for e in s.elements}

    def content_hash(self) -> bytes:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        ).digest()


@cache
def structure() -> SmsStructure:
    return SmsStructure.model_validate(json.loads(STRUCTURE_FILE.read_text(encoding="utf-8")))


def clean_content(changes: dict[str, str | None]) -> dict[str, str | None]:
    """Validated changes: known keys only, trimmed, ``None`` (or blank) clears an element.
    Raises ``ValueError`` naming the problem."""
    elements = structure().elements
    out: dict[str, str | None] = {}
    for key, value in changes.items():
        if key not in elements:
            raise ValueError(f"{key}: not part of the safety management system structure")
        text = (value or "").strip()
        if len(text) > MAX_ELEMENT_CHARS:
            raise ValueError(f"{key}: keep each part under {MAX_ELEMENT_CHARS:,} characters")
        out[key] = text or None
    return out


def completeness(content: dict[str, str]) -> tuple[int, int, list[str]]:
    """``(required parts written, required parts, keys of required parts still empty)``."""
    required = [e.key for e in structure().elements.values() if e.required]
    missing = [k for k in required if not content.get(k)]
    return len(required) - len(missing), len(required), missing
