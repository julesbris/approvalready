from httpx import AsyncClient
from pydantic import SecretStr

from app.core.config import Environment


async def test_security_headers_on_api_responses(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    h = response.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'none'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"
    assert "strict-transport-security" not in h  # only behind TLS in production


async def test_hsts_and_no_docs_in_production(client_factory) -> None:  # type: ignore[no-untyped-def]
    async with client_factory(
        app_env=Environment.PRODUCTION,
        secret_key=SecretStr("y" * 48),
        cors_origins=["https://app.approvalready.com.au"],
    ) as client:
        live = await client.get("/health/live")
        docs = await client.get("/docs")
        schema = await client.get("/openapi.json")
    assert live.headers["strict-transport-security"].startswith("max-age=")
    assert docs.status_code == 404
    assert schema.status_code == 404


async def test_request_id_generated(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert len(response.headers["x-request-id"]) == 32


async def test_well_formed_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"x-request-id": "edge-abc12345"})
    assert response.headers["x-request-id"] == "edge-abc12345"


async def test_malformed_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"x-request-id": "bad id\r\ninject"})
    assert response.headers["x-request-id"] != "bad id\r\ninject"
    assert len(response.headers["x-request-id"]) == 32


async def test_untrusted_host_rejected_with_headers(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"host": "evil.example"})
    assert response.status_code == 400
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "x-request-id" in response.headers


async def test_container_health_check_host_is_always_trusted(client: AsyncClient) -> None:
    # Docker HEALTHCHECK calls http://127.0.0.1:8000 and the web container calls http://api:8000,
    # even when ALLOWED_HOSTS only lists public hostnames.
    for host in ("127.0.0.1:8000", "api:8000"):
        response = await client.get("/health/live", headers={"host": host})
        assert response.status_code == 200, host


async def test_cors_allows_configured_origin(client: AsyncClient) -> None:
    response = await client.options(
        "/health/live",
        headers={"origin": "http://localhost:3000", "access-control-request-method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_cors_rejects_unknown_origin(client: AsyncClient) -> None:
    response = await client.options(
        "/health/live",
        headers={"origin": "https://evil.example", "access-control-request-method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
