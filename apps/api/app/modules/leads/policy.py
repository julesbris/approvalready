"""Release policy: how many partners a lead can go to, how it is offered in waves and when
it expires. Read from the reviewed file ``policy.json``; each lead stores the policy it was
made with, so changing the file never changes a lead already offered."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

POLICY_FILE = Path(__file__).parent / "policy.json"


class ReleasePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_providers: int = Field(ge=1, le=3)
    first_wave: int = Field(ge=1, le=20)
    wave_size: int = Field(ge=1, le=20)
    wave_hours: int = Field(ge=1, le=24 * 14)
    expires_after_days: int = Field(ge=1, le=90)


class PolicyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str
    default: ReleasePolicy
    categories: dict[str, dict[str, int]]

    def for_category(self, key: str) -> ReleasePolicy:
        override = self.categories.get(key)
        if not override:
            return self.default
        return ReleasePolicy.model_validate(self.default.model_dump() | override)


@cache
def load_bundled(path: Path = POLICY_FILE) -> PolicyFile:
    policy = PolicyFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for key in policy.categories:
        policy.for_category(key)  # validate every override now, not when a lead is made
    return policy


def for_category(key: str) -> ReleasePolicy:
    return load_bundled().for_category(key)


def of_lead(stored: dict[str, Any]) -> ReleasePolicy:
    return ReleasePolicy.model_validate(stored)
