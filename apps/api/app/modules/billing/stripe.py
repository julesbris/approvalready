"""A small Stripe client (the few calls we make, over httpx) and webhook verification.

We only ever send Stripe what it needs to take a payment: the organisation's name, the
paying user's email, what is being bought and its price. Card details go straight from the
customer's browser to Stripe's hosted checkout; they never touch this server.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings


class StripeError(Exception):
    """Stripe could not be reached or refused the call."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class SignatureError(Exception):
    """A webhook whose signature or timestamp does not check out."""


def encode_form(params: Mapping[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's form encoding: ``a[b][0][c]=v``. ``None`` values are left out."""
    out: list[tuple[str, str]] = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, Mapping):
            out += encode_form(value, name)
        elif isinstance(value, list | tuple):
            for i, item in enumerate(value):
                if isinstance(item, Mapping):
                    out += encode_form(item, f"{name}[{i}]")
                else:
                    out.append((f"{name}[{i}]", _scalar(item)))
        else:
            out.append((name, _scalar(value)))
    return out


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


class StripeClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        key = settings.stripe_secret_key
        self._client = httpx.AsyncClient(
            base_url=settings.stripe_api_base,
            timeout=settings.stripe_timeout_seconds,
            transport=transport,
            headers={"authorization": f"Bearer {key.get_secret_value() if key else ''}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(
        self, path: str, params: Mapping[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        headers = {"idempotency-key": idempotency_key} if idempotency_key else {}
        try:
            response = await self._client.post(
                path,
                content=urlencode(encode_form(params)).encode(),
                headers={"content-type": "application/x-www-form-urlencoded", **headers},
            )
        except httpx.HTTPError as exc:
            raise StripeError(f"Stripe could not be reached: {type(exc).__name__}") from exc
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise StripeError("Stripe answered with something that isn't JSON") from exc
        if response.status_code >= 400:
            error = body.get("error") or {}
            raise StripeError(
                str(error.get("message") or f"Stripe refused the call ({response.status_code})"),
                response.status_code,
            )
        return body

    async def create_customer(
        self, *, name: str, email: str | None, metadata: dict[str, str], idempotency_key: str
    ) -> str:
        body = await self._post(
            "/v1/customers",
            {"name": name, "email": email, "metadata": metadata},
            idempotency_key,
        )
        return str(body["id"])

    async def create_checkout_session(
        self, params: dict[str, Any], *, idempotency_key: str
    ) -> CheckoutSession:
        body = await self._post("/v1/checkout/sessions", params, idempotency_key)
        return CheckoutSession(id=str(body["id"]), url=str(body["url"]))

    async def expire_checkout_session(self, session_id: str) -> None:
        await self._post(f"/v1/checkout/sessions/{session_id}/expire", {})

    async def create_portal_session(self, *, customer: str, return_url: str) -> str:
        body = await self._post(
            "/v1/billing_portal/sessions", {"customer": customer, "return_url": return_url}
        )
        return str(body["url"])


def verify_webhook(
    payload: bytes, header: str | None, secret: str, *, tolerance: int, now: float | None = None
) -> dict[str, Any]:
    """Check a ``Stripe-Signature`` header (HMAC-SHA256 of ``t.payload``, any ``v1``
    matching) and its age, then parse the event."""
    if not header:
        raise SignatureError("missing signature")
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError as exc:
                raise SignatureError("bad timestamp") from exc
        elif key == "v1":
            signatures.append(value)
    if timestamp is None or not signatures:
        raise SignatureError("malformed signature header")
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise SignatureError("signature does not match")
    if abs((now if now is not None else time.time()) - timestamp) > tolerance:
        raise SignatureError("signature is too old")
    try:
        event: dict[str, Any] = json.loads(payload)
    except ValueError as exc:
        raise SignatureError("payload is not JSON") from exc
    if not isinstance(event, dict) or event.get("object") != "event" or not event.get("id"):
        raise SignatureError("payload is not a Stripe event")
    return event


def sign_payload(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """A ``Stripe-Signature`` header for ``payload`` (tests and local development)."""
    t = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={signature}"
