"""Marketing: the guides email list, guide posts to Facebook, Instagram and the list, and
the auto-post schedule."""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.guidance.guides import guides as approval_guides
from app.modules.marketing import catalogue, newsletter, service
from app.modules.marketing.cards import render
from app.modules.marketing.meta import MetaClient, MetaError
from app.modules.marketing.models import (
    Channel,
    MarketingAutopost,
    MarketingPost,
    NewsletterSubscriber,
)
from tests.conftest import make_settings
from tests.harness import PASSWORD, ApiHarness, User, platform_user, unique_email

ADMIN = "/v1/admin/marketing"
META = {
    "meta_page_id": "1234567890",
    "meta_instagram_account_id": "17841400000000000",
    "meta_page_access_token": "EAAB-test-token",
}

# --- Guides, drafts and cards ------------------------------------------------------------


def test_every_guide_can_be_posted() -> None:
    refs = [g.ref for g in catalogue.catalogue()]
    assert len(refs) == len(set(refs))
    assert len(refs) == 4 + len(approval_guides())
    assert catalogue.find("guide-cairns-subdivision") is not None
    for guide in catalogue.catalogue():
        for draft in catalogue.drafts(guide, "https://app.approvalready.au"):
            limit = catalogue.CAPTION_LIMIT.get(draft.channel)
            if limit is not None:
                assert len(draft.body) <= limit, (guide.ref, draft.channel)
            assert guide.title in draft.body


def test_drafts_link_to_the_guide_with_campaign_tags() -> None:
    page = catalogue.find("guide-importing-goods-into-australia")
    assert page is not None
    fb = catalogue.draft_for(page, Channel.FACEBOOK, "https://app.approvalready.au")
    assert (
        "https://app.approvalready.au/guides/importing-goods-into-australia?utm_source=facebook"
        "&utm_medium=social&utm_campaign=guides&utm_content=guide-importing-goods-into-australia"
    ) in fb.body
    ig = catalogue.draft_for(page, Channel.INSTAGRAM, "https://app.approvalready.au")
    assert "http" not in ig.body  # not clickable on Instagram
    assert "Link in bio, or visit approvalready.au" in ig.body
    approval = catalogue.find("approval-company-registration")
    assert approval is not None
    email = catalogue.draft_for(approval, Channel.EMAIL, "https://app.approvalready.au")
    assert email.subject == "Guide: Register a company (Pty Ltd) with ASIC"
    assert "Step by step:" in email.body and "Who to contact:" in email.body
    assert "/projects/new?vertical=BUSINESS&utm_source=email&utm_medium=email" in email.body
    assert "check the official page before you apply" in email.body


@pytest.mark.parametrize(
    "ref", ["guide-cairns-subdivision", "approval-education-care-service-approval"]
)
def test_cards_are_square_jpegs(ref: str) -> None:
    guide = catalogue.find(ref)
    assert guide is not None
    image = Image.open(io.BytesIO(render(guide)))
    assert image.format == "JPEG"
    assert image.size == (1080, 1080)


def test_links_are_signed_per_purpose() -> None:
    settings = make_settings()
    sid = uuid.uuid4()
    t = newsletter.token(settings, newsletter.UNSUBSCRIBE, sid)
    assert newsletter.read_token(settings, newsletter.UNSUBSCRIBE, t) == sid
    assert newsletter.read_token(settings, newsletter.CONFIRM, t) is None
    assert newsletter.read_token(settings, newsletter.UNSUBSCRIBE, t[:-2] + "xx") is None
    other = make_settings(secret_key="another-secret-key-of-enough-length-1234")
    assert newsletter.read_token(other, newsletter.UNSUBSCRIBE, t) is None
    assert newsletter.read_token(settings, newsletter.UNSUBSCRIBE, "nope") is None


def test_schedule_runs_on_its_days_after_its_time() -> None:
    row = MarketingAutopost(enabled=True, channels=["EMAIL"], weekdays=[2], post_at=time(9, 0))
    # Tuesday 13 October 2026, 8:59 and 9:00 am in Brisbane (UTC+10).
    assert service.due_today(row, datetime(2026, 10, 12, 22, 59, tzinfo=UTC)) is None
    assert service.due_today(row, datetime(2026, 10, 12, 23, 0, tzinfo=UTC)) == (
        datetime(2026, 10, 13).date()
    )
    assert service.due_today(row, datetime(2026, 10, 13, 23, 0, tzinfo=UTC)) is None  # Wed
    row.enabled = False
    assert service.due_today(row, datetime(2026, 10, 12, 23, 0, tzinfo=UTC)) is None


# --- Meta ----------------------------------------------------------------------------------


class FakeGraph:
    """Stands in for graph.facebook.com."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.fail: dict[str, Any] | None = None
        self.status = 400

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer EAAB-test-token"
        assert "EAAB" not in str(request.url)
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        path = request.url.path
        self.calls.append((request.method, path, form or dict(request.url.params)))
        if self.fail is not None:
            return httpx.Response(self.status, json={"error": self.fail})
        if path.endswith("/photos"):
            return httpx.Response(200, json={"id": "111", "post_id": "1234567890_222"})
        if path.endswith("/media"):
            return httpx.Response(200, json={"id": "333"})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "444"})
        if path.endswith("/333"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if path.endswith("/444"):
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/abc/"})
        if path.endswith("/1234567890"):
            return httpx.Response(200, json={"name": "ApprovalReady"})
        if path.endswith("/17841400000000000"):
            return httpx.Response(200, json={"username": "approvalready.au"})
        return httpx.Response(404, json={"error": {"message": "unknown", "code": 803}})


def meta_client(graph: FakeGraph, **overrides: object) -> MetaClient:
    client = MetaClient(make_settings(**META, **overrides), httpx.MockTransport(graph.handler))
    client.wait_seconds = 0
    return client


async def test_posts_to_facebook_and_instagram() -> None:
    graph = FakeGraph()
    client = meta_client(graph)
    fb = await client.publish(Channel.FACEBOOK, "Hello", "https://x.au/card.jpg")
    assert fb.external_id == "1234567890_222"
    assert fb.url == "https://www.facebook.com/1234567890_222"
    assert graph.calls[0] == (
        "POST",
        "/v23.0/1234567890/photos",
        {"url": "https://x.au/card.jpg", "caption": "Hello"},
    )
    ig = await client.publish(Channel.INSTAGRAM, "Hi", "https://x.au/card.jpg")
    assert ig.external_id == "444"
    assert ig.url == "https://www.instagram.com/p/abc/"
    assert [c[1] for c in graph.calls[1:]] == [
        "/v23.0/17841400000000000/media",
        "/v23.0/333",
        "/v23.0/17841400000000000/media_publish",
        "/v23.0/444",
    ]
    checks = [await client.check(c) for c in (Channel.FACEBOOK, Channel.INSTAGRAM)]
    assert [c.name for c in checks] == ["ApprovalReady", "@approvalready.au"]


async def test_facebook_errors_say_whether_retrying_can_help() -> None:
    graph = FakeGraph()
    client = meta_client(graph)
    graph.fail = {"message": "Error validating access token", "code": 190}
    with pytest.raises(MetaError) as expired:
        await client.publish(Channel.FACEBOOK, "Hello", "https://x.au/c.jpg")
    assert expired.value.permanent
    assert "Error validating access token" in str(expired.value)
    graph.fail, graph.status = {"message": "Please retry", "code": 2}, 500
    with pytest.raises(MetaError) as busy:
        await client.publish(Channel.FACEBOOK, "Hello", "https://x.au/c.jpg")
    assert not busy.value.permanent
    unset = MetaClient(make_settings())
    assert (await unset.check(Channel.FACEBOOK)).configured is False


# --- The email list --------------------------------------------------------------------------


@pytest.fixture
async def clean(owner_sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    """Marketing tables are platform-wide: start each test with none of them."""

    async def wipe() -> None:
        async with owner_sessions() as db:
            await db.execute(delete(MarketingPost))
            await db.execute(delete(NewsletterSubscriber))
            await db.execute(
                update(MarketingAutopost).values(
                    enabled=False, channels=[], weekdays=[2, 5], post_at=time(9), skip_guides=[]
                )
            )
            await db.commit()

    await wipe()
    yield
    await wipe()


def _query_value(url: str, name: str) -> str:
    return parse_qs(urlparse(url).query)[name][0]


async def _join(api: ApiHarness, email: str) -> None:
    anon = await api.new_client()
    r = await anon.post("/v1/marketing/subscribe", json={"email": email})
    assert r.status_code == 202, r.text
    message = api.last_email(email, "marketing.confirm")
    token = _query_value(message.links["confirm"], "confirm")
    r = await anon.post("/v1/marketing/confirm", json={"token": token})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SUBSCRIBED"


@pytest.mark.integration
async def test_sign_up_confirm_and_leave(api: ApiHarness, clean: None) -> None:
    email = unique_email("Reader")
    anon = await api.new_client()
    r = await anon.post("/v1/marketing/subscribe", json={"email": email})
    assert r.status_code == 202
    message = api.last_email(email.lower(), "marketing.confirm")
    assert "If this wasn't you, ignore this email" in message.text
    token = _query_value(message.links["confirm"], "confirm")

    # Opening the link changes nothing (mail scanners open links); the button confirms.
    r = await anon.get("/v1/marketing/confirm", params={"token": token})
    assert r.json() == {"email": email.lower(), "status": "PENDING"}
    r = await anon.post("/v1/marketing/confirm", json={"token": "x" + token})
    assert r.status_code == 400
    r = await anon.post("/v1/marketing/confirm", json={"token": token})
    assert r.json()["status"] == "SUBSCRIBED"

    # Signing up again sends nothing and says the same thing.
    before = len(api.outbox)
    r = await anon.post("/v1/marketing/subscribe", json={"email": email.upper()})
    assert r.status_code == 202
    assert len(api.outbox) == before

    # A confirmation token can't unsubscribe, and vice versa.
    r = await anon.post("/v1/marketing/unsubscribe", params={"token": token})
    assert r.status_code == 400

    async with api.app.state.resources.session_factory() as db:
        row = await newsletter.by_email(db, email)
        assert row is not None
    settings = api.app.state.settings
    page, one_click = newsletter.links(settings, row.id)
    leave = _query_value(page, "unsubscribe")
    assert one_click.endswith(f"/api/v1/marketing/unsubscribe?token={leave}")
    r = await anon.get("/v1/marketing/unsubscribe", params={"token": leave})
    assert r.json()["status"] == "SUBSCRIBED"
    # One-click: the token is in the address and the body is ignored (RFC 8058).
    r = await anon.post(
        "/v1/marketing/unsubscribe",
        params={"token": leave},
        content="List-Unsubscribe=One-Click",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "UNSUBSCRIBED"

    # Coming back means confirming again.
    r = await anon.post("/v1/marketing/subscribe", json={"email": email})
    assert api.last_email(email.lower(), "marketing.confirm") is not message


@pytest.mark.integration
async def test_sign_ups_are_rate_limited(api: ApiHarness, clean: None) -> None:
    anon = await api.new_client()
    email = unique_email()
    for _ in range(3):
        await anon.post("/v1/marketing/subscribe", json={"email": email})
    # At most one confirmation in 15 minutes, whatever the form is sent.
    assert len(api.emails_to(email, "marketing.confirm")) == 1
    for _ in range(7):
        await anon.post("/v1/marketing/subscribe", json={"email": unique_email()})
    r = await anon.post("/v1/marketing/subscribe", json={"email": unique_email()})
    assert r.status_code == 429


@pytest.mark.integration
async def test_account_holders_join_from_their_account(api: ApiHarness, clean: None) -> None:
    user = await api.user()
    assert (await user.get("/v1/auth/newsletter")).json() == {"subscribed": False}
    r = await user.put("/v1/auth/newsletter", json={"subscribed": True})
    assert r.json() == {"subscribed": True}
    assert api.emails_to(user.email, "marketing.confirm") == []  # verified already

    r = await user.get("/v1/auth/account/export")
    assert r.json()["guides_email_list"]["status"] == "SUBSCRIBED"

    r = await user.put("/v1/auth/newsletter", json={"subscribed": False})
    assert r.json() == {"subscribed": False}
    await user.put("/v1/auth/newsletter", json={"subscribed": True})

    r = await user.post("/v1/auth/account/close", json={"password": PASSWORD})
    assert r.status_code == 204
    async with api.app.state.resources.session_factory() as db:
        assert await newsletter.by_email(db, user.email) is None


# --- Admin --------------------------------------------------------------------------------


async def _staff(api: ApiHarness) -> User:
    return await platform_user(api, role="ADMIN", name="Marketer")


@pytest.mark.integration
async def test_only_admins_reach_marketing(api: ApiHarness, clean: None) -> None:
    customer = await api.user()
    assert (await customer.get(f"{ADMIN}/guides")).status_code == 403
    staff = await platform_user(api, role="STAFF")
    assert (await staff.get(f"{ADMIN}/guides")).status_code == 403


@pytest.mark.integration
async def test_staff_draft_schedule_and_send_a_guide_email(api: ApiHarness, clean: None) -> None:
    admin = await _staff(api)
    readers = [unique_email("reader") for _ in range(3)]
    for email in readers:
        await _join(api, email)

    r = await admin.get(f"{ADMIN}/overview")
    assert r.status_code == 200, r.text
    overview = r.json()
    assert [(c["channel"], c["configured"]) for c in overview["channels"]] == [
        ("FACEBOOK", False),
        ("INSTAGRAM", False),
        ("EMAIL", True),
    ]
    assert overview["subscribers"]["subscribed"] == 3
    assert overview["autopost"]["enabled"] is False

    guides = (await admin.get(f"{ADMIN}/guides")).json()
    assert {g["ref"] for g in guides} >= {"guide-cairns-subdivision"}
    r = await admin.get(f"{ADMIN}/guides/approval-abn-registration/drafts")
    drafts = {d["channel"]: d for d in r.json()["drafts"]}

    # Facebook isn't set up, so it can't be posted to.
    r = await admin.post(
        f"{ADMIN}/posts",
        json={
            "guide_ref": "approval-abn-registration",
            "posts": [{"channel": "FACEBOOK", "body": drafts["FACEBOOK"]["body"]}],
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "channel_not_set_up"

    later = datetime.now(UTC) + timedelta(days=2)
    r = await admin.post(
        f"{ADMIN}/posts",
        json={
            "guide_ref": "approval-abn-registration",
            "scheduled_for": later.isoformat(),
            "posts": [{"channel": "EMAIL", "subject": "Your ABN, step by step", "body": "Steps…"}],
        },
    )
    assert r.status_code == 201, r.text
    post = r.json()[0]
    assert post["status"] == "SCHEDULED"
    assert post["link_url"].endswith("utm_content=approval-abn-registration")

    factory = api.app.state.resources.session_factory
    settings = api.app.state.settings
    email = api.app.state.resources.email
    # Not due yet.
    assert await service.publish_due(factory, email, settings, meta=MetaClient(settings)) == 0
    r = await admin.patch(
        f"{ADMIN}/posts/{post['id']}", json={"body": "Here is how to get an ABN."}
    )
    assert r.json()["body"] == "Here is how to get an ABN."

    sent = await service.publish_due(
        factory, email, settings, meta=MetaClient(settings), now=later + timedelta(minutes=1)
    )
    assert sent == 1
    for address in readers:
        message = api.last_email(address.lower(), "marketing.guide")
        assert message.subject == "Your ABN, step by step"
        assert message.text.startswith("Here is how to get an ABN.")
        assert "Unsubscribe (one click, no sign-in):" in message.text
        assert message.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        assert "/api/v1/marketing/unsubscribe?token=" in message.headers["List-Unsubscribe"]

    history = (await admin.get(f"{ADMIN}/posts")).json()
    done = next(p for p in history if p["id"] == post["id"])
    assert done["status"] == "POSTED" and done["sent_count"] == 3

    # Running again sends nobody anything twice.
    before = len(api.outbox)
    await service.publish_due(factory, email, settings, meta=MetaClient(settings), now=later)
    assert len(api.outbox) == before
    assert (await admin.post(f"{ADMIN}/posts/{post['id']}/cancel")).status_code == 409


@pytest.mark.integration
async def test_emails_stop_at_the_daily_limit_and_carry_on(api: ApiHarness, clean: None) -> None:
    for _ in range(3):
        await _join(api, unique_email("reader"))
    admin = await _staff(api)
    r = await admin.post(
        f"{ADMIN}/posts",
        json={
            "guide_ref": "guide-cairns-subdivision",
            "posts": [{"channel": "EMAIL", "subject": "Subdividing", "body": "Read it"}],
        },
    )
    post_id = uuid.UUID(r.json()[0]["id"])
    factory = api.app.state.resources.session_factory
    email = api.app.state.resources.email
    settings = api.app.state.settings.model_copy(update={"newsletter_daily_limit": 2})
    now = datetime.now(UTC) + timedelta(seconds=1)
    await service.publish_due(factory, email, settings, meta=MetaClient(settings), now=now)
    async with factory() as db:
        post = await db.get(MarketingPost, post_id)
        assert post is not None
        assert (post.status, post.sent_count) == ("SCHEDULED", 2)
        assert "daily limit" in (post.error or "")
    later = now + service.LIMIT_WAIT
    await service.publish_due(factory, email, settings, meta=MetaClient(settings), now=later)
    async with factory() as db:
        post = await db.get(MarketingPost, post_id)
        assert post is not None
        assert (post.status, post.sent_count) == ("POSTED", 3)


@pytest.mark.integration
async def test_social_posts_publish_retry_and_fail(api: ApiHarness, clean: None) -> None:
    settings = api.app.state.settings.model_copy(
        update={
            "meta_page_id": META["meta_page_id"],
            "meta_instagram_account_id": META["meta_instagram_account_id"],
            "meta_page_access_token": make_settings(**META).meta_page_access_token,
        }
    )
    graph = FakeGraph()
    client = MetaClient(settings, httpx.MockTransport(graph.handler))
    client.wait_seconds = 0
    factory = api.app.state.resources.session_factory
    email = api.app.state.resources.email
    guide = catalogue.find("guide-cairns-secondary-dwellings")
    assert guide is not None
    now = datetime.now(UTC)
    async with factory() as db:
        ids = []
        for channel in (Channel.FACEBOOK, Channel.INSTAGRAM):
            post = await service.create_post(
                db,
                settings,
                guide=guide,
                channel=channel,
                body="Granny flats in Cairns",
                subject=None,
                scheduled_for=now,
                actor_id=None,
            )
            ids.append(post.id)
        await db.commit()

    assert await service.publish_due(factory, email, settings, meta=client, now=now) == 2
    card = service.card_url(settings, guide.ref)
    assert (
        "POST",
        "/v23.0/1234567890/photos",
        {"url": card, "caption": "Granny flats in Cairns"},
    ) in graph.calls
    async with factory() as db:
        posted = [await db.get(MarketingPost, i) for i in ids]
        assert [p.status for p in posted if p] == ["POSTED", "POSTED"]
        assert [p.external_url for p in posted if p] == [
            "https://www.facebook.com/1234567890_222",
            "https://www.instagram.com/p/abc/",
        ]

    # Facebook busy: tried again later. Token expired: failed with the reason.
    async with factory() as db:
        busy = await service.create_post(
            db,
            settings,
            guide=guide,
            channel=Channel.FACEBOOK,
            body="Again",
            subject=None,
            scheduled_for=now,
            actor_id=None,
        )
        await db.commit()
    graph.fail, graph.status = {"message": "Please retry", "code": 2}, 500
    await service.publish_due(factory, email, settings, meta=client, now=now)
    async with factory() as db:
        row = await db.get(MarketingPost, busy.id)
        assert row is not None
        assert row.status == "SCHEDULED" and row.scheduled_for > now
    graph.fail, graph.status = {"message": "Error validating access token", "code": 190}, 400
    await service.publish_due(factory, email, settings, meta=client, now=now + timedelta(hours=1))
    async with factory() as db:
        row = await db.get(MarketingPost, busy.id)
        assert row is not None
        assert row.status == "FAILED"
        assert "Error validating access token" in (row.error or "")

    admin = await _staff(api)
    r = await admin.post(f"{ADMIN}/posts/{busy.id}/retry")
    assert r.json()["status"] == "SCHEDULED"
    r = await admin.post(f"{ADMIN}/posts/{busy.id}/cancel")
    assert r.json()["status"] == "CANCELLED"


@pytest.mark.integration
async def test_auto_post_rotates_through_the_guides(api: ApiHarness, clean: None) -> None:
    await _join(api, unique_email("reader"))
    admin = await _staff(api)
    r = await admin.put(
        f"{ADMIN}/autopost",
        json={"enabled": True, "channels": ["EMAIL"], "weekdays": [], "post_at": "09:00"},
    )
    assert r.status_code == 422
    skip = ["guide-cairns-secondary-dwellings"]
    r = await admin.put(
        f"{ADMIN}/autopost",
        json={
            "enabled": True,
            "channels": ["EMAIL", "FACEBOOK"],
            "weekdays": [1, 2, 3, 4, 5, 6, 7],
            "post_at": "09:00",
            "skip_guides": skip,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["next_guide_ref"] == "guide-cairns-subdivision"

    factory = api.app.state.resources.session_factory
    email = api.app.state.resources.email
    settings = api.app.state.settings
    nine = datetime(2030, 1, 7, 23, 5, tzinfo=UTC)  # 9:05 am in Brisbane
    for _ in range(2):  # however often the job runs
        await service.publish_due(factory, email, settings, meta=MetaClient(settings), now=nine)
    async with factory() as db:
        posts = list((await db.execute(select(MarketingPost))).scalars())
    # Facebook isn't set up, so only the email went out.
    assert [(p.channel, p.origin, p.guide_ref, p.status) for p in posts] == [
        ("EMAIL", "AUTO", "guide-cairns-subdivision", "POSTED")
    ]
    await service.publish_due(
        factory, email, settings, meta=MetaClient(settings), now=nine + timedelta(days=1)
    )
    async with factory() as db:
        refs = [
            p.guide_ref
            for p in (
                await db.execute(select(MarketingPost).order_by(MarketingPost.auto_day))
            ).scalars()
        ]
    assert refs == ["guide-cairns-subdivision", "guide-importing-goods-into-australia"]


@pytest.mark.integration
async def test_staff_see_and_remove_subscribers(api: ApiHarness, clean: None) -> None:
    email = unique_email("listed")
    await _join(api, email)
    admin = await _staff(api)
    rows = (await admin.post(f"{ADMIN}/subscribers/search", json={"query": email[:12]})).json()
    assert [r["email"] for r in rows] == [email.lower()]
    r = await admin.post(f"{ADMIN}/subscribers/{rows[0]['id']}/unsubscribe")
    assert r.json()["status"] == "UNSUBSCRIBED"


@pytest.mark.integration
async def test_cards_are_public(api: ApiHarness) -> None:
    anon = await api.new_client()
    r = await anon.get("/v1/marketing/cards/guide-cairns-subdivision.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert (await anon.get("/v1/marketing/cards/nope.jpg")).status_code == 404


def test_web_guides_file_is_valid_json() -> None:
    data = json.loads(catalogue.WEB_GUIDES_FILE.read_text())
    assert all({"slug", "title", "description", "vertical"} <= set(g) for g in data["guides"])
