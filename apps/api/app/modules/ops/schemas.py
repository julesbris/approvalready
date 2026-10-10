"""Operations schemas (Milestone 17)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.ops.checks import CheckState


class CheckOut(BaseModel):
    key: str
    label: str
    state: CheckState
    detail: str


class BackupRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime
    database_file: str | None
    database_bytes: int | None
    uploads_file: str | None
    uploads_bytes: int | None
    detail: str | None
    offsite_status: str | None
    offsite_at: datetime | None
    offsite_error: str | None


class OpsStatusOut(BaseModel):
    checked_at: datetime
    checks: list[CheckOut]
    # Newest first: the last 30 backups and restore checks.
    runs: list[BackupRunOut]
    offsite_enabled: bool
    error_tracking_enabled: bool
    # How many extra addresses (OPS_ALERT_EMAILS) get alerts besides platform admins.
    alert_email_count: int
    version: str
    git_sha: str
