"""Marketing: the guides email list and guide posts to Facebook, Instagram and the list.

Platform data, not tenant data (no row-level security): subscribers are people who asked for
our guides, and posts are ApprovalReady's own public content. Only staff with
``marketing.manage`` see either.

* ``newsletter_subscriber``: one row per address. People join from the public sign-up form
  (they confirm by email first) or from their account (already a verified address). Leaving
  is one click from any email. A subscriber linked to an account is sent to the account's
  current address.
* ``marketing_post``: one guide on one channel, scheduled or sent, with what happened. Staff
  write them from the admin page, or the auto-post schedule makes them.
* ``marketing_autopost``: the single row of auto-post settings (switched off until staff turn
  it on).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedByMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class SubscriberStatus(StrEnum):
    PENDING = "PENDING"  # signed up on the form, hasn't confirmed by email yet
    SUBSCRIBED = "SUBSCRIBED"
    UNSUBSCRIBED = "UNSUBSCRIBED"


class SubscriberSource(StrEnum):
    FORM = "FORM"  # the public sign-up form (confirmed by email)
    ACCOUNT = "ACCOUNT"  # ticked in their account (verified address)


class Channel(StrEnum):
    FACEBOOK = "FACEBOOK"
    INSTAGRAM = "INSTAGRAM"
    EMAIL = "EMAIL"  # the guides email list


class PostStatus(StrEnum):
    SCHEDULED = "SCHEDULED"  # waiting for its time
    PUBLISHING = "PUBLISHING"  # being posted or sent now
    POSTED = "POSTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PostOrigin(StrEnum):
    MANUAL = "MANUAL"  # written by staff
    AUTO = "AUTO"  # made by the auto-post schedule


class NewsletterSubscriber(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "newsletter_subscriber"
    __table_args__ = (
        enum_check("status", SubscriberStatus),
        enum_check("source", SubscriberSource),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        Index("uq_newsletter_subscriber_email", "email", unique=True),
        Index(
            "uq_newsletter_subscriber_user_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index("ix_newsletter_subscriber_status", "status", "id"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confirm_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketingPost(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "marketing_post"
    __table_args__ = (
        enum_check("channel", Channel),
        enum_check("status", PostStatus),
        enum_check("origin", PostOrigin),
        CheckConstraint("channel <> 'EMAIL' OR subject IS NOT NULL", name="email_has_subject"),
        CheckConstraint("(origin = 'AUTO') = (auto_day IS NOT NULL)", name="auto_has_day"),
        Index(
            "ix_marketing_post_due", "scheduled_for", postgresql_where=text("status = 'SCHEDULED'")
        ),
        Index("ix_marketing_post_created", "created_at"),
        Index("ix_marketing_post_guide", "guide_ref", "posted_at"),
        # The schedule makes one post per channel a day, however often the job runs.
        Index("uq_marketing_post_auto_day", "channel", "auto_day", unique=True),
    )

    guide_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    guide_title: Mapped[str] = mapped_column(String(300), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="MANUAL")
    auto_day: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="SCHEDULED")
    # Email only: the subject line.
    subject: Mapped[str | None] = mapped_column(String(200))
    # The caption (Facebook, Instagram) or the email's text.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(String(1000))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Facebook or Instagram's id for the post, and its address.
    external_id: Mapped[str | None] = mapped_column(String(200))
    external_url: Mapped[str | None] = mapped_column(String(2000))
    # Email: subscribers sent to so far, and the last one (sending resumes after it).
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_subscriber_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class MarketingAutopost(Base):
    __tablename__ = "marketing_autopost"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    channels: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    # ISO weekdays, 1 Monday to 7 Sunday.
    weekdays: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, server_default="{2,5}"
    )
    # Brisbane time.
    post_at: Mapped[time] = mapped_column(Time, nullable=False, server_default="09:00")
    # Guides the schedule never picks (staff can still post them by hand).
    skip_guides: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
