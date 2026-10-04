"""Row-level security binding: which organisation a database session acts for.

Tenant-owned tables carry ``organisation_id`` and a policy that only exposes rows whose
``organisation_id`` equals the transaction-local setting ``app.current_org``. With no
organisation bound the setting is empty and those tables look empty: a forgotten tenant
filter fails closed instead of leaking another organisation's rows.

This is defence in depth. Authorisation still happens in the API (``app/api/deps.py``);
RLS catches the query that forgot its ``WHERE organisation_id = ...``.

The setting is transaction-local (``set_config(..., true)``), so it can never leak to the
next user of a pooled connection. Request handlers commit more than once (the session
dependency commits session housekeeping before the handler runs), so the binding lives on
the ORM session and is re-applied at the start of every transaction.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

SETTING = "app.current_org"
_INFO_KEY = "tenant_organisation_id"
_SET_SQL = "SELECT set_config('app.current_org', %(org)s, true)"


async def bind_tenant(db: AsyncSession, organisation_id: uuid.UUID) -> None:
    """Act for ``organisation_id`` in this session, now and in every later transaction."""
    db.sync_session.info[_INFO_KEY] = str(organisation_id)
    # Applies to the transaction that is already open (or opens one, firing the hook).
    await db.execute(
        text("SELECT set_config('app.current_org', :org, true)"), {"org": str(organisation_id)}
    )


def bound_tenant(db: AsyncSession) -> uuid.UUID | None:
    value = db.sync_session.info.get(_INFO_KEY)
    return uuid.UUID(value) if value else None


@event.listens_for(Session, "after_begin")
def _apply_tenant(session: Session, _tx: SessionTransaction, connection: Connection) -> Any:
    org = session.info.get(_INFO_KEY)
    if org:
        connection.exec_driver_sql(_SET_SQL, {"org": org})
