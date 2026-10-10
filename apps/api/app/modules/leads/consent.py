"""Consent texts: the reviewed file, syncing it, and the current version.

``python -m app.cli leads sync-consent`` runs on every migrate (as the owner: the
application role can only read the table). A text whose title or body changed becomes a new
version; old versions stay, because every consent points at the exact words agreed to.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.modules.leads.models import ConsentPurpose, ConsentTextVersion

CONSENT_FILE = Path(__file__).parent / "consent.json"


class ConsentTextDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: ConsentPurpose
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.title}\n\n{self.body}".encode()).hexdigest()


class ConsentFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str
    texts: list[ConsentTextDef] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_per_purpose(self) -> ConsentFile:
        purposes = [t.purpose for t in self.texts]
        if len(purposes) != len(set(purposes)):
            raise ValueError("each purpose must appear once")
        return self


def load_bundled(path: Path = CONSENT_FILE) -> list[ConsentTextDef]:
    return ConsentFile.model_validate(json.loads(path.read_text(encoding="utf-8"))).texts


async def sync(db: AsyncSession, texts: list[ConsentTextDef]) -> list[str]:
    """Publish a new version of each text that changed. Returns what happened."""
    out: list[str] = []
    for t in texts:
        current = await current_version(db, t.purpose)
        if current is not None and current.content_hash == t.content_hash:
            continue
        previous = (
            await db.execute(
                select(ConsentTextVersion).where(
                    ConsentTextVersion.purpose == t.purpose,
                    ConsentTextVersion.content_hash == t.content_hash,
                )
            )
        ).scalar_one_or_none()
        if previous is not None:
            # Going back to earlier words: a new version, so "current" is always the latest.
            raise ValueError(
                f"{t.purpose}: this text was version {previous.version}; change a word so "
                "the new version is distinct"
            )
        latest = (
            await db.execute(
                select(func.max(ConsentTextVersion.version)).where(
                    ConsentTextVersion.purpose == t.purpose
                )
            )
        ).scalar_one()
        version = (latest or 0) + 1
        db.add(
            ConsentTextVersion(
                purpose=t.purpose,
                version=version,
                title=t.title,
                body=t.body,
                content_hash=t.content_hash,
            )
        )
        out.append(f"{t.purpose}: published version {version}")
    await db.flush()
    return out or ["consent texts unchanged"]


async def current_version(
    db: AsyncSession, purpose: ConsentPurpose = ConsentPurpose.PARTNER_REFERRAL
) -> ConsentTextVersion | None:
    return (
        await db.execute(
            select(ConsentTextVersion)
            .where(ConsentTextVersion.purpose == purpose)
            .order_by(ConsentTextVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def require_current(db: AsyncSession) -> ConsentTextVersion:
    text = await current_version(db)
    if text is None:
        raise ApiError(503, "consent_unavailable", "Introductions aren't available yet.")
    return text
