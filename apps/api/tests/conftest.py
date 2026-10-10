from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import (
    EmailProviderKind,
    Environment,
    JobsMode,
    MalwareScannerKind,
    Settings,
)
from app.main import create_app
from tests.harness import ApiHarness

# Owner (runs migrations, provisions roles, syncs reference data).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://approvalready:approvalready@localhost:5432/approvalready_test",
)
# What the application connects as: a non-owner role subject to row-level security,
# created by ``prepare_database``.
TEST_APP_DATABASE_URL = os.environ.get(
    "TEST_APP_DATABASE_URL",
    "postgresql+psycopg://approvalready_app:approvalready_app@localhost:5432/approvalready_test",
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
# Uploaded and generated documents (local storage backend) for this test run.
TEST_STORAGE_ROOT = tempfile.mkdtemp(prefix="approvalready-test-storage-")


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": Environment.TEST,
        "database_url": TEST_APP_DATABASE_URL,
        "migration_database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "cors_origins": ["http://localhost:3000"],
        "allowed_hosts": ["testserver", "localhost"],
        "health_check_timeout_seconds": 2.0,
        "storage_local_root": TEST_STORAGE_ROOT,
        # Scans and document generation run right after the request instead of on a worker.
        "jobs_mode": JobsMode.INLINE,
        "_env_file": None,
    }
    if overrides.get("app_env") in (Environment.PRODUCTION, Environment.STAGING):
        values.update(
            web_base_url="https://app.approvalready.com.au",
            malware_scanner=MalwareScannerKind.CLAMAV,
        )
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


def prepare_database() -> None:
    """What a deploy's ``migrate`` step does: migrate, provision the app role, publish the
    bundled questionnaires, marketplace categories, billing catalogue, consent texts, report
    templates and AI prompts."""
    import asyncio

    from alembic import command
    from alembic.config import Config

    from app import cli

    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")
    settings = make_settings()
    assert asyncio.run(cli.provision_db_role(settings)) == 0
    assert asyncio.run(cli.sync_questionnaires(settings)) == 0
    assert asyncio.run(cli.sync_categories(settings)) == 0
    assert asyncio.run(cli.sync_catalogue(settings)) == 0
    assert asyncio.run(cli.sync_consent(settings)) == 0
    assert asyncio.run(cli.sync_templates(settings)) == 0
    assert asyncio.run(cli.sync_prompts(settings)) == 0


@pytest.fixture(scope="session")
def migrated() -> None:
    """Bring the test database to the latest migration once per run."""
    prepare_database()


@pytest.fixture
async def api(migrated: None, app: FastAPI, client: AsyncClient) -> AsyncIterator[ApiHarness]:
    """Client plus helpers for auth flows, with rate-limit counters reset."""
    await app.state.resources.redis.flushdb()
    harness = ApiHarness(app, client)
    try:
        yield harness
    finally:
        await harness.aclose()


@pytest.fixture
async def owner_sessions(migrated: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions as the schema owner (a superuser in tests): bypasses RLS and privileges.
    For setting up and inspecting state the application role must not be able to touch."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
