"""Copy backups off the server (Milestone 17).

The ``backup`` service has no internet access (it sits on the internal data network with the
database owner's password), so the worker copies its files to S3-compatible storage
(``BACKUP_S3_*``: AWS Sydney, Backblaze B2, Wasabi) and records the result on the backup run.
Files are uploaded under ``BACKUP_S3_PREFIX`` + ``db/`` or ``uploads/`` and checked by size
afterwards. Keep the bucket private, with encryption at rest and versioning or object lock;
how long copies are kept is the bucket's lifecycle rule, not ours.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.ops.models import BackupKind, BackupRun, BackupStatus, OffsiteStatus

logger = logging.getLogger(__name__)

# Backups older than this are not chased any more (their local files are pruned anyway).
LOOKBACK = timedelta(days=14)


class Uploader(Protocol):
    def upload(self, path: Path, key: str) -> int:
        """Upload ``path`` to ``key``; return the stored object's size in bytes."""
        ...


class S3Uploader:
    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        secret = settings.backup_s3_secret_access_key
        self.bucket = settings.backup_s3_bucket or ""
        self.client: Any = boto3.client(
            "s3",
            region_name=settings.backup_s3_region,
            endpoint_url=settings.backup_s3_endpoint_url,
            aws_access_key_id=settings.backup_s3_access_key_id,
            aws_secret_access_key=secret.get_secret_value() if secret else None,
            # Non-AWS providers reject the newer default checksums on uploads.
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 5},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def upload(self, path: Path, key: str) -> int:
        self.client.upload_file(str(path), self.bucket, key)
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        return int(head["ContentLength"])


@dataclass(frozen=True)
class ShipResult:
    uploaded: int = 0
    failed: int = 0
    missing: int = 0


def _key(settings: Settings, folder: str, name: str) -> str:
    prefix = settings.backup_s3_prefix
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return f"{prefix}{folder}/{name}"


def _files(run: BackupRun, root: Path) -> list[tuple[str, Path, int | None]]:
    out: list[tuple[str, Path, int | None]] = []
    for folder, name, size in (
        ("db", run.database_file, run.database_bytes),
        ("uploads", run.uploads_file, run.uploads_bytes),
    ):
        if name:
            # Names come from our own backup script; never follow a path out of the volume.
            out.append((folder, root / Path(name).name, size))
    return out


async def ship(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    uploader_factory: Callable[[Settings], Uploader] = S3Uploader,
    now: datetime | None = None,
) -> ShipResult:
    """Copy every recent successful backup not yet off the server. A no-op until
    ``BACKUP_S3_BUCKET`` is set; then backups made before that are copied too."""
    if not settings.offsite_backups_enabled:
        return ShipResult()
    now = now or datetime.now(UTC)
    async with factory() as db:
        runs = list(
            (
                await db.execute(
                    select(BackupRun)
                    .where(
                        BackupRun.kind == BackupKind.BACKUP,
                        BackupRun.status == BackupStatus.OK,
                        BackupRun.offsite_status.in_([OffsiteStatus.PENDING, OffsiteStatus.FAILED]),
                        BackupRun.finished_at >= now - LOOKBACK,
                    )
                    .order_by(BackupRun.finished_at)
                )
            ).scalars()
        )
        await db.commit()
    if not runs:
        return ShipResult()
    uploader = uploader_factory(settings)
    root = Path(settings.backup_dir)
    uploaded = failed = missing = 0
    for run in runs:
        files = _files(run, root)
        status = OffsiteStatus.UPLOADED
        error: str | None = None
        if any(not path.is_file() for _, path, _ in files):
            status, error = OffsiteStatus.MISSING, "backup files no longer on the server"
        else:
            try:
                for folder, path, size in files:
                    stored = await asyncio.to_thread(
                        uploader.upload, path, _key(settings, folder, path.name)
                    )
                    if size is not None and stored != size:
                        raise RuntimeError(f"{path.name}: stored {stored} bytes, expected {size}")
            except Exception as exc:
                logger.warning("off-site backup copy failed", exc_info=True)
                status = OffsiteStatus.FAILED
                # Provider errors can be long; keep enough to act on, never credentials.
                error = f"{type(exc).__name__}: {exc}"[:500]
        async with factory() as db:
            row = await db.get(BackupRun, run.id)
            if row is not None:
                row.offsite_status = status
                row.offsite_attempts = row.offsite_attempts + 1
                row.offsite_error = error
                row.offsite_at = datetime.now(UTC) if status == OffsiteStatus.UPLOADED else None
            await db.commit()
        if status == OffsiteStatus.UPLOADED:
            uploaded += 1
        elif status == OffsiteStatus.MISSING:
            missing += 1
        else:
            failed += 1
    return ShipResult(uploaded=uploaded, failed=failed, missing=missing)
