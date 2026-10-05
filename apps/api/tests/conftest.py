from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import EmailProviderKind, Environment, Settings
from app.main import create_app
from tests.harness import ApiHarness

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://approvalready:approvalready@localhost:5432/approvalready_test",
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": Environment.TEST,
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "cors_origins": ["http://localhost:3000"],
        "allowed_hosts": ["testserver", "localhost"],
        "health_check_timeout_seconds": 2.0,
        "_env_file": None,
    }
    if overrides.get("app_env") in (Environment.PRODUCTION, Environment.STAGING):
        values.update(web_base_url="https://app.approvalready.com.au")
    else:
        # Plain-HTTP test client: no Secure cookies; capture emails in memory.
        values.update(cookie_secure=False, email_provider=EmailProviderKind.MEMORY)
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


async def _client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async for c in _client_for(app):
        yield c


@pytest.fixture
def client_factory():  # type: ignore[no-untyped-def]
    """Build a client for an app with custom settings: ``async with client_factory(...)``."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory(**overrides: object) -> AsyncIterator[AsyncClient]:
        async for c in _client_for(create_app(make_settings(**overrides))):
            yield c

    return factory


# --- Database-backed fixtures (Milestone 2+) -------------------------------------------


@pytest.fixture(scope="session")
def migrated() -> None:
    """Bring the test database to the latest migration once per run."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")


@pytest.fixture
async def api(migrated: None, app: FastAPI, client: AsyncClient) -> AsyncIterator[ApiHarness]:
    """Client plus helpers for auth flows, with rate-limit counters reset."""
    await app.state.resources.redis.flushdb()
    harness = ApiHarness(app, client)
    try:
        yield harness
    finally:
        await harness.aclose()
