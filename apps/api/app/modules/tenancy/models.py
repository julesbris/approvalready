"""Tenancy: organisations, memberships, invitations, roles and permissions."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedByMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
)


class OrganisationKind(StrEnum):
    PERSONAL = "PERSONAL"
    BUSINESS = "BUSINESS"
    PROFESSIONAL_PRACTICE = "PROFESSIONAL_PRACTICE"
    PARTNER = "PARTNER"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"


class OrganisationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MemberStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class RoleScope(StrEnum):
    ORG = "ORG"
    PLATFORM = "PLATFORM"


class Organisation(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, Base):
    __tablename__ = "organisation"
    __table_args__ = (
        enum_check("kind", OrganisationKind),
        enum_check("status", OrganisationStatus),
        CheckConstraint("abn IS NULL OR abn ~ '^[0-9]{11}$'", name="abn_format"),
    )

    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    abn: Mapped[str | None] = mapped_column(String(11))
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=OrganisationStatus.ACTIVE,
        server_default=OrganisationStatus.ACTIVE,
    )


class OrganisationMember(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    """A user's membership of an organisation. Removal is a status change (history kept)."""

    __tablename__ = "organisation_member"
    __table_args__ = (
        UniqueConstraint("organisation_id", "user_id"),
        enum_check("status", MemberStatus),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=MemberStatus.ACTIVE, server_default=MemberStatus.ACTIVE
    )


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Seeded reference data. ``allowed_org_kinds`` is enforced by a trigger on member_role."""

    __tablename__ = "role"
    __table_args__ = (enum_check("scope", RoleScope),)

    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_org_kinds: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permission"

    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


role_permission = Table(
    "role_permission",
    Base.metadata,
    Column(
        "role_id", UUID(as_uuid=True), ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "permission_id",
        UUID(as_uuid=True),
        ForeignKey("permission.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class MemberRole(Base):
    __tablename__ = "member_role"

    organisation_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisation_member.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("role.id", ondelete="RESTRICT"), primary_key=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OrganisationInvitation(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    """Email invitation to join an organisation with a set of roles. Token is single use."""

    __tablename__ = "organisation_invitation"
    __table_args__ = (
        Index(
            "uq_organisation_invitation_open",
            "organisation_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
