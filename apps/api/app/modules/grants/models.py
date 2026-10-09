"""GrantReady (Milestone 10): grant programs, their rounds and a project's matches.

* ``grant_program`` and ``grant_round`` are platform reference data (no tenant), managed by
  staff. A program's eligibility criteria are an ordinary rule set of the ``GRANT``
  vertical (versioned, sourced, published through the publish gate), so a program is just
  the funding body, the money and the rounds around one rule set.
* A round's status and dates must cite a source reference (R12): we never show a date we
  can't point to. ``status`` is what the source says; the dates refine it (an ``OPEN``
  round whose closing date has passed reads as closed).
* ``grant_match`` (tenant, append-only) is one program's result for one assessment of a
  grant project, derived from that rule set's findings. A new assessment means new rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedByMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    tenant_fk,
)
from app.modules.regulatory.models import JURISDICTION_PATTERN
from app.modules.rules.models import KEY_PATTERN, Confidence


class ProgramStatus(StrEnum):
    ACTIVE = "ACTIVE"  # matched in assessments
    RETIRED = "RETIRED"  # kept for history, no longer matched


class RoundStatus(StrEnum):
    """What the source says about taking applications."""

    UPCOMING = "UPCOMING"
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class MatchStatus(StrEnum):
    STRONG_MATCH = "STRONG_MATCH"  # every criterion we check is met, at least likely
    POSSIBLE_MATCH = "POSSIBLE_MATCH"  # every criterion met, but a source needs review
    NEEDS_INFORMATION = "NEEDS_INFORMATION"  # nothing unmet, something unanswered
    NOT_ELIGIBLE = "NOT_ELIGIBLE"  # a criterion (or who can apply) is not met


class GrantProgram(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "grant_program"
    __table_args__ = (
        UniqueConstraint("key"),
        UniqueConstraint("rule_set_id"),
        CheckConstraint(f"key ~ '{KEY_PATTERN}'", name="key_format"),
        CheckConstraint(f"jurisdiction ~ '{JURISDICTION_PATTERN}'", name="jurisdiction_format"),
        CheckConstraint("min_amount_cents IS NULL OR min_amount_cents >= 0", name="min_amount"),
        CheckConstraint(
            "max_amount_cents IS NULL OR min_amount_cents IS NULL "
            "OR max_amount_cents >= min_amount_cents",
            name="amount_range",
        ),
        enum_check("status", ProgramStatus),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    # Who runs the program (e.g. Austrade), from the source register.
    administrator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_organisation.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    # The eligibility criteria: a GRANT rule set, one per program.
    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_set.id", ondelete="RESTRICT"), nullable=False
    )
    # Plain words, e.g. "$20,000 to $80,000 a year; you match the grant with your own money".
    funding_summary: Mapped[str | None] = mapped_column(String(500))
    min_amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    max_amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ProgramStatus.ACTIVE, server_default="ACTIVE"
    )


class GrantRound(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "grant_round"
    __table_args__ = (
        UniqueConstraint("program_id", "title"),
        enum_check("status", RoundStatus),
        CheckConstraint(
            "closes_on IS NULL OR opens_on IS NULL OR closes_on >= opens_on",
            name="closes_after_opens",
        ),
        Index("ix_grant_round_program_id", "program_id"),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grant_program.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    opens_on: Mapped[date | None] = mapped_column(Date)
    closes_on: Mapped[date | None] = mapped_column(Date)
    # Anything the dates alone don't say, e.g. "5pm AEDT" or "tier 2 closed early".
    dates_note: Mapped[str | None] = mapped_column(String(500))
    # Where the status and dates come from (R12: dates must cite a source).
    source_reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_reference.id", ondelete="RESTRICT"),
        nullable=False,
    )


class GrantMatch(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "grant_match"
    __table_args__ = (
        UniqueConstraint("assessment_id", "program_id"),
        tenant_fk("assessment_id", "assessment", ondelete="CASCADE"),
        enum_check("status", MatchStatus),
        enum_check("confidence", Confidence),
        Index("ix_grant_match_assessment_id", "assessment_id"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grant_program.id", ondelete="RESTRICT"), nullable=False
    )
    # The round the customer was shown when the assessment ran (open, else upcoming, else
    # the latest); the screens show the program's rounds as they are now.
    round_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grant_round.id", ondelete="SET NULL")
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    # Each criterion: finding id, rule title, result ("MATCH" met, "NO_MATCH" not met,
    # "UNKNOWN" unanswered), or the program's "who can apply" scope when that decided it.
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    missing_facts: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
