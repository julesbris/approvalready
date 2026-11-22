"""Staff notes on an account: what support knows about a customer, and every time staff
called or emailed them.

Platform data (no row-level security): only staff read or write it, through
``/v1/admin/accounts``. The person's notes are deleted when they close their account; the
audit log keeps that a note was written or an email sent, never what it said.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, enum_check


class NoteKind(StrEnum):
    NOTE = "NOTE"  # something worth knowing next time
    CALL = "CALL"  # a phone call and how it went
    EMAIL = "EMAIL"  # an email staff sent from the account page (the copy is kept here)


class StaffNote(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "staff_note"
    __table_args__ = (
        enum_check("kind", NoteKind),
        Index("ix_staff_note_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Email subject (EMAIL only).
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # The project it was about, by its reference code (for example from Stuck projects).
    project_reference: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
