"""VesselReady (Milestone 9): a vessel's certificates and a project's safety management system.

Both are tenant-owned. Certificates are what the customer holds (with an optional copy from
their uploads); we record them, we don't issue or check them. A safety management system
(SMS) is the operator's own document: the builder helps write it against the structure in
``sms_structure.json``, and the customer's text is never presented as approved by anyone.
"""

from __future__ import annotations

import uuid
from datetime import date
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedByMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    tenant_fk,
)


class CertificateKind(StrEnum):
    CERTIFICATE_OF_SURVEY = "CERTIFICATE_OF_SURVEY"
    CERTIFICATE_OF_OPERATION = "CERTIFICATE_OF_OPERATION"
    EXEMPTION = "EXEMPTION"
    STATE_REGISTRATION = "STATE_REGISTRATION"
    OTHER = "OTHER"


class VesselCertificate(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "vessel_certificate"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("vessel_id", "vessel", ondelete="CASCADE"),
        tenant_fk("uploaded_document_id", "uploaded_document"),
        enum_check("kind", CertificateKind),
        CheckConstraint(
            "expires_on IS NULL OR issued_on IS NULL OR expires_on >= issued_on",
            name="expires_after_issue",
        ),
        Index("ix_vessel_certificate_vessel_id", "vessel_id"),
    )

    vessel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    number: Mapped[str | None] = mapped_column(String(60))
    issuer: Mapped[str | None] = mapped_column(String(200))
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    uploaded_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str | None] = mapped_column(String(1000))


class SafetyManagementSystem(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base
):
    """One draft SMS per vessel project: the customer's text for each element of the
    structure, keyed by element key. ``structure_hash`` is the structure file the text was
    last saved against."""

    __tablename__ = "safety_management_system"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("project_id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        CheckConstraint("jsonb_typeof(content) = 'object'", name="content_object"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    structure_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
