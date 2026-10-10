"""Automatic source checks (Milestone 24): reading source documents from their official
addresses, change detection, the weekly run and its staff notice.

Every site here is fictional (``*.test.gov.au``, served by an in-memory transport) and
nothing is fetched from a real government system.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text, update

from app.core.config import Settings
from app.main import create_app
from app.modules.notifications.models import Notification
from app.modules.regulatory import checks
from app.modules.regulatory.fetch import (
    FetchRefused,
    SourceFetcher,
    check_url,
    html_to_text,
)
from app.modules.regulatory.models import SourceCheck, SourceDocument
from tests.conftest import make_settings
from tests.harness import ApiHarness, platform_user
from tests.regulatory_helpers import ADMIN, reference, source_document

PUBLIC_IP = "104.18.32.7"
FILLER = " ".join(["The applicant must lodge the form before work starts."] * 4)


def page(body: str, *, main: bool = True) -> str:
    content = f"<main><h1>Secondary dwellings</h1><p>{body}</p></main>" if main else body
    return (
        "<html><head><title>Council</title><script>var t = Date.now();</script></head>"
        "<body><header>Menu</header><nav><a href='/'>Home</a></nav>"
        f"{content}<footer>Updated today</footer></body></html>"
    )


@dataclass
class FakeSite:
    """URL → (status, headers, body). Unknown URLs answer 404."""

    pages: dict[str, tuple[int, dict[str, str], bytes]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def html(self, url: str, html: str, status: int = 200) -> None:
        self.pages[url] = (status, {"content-type": "text/html; charset=utf-8"}, html.encode())

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        status, headers, body = self.pages.get(url, (404, {}, b"not found"))
        return httpx.Response(status, headers=headers, content=body)

    def fetcher(self, settings: Settings, ip: str = PUBLIC_IP) -> SourceFetcher:
        async def resolve(host: str) -> list[str]:
            return [ip]

        return SourceFetcher(settings, httpx.MockTransport(self.handle), resolve)


def unique_url(path: str = "page") -> str:
    return f"https://www.council.test.gov.au/{uuid.uuid4().hex[:8]}/{path}"


# --- Rules for addresses ---------------------------------------------------------------

ALLOWED = ["gov.au", "workcoverqld.com.au"]


@pytest.mark.parametrize(
    "url",
    [
        "http://www.cairns.qld.gov.au/page",  # not https
        "https://example.com/page",  # not an allowed domain
        "https://evilgov.au/page",  # looks like one
        "https://gov.au.example.com/page",
        "https://www.qld.gov.au:8443/page",  # another port
        "https://user:pw@www.qld.gov.au/page",
        "https://10.0.0.1/page",
    ],
)
def test_addresses_that_are_never_read(url: str) -> None:
    with pytest.raises(FetchRefused):
        check_url(url, ALLOWED)


def test_allowed_addresses() -> None:
    assert check_url("https://www.cairns.qld.gov.au/x?y=1", ALLOWED) == "www.cairns.qld.gov.au"
    assert check_url("https://gov.au/", ALLOWED) == "gov.au"
    assert check_url("https://www.workcoverqld.com.au/a", ALLOWED) == "www.workcoverqld.com.au"


def test_allowed_domains_setting() -> None:
    settings = make_settings(source_fetch_allowed_domains="gov.au, .Example.org.")
    assert settings.source_fetch_allowed_domains == ["gov.au", "example.org"]
    with pytest.raises(ValueError, match="domain name"):
        make_settings(source_fetch_allowed_domains="localhost")


# --- Text of a page --------------------------------------------------------------------


def test_page_text_keeps_the_wording_only() -> None:
    got = html_to_text(page(FILLER + " Fees &amp; charges apply."))
    assert got.startswith("Secondary dwellings\nThe applicant must lodge")
    assert got.endswith("Fees & charges apply.")
    for noise in ("Menu", "Home", "Date.now", "Updated today", "Council"):
        assert noise not in got


def test_page_without_main_uses_the_body() -> None:
    got = html_to_text(page(f"<div><p>{FILLER}</p><ul><li>One<li>Two</ul></div>", main=False))
    assert got.splitlines() == [FILLER, "One", "Two"]


def test_the_same_wording_gives_the_same_text() -> None:
    a = html_to_text(page(FILLER))
    b = html_to_text(page(FILLER).replace("Date.now()", "123").replace("today", "yesterday"))
    assert a == b


# --- Fetching --------------------------------------------------------------------------


async def test_redirects_are_checked_at_every_hop() -> None:
    settings = make_settings()
    site = FakeSite()
    start = "https://www.council.test.gov.au/old"
    site.pages[start] = (301, {"location": "https://evil.example.com/page"}, b"")
    with pytest.raises(FetchRefused, match="not on an allowed domain"):
        await site.fetcher(settings).fetch(start)

    site.pages[start] = (302, {"location": "/new"}, b"")
    site.html("https://www.council.test.gov.au/new", page(FILLER))
    fetched = await site.fetcher(settings).fetch(start)
    assert fetched.final_url == "https://www.council.test.gov.au/new"

    site.pages[start] = (302, {"location": start}, b"")
    with pytest.raises(FetchRefused, match="too many"):
        await site.fetcher(settings).fetch(start)


async def test_private_addresses_are_refused() -> None:
    site = FakeSite()
    site.html("https://intranet.test.gov.au/", page(FILLER))
    for ip in ("10.0.0.5", "127.0.0.1", "169.254.169.254", "::1", "fd00::1"):
        with pytest.raises(FetchRefused, match="public internet"):
            await site.fetcher(make_settings(), ip).fetch("https://intranet.test.gov.au/")
    assert site.calls == []


async def test_large_files_and_errors_are_refused() -> None:
    settings = make_settings(source_fetch_max_mb=1)
    site = FakeSite()
    url = "https://www.council.test.gov.au/big.pdf"
    site.pages[url] = (200, {"content-type": "application/pdf"}, b"x" * 1_000_001)
    with pytest.raises(FetchRefused, match="larger than 1 MB"):
        await site.fetcher(settings).fetch(url)
    site.pages[url] = (403, {}, b"blocked")
    with pytest.raises(FetchRefused) as refused:
        await site.fetcher(settings).fetch(url)
    assert refused.value.http_status == 403


# --- Through the API -------------------------------------------------------------------


@pytest.fixture
def site() -> FakeSite:
    return FakeSite()


@pytest.fixture
def app(settings: Settings, site: FakeSite) -> FastAPI:
    async def resolve(host: str) -> list[str]:
        return [PUBLIC_IP]

    return create_app(
        settings,
        source_fetch_transport=httpx.MockTransport(site.handle),
        source_fetch_resolver=resolve,
    )


@pytest.mark.integration
async def test_check_now_saves_snapshots_and_flags_changes(api: ApiHarness, site: FakeSite) -> None:
    staff = await platform_user(api, "STAFF")
    url = unique_url()
    document = await source_document(staff, url=url)
    assert document["auto_check"] is True and document["last_check"] is None
    check_path = f"{ADMIN}/source-documents/{document['id']}/check"

    site.html(url, page(FILLER))
    r = await staff.post(check_path)
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["outcome"] == "SAVED" and first["snapshot_id"]
    assert first["http_status"] == 200 and first["content_type"] == "text/html"

    snapshot = (
        await staff.get(
            f"{ADMIN}/source-documents/{document['id']}/snapshots/{first['snapshot_id']}"
        )
    ).json()
    assert snapshot["capture_method"] == "FETCHED"
    assert snapshot["content_text"].startswith("Secondary dwellings")

    # Verify a reference against what the app read, then the page changes.
    ref = await reference(staff, verify=False, document=document)
    r = await staff.post(f"{ADMIN}/source-references/{ref['id']}/review", json={"action": "VERIFY"})
    assert r.status_code == 200, r.text
    assert r.json()["verified_snapshot_id"] == first["snapshot_id"]

    r = await staff.post(check_path)
    assert r.json()["outcome"] == "UNCHANGED"
    assert r.json()["snapshot_id"] == first["snapshot_id"]

    site.html(url, page(FILLER + " The fee is now higher."))
    r = await staff.post(check_path)
    assert r.json()["outcome"] == "CHANGED"
    assert r.json()["snapshot_id"] != first["snapshot_id"]
    ref = (await staff.get(f"{ADMIN}/source-references/{ref['id']}")).json()
    assert "The document has changed since this was verified." in ref["attention"]

    history = (await staff.get(f"{ADMIN}/source-documents/{document['id']}/checks")).json()
    assert [c["outcome"] for c in history] == ["CHANGED", "UNCHANGED", "SAVED"]
    assert all(c["trigger"] == "MANUAL" for c in history)
    listed = (await staff.get(f"{ADMIN}/source-documents/{document['id']}")).json()
    assert listed["last_check"]["outcome"] == "CHANGED"
    assert listed["latest_snapshot"]["capture_method"] == "FETCHED"


@pytest.mark.integration
async def test_first_reading_after_a_pasted_snapshot_is_not_a_change(
    api: ApiHarness, site: FakeSite
) -> None:
    staff = await platform_user(api, "STAFF")
    url = unique_url()
    document = await source_document(staff, url=url)
    r = await staff.post(
        f"{ADMIN}/source-documents/{document['id']}/snapshots",
        json={"content_text": "Pasted by hand.", "retrieved_at": datetime.now(UTC).isoformat()},
    )
    assert r.json()["capture_method"] == "MANUAL"
    site.html(url, page(FILLER))
    r = await staff.post(f"{ADMIN}/source-documents/{document['id']}/check")
    assert r.json()["outcome"] == "SAVED"


@pytest.mark.integration
async def test_failures_and_files_are_recorded(api: ApiHarness, site: FakeSite) -> None:
    staff = await platform_user(api, "STAFF")

    blocked = await source_document(staff, url=unique_url())
    r = await staff.post(f"{ADMIN}/source-documents/{blocked['id']}/check")
    assert r.status_code == 201
    assert r.json()["outcome"] == "FAILED"
    assert r.json()["http_status"] == 404 and r.json()["error"] == "The site answered 404."

    elsewhere = await source_document(staff, url="https://example.com/rules")
    r = await staff.post(f"{ADMIN}/source-documents/{elsewhere['id']}/check")
    assert r.json()["outcome"] == "FAILED" and "allowed domain" in r.json()["error"]

    empty_url = unique_url()
    empty = await source_document(staff, url=empty_url)
    site.html(empty_url, page("<div id='app'></div>", main=False))
    r = await staff.post(f"{ADMIN}/source-documents/{empty['id']}/check")
    assert r.json()["outcome"] == "FAILED" and "JavaScript" in r.json()["error"]

    pdf_url = unique_url("fact-sheet.pdf")
    pdf = await source_document(staff, url=pdf_url)
    site.pages[pdf_url] = (200, {"content-type": "application/pdf"}, b"%PDF-1.7 one")
    outcomes = []
    for body in (b"%PDF-1.7 one", b"%PDF-1.7 one", b"%PDF-1.7 two"):
        site.pages[pdf_url] = (200, {"content-type": "application/pdf"}, body)
        r = await staff.post(f"{ADMIN}/source-documents/{pdf['id']}/check")
        outcomes.append(r.json()["outcome"])
        assert r.json()["snapshot_id"] is None
    assert outcomes == ["FILE_SEEN", "FILE_UNCHANGED", "FILE_CHANGED"]
    assert (await staff.get(f"{ADMIN}/source-documents/{pdf['id']}")).json()[
        "latest_snapshot"
    ] is None


@pytest.mark.integration
async def test_only_source_staff_can_check(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    document = await source_document(staff, url=unique_url())
    customer = await api.user()
    r = await customer.post(f"{ADMIN}/source-documents/{document['id']}/check")
    assert r.status_code == 403
    assert (
        await customer.get(f"{ADMIN}/source-documents/{document['id']}/checks")
    ).status_code == 403

    r = await staff.patch(f"{ADMIN}/source-documents/{document['id']}", json={"auto_check": False})
    assert r.status_code == 200 and r.json()["auto_check"] is False


@pytest.mark.integration
async def test_checks_are_append_only(api: ApiHarness, site: FakeSite) -> None:
    staff = await platform_user(api, "STAFF")
    document = await source_document(staff, url=unique_url())
    await staff.post(f"{ADMIN}/source-documents/{document['id']}/check")
    factory = api.app.state.resources.session_factory
    for statement in ("UPDATE source_check SET error = 'x'", "DELETE FROM source_check"):
        async with factory() as db:
            with pytest.raises(Exception, match="permission denied"):
                await db.execute(text(statement))


@pytest.mark.integration
async def test_weekly_run(api: ApiHarness, site: FakeSite, owner_sessions: object) -> None:
    staff = await platform_user(api, "STAFF", name="Source Keeper")
    changing_url, failing_url, steady_url, old_url = (unique_url() for _ in range(4))
    changing = await source_document(staff, url=changing_url)
    failing = await source_document(staff, url=failing_url)
    steady = await source_document(staff, url=steady_url)
    off = await source_document(staff, url=unique_url(), auto_check=False)
    expired = await source_document(staff, url=unique_url(), effective_to="2021-01-01")
    old = await source_document(staff, url=old_url)
    await source_document(staff, url=unique_url(), supersedes_id=old["id"])
    ours = {d["id"] for d in (changing, failing, steady, off, expired, old)}

    # Other tests' documents stay out of this run.
    async with owner_sessions() as db:  # type: ignore[operator]
        await db.execute(
            update(SourceDocument).where(SourceDocument.id.not_in(ours)).values(auto_check=False)
        )
        await db.commit()

    site.html(changing_url, page(FILLER))
    site.html(steady_url, page(FILLER))
    settings = api.app.state.settings
    factory = api.app.state.resources.session_factory
    email = api.app.state.resources.email
    pauses: list[float] = []

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    fetcher = site.fetcher(settings)
    now = datetime.now(UTC)
    today = date(2026, 10, 12)
    first = await checks.run_weekly(
        factory, email, settings, fetcher, now=now, today=today, sleep=sleep
    )
    # Not the one switched off, the one out of force or the superseded one.
    assert first.checked == 3, first
    assert first.outcomes == {"SAVED": 2, "FAILED": 1}
    assert first.news == [(failing["title"], "FAILED", "The site answered 404.")]
    assert pauses == [2.0, 2.0]

    async def notices() -> list[Notification]:
        async with owner_sessions() as db:  # type: ignore[operator]
            return list(
                (
                    await db.execute(
                        select(Notification)
                        .where(Notification.recipient_user_id == uuid.UUID(staff.id))
                        .order_by(Notification.created_at)
                    )
                ).scalars()
            )

    [notice] = await notices()
    assert notice.title == "Weekly source check: 1 couldn't be read"
    assert f"{failing['title']}: couldn't be read (The site answered 404.)" in notice.body
    assert notice.link_path == "/admin/sources"
    assert api.emails_to(staff.email)

    # Run again at once: everything was just checked.
    again = await checks.run_weekly(factory, email, settings, fetcher, now=now, today=today)
    assert again.checked == 0

    # A week later one page has changed.
    site.html(changing_url, page(FILLER + " New rules from 1 July."))
    later = await checks.run_weekly(
        factory,
        email,
        settings,
        fetcher,
        now=now + timedelta(days=7),
        today=today + timedelta(days=7),
        sleep=sleep,
    )
    assert later.outcomes == {"CHANGED": 1, "FAILED": 1, "UNCHANGED": 1}
    assert [n.title for n in await notices()][-1] == (
        "Weekly source check: 1 changed and 1 couldn't be read"
    )
    async with owner_sessions() as db:  # type: ignore[operator]
        triggers = set(
            (
                await db.execute(
                    select(SourceCheck.trigger).where(
                        SourceCheck.source_document_id == uuid.UUID(changing["id"])
                    )
                )
            ).scalars()
        )
    assert triggers == {"SCHEDULED"}


@pytest.mark.integration
async def test_weekly_run_can_be_switched_off(api: ApiHarness, site: FakeSite) -> None:
    settings = make_settings(source_checks_enabled=False)
    result = await checks.run_weekly(
        api.app.state.resources.session_factory,
        api.app.state.resources.email,
        settings,
        site.fetcher(settings),
    )
    assert result.checked == 0 and site.calls == []


@pytest.mark.integration
async def test_command_line(migrated: None, capsys: pytest.CaptureFixture[str]) -> None:
    from app import cli

    assert await cli.check_sources(make_settings(source_checks_enabled=False)) == 0
    assert "Checked 0 source document(s)." in capsys.readouterr().out
