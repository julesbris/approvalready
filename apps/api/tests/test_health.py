import pytest
from httpx import AsyncClient

from tests.conftest import TEST_DATABASE_URL


async def test_live_does_not_need_dependencies(client_factory) -> None:  # type: ignore[no-untyped-def]
    async with client_factory(
        database_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/none",
        redis_url="redis://127.0.0.1:1/0",
    ) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_version(client: AsyncClient) -> None:
    response = await client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "ApprovalReady API"
    assert body["environment"] == "test"
    assert set(body) == {"name", "version", "git_sha", "environment"}


@pytest.mark.integration
async def test_ready_when_dependencies_up(migrated: None, client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"


@pytest.mark.integration
async def test_ready_reports_redis_outage(migrated: None, client_factory) -> None:  # type: ignore[no-untyped-def]
    async with client_factory(redis_url="redis://127.0.0.1:1/0") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "error"


async def test_ready_reports_database_outage_without_leaking_dsn(client_factory) -> None:  # type: ignore[no-untyped-def]
    bad_dsn = "postgresql+psycopg://secretuser:secretpass@127.0.0.1:1/secretdb"
    async with client_factory(
        database_url=bad_dsn, redis_url="redis://127.0.0.1:1/0", health_check_timeout_seconds=1.0
    ) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"]["status"] == "error"
    for secret in ("secretuser", "secretpass", "secretdb", "127.0.0.1"):
        assert secret not in response.text
    assert TEST_DATABASE_URL not in response.text


@pytest.mark.integration
async def test_ready_refuses_a_role_that_bypasses_rls_in_production(
    migrated: None,
    client_factory,  # type: ignore[no-untyped-def]
) -> None:
    from tests.conftest import TEST_APP_DATABASE_URL

    production = {
        "app_env": "production",
        "secret_key": "x" * 40,
        "cors_origins": ["https://app.approvalready.com.au"],
        "email_provider": "console",
        "migration_database_url": None,
    }
    async with client_factory(database_url=TEST_DATABASE_URL, **production) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database_role"]["status"] == "error"

    async with client_factory(database_url=TEST_APP_DATABASE_URL, **production) as client:
        response = await client.get("/health/ready")
    assert response.json()["checks"]["database_role"]["status"] == "ok"
