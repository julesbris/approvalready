"""The watchdog (Milestone 17): run the operational checks and alert people.

Every 10 minutes the worker runs the checks in ``checks``. When one starts failing, platform
admins (anyone holding ``platform.audit.read``) get an in-app notification and an email, as
do the addresses in ``OPS_ALERT_EMAILS``; a check that is still failing is repeated every 12
hours, and its recovery is announced once. Warnings are only shown at ``/admin/ops``.

What is failing, and since when, is kept in Redis (``ops:failing:<check>``), so a restart of
the worker neither repeats nor loses an alert.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.email import EmailProvider
from app.db.tenant import bind_tenant
from app.modules.notifications import emails
from app.modules.notifications import service as notifications
from app.modules.notifications.models import NotificationKind
from app.modules.ops.checks import Check, CheckState, collect
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation, OrganisationKind, OrganisationMember
from app.modules.tenancy.rbac import Perm

logger = logging.getLogger(__name__)

FAILING_KEY = "ops:failing:{}"  # value: ISO time the check started failing
ALERTED_KEY = "ops:alerted:{}"  # value: ISO time of the last alert for it
REPEAT_AFTER = timedelta(hours=12)
OPS_PATH = "/admin/ops"


@dataclass(frozen=True)
class Alert:
    title: str
    body: str
    dedupe_key: str


def _since_key(since: str) -> str:
    return since.replace(":", "").replace("-", "")[:15]


async def plan_alerts(redis: Redis, checks: list[Check], now: datetime) -> list[Alert]:
    """Decide what to announce, and remember it in Redis."""
    alerts: list[Alert] = []
    for check in checks:
        failing_key = FAILING_KEY.format(check.key)
        alerted_key = ALERTED_KEY.format(check.key)
        since = await redis.get(failing_key)
        if check.state == CheckState.FAILING:
            if since is None:
                since = now.isoformat()
                await redis.set(failing_key, since)
            last = await redis.get(alerted_key)
            if last is not None and now - datetime.fromisoformat(last) < REPEAT_AFTER:
                continue
            await redis.set(alerted_key, now.isoformat())
            alerts.append(
                Alert(
                    title=f"Needs attention: {check.label}",
                    body=check.detail,
                    dedupe_key=f"ops:{check.key}:{_since_key(since)}:{_since_key(now.isoformat())}",
                )
            )
        elif since is not None:
            await redis.delete(failing_key, alerted_key)
            alerts.append(
                Alert(
                    title=f"Back to normal: {check.label}",
                    body=check.detail,
                    dedupe_key=f"ops:{check.key}:{_since_key(since)}:ok",
                )
            )
    return alerts


async def _platform_admins(
    factory: async_sessionmaker[AsyncSession],
) -> list[tuple[uuid.UUID, list[uuid.UUID]]]:
    async with factory() as db:
        orgs = list(
            (
                await db.execute(
                    select(Organisation.id).where(
                        Organisation.kind == OrganisationKind.PLATFORM_ADMIN,
                        Organisation.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        await db.commit()
    out: list[tuple[uuid.UUID, list[uuid.UUID]]] = []
    for org_id in orgs:
        async with factory() as db:
            await bind_tenant(db, org_id)
            members = list(
                (
                    await db.execute(
                        select(OrganisationMember.user_id).where(
                            OrganisationMember.organisation_id == org_id
                        )
                    )
                ).scalars()
            )
            admins = []
            for user_id in members:
                m = await tenancy.membership(db, user_id, org_id)
                if m is not None and Perm.PLATFORM_AUDIT_READ in m.permissions:
                    admins.append(user_id)
            await db.commit()
        out.append((org_id, admins))
    return out


async def send_alerts(
    factory: async_sessionmaker[AsyncSession],
    provider: EmailProvider,
    settings: Settings,
    alerts: list[Alert],
) -> int:
    """Notify platform admins (in the app and by email) and OPS_ALERT_EMAILS."""
    if not alerts:
        return 0
    sent = 0
    for org_id, admins in await _platform_admins(factory):
        async with factory() as db:
            await bind_tenant(db, org_id)
            ids: list[uuid.UUID] = []
            for alert in alerts:
                for user_id in admins:
                    nid = await notifications.create(
                        db,
                        organisation_id=org_id,
                        recipient_user_id=user_id,
                        kind=NotificationKind.OPS_ALERT,
                        title=alert.title,
                        body=alert.body,
                        link_path=OPS_PATH,
                        dedupe_key=alert.dedupe_key,
                    )
                    if nid is not None:
                        ids.append(nid)
            await db.commit()
            sent += await notifications.send_emails(db, provider, settings, org_id, ids)
    for address in settings.ops_alert_emails:
        for alert in alerts:
            message = emails.notification(
                settings, address, "there", alert.title, alert.body, OPS_PATH
            )
            try:
                await provider.send(message)
                sent += 1
            except Exception:
                logger.exception("ops alert email failed")
    return sent


async def watchdog(
    factory: async_sessionmaker[AsyncSession],
    provider: EmailProvider,
    settings: Settings,
    redis: Redis,
    now: datetime,
) -> list[Check]:
    async with factory() as db:
        checks = await collect(db, redis, settings, now)
        await db.commit()
    for check in checks:
        if check.state != CheckState.OK:
            logger.warning(
                "ops check %s: %s",
                check.key,
                check.state.value,
                extra={"check": check.key, "state": check.state.value, "detail": check.detail},
            )
    alerts = await plan_alerts(redis, checks, now)
    await send_alerts(factory, provider, settings, alerts)
    return checks
