"""Report template definitions (the files in ``templates/``) and syncing them to the database.

Like questionnaire definitions, templates are reviewed in the repository and published by
the migrate step (``python -m app.cli documents sync-templates``). A changed file becomes a
new immutable version and retires the previous one; generated documents keep pointing at
the version they were made from. The application role can only read these tables.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import (
    DocumentTemplate,
    DocumentTemplateVersion,
    OutputFormat,
    TemplateEngine,
    TemplateStatus,
)
from app.modules.documents.render import RenderError, sandbox
from app.modules.projects.models import Vertical

TEMPLATES_DIR = Path(__file__).parent / "templates"


class TemplateDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,59}$")
    title: str = Field(min_length=1, max_length=200)
    vertical: Vertical
    engine: TemplateEngine = TemplateEngine.JINJA_HTML
    body: str = Field(description="The Jinja body itself once loaded (a file name on disk).")
    output_formats: list[OutputFormat] = Field(min_length=1)

    def content_hash(self) -> bytes:
        canonical = json.dumps(
            {"engine": self.engine, "body": self.body, "formats": sorted(self.output_formats)},
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).digest()


def load_file(path: Path) -> TemplateDef:
    raw = json.loads(path.read_text(encoding="utf-8"))
    body_path = (path.parent / raw["body"]).resolve()
    if body_path.parent != path.parent.resolve():
        raise ValueError(f"{path.name}: the body must be a file next to the definition")
    raw["body"] = body_path.read_text(encoding="utf-8")
    definition = TemplateDef.model_validate(raw)
    try:
        sandbox().parse(definition.body)
    except Exception as exc:
        raise RenderError(f"{path.name}: {exc}") from exc
    return definition


def load_bundled() -> list[TemplateDef]:
    return [load_file(p) for p in sorted(TEMPLATES_DIR.glob("*.json"))]


@dataclass(frozen=True)
class SyncResult:
    key: str
    version: int
    changed: bool


async def sync_template(db: AsyncSession, definition: TemplateDef) -> SyncResult:
    template = (
        await db.execute(select(DocumentTemplate).where(DocumentTemplate.key == definition.key))
    ).scalar_one_or_none()
    if template is None:
        template = DocumentTemplate(
            key=definition.key, title=definition.title, vertical=definition.vertical
        )
        db.add(template)
        await db.flush()
    template.title = definition.title
    template.vertical = definition.vertical

    content_hash = definition.content_hash()
    current = (
        await db.execute(
            select(DocumentTemplateVersion).where(
                DocumentTemplateVersion.template_id == template.id,
                DocumentTemplateVersion.status == TemplateStatus.PUBLISHED,
            )
        )
    ).scalar_one_or_none()
    if current is not None and current.content_hash == content_hash:
        return SyncResult(definition.key, current.version, changed=False)
    latest = (
        await db.execute(
            select(func.max(DocumentTemplateVersion.version)).where(
                DocumentTemplateVersion.template_id == template.id
            )
        )
    ).scalar_one()
    if current is not None:
        current.status = TemplateStatus.RETIRED
        await db.flush()
    version = DocumentTemplateVersion(
        template_id=template.id,
        version=(latest or 0) + 1,
        status=TemplateStatus.PUBLISHED,
        engine=definition.engine,
        body=definition.body,
        output_formats=[str(f) for f in definition.output_formats],
        content_hash=content_hash,
    )
    db.add(version)
    await db.flush()
    return SyncResult(definition.key, version.version, changed=True)


async def sync_templates(db: AsyncSession, definitions: list[TemplateDef]) -> list[SyncResult]:
    return [await sync_template(db, d) for d in definitions]


async def published(db: AsyncSession, key: str) -> DocumentTemplateVersion | None:
    return (
        await db.execute(
            select(DocumentTemplateVersion)
            .join(DocumentTemplate, DocumentTemplate.id == DocumentTemplateVersion.template_id)
            .where(
                DocumentTemplate.key == key,
                DocumentTemplateVersion.status == TemplateStatus.PUBLISHED,
            )
        )
    ).scalar_one_or_none()
