"""Operations routes (Milestone 17).

* ``GET /v1/admin/ops``: the operational checks, recent backups and restore checks
  (``platform.audit.read``: platform admins).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import DbDep, OrgContext, ResourcesDep, SettingsDep, require_platform_permission
from app.modules.ops import checks
from app.modules.ops.models import BackupRun
from app.modules.ops.schemas import BackupRunOut, CheckOut, OpsStatusOut
from app.modules.tenancy.rbac import Perm

admin_router = APIRouter(prefix="/v1/admin/ops", tags=["admin: operations"])

Admin = Annotated[OrgContext, Depends(require_platform_permission(Perm.PLATFORM_AUDIT_READ))]


@admin_router.get("", response_model=OpsStatusOut)
async def ops_status(
    ctx: Admin, db: DbDep, resources: ResourcesDep, settings: SettingsDep
) -> OpsStatusOut:
    """Is the platform looking after itself: background jobs, backups, disk."""
    now = datetime.now(UTC)
    results = await checks.collect(db, resources.redis, settings, now)
    runs = (
        await db.execute(select(BackupRun).order_by(BackupRun.finished_at.desc()).limit(30))
    ).scalars()
    return OpsStatusOut(
        checked_at=now,
        checks=[CheckOut(**c.__dict__) for c in results],
        runs=[BackupRunOut.model_validate(r) for r in runs],
        offsite_enabled=settings.offsite_backups_enabled,
        error_tracking_enabled=settings.sentry_dsn is not None,
        alert_email_count=len(settings.ops_alert_emails),
        version=settings.app_version,
        git_sha=settings.git_sha,
    )
