"""Privacy and legal (Milestone 19): policy acceptances and privacy requests.

* ``policy_acceptance``: which version of the Terms of Use and Privacy Policy a user agreed
  to, when, and from where. Append-only (a database trigger refuses updates and deletes),
  so it stays evidence of what each person agreed to.
* ``privacy_request``: a request about personal information (access, correction, deletion,
  a complaint) made from the contact page or by closing an account, worked by staff at
  ``/admin/privacy``. The Australian Privacy Principles expect an answer within 30 days,
  so each request carries ``due_at``.

Platform data, not tenant data: no row-level security. The API only reads a user's own rows
outside the staff routes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class PolicyDocument(StrEnum):
    TERMS = "terms"
    PRIVACY = "privacy"


class PrivacyRequestKind(StrEnum):
    ACCESS = "ACCESS"
    CORRECTION = "CORRECTION"
    DELETION = "DELETION"
    COMPLAINT = "COMPLAINT"
    OTHER = "OTHER"


class PrivacyRequestStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"
    DECLINED = "DECLINED"


class PrivacyRequestSource(StrEnum):
    CONTACT_FORM = "CONTACT_FORM"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"


class PolicyAcceptance(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "policy_acceptance"
    __table_args__ = (
        enum_check("document", PolicyDocument),
        Index("ix_policy_acceptance_user_document", "user_id", "document", "version"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    document: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)


class PrivacyRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "privacy_request"
    __table_args__ = (
        enum_check("kind", PrivacyRequestKind),
        enum_check("status", PrivacyRequestStatus),
        enum_check("source", PrivacyRequestSource),
        Index("ix_privacy_request_status_due", "status", "due_at"),
    )

    # The account it is about, when known (signed in, or the account being closed).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    # Where to answer. For a closed account, the address it had before it was anonymised.
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=PrivacyRequestStatus.OPEN,
        server_default=PrivacyRequestStatus.OPEN,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    # Closing an account (Milestone 29): the personal workspace to delete, and when it was.
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisation.id", ondelete="SET NULL")
    )
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
