"""Prompt registry: the reviewed prompt files in ``prompts/`` and syncing them to the database.

Like report templates, prompts are reviewed in the repository and published by the migrate
step (``python -m app.cli ai sync-prompts``). A changed file becomes a new immutable version
and retires the previous one; every job and provider log row points at the version it used.
There is no screen or endpoint that edits a prompt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import AITask, PromptStatus, PromptVersion
from app.modules.ai.outputs import get_schema

PROMPTS_DIR = Path(__file__).parent / "prompts"


def sandbox() -> SandboxedEnvironment:
    # Plain text, not HTML: no autoescaping (the data block escapes itself, data_block()).
    return SandboxedEnvironment(
        autoescape=False, undefined=StrictUndefined, keep_trailing_newline=True
    )


class SchemaRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    version: int


class PromptDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: AITask
    output_schema: SchemaRef
    system: str
    template: str

    def content_hash(self) -> bytes:
        canonical = json.dumps(
            {
                "system": self.system,
                "template": self.template,
                "schema": [self.output_schema.name, self.output_schema.version],
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).digest()


def _read_beside(path: Path, name: str) -> str:
    target = (path.parent / name).resolve()
    if target.parent != path.parent.resolve():
        raise ValueError(f"{path.name}: {name} must be a file next to the definition")
    return target.read_text(encoding="utf-8")


def load_file(path: Path) -> PromptDef:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["system"] = _read_beside(path, raw["system"])
    raw["template"] = _read_beside(path, raw["template"])
    definition = PromptDef.model_validate(raw)
    get_schema(definition.output_schema.name, definition.output_schema.version)
    sandbox().parse(definition.template)
    if "{{ data }}" not in definition.template:
        raise ValueError(f"{path.name}: the template must place the data block ({{{{ data }}}})")
    return definition


def load_bundled() -> list[PromptDef]:
    definitions = [load_file(p) for p in sorted(PROMPTS_DIR.glob("*.json"))]
    tasks = [d.task for d in definitions]
    if len(tasks) != len(set(tasks)):
        raise ValueError("each AI task needs exactly one prompt file")
    return definitions


def data_block(data: dict[str, Any]) -> str:
    """The data as JSON, with ``<``, ``>`` and ``&`` escaped so nothing inside it can close
    the ``<data>`` block or open another tag."""
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1)
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def render_user(version: PromptVersion, data: dict[str, Any]) -> str:
    return sandbox().from_string(version.user_template).render(data=data_block(data))


@dataclass(frozen=True)
class SyncResult:
    task: str
    version: int
    changed: bool


async def sync_prompt(db: AsyncSession, definition: PromptDef) -> SyncResult:
    content_hash = definition.content_hash()
    current = (
        await db.execute(
            select(PromptVersion).where(
                PromptVersion.task == definition.task,
                PromptVersion.status == PromptStatus.PUBLISHED,
            )
        )
    ).scalar_one_or_none()
    if current is not None and current.content_hash == content_hash:
        return SyncResult(definition.task, current.version, changed=False)
    latest = (
        await db.execute(
            select(func.max(PromptVersion.version)).where(PromptVersion.task == definition.task)
        )
    ).scalar_one()
    if current is not None:
        current.status = PromptStatus.RETIRED
        await db.flush()
    version = PromptVersion(
        task=definition.task,
        version=(latest or 0) + 1,
        status=PromptStatus.PUBLISHED,
        system_prompt=definition.system,
        user_template=definition.template,
        output_schema_name=definition.output_schema.name,
        output_schema_version=definition.output_schema.version,
        content_hash=content_hash,
    )
    db.add(version)
    await db.flush()
    return SyncResult(definition.task, version.version, changed=True)


async def sync_prompts(db: AsyncSession, definitions: list[PromptDef]) -> list[SyncResult]:
    return [await sync_prompt(db, d) for d in definitions]


async def published(db: AsyncSession, task: AITask) -> PromptVersion | None:
    return (
        await db.execute(
            select(PromptVersion).where(
                PromptVersion.task == task, PromptVersion.status == PromptStatus.PUBLISHED
            )
        )
    ).scalar_one_or_none()
