"""Reading a source document from its official address (Milestone 24).

The app only ever reads addresses staff entered as source documents, and only when they are
``https`` on an allowed domain (``SOURCE_FETCH_ALLOWED_DOMAINS``, government domains by
default) and every address the name resolves to is on the public internet. Redirects are
followed by hand so each hop passes the same checks. Responses are capped in size.

Web pages become plain text (the page's main content when it marks one, without scripts,
menus, headers and footers) so a snapshot changes when the wording changes, not when a
banner or a script does. Other files (PDFs) are not read as text: their bytes are hashed so
staff know when to capture them by hand.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import Settings

USER_AGENT = "ApprovalReady source check/1.0 (+https://approvalready.au; team@approvalready.au)"
MAX_REDIRECTS = 5
# Fewer characters than this after stripping a page means it shows nothing without
# JavaScript, or is an error page dressed as a success.
MIN_TEXT_CHARS = 100

Resolver = Callable[[str], Awaitable[list[str]]]


class FetchRefused(Exception):
    """The address may not be read, or what came back can't be used. The message is shown
    to staff."""

    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class Fetched:
    final_url: str
    http_status: int
    content_type: str  # media type only, lower case
    charset: str | None
    body: bytes

    @property
    def sha256(self) -> bytes:
        return hashlib.sha256(self.body).digest()


async def resolve_host(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def check_url(url: str, allowed_domains: list[str]) -> str:
    """The host to resolve, or ``FetchRefused`` when the address may not be read."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise FetchRefused("Only https addresses are read automatically.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or parts.username or parts.password:
        raise FetchRefused("The address has no usable host name.")
    if parts.port not in (None, 443):
        raise FetchRefused("Only the standard https port is read automatically.")
    if not any(host == d or host.endswith(f".{d}") for d in allowed_domains):
        raise FetchRefused(
            f"{host} is not on an allowed domain ({', '.join(allowed_domains)}). "
            "Capture it by hand, or ask for the domain to be added."
        )
    return host


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_global


class SourceFetcher:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self.allowed_domains = settings.source_fetch_allowed_domains
        self.max_bytes = settings.source_fetch_max_mb * 1_000_000
        self.timeout = settings.source_fetch_timeout_seconds
        self.transport = transport
        self.resolver = resolver or resolve_host

    async def _check(self, url: str) -> None:
        host = check_url(url, self.allowed_domains)
        try:
            addresses = await self.resolver(host)
        except OSError as exc:
            raise FetchRefused(f"{host} could not be found.") from exc
        if not addresses or not all(_public(a) for a in addresses):
            raise FetchRefused(f"{host} does not point to a public internet address.")

    async def fetch(self, url: str) -> Fetched:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"user-agent": USER_AGENT, "accept": "text/html,text/plain,*/*;q=0.5"},
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                await self._check(current)
                try:
                    fetched = await self._get(client, current)
                except httpx.TimeoutException as exc:
                    raise FetchRefused("The site took too long to answer.") from exc
                except httpx.HTTPError as exc:
                    reason = type(exc).__name__
                    raise FetchRefused(f"The site could not be reached ({reason}).") from exc
                if isinstance(fetched, str):
                    current = urljoin(current, fetched)
                    continue
                return fetched
        raise FetchRefused("The address redirects too many times.")

    async def _get(self, client: httpx.AsyncClient, url: str) -> Fetched | str:
        """The response, or the next address when it redirects."""
        async with client.stream("GET", url) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise FetchRefused("The site redirected without saying where.")
                return str(location)
            if response.status_code != 200:
                raise FetchRefused(
                    f"The site answered {response.status_code}.", response.status_code
                )
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                raise FetchRefused(self._too_large())
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise FetchRefused(self._too_large())
                chunks.append(chunk)
            media, charset = _content_type(response.headers.get("content-type", ""))
            return Fetched(
                final_url=str(response.url),
                http_status=response.status_code,
                content_type=media,
                charset=charset,
                body=b"".join(chunks),
            )

    def _too_large(self) -> str:
        return f"The file is larger than {self.max_bytes // 1_000_000} MB."


def _content_type(header: str) -> tuple[str, str | None]:
    media, _, params = header.partition(";")
    found = re.search(r"charset=\"?([\w.:-]+)", params, re.IGNORECASE)
    return media.strip().lower(), found.group(1) if found else None


# --- Text ------------------------------------------------------------------------------

# Elements whose content is never part of the document's wording.
_SKIP = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "nav",
    "header",
    "footer",
    "form",
    "button",
    "select",
    "head",
    "aside",
}
# Elements that start a new line in the text.
_BLOCK = {
    "address", "article", "blockquote", "br", "caption", "dd", "div", "dl", "dt",
    "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "main", "ol",
    "p", "pre", "section", "table", "tbody", "td", "th", "thead", "tr", "ul", "summary",
    "details",
}  # fmt: skip
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source",
         "track", "wbr"}  # fmt: skip


class _TextParser(HTMLParser):
    """Collects text, separately for the whole page and for its main content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.skipping = 0
        self.main_depth = 0
        self.all: list[str] = []
        self.main: list[str] = []

    def _is_main(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        return tag == "main" or dict(attrs).get("role") == "main"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            if tag in _BLOCK:
                self._text("\n")
            return
        self.stack.append(tag)
        if tag in _SKIP:
            self.skipping += 1
        if self._is_main(tag, attrs) or self.main_depth:
            self.main_depth += 1
        if tag in _BLOCK:
            self._text("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or tag not in self.stack:
            return
        while self.stack:  # close anything left open inside it
            open_tag = self.stack.pop()
            if open_tag in _SKIP:
                self.skipping -= 1
            if open_tag in _BLOCK:
                self._text("\n")
            if self.main_depth:
                self.main_depth -= 1
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        self._text(data)

    def _text(self, data: str) -> None:
        if self.skipping:
            return
        self.all.append(data)
        if self.main_depth:
            self.main.append(data)


def _tidy(parts: list[str]) -> str:
    lines = (re.sub(r"\s+", " ", line).strip() for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    main = _tidy(parser.main)
    return main if len(main) >= MIN_TEXT_CHARS else _tidy(parser.all)


def _decode(body: bytes, charset: str | None) -> str:
    for candidate in (charset, "utf-8"):
        if not candidate:
            continue
        try:
            return body.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


TEXT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}


def readable_text(fetched: Fetched) -> str | None:
    """The document's wording, or ``None`` for a file the app doesn't read as text."""
    if fetched.content_type not in TEXT_TYPES:
        return None
    if fetched.content_type == "text/plain":
        return _tidy([_decode(fetched.body, fetched.charset)])
    charset = fetched.charset
    if charset is None:
        head = fetched.body[:2048].decode("ascii", errors="ignore")
        found = re.search(r"<meta[^>]+charset=[\"']?([\w.:-]+)", head, re.IGNORECASE)
        charset = found.group(1) if found else None
    return html_to_text(_decode(fetched.body, charset))
