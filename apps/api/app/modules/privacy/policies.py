"""The current versions of the Terms of Use and Privacy Policy.

``policies.json`` is the single list: the web app's pages (apps/web/src/lib/legal.ts) carry
the same versions, and a web test fails if they drift. Publishing a changed policy means a
new ``version`` here and on the page; every signed-in user is then asked to agree again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.modules.privacy.models import PolicyDocument

_FILE = Path(__file__).with_name("policies.json")


@dataclass(frozen=True)
class Policy:
    document: PolicyDocument
    title: str
    path: str
    version: str


@cache
def current() -> tuple[Policy, ...]:
    data = json.loads(_FILE.read_text(encoding="utf-8"))
    return tuple(
        Policy(PolicyDocument(key), item["title"], item["path"], item["version"])
        for key, item in data.items()
    )


def version_of(document: PolicyDocument) -> str:
    return next(p.version for p in current() if p.document == document)
