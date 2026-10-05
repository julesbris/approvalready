"""Test harness for authenticated API flows: users, sessions, emails and CSRF headers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.core.email import MemoryEmailProvider, OutgoingEmail

PASSWORD = "correct horse battery staple"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


@dataclass
class User:
    email: str
    password: str
    client: AsyncClient
    session: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.session["user"]["id"])

    @property
    def personal_org_id(self) -> str:
        return str(
            next(o for o in self.session["organisations"] if o["kind"] == "PERSONAL")[
                "organisation_id"
            ]
        )

    def csrf(self) -> dict[str, str]:
        return {"x-csrf-token": self.client.cookies.get("ar_csrf") or ""}

    async def get(self, url: str, **kw: Any) -> Response:
        return await self.client.get(url, **kw)

    async def post(self, url: str, **kw: Any) -> Response:
        return await self.client.post(url, headers=self.csrf(), **kw)

    async def put(self, url: str, **kw: Any) -> Response:
        return await self.client.put(url, headers=self.csrf(), **kw)

    async def patch(self, url: str, **kw: Any) -> Response:
        return await self.client.patch(url, headers=self.csrf(), **kw)

    async def delete(self, url: str, **kw: Any) -> Response:
        return await self.client.delete(url, headers=self.csrf(), **kw)


class ApiHarness:
    def __init__(self, app: FastAPI, client: AsyncClient) -> None:
        self.app = app
        self.client = client
        self._clients: list[AsyncClient] = []

    @property
    def outbox(self) -> list[OutgoingEmail]:
        provider = self.app.state.resources.email
        assert isinstance(provider, MemoryEmailProvider)
        return provider.outbox

    def last_email(self, to: str, kind: str | None = None) -> OutgoingEmail:
        for message in reversed(self.outbox):
            if message.to.lower() == to.lower() and (kind is None or message.kind == kind):
                return message
        raise AssertionError(f"no {kind or 'email'} sent to {to}")

    def emails_to(self, to: str, kind: str | None = None) -> list[OutgoingEmail]:
        return [
            m
            for m in self.outbox
            if m.to.lower() == to.lower() and (kind is None or m.kind == kind)
        ]

    @staticmethod
    def token_from(message: OutgoingEmail, link: str) -> str:
        return parse_qs(urlparse(message.links[link]).query)["token"][0]

    async def new_client(self) -> AsyncClient:
        """A separate browser (own cookie jar) against the same running app."""
        c = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://testserver")
        self._clients.append(c)
        return c

    async def session_status(self, token: str | None) -> int:
        """GET /v1/auth/session from a fresh browser holding only this session token."""
        c = await self.new_client()
        c.cookies.set("ar_session", token or "")
        return (await c.get("/v1/auth/session")).status_code

    async def register(
        self, email: str | None = None, password: str = PASSWORD, name: str = "Test User"
    ) -> str:
        email = email or unique_email()
        r = await self.client.post(
            "/v1/auth/register",
            json={"email": email, "password": password, "display_name": name},
        )
        assert r.status_code == 202, r.text
        return email

    async def verify(self, email: str) -> None:
        token = self.token_from(self.last_email(email, "auth.verify_email"), "verify")
        r = await self.client.post("/v1/auth/verify-email", json={"token": token})
        assert r.status_code == 200, r.text

    async def login(self, email: str, password: str = PASSWORD) -> User:
        c = await self.new_client()
        r = await c.post("/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return User(email, password, c, r.json())

    async def user(self, name: str = "Test User", email: str | None = None) -> User:
        email = await self.register(email=email, name=name)
        await self.verify(email)
        return await self.login(email)

    async def aclose(self) -> None:
        for c in self._clients:
            await c.aclose()
