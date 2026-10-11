"""Guide posts: scheduling, publishing to Facebook, Instagram and the email list, and the
auto-post schedule.

Every couple of minutes the worker (``marketing.publish_due``, Celery beat):

1. makes today's auto posts when the schedule is on, today is one of its days and its time
   has passed: the next guide in the rotation (the one posted least recently, never-posted
   first) on each chosen channel that is set up. One post per channel a day at most
   (``uq_marketing_post_auto_day``), however often the job runs;
2. picks up posts that are due and publishes them. A Facebook or Instagram failure is
   tried again 15 minutes later, up to ``MAX_ATTEMPTS`` times, unless retrying can't help
   (an expired token): then the post is marked failed with Facebook's reason. Emails go out
   in batches, remembering the last subscriber sent to, so a restart carries on where it
   stopped and nobody gets the same guide twice. At most ``NEWSLETTER_DAILY_LIMIT`` guide
   emails go out in any 24 hours; the rest wait an hour and carry on;
3. deletes sign-ups nobody confirmed.

A post being published is claimed with ``FOR UPDATE SKIP LOCKED``, so two workers never
publish the same post.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.email import EmailProvider
from app.modules.marketing import catalogue, newsletter
from app.modules.marketing.catalogue import Guide
from app.modules.marketing.meta import MetaClient, MetaError, configured
from app.modules.marketing.models import (
    Channel,
    MarketingAutopost,
    MarketingPost,
    PostOrigin,
    PostStatus,
)
from app.modules.outbox.models import OutboxEmail

logger = logging.getLogger(__name__)

Factory = async_sessionmaker[AsyncSession]

BRISBANE = ZoneInfo("Australia/Brisbane")
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=15)
LIMIT_WAIT = timedelta(hours=1)
# A post still "publishing" this long after its last change was interrupted (a restart).
STUCK_AFTER = timedelta(minutes=30)
EMAIL_BATCH = 100
CLAIM_BATCH = 20
ERROR_LIMIT = 1000


def utcnow() -> datetime:
    return datetime.now(UTC)


def card_url(settings: Settings, ref: str) -> str:
    """Where Facebook and Instagram fetch the guide's image card (through the web app)."""
    return f"{settings.web_base_url.rstrip('/')}/guide-cards/{ref}.jpg"


def _error(message: str) -> str:
    return message[:ERROR_LIMIT]


# --- Posts -----------------------------------------------------------------------------


async def create_post(
    db: AsyncSession,
    settings: Settings,
    *,
    guide: Guide,
    channel: Channel,
    body: str,
    subject: str | None,
    scheduled_for: datetime,
    actor_id: uuid.UUID | None,
) -> MarketingPost:
    post = MarketingPost(
        guide_ref=guide.ref,
        guide_title=guide.title,
        channel=channel,
        origin=PostOrigin.MANUAL,
        status=PostStatus.SCHEDULED,
        subject=subject if channel == Channel.EMAIL else None,
        body=body,
        link_url=catalogue.link(settings.web_base_url, guide, channel),
        scheduled_for=scheduled_for,
        created_by=actor_id,
    )
    db.add(post)
    await db.flush()
    return post


async def list_posts(db: AsyncSession, limit: int = 200) -> list[MarketingPost]:
    """Scheduled posts first (soonest first), then everything else, newest first."""
    upcoming = (
        await db.execute(
            select(MarketingPost)
            .where(MarketingPost.status.in_((PostStatus.SCHEDULED, PostStatus.PUBLISHING)))
            .order_by(MarketingPost.scheduled_for, MarketingPost.id)
        )
    ).scalars()
    history = (
        await db.execute(
            select(MarketingPost)
            .where(MarketingPost.status.not_in((PostStatus.SCHEDULED, PostStatus.PUBLISHING)))
            .order_by(MarketingPost.scheduled_for.desc(), MarketingPost.id.desc())
            .limit(limit)
        )
    ).scalars()
    return [*upcoming, *history]


def cancel(post: MarketingPost) -> bool:
    if post.status != PostStatus.SCHEDULED:
        return False
    post.status = PostStatus.CANCELLED
    return True


def retry(post: MarketingPost, now: datetime | None = None) -> bool:
    """Try a failed post again now. An email carries on from the last subscriber sent to."""
    if post.status != PostStatus.FAILED:
        return False
    post.status = PostStatus.SCHEDULED
    post.scheduled_for = now or utcnow()
    post.attempts = 0
    post.error = None
    return True


# --- Auto-post ---------------------------------------------------------------------------


async def autopost_settings(db: AsyncSession) -> MarketingAutopost:
    row = await db.get(MarketingAutopost, 1)
    if row is None:  # the migration adds it; this only guards a hand-deleted row
        row = MarketingAutopost(id=1, enabled=False, channels=[], weekdays=[2, 5], skip_guides=[])
        db.add(row)
        await db.flush()
    return row


async def last_posted(db: AsyncSession) -> dict[str, datetime]:
    """When each guide was last posted or is due to be, on any channel."""
    when = func.max(func.coalesce(MarketingPost.posted_at, MarketingPost.scheduled_for))
    rows = await db.execute(
        select(MarketingPost.guide_ref, when)
        .where(
            MarketingPost.status.in_(
                (PostStatus.POSTED, PostStatus.SCHEDULED, PostStatus.PUBLISHING)
            )
        )
        .group_by(MarketingPost.guide_ref)
    )
    return {ref: at for ref, at in rows.all()}


async def next_guides(db: AsyncSession, skip: list[str], count: int = 1) -> list[Guide]:
    """The rotation: guides never posted first (in catalogue order), then the ones posted
    longest ago."""
    last = await last_posted(db)
    never = datetime(1970, 1, 1, tzinfo=UTC)
    candidates = [g for g in catalogue.catalogue() if g.ref not in set(skip)]
    order = {g.ref: i for i, g in enumerate(candidates)}
    candidates.sort(key=lambda g: (last.get(g.ref, never), order[g.ref]))
    return candidates[:count]


def due_today(row: MarketingAutopost, now: datetime) -> date | None:
    """Brisbane's date today if the schedule should have posted by now, else ``None``."""
    local = now.astimezone(BRISBANE)
    if not row.enabled or local.isoweekday() not in row.weekdays or local.time() < row.post_at:
        return None
    return local.date()


async def run_autopost(factory: Factory, settings: Settings, now: datetime) -> int:
    """Make today's auto posts if they are due. Returns how many were made."""
    async with factory() as db:
        row = await autopost_settings(db)
        day = due_today(row, now)
        channels = [Channel(c) for c in row.channels if configured(settings, Channel(c))]
        if day is None or not channels:
            await db.commit()
            return 0
        made_today = set(
            (
                await db.execute(select(MarketingPost.channel).where(MarketingPost.auto_day == day))
            ).scalars()
        )
        todo = [c for c in channels if c.value not in made_today]
        if not todo:
            await db.commit()
            return 0
        picked = await next_guides(db, row.skip_guides)
        if not picked:
            await db.commit()
            return 0
        guide = picked[0]
        made = 0
        for channel in todo:
            draft = catalogue.draft_for(guide, channel, settings.web_base_url)
            result = await db.execute(
                insert(MarketingPost)
                .values(
                    id=uuid.uuid4(),
                    guide_ref=guide.ref,
                    guide_title=guide.title,
                    channel=channel,
                    origin=PostOrigin.AUTO,
                    auto_day=day,
                    status=PostStatus.SCHEDULED,
                    subject=draft.subject,
                    body=draft.body,
                    link_url=catalogue.link(settings.web_base_url, guide, channel),
                    scheduled_for=now,
                )
                .on_conflict_do_nothing(index_elements=["channel", "auto_day"])
            )
            made += int(result.rowcount or 0)  # type: ignore[attr-defined]
        await db.commit()
        return made


# --- Publishing ----------------------------------------------------------------------------


async def claim_due(factory: Factory, now: datetime) -> list[uuid.UUID]:
    async with factory() as db:
        ids = list(
            (
                await db.execute(
                    text(
                        """
                        UPDATE marketing_post SET status = 'PUBLISHING',
                               attempts = attempts + 1, updated_at = now()
                         WHERE id IN (
                               SELECT id FROM marketing_post
                                WHERE status = 'SCHEDULED' AND scheduled_for <= :now
                                ORDER BY scheduled_for, id
                                LIMIT :n
                                FOR UPDATE SKIP LOCKED)
                        RETURNING id
                        """
                    ),
                    {"now": now, "n": CLAIM_BATCH},
                )
            ).scalars()
        )
        await db.commit()
        return ids


async def recover_stuck(factory: Factory, now: datetime) -> int:
    """Posts left "publishing" by a restart: emails carry on from where they stopped; a
    Facebook or Instagram post may or may not have gone out, so a person checks."""
    cutoff = now - STUCK_AFTER
    async with factory() as db:
        emails = await db.execute(
            update(MarketingPost)
            .where(
                MarketingPost.status == PostStatus.PUBLISHING,
                MarketingPost.updated_at < cutoff,
                MarketingPost.channel == Channel.EMAIL,
            )
            .values(status=PostStatus.SCHEDULED, scheduled_for=now)
        )
        social = await db.execute(
            update(MarketingPost)
            .where(
                MarketingPost.status == PostStatus.PUBLISHING,
                MarketingPost.updated_at < cutoff,
                MarketingPost.channel != Channel.EMAIL,
            )
            .values(
                status=PostStatus.FAILED,
                error="Interrupted while posting. Check the Page before trying again, in "
                "case it went out.",
            )
        )
        await db.commit()
        return int(emails.rowcount or 0) + int(social.rowcount or 0)  # type: ignore[attr-defined]


async def _publish_social(
    factory: Factory, settings: Settings, meta: MetaClient, post_id: uuid.UUID, now: datetime
) -> str:
    async with factory() as db:
        post = await db.get(MarketingPost, post_id)
        if post is None or post.status != PostStatus.PUBLISHING:
            return "skipped"
        channel = Channel(post.channel)
        if not configured(settings, channel):
            post.status = PostStatus.FAILED
            post.error = (
                f"{channel.value.title()} isn't set up yet: add its settings to the server "
                "and try again."
            )
            await db.commit()
            return post.status
        caption, ref, attempts = post.body, post.guide_ref, post.attempts
        await db.commit()
    try:
        published = await meta.publish(channel, caption, card_url(settings, ref))
    except MetaError as exc:
        async with factory() as db:
            post = await db.get(MarketingPost, post_id)
            if post is None:
                return "skipped"
            post.error = _error(str(exc))
            if exc.permanent or attempts >= MAX_ATTEMPTS:
                post.status = PostStatus.FAILED
            else:
                post.status = PostStatus.SCHEDULED
                post.scheduled_for = now + RETRY_AFTER
            await db.commit()
            logger.warning(
                "marketing post failed",
                extra={"channel": channel.value, "post_id": str(post_id), "status": post.status},
            )
            return post.status
    async with factory() as db:
        post = await db.get(MarketingPost, post_id)
        if post is None:
            return "skipped"
        post.status = PostStatus.POSTED
        post.posted_at = utcnow()
        post.external_id = published.external_id[:200]
        post.external_url = (published.url or "")[:2000] or None
        post.error = None
        await db.commit()
        return post.status


async def sent_last_day(db: AsyncSession, now: datetime) -> int:
    """Guide emails queued in the last 24 hours (the outbox keeps every email's kind)."""
    return int(
        (
            await db.execute(
                select(func.count()).where(
                    OutboxEmail.kind == "marketing.guide",
                    OutboxEmail.created_at > now - timedelta(days=1),
                )
            )
        ).scalar_one()
    )


async def _publish_email(
    factory: Factory, settings: Settings, email: EmailProvider, post_id: uuid.UUID, now: datetime
) -> str:
    async with factory() as db:
        budget = settings.newsletter_daily_limit - await sent_last_day(db, now)
    while True:
        async with factory() as db:
            post = await db.get(MarketingPost, post_id)
            if post is None or post.status != PostStatus.PUBLISHING:
                return "skipped"
            if budget <= 0:
                post.status = PostStatus.SCHEDULED
                post.scheduled_for = now + LIMIT_WAIT
                post.error = (
                    f"Paused at the daily limit of {settings.newsletter_daily_limit} guide "
                    "emails; it carries on automatically."
                )
                await db.commit()
                return post.status
            batch = await newsletter.recipients(
                db, post.last_subscriber_id, min(EMAIL_BATCH, budget)
            )
            if not batch:
                post.status = PostStatus.POSTED
                post.posted_at = utcnow()
                post.error = None
                await db.commit()
                return post.status
            subject, body = post.subject or post.guide_title, post.body
            sent_to: uuid.UUID | None = None
            failure: Exception | None = None
            sent = 0
            for subscriber_id, address in batch:
                try:
                    await email.send(
                        newsletter.guide_email(settings, address, subscriber_id, subject, body)
                    )
                except Exception as exc:
                    failure = exc
                    break
                sent_to = subscriber_id
                sent += 1
            if sent_to is not None:
                post.last_subscriber_id = sent_to
                post.sent_count += sent
            budget -= sent
            post.updated_at = utcnow()  # not stuck: still going
            if failure is not None:
                logger.warning("guide email failed", extra={"post_id": str(post_id)})
                post.error = _error(f"Sending stopped: {type(failure).__name__}. Retrying.")
                if post.attempts >= MAX_ATTEMPTS * 2:
                    post.status = PostStatus.FAILED
                else:
                    post.status = PostStatus.SCHEDULED
                    post.scheduled_for = now + RETRY_AFTER
                await db.commit()
                return post.status
            await db.commit()


async def publish(
    factory: Factory,
    settings: Settings,
    email: EmailProvider,
    meta: MetaClient,
    post_id: uuid.UUID,
    now: datetime,
) -> str:
    async with factory() as db:
        channel = (
            await db.execute(select(MarketingPost.channel).where(MarketingPost.id == post_id))
        ).scalar_one_or_none()
    if channel is None:
        return "skipped"
    if channel == Channel.EMAIL:
        return await _publish_email(factory, settings, email, post_id, now)
    return await _publish_social(factory, settings, meta, post_id, now)


async def publish_due(
    factory: Factory,
    email: EmailProvider,
    settings: Settings,
    *,
    meta: MetaClient | None = None,
    now: datetime | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> int:
    """The worker's job: auto posts, then everything due. Returns how many were posted."""
    now = now or clock()
    meta = meta or MetaClient(settings)
    await run_autopost(factory, settings, now)
    await recover_stuck(factory, now)
    posted = 0
    for post_id in await claim_due(factory, now):
        try:
            status = await publish(factory, settings, email, meta, post_id, now)
        except Exception:
            # Left "publishing": recover_stuck picks it up later.
            logger.exception("marketing post crashed", extra={"post_id": str(post_id)})
            continue
        posted += int(status == PostStatus.POSTED)
    async with factory() as db:
        await newsletter.purge_unconfirmed(db, now)
        await db.commit()
    return posted
