"""Writing and verifying audit events.

``record`` adds the event to the caller's transaction, so the audit row commits or rolls
back together with the change it describes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_var
from app.db.base import uuid7
from app.modules.audit.models import AuditEvent

# Any constant works; it only has to be shared by every writer of the chain.
_CHAIN_LOCK_KEY = 0x41524155  # "ARAU"


@dataclass(frozen=True)
class RequestMeta:
    ip: str | None = None
    user_agent: str | None = None


def _canonical(event: AuditEvent) -> bytes:
    payload = {
        "id": str(event.id),
        "occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "organisation_id": str(event.organisation_id) if event.organisation_id else None,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "ip": event.ip,
        "user_agent": event.user_agent,
        "request_id": event.request_id,
        "details": event.details,
        "prev_hash": event.prev_hash.hex() if event.prev_hash else None,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def compute_hash(event: AuditEvent) -> bytes:
    return hashlib.sha256(_canonical(event)).digest()


async def record(
    db: AsyncSession,
    action: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    organisation_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    meta: RequestMeta | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    # Serialise chain writers for the rest of this transaction (released at commit/rollback).
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    prev_hash = (
        await db.execute(select(AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1))
    ).scalar_one_or_none()
    request_id = request_id_var.get()
    event = AuditEvent(
        id=uuid7(),
        occurred_at=datetime.now(UTC),
        actor_user_id=actor_user_id,
        organisation_id=organisation_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        ip=meta.ip if meta else None,
        user_agent=meta.user_agent[:512] if meta and meta.user_agent else None,
        request_id=request_id if request_id and request_id != "-" else None,
        details=json.loads(json.dumps(details or {}, default=str)),
        prev_hash=prev_hash,
    )
    event.hash = compute_hash(event)
    db.add(event)
    await db.flush()
    return event


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    checked: int
    first_bad_seq: int | None = None


async def verify_chain(db: AsyncSession, batch_size: int = 1000) -> ChainVerification:
    prev: bytes | None = None
    checked = 0
    last_seq = 0
    while True:
        rows = (
            (
                await db.execute(
                    select(AuditEvent)
                    .where(AuditEvent.seq > last_seq)
                    .order_by(AuditEvent.seq)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return ChainVerification(ok=True, checked=checked)
        for event in rows:
            if event.prev_hash != prev or compute_hash(event) != event.hash:
                return ChainVerification(ok=False, checked=checked, first_bad_seq=event.seq)
            prev = event.hash
            checked += 1
            last_seq = event.seq
