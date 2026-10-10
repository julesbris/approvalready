"""Breached-password check against Have I Been Pwned's Pwned Passwords range API.

k-anonymity: only the first five hex characters of the password's SHA-1 leave the server;
the API answers with every suffix sharing that prefix (padded with decoys so the response
size reveals nothing) and the match happens here. The password itself is never sent, logged
or stored. If the service is slow or down the check is skipped (fail open), because refusing
every new password during an outage would lock people out of registration and resets.
"""

from __future__ import annotations

import hashlib
import logging

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

USER_AGENT = "ApprovalReady/1.0 (+https://approvalready.au)"


class BreachChecker:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.enabled = settings.password_breach_check
        self.base_url = settings.pwned_passwords_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=settings.password_breach_timeout_seconds,
            headers={"user-agent": USER_AGENT, "add-padding": "true"},
            transport=transport,
        )

    async def times_seen(self, password: str) -> int | None:
        """How often the password appears in known breaches (0 if never), or None when the
        check is off or the service could not be asked."""
        if not self.enabled:
            return None
        digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        try:
            response = await self._client.get(f"{self.base_url}/{prefix}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("breached-password check skipped", extra={"error": type(exc).__name__})
            return None
        for line in response.text.splitlines():
            candidate, _, count = line.strip().partition(":")
            if candidate.upper() == suffix:
                try:
                    return int(count)
                except ValueError:
                    return 1
        return 0

    async def aclose(self) -> None:
        await self._client.aclose()
