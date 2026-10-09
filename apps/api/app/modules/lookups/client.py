"""The shared outbound HTTP client for lookups, a small in-process cache and the error
customers see when a government service doesn't answer."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ApiError

USER_AGENT = "ApprovalReady/1.0 (+https://approvalready.au)"


class LookupUnavailable(Exception):
    """A government service failed, timed out or answered with something we can't read."""


def unavailable(what: str) -> ApiError:
    return ApiError(
        502,
        "lookup_unavailable",
        f"{what} didn't answer just now. Try again shortly, or type the details in yourself.",
    )


class TtlCache:
    """Least-recently-used cache whose entries expire. Per process: lookups are cheap to
    repeat, so nothing needs sharing between workers."""

    def __init__(self, max_entries: int = 512, ttl_seconds: float = 3600) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        found = self._items.get(key)
        if found is None:
            return None
        stored_at, value = found
        if time.monotonic() - stored_at > self.ttl_seconds:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: str, value: Any) -> None:
        self._items[key] = (time.monotonic(), value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)


def create_http_client(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.lookup_timeout_seconds,
        headers={"user-agent": USER_AGENT},
        follow_redirects=True,
        transport=transport,
    )
