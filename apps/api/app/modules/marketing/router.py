"""Marketing routes.

Public (``/v1/marketing``, reached through the web app's ``/api/v1`` proxy):

* ``POST /subscribe``: join the guides email list (a confirmation email follows).
* ``GET|POST /confirm``: what a confirmation link is for / confirm it. Confirming needs a
  button press, because mail scanners open links on their own.
* ``GET|POST /unsubscribe``: what an unsubscribe link is for / leave. ``POST`` with the token
  in the address is the one-click unsubscribe mail providers use (RFC 8058).
* ``GET /cards/{ref}.jpg``: a guide's image card (``?format=square|portrait|wide``), which
  Facebook, Instagram and search engines fetch.

Account (``/v1/auth/newsletter``): the signed-in person's "Send me new guides" choice.

Staff (``/v1/admin/marketing``, ``marketing.manage``): channels, guides and drafts, posts,
the auto-post schedule and the list.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from app.api.deps import (
    AuthDep,
    DbDep,
    LimiterDep,
    MetaDep,
    OrgContext,
    ResourcesDep,
    SettingsDep,
    require_platform_permission,
)
from app.core.config import JobsMode, Settings
from app.core.errors import ApiError, not_found, rate_limited
from app.core.ratelimit import Limit, subject_digest
from app.modules.audit import service as audit
from app.modules.marketing import cards, catalogue, newsletter, service
from app.modules.marketing.meta import MetaClient, configured
from app.modules.marketing.models import (
    Channel,
    MarketingPost,
    NewsletterSubscriber,
    PostStatus,
    SubscriberStatus,
)
from app.modules.marketing.schemas import (
    AccountNewsletterIn,
    AccountNewsletterOut,
    AutopostIn,
    AutopostOut,
    ChannelOut,
    DraftOut,
    GuideDraftsOut,
    GuideOut,
    NewsletterStateOut,
    OverviewOut,
    PostEditIn,
    PostOut,
    PostsIn,
    SignUpIn,
    SignUpOut,
    SubscriberCountsOut,
    SubscriberOut,
    SubscriberSearchIn,
    TokenIn,
)
from app.modules.tenancy.rbac import Perm

public_router = APIRouter(prefix="/v1/marketing", tags=["marketing"])
account_router = APIRouter(prefix="/v1/auth", tags=["marketing"])
admin_router = APIRouter(prefix="/v1/admin/marketing", tags=["admin: marketing"])

Staff = Annotated[OrgContext, Depends(require_platform_permission(Perm.MARKETING_MANAGE))]

SIGN_UPS_PER_IP_PER_HOUR = Limit("newsletter-ip", 10, 3600)
SIGN_UPS_PER_ADDRESS_PER_DAY = Limit("newsletter-address", 3, 86400)
SIGN_UP_MESSAGE = (
    "Thanks. Check your inbox for an email from us and press the button in it to start "
    "getting guides."
)
SUBSCRIBER_LIMIT = 500
CHECK_TIMEOUT_SECONDS = 8.0
MAX_AHEAD = timedelta(days=366)


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- Public ------------------------------------------------------------------------------


@public_router.post("/subscribe", status_code=status.HTTP_202_ACCEPTED, response_model=SignUpOut)
async def subscribe(
    body: SignUpIn,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> SignUpOut:
    ip = meta.ip or "unknown"
    if await limiter.hit(SIGN_UPS_PER_IP_PER_HOUR, ip) > SIGN_UPS_PER_IP_PER_HOUR.max_hits:
        raise rate_limited(await limiter.retry_after(SIGN_UPS_PER_IP_PER_HOUR, ip))
    per_address = SIGN_UPS_PER_ADDRESS_PER_DAY
    if await limiter.hit(per_address, subject_digest(body.email)) > per_address.max_hits:
        return SignUpOut(message=SIGN_UP_MESSAGE)  # quietly: never say who is on the list
    row = await newsletter.sign_up(db, body.email)
    await db.commit()
    if row is not None:
        await resources.email.send(newsletter.confirm_email(settings, row))
    return SignUpOut(message=SIGN_UP_MESSAGE)


async def _from_token(
    db: DbDep, settings: Settings, purpose: str, value: str
) -> NewsletterSubscriber:
    subscriber_id = newsletter.read_token(settings, purpose, value)
    row = await db.get(NewsletterSubscriber, subscriber_id) if subscriber_id else None
    if row is None:
        raise ApiError(
            400,
            "invalid_link",
            "This link doesn't work any more. Sign up again, or contact us if you keep "
            "getting emails.",
        )
    return row


def _state(row: NewsletterSubscriber) -> NewsletterStateOut:
    return NewsletterStateOut(email=row.email, status=SubscriberStatus(row.status))


Token = Annotated[str, Query(min_length=1, max_length=200)]


@public_router.get("/confirm", response_model=NewsletterStateOut)
async def confirm_info(token: Token, db: DbDep, settings: SettingsDep) -> NewsletterStateOut:
    return _state(await _from_token(db, settings, newsletter.CONFIRM, token))


@public_router.post("/confirm", response_model=NewsletterStateOut)
async def confirm(body: TokenIn, db: DbDep, settings: SettingsDep) -> NewsletterStateOut:
    row = await _from_token(db, settings, newsletter.CONFIRM, body.token)
    await newsletter.confirm(db, row.id)
    await db.commit()
    return _state(row)


@public_router.get("/unsubscribe", response_model=NewsletterStateOut)
async def unsubscribe_info(token: Token, db: DbDep, settings: SettingsDep) -> NewsletterStateOut:
    return _state(await _from_token(db, settings, newsletter.UNSUBSCRIBE, token))


@public_router.post("/unsubscribe", response_model=NewsletterStateOut)
async def unsubscribe(token: Token, db: DbDep, settings: SettingsDep) -> NewsletterStateOut:
    """Leave the list. The token is in the address and any body is ignored, as RFC 8058's
    one-click unsubscribe posts ``List-Unsubscribe=One-Click`` there."""
    row = await _from_token(db, settings, newsletter.UNSUBSCRIBE, token)
    await newsletter.unsubscribe(db, row)
    await db.commit()
    return _state(row)


@public_router.get("/cards/{ref}.jpg")
async def guide_card(ref: str, format: cards.CardFormat = cards.CardFormat.SQUARE) -> Response:
    """A guide's image: ``square`` for feed posts, ``portrait`` for Instagram, ``wide`` for
    link previews and search results."""
    image = cards.card(ref, format) if len(ref) <= 120 else None
    if image is None:
        raise not_found("Guide")
    return Response(
        content=image, media_type="image/jpeg", headers={"cache-control": "public, max-age=3600"}
    )


# --- Account -----------------------------------------------------------------------------


@account_router.get("/newsletter", response_model=AccountNewsletterOut)
async def get_account_newsletter(auth: AuthDep, db: DbDep) -> AccountNewsletterOut:
    return AccountNewsletterOut(subscribed=await newsletter.is_subscribed(db, auth.user))


@account_router.put("/newsletter", response_model=AccountNewsletterOut)
async def put_account_newsletter(
    body: AccountNewsletterIn, auth: AuthDep, db: DbDep
) -> AccountNewsletterOut:
    if body.subscribed and auth.user.email_verified_at is None:
        raise ApiError(409, "email_not_verified", "Verify your email address first.")
    await newsletter.set_for_account(db, auth.user, body.subscribed)
    await db.commit()
    return AccountNewsletterOut(subscribed=await newsletter.is_subscribed(db, auth.user))


# --- Staff -------------------------------------------------------------------------------


def _guide_out(guide: catalogue.Guide, last: dict[str, datetime]) -> GuideOut:
    return GuideOut(
        ref=guide.ref,
        title=guide.title,
        summary=guide.summary,
        vertical=guide.vertical,
        product=guide.product,
        link_path=guide.link_path,
        card_path=f"/guide-cards/{guide.ref}.jpg",
        card_alt=cards.alt_text(guide),
        last_posted_at=last.get(guide.ref),
    )


async def _autopost_out(db: DbDep) -> AutopostOut:
    row = await service.autopost_settings(db)
    upcoming = await service.next_guides(db, row.skip_guides)
    next_run = None
    if row.enabled and row.weekdays:
        today = utcnow().astimezone(service.BRISBANE)
        for ahead in range(8):
            day = today + timedelta(days=ahead)
            if day.isoweekday() in row.weekdays and (ahead > 0 or today.time() < row.post_at):
                next_run = day.date()
                break
    return AutopostOut(
        enabled=row.enabled,
        channels=[Channel(c) for c in row.channels],
        weekdays=sorted(row.weekdays),
        post_at=row.post_at,
        skip_guides=row.skip_guides,
        next_guide_ref=upcoming[0].ref if upcoming else None,
        next_run=next_run,
    )


@admin_router.get("/overview", response_model=OverviewOut)
async def overview(_: Staff, db: DbDep, settings: SettingsDep) -> OverviewOut:
    client = MetaClient(settings.model_copy(update={"meta_timeout_seconds": CHECK_TIMEOUT_SECONDS}))
    checks = await asyncio.gather(client.check(Channel.FACEBOOK), client.check(Channel.INSTAGRAM))
    counts = await newsletter.counts(db)
    channels = [
        ChannelOut(channel=c.channel, configured=c.configured, name=c.name, error=c.error)
        for c in checks
    ]
    channels.append(
        ChannelOut(
            channel=Channel.EMAIL,
            configured=True,
            name=f"{counts[SubscriberStatus.SUBSCRIBED]} subscribers",
            error=None,
        )
    )
    return OverviewOut(
        channels=channels,
        autopost=await _autopost_out(db),
        subscribers=SubscriberCountsOut(
            pending=counts[SubscriberStatus.PENDING],
            subscribed=counts[SubscriberStatus.SUBSCRIBED],
            unsubscribed=counts[SubscriberStatus.UNSUBSCRIBED],
        ),
        newsletter_daily_limit=settings.newsletter_daily_limit,
    )


@admin_router.get("/guides", response_model=list[GuideOut])
async def list_guides(_: Staff, db: DbDep) -> list[GuideOut]:
    last = await service.last_posted(db)
    return [_guide_out(g, last) for g in catalogue.catalogue()]


def _guide(ref: str) -> catalogue.Guide:
    guide = catalogue.find(ref)
    if guide is None:
        raise not_found("Guide")
    return guide


@admin_router.get("/guides/{ref}/drafts", response_model=GuideDraftsOut)
async def guide_drafts(ref: str, _: Staff, db: DbDep, settings: SettingsDep) -> GuideDraftsOut:
    guide = _guide(ref)
    return GuideDraftsOut(
        guide=_guide_out(guide, await service.last_posted(db)),
        drafts=[
            DraftOut(channel=d.channel, subject=d.subject, body=d.body)
            for d in catalogue.drafts(guide, settings.web_base_url)
        ],
    )


def _check_post(settings: Settings, channel: Channel, subject: str | None, body: str) -> None:
    if not configured(settings, channel):
        raise ApiError(
            409,
            "channel_not_set_up",
            f"{channel.value.title()} isn't set up yet, so it can't be posted to.",
        )
    if channel == Channel.EMAIL and not subject:
        raise ApiError(422, "subject_required", "An email needs a subject.")
    limit = catalogue.CAPTION_LIMIT.get(channel)
    if limit is not None and len(body) > limit:
        raise ApiError(
            422,
            "too_long",
            f"{channel.value.title()} posts can be at most {limit} characters "
            f"(this one is {len(body)}).",
        )


def _when(value: datetime | None) -> datetime:
    now = utcnow()
    if value is None:
        return now
    if value.tzinfo is None:
        raise ApiError(422, "timezone_required", "Give the time with its time zone.")
    if value > now + MAX_AHEAD:
        raise ApiError(422, "too_far_ahead", "Schedule posts at most a year ahead.")
    return max(value, now)


async def _kick(settings: Settings) -> None:
    """Publish posts due now without waiting for the next scheduled run."""
    if settings.jobs_mode != JobsMode.CELERY:
        return
    from app.worker import celery_app

    # If the queue is down, the scheduled run picks it up within minutes.
    with contextlib.suppress(Exception):
        await asyncio.to_thread(celery_app.send_task, "marketing.publish_due")


@admin_router.post("/posts", response_model=list[PostOut], status_code=status.HTTP_201_CREATED)
async def create_posts(
    body: PostsIn, ctx: Staff, db: DbDep, settings: SettingsDep, meta: MetaDep
) -> list[MarketingPost]:
    guide = _guide(body.guide_ref)
    channels = [p.channel for p in body.posts]
    if len(set(channels)) != len(channels):
        raise ApiError(422, "duplicate_channel", "Each channel can be posted to once.")
    for p in body.posts:
        _check_post(settings, p.channel, p.subject, p.body)
    when = _when(body.scheduled_for)
    posts = [
        await service.create_post(
            db,
            settings,
            guide=guide,
            channel=p.channel,
            body=p.body,
            subject=p.subject,
            scheduled_for=when,
            actor_id=ctx.auth.user.id,
        )
        for p in body.posts
    ]
    await audit.record(
        db,
        "marketing.posts_scheduled",
        actor_user_id=ctx.auth.user.id,
        meta=meta,
        target_type="marketing_guide",
        target_id=guide.ref,
        details={"channels": [c.value for c in channels], "scheduled_for": when.isoformat()},
    )
    await db.commit()
    if when <= utcnow():
        await _kick(settings)
    return posts


@admin_router.get("/posts", response_model=list[PostOut])
async def list_posts(_: Staff, db: DbDep) -> list[MarketingPost]:
    return await service.list_posts(db)


async def _post(db: DbDep, post_id: uuid.UUID) -> MarketingPost:
    post = await db.get(MarketingPost, post_id, with_for_update=True)
    if post is None:
        raise not_found("Post")
    return post


@admin_router.patch("/posts/{post_id}", response_model=PostOut)
async def edit_post(
    post_id: uuid.UUID, body: PostEditIn, ctx: Staff, db: DbDep, settings: SettingsDep
) -> MarketingPost:
    post = await _post(db, post_id)
    if post.status != PostStatus.SCHEDULED:
        raise ApiError(409, "not_scheduled", "Only posts still waiting to go out can be changed.")
    subject = body.subject if body.subject is not None else post.subject
    text = body.body if body.body is not None else post.body
    _check_post(settings, Channel(post.channel), subject, text)
    post.subject = subject if post.channel == Channel.EMAIL else None
    post.body = text
    if body.scheduled_for is not None:
        post.scheduled_for = _when(body.scheduled_for)
    await db.commit()
    return post


@admin_router.post("/posts/{post_id}/cancel", response_model=PostOut)
async def cancel_post(post_id: uuid.UUID, ctx: Staff, db: DbDep, meta: MetaDep) -> MarketingPost:
    post = await _post(db, post_id)
    if not service.cancel(post):
        raise ApiError(409, "not_scheduled", "Only posts still waiting to go out can be cancelled.")
    await audit.record(
        db,
        "marketing.post_cancelled",
        actor_user_id=ctx.auth.user.id,
        meta=meta,
        target_type="marketing_post",
        target_id=post.id,
    )
    await db.commit()
    return post


@admin_router.post("/posts/{post_id}/retry", response_model=PostOut)
async def retry_post(
    post_id: uuid.UUID, ctx: Staff, db: DbDep, settings: SettingsDep, meta: MetaDep
) -> MarketingPost:
    post = await _post(db, post_id)
    if not service.retry(post):
        raise ApiError(409, "not_failed", "Only failed posts can be tried again.")
    await audit.record(
        db,
        "marketing.post_retried",
        actor_user_id=ctx.auth.user.id,
        meta=meta,
        target_type="marketing_post",
        target_id=post.id,
    )
    await db.commit()
    await _kick(settings)
    return post


@admin_router.put("/autopost", response_model=AutopostOut)
async def put_autopost(body: AutopostIn, ctx: Staff, db: DbDep, meta: MetaDep) -> AutopostOut:
    if any(d < 1 or d > 7 for d in body.weekdays):
        raise ApiError(422, "invalid_weekday", "Days are 1 (Monday) to 7 (Sunday).")
    unknown = [r for r in body.skip_guides if catalogue.find(r) is None]
    if unknown:
        raise ApiError(422, "unknown_guide", f"No guide called {unknown[0]}.")
    if body.enabled and (not body.channels or not body.weekdays):
        raise ApiError(
            422, "nothing_to_post", "Pick at least one channel and one day to turn auto-posting on."
        )
    row = await service.autopost_settings(db)
    row.enabled = body.enabled
    row.channels = sorted({c.value for c in body.channels})
    row.weekdays = sorted(set(body.weekdays))
    row.post_at = body.post_at.replace(second=0, microsecond=0, tzinfo=None)
    row.skip_guides = sorted(set(body.skip_guides))
    row.updated_at = utcnow()
    row.updated_by = ctx.auth.user.id
    await audit.record(
        db,
        "marketing.autopost_changed",
        actor_user_id=ctx.auth.user.id,
        meta=meta,
        target_type="marketing_autopost",
        target_id="1",
        details={
            "enabled": row.enabled,
            "channels": row.channels,
            "weekdays": row.weekdays,
            "post_at": row.post_at.isoformat(),
        },
    )
    await db.commit()
    return await _autopost_out(db)


def _subscriber_out(r: NewsletterSubscriber) -> SubscriberOut:
    return SubscriberOut(
        id=r.id,
        email=r.email,
        status=SubscriberStatus(r.status),
        source=r.source,
        has_account=r.user_id is not None,
        subscribed_at=r.subscribed_at,
        unsubscribed_at=r.unsubscribed_at,
        created_at=r.created_at,
    )


async def _subscribers(
    db: DbDep, query: str | None, status_: SubscriberStatus | None
) -> list[SubscriberOut]:
    stmt = select(NewsletterSubscriber).order_by(NewsletterSubscriber.created_at.desc())
    if query:
        stmt = stmt.where(
            NewsletterSubscriber.email.contains(query.strip().lower(), autoescape=True)
        )
    if status_ is not None:
        stmt = stmt.where(NewsletterSubscriber.status == status_)
    return [_subscriber_out(r) for r in (await db.execute(stmt.limit(SUBSCRIBER_LIMIT))).scalars()]


@admin_router.get("/subscribers", response_model=list[SubscriberOut])
async def list_subscribers(_: Staff, db: DbDep) -> list[SubscriberOut]:
    """The newest people on the list."""
    return await _subscribers(db, None, None)


@admin_router.post("/subscribers/search", response_model=list[SubscriberOut])
async def search_subscribers(body: SubscriberSearchIn, _: Staff, db: DbDep) -> list[SubscriberOut]:
    """Posted, so email addresses never end up in a page address or server log."""
    return await _subscribers(db, body.query, body.status)


@admin_router.post("/subscribers/{subscriber_id}/unsubscribe", response_model=SubscriberOut)
async def staff_unsubscribe(
    subscriber_id: uuid.UUID, ctx: Staff, db: DbDep, meta: MetaDep
) -> SubscriberOut:
    """Take someone off the list (they asked by phone or reply)."""
    row = await db.get(NewsletterSubscriber, subscriber_id)
    if row is None:
        raise not_found("Subscriber")
    await newsletter.unsubscribe(db, row)
    await audit.record(
        db,
        "marketing.subscriber_removed",
        actor_user_id=ctx.auth.user.id,
        meta=meta,
        target_type="newsletter_subscriber",
        target_id=row.id,
    )
    await db.commit()
    return _subscriber_out(row)
