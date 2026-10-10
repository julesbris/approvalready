"""Identity: users, credentials, external identities, sessions and one-time tokens."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
)


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    SUSPENDED = "SUSPENDED"
    DELETION_REQUESTED = "DELETION_REQUESTED"


class AuthProvider(StrEnum):
    GOOGLE = "GOOGLE"
    MICROSOFT = "MICROSOFT"
    PASSKEY = "PASSKEY"


class TokenPurpose(StrEnum):
    EMAIL_VERIFY = "EMAIL_VERIFY"
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105 - enum label, not a secret
    EMAIL_CHANGE = "EMAIL_CHANGE"  # Milestone 28: carries ``new_email``


class Surface(StrEnum):
    PUBLIC = "public"
    APP = "app"
    PARTNERS = "partners"
    REVIEW = "review"


class AppUser(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "app_user"
    __table_args__ = (enum_check("status", UserStatus),)

    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=UserStatus.ACTIVE, server_default=UserStatus.ACTIVE
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="en-AU")


class PasswordCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Separate from ``app_user`` so SSO/passkey-only users simply have no row."""

    __tablename__ = "password_credential"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AuthIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """External identities (Google/Microsoft OIDC, WebAuthn passkeys). Schema only for now."""

    __tablename__ = "auth_identity"
    __table_args__ = (
        UniqueConstraint("provider", "subject"),
        enum_check("provider", AuthProvider),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    public_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Server-side session behind an opaque cookie token.

    Rotation replaces ``token_hash`` in place and keeps the previous hash valid for a short
    grace period, so concurrent in-flight requests carrying the old cookie still succeed.
    """

    __tablename__ = "auth_session"
    __table_args__ = (
        enum_check("surface", Surface),
        Index(
            "ix_auth_session_previous_token_hash",
            "previous_token_hash",
            unique=True,
            postgresql_where=text("previous_token_hash IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    previous_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    previous_token_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    surface: Mapped[str] = mapped_column(Text, nullable=False, server_default=Surface.APP)
    active_organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisation.id", ondelete="SET NULL")
    )
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    # When this session passed two-step sign-in (an authenticator or recovery code), at
    # sign-in or later by turning two-step sign-in on. Staff routes need it (Milestone 18).
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OneTimeToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "one_time_token"
    __table_args__ = (
        enum_check("purpose", TokenPurpose),
        CheckConstraint(
            "(purpose = 'EMAIL_CHANGE') = (new_email IS NOT NULL)",
            name="new_email_only_for_change",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The address an EMAIL_CHANGE link moves the account to (the link goes there).
    new_email: Mapped[str | None] = mapped_column(CITEXT)


class MfaTotp(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's authenticator app (two-step sign-in, Milestone 18).

    The shared secret is sealed with a key derived from SECRET_KEY (app/core/crypto.py): the
    application has to read it back to check codes, so it can't be hashed. Until
    ``confirmed_at`` is set (the user typed a correct code) it does nothing at sign-in.
    ``last_used_step`` is the time step of the last accepted code, so a code can't be used
    twice.
    """

    __tablename__ = "mfa_totp"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    secret_sealed: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)


class MfaRecoveryCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Single-use codes for signing in without the authenticator app. 80-bit random values,
    so a SHA-256 digest is enough (as for session tokens); shown to the user once."""

    __tablename__ = "mfa_recovery_code"
    __table_args__ = (UniqueConstraint("user_id", "code_hash"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
