"""Posting to a Facebook Page and an Instagram professional account through Meta's Graph API.

Both use the Page access token in ``META_PAGE_ACCESS_TOKEN`` (the Instagram account must be
linked to the Page). A channel is switched on only when its settings are present, so
nothing is posted publicly until those are added to ``.env``:

* Facebook: ``META_PAGE_ID`` and the token. A photo post (``/{page}/photos``) with the guide's
  card and the caption.
* Instagram: ``META_INSTAGRAM_ACCOUNT_ID`` and the token. A media container from the card's
  public address, then ``media_publish``.

The token goes in the ``Authorization`` header, never in a URL, so it can't end up in logs
or error messages.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.modules.marketing.models import Channel

# Meta's error codes for an expired, revoked or wrong token or missing permission: retrying
# can't help, a person has to fix the settings.
PERMANENT_CODES = {10, 100, 190, 200, 803}
CONTAINER_CHECKS = 10
CONTAINER_WAIT_SECONDS = 3.0


class MetaError(Exception):
    def __init__(self, message: str, *, permanent: bool) -> None:
        super().__init__(message)
        self.permanent = permanent


@dataclass(frozen=True)
class Published:
    external_id: str
    url: str | None


@dataclass(frozen=True)
class Connection:
    channel: Channel
    configured: bool
    name: str | None = None
    error: str | None = None


def configured(settings: Settings, channel: Channel) -> bool:
    if channel == Channel.EMAIL:
        return True
    if settings.meta_page_access_token is None:
        return False
    if channel == Channel.FACEBOOK:
        return settings.meta_page_id is not None
    return settings.meta_instagram_account_id is not None


class MetaClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport
        self.wait_seconds = CONTAINER_WAIT_SECONDS

    def _client(self) -> httpx.AsyncClient:
        token = self.settings.meta_page_access_token
        headers = {"authorization": f"Bearer {token.get_secret_value()}"} if token else {}
        return httpx.AsyncClient(
            base_url=f"{self.settings.meta_graph_base.rstrip('/')}/{self.settings.meta_graph_version}",
            headers=headers,
            timeout=self.settings.meta_timeout_seconds,
            transport=self.transport,
        )

    @staticmethod
    async def _call(client: httpx.AsyncClient, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            r = await client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise MetaError(
                f"Couldn't reach Facebook: {type(exc).__name__}", permanent=False
            ) from exc
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400 or "error" in data:
            error = data.get("error") or {}
            code = error.get("code")
            message = str(error.get("message") or f"HTTP {r.status_code}")[:400]
            permanent = code in PERMANENT_CODES or (
                r.status_code in (400, 401, 403) and code is None
            )
            raise MetaError(f"Facebook said: {message} (code {code})", permanent=permanent)
        return data if isinstance(data, dict) else {}

    async def publish(self, channel: Channel, caption: str, image_url: str) -> Published:
        if channel == Channel.FACEBOOK:
            return await self.publish_facebook(caption, image_url)
        if channel == Channel.INSTAGRAM:
            return await self.publish_instagram(caption, image_url)
        raise ValueError(f"{channel} is not a Meta channel")

    async def publish_facebook(self, caption: str, image_url: str) -> Published:
        page = self.settings.meta_page_id
        async with self._client() as client:
            data = await self._call(
                client, "POST", f"/{page}/photos", data={"url": image_url, "caption": caption}
            )
        post_id = str(data.get("post_id") or data.get("id") or "")
        if not post_id:
            raise MetaError("Facebook didn't return the new post's id", permanent=False)
        return Published(post_id, f"https://www.facebook.com/{post_id}")

    async def publish_instagram(self, caption: str, image_url: str) -> Published:
        account = self.settings.meta_instagram_account_id
        async with self._client() as client:
            container = await self._call(
                client,
                "POST",
                f"/{account}/media",
                data={"image_url": image_url, "caption": caption},
            )
            creation_id = str(container.get("id") or "")
            if not creation_id:
                raise MetaError("Instagram didn't return a media container", permanent=False)
            for _ in range(CONTAINER_CHECKS):
                state = await self._call(
                    client, "GET", f"/{creation_id}", params={"fields": "status_code"}
                )
                status = state.get("status_code")
                if status in (None, "FINISHED"):
                    break
                if status in ("ERROR", "EXPIRED"):
                    raise MetaError(f"Instagram couldn't use the image ({status})", permanent=False)
                await asyncio.sleep(self.wait_seconds)
            published = await self._call(
                client, "POST", f"/{account}/media_publish", data={"creation_id": creation_id}
            )
            media_id = str(published.get("id") or "")
            if not media_id:
                raise MetaError("Instagram didn't return the new post's id", permanent=False)
            url: str | None = None
            with contextlib.suppress(MetaError):  # posted; the link is a nicety
                url = (
                    await self._call(client, "GET", f"/{media_id}", params={"fields": "permalink"})
                ).get("permalink")
        return Published(media_id, url)

    async def check(self, channel: Channel) -> Connection:
        """Whether the channel is set up, and the Page or account name it posts as."""
        if not configured(self.settings, channel):
            return Connection(channel, configured=False)
        if channel == Channel.FACEBOOK:
            path, field = f"/{self.settings.meta_page_id}", "name"
        else:
            path, field = f"/{self.settings.meta_instagram_account_id}", "username"
        try:
            async with self._client() as client:
                data = await self._call(client, "GET", path, params={"fields": field})
        except MetaError as exc:
            return Connection(channel, configured=True, error=str(exc))
        name = data.get(field)
        if channel == Channel.INSTAGRAM and name:
            name = f"@{name}"
        return Connection(channel, configured=True, name=name)
