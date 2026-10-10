"""Agreement to the Terms of Use and Privacy Policy (Milestone 19).

Kept apart from ``service`` so the identity module (registration, the session) can use it
without an import cycle.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.privacy import policies
from app.modules.privacy.models import PolicyAcceptance, PolicyDocument


async def outstanding(db: AsyncSession, user_id: uuid.UUID) -> list[policies.Policy]:
    """The current policies this user hasn't agreed to."""
    accepted = {
        (row.document, row.version)
        for row in (
            await db.execute(
                select(PolicyAcceptance.document, PolicyAcceptance.version).where(
                    PolicyAcceptance.user_id == user_id
                )
            )
        ).all()
    }
    return [p for p in policies.current() if (p.document, p.version) not in accepted]


async def record_acceptance(
    db: AsyncSession,
    user_id: uuid.UUID,
    documents: Iterable[PolicyDocument],
    meta: RequestMeta,
) -> list[policies.Policy]:
    """Record agreement to the current version of each document (once per version)."""
    wanted = set(documents)
    due = [p for p in await outstanding(db, user_id) if p.document in wanted]
    for policy in due:
        db.add(
            PolicyAcceptance(
                user_id=user_id,
                document=policy.document,
                version=policy.version,
                ip=meta.ip,
                user_agent=meta.user_agent[:512] if meta.user_agent else None,
            )
        )
    if due:
        await db.flush()
        await audit.record(
            db,
            "privacy.policies.accepted",
            actor_user_id=user_id,
            meta=meta,
            target_type="app_user",
            target_id=user_id,
            details={p.document.value: p.version for p in due},
        )
    return due
