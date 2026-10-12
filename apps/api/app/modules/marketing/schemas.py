from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.marketing.models import Channel, PostOrigin, PostStatus, SubscriberStatus


class GuideOut(BaseModel):
    ref: str
    title: str
    summary: str
    vertical: str
    product: str
    link_path: str
    card_path: str
    # What the card shows, for the post's alt text.
    card_alt: str
    last_posted_at: datetime | None


class DraftOut(BaseModel):
    channel: Channel
    subject: str | None
    body: str


class GuideDraftsOut(BaseModel):
    guide: GuideOut
    drafts: list[DraftOut]


class PostIn(BaseModel):
    channel: Channel
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)


class PostsIn(BaseModel):
    guide_ref: str = Field(min_length=1, max_length=120)
    posts: list[PostIn] = Field(min_length=1, max_length=3)
    # Omitted: post now.
    scheduled_for: datetime | None = None


class PostEditIn(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=20_000)
    scheduled_for: datetime | None = None


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    guide_ref: str
    guide_title: str
    channel: Channel
    origin: PostOrigin
    status: PostStatus
    subject: str | None
    body: str
    link_url: str
    scheduled_for: datetime
    attempts: int
    error: str | None
    posted_at: datetime | None
    external_url: str | None
    sent_count: int
    created_at: datetime


class ChannelOut(BaseModel):
    channel: Channel
    configured: bool
    # The Facebook Page or Instagram account it posts as, when it could be checked.
    name: str | None
    error: str | None


class AutopostIn(BaseModel):
    enabled: bool
    channels: list[Channel] = Field(max_length=3)
    weekdays: list[int] = Field(max_length=7)
    post_at: time
    skip_guides: list[str] = Field(default_factory=list, max_length=200)


class AutopostOut(BaseModel):
    enabled: bool
    channels: list[Channel]
    weekdays: list[int]
    post_at: time
    skip_guides: list[str]
    next_guide_ref: str | None
    next_run: date | None


class SubscriberCountsOut(BaseModel):
    pending: int
    subscribed: int
    unsubscribed: int


class SubscriberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    status: SubscriberStatus
    source: str
    has_account: bool
    subscribed_at: datetime | None
    unsubscribed_at: datetime | None
    created_at: datetime


class SubscriberSearchIn(BaseModel):
    query: str = Field(default="", max_length=320)
    status: SubscriberStatus | None = None


class OverviewOut(BaseModel):
    channels: list[ChannelOut]
    autopost: AutopostOut
    subscribers: SubscriberCountsOut
    newsletter_daily_limit: int


class SignUpIn(BaseModel):
    email: EmailStr


class SignUpOut(BaseModel):
    message: str


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class NewsletterStateOut(BaseModel):
    # What a confirm or unsubscribe link is for, shown before the person presses the button.
    email: str
    status: SubscriberStatus


class AccountNewsletterIn(BaseModel):
    subscribed: bool


class AccountNewsletterOut(BaseModel):
    subscribed: bool
