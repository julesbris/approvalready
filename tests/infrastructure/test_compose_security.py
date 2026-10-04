"""Guards on the production Compose file: only the proxy is reachable from outside.

Run: uv run --project apps/api pytest tests/infrastructure
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict[str, Any]:
    with (ROOT / name).open() as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


@pytest.fixture(scope="module")
def prod() -> dict[str, Any]:
    return _load("docker-compose.prod.yml")


@pytest.fixture(scope="module")
def dev() -> dict[str, Any]:
    return _load("docker-compose.yml")


def test_only_proxy_publishes_ports(prod: dict[str, Any]) -> None:
    publishing = {name for name, svc in prod["services"].items() if svc.get("ports")}
    assert publishing == {"proxy"}


def test_proxy_publishes_only_web_ports(prod: dict[str, Any]) -> None:
    ports = {str(p).split("/")[0] for p in prod["services"]["proxy"]["ports"]}
    assert ports == {"80:80", "443:443"}


@pytest.mark.parametrize("service", ["db", "redis"])
def test_data_services_are_internal_only(prod: dict[str, Any], service: str) -> None:
    svc = prod["services"][service]
    assert "ports" not in svc
    assert "expose" not in svc
    assert svc["networks"] == ["data"]
    assert prod["networks"]["data"]["internal"] is True


def test_proxy_cannot_reach_data_network(prod: dict[str, Any]) -> None:
    assert "data" not in prod["services"]["proxy"]["networks"]
    assert "data" not in prod["services"]["web"]["networks"]


def test_redis_requires_password(prod: dict[str, Any]) -> None:
    assert "--requirepass" in prod["services"]["redis"]["command"]


def test_production_secrets_are_mandatory(prod: dict[str, Any]) -> None:
    raw = (ROOT / "docker-compose.prod.yml").read_text()
    for var in ("SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD"):
        assert f"${{{var}:?" in raw, f"{var} must fail fast when unset"


def test_postgres_major_version_is_18(prod: dict[str, Any], dev: dict[str, Any]) -> None:
    assert prod["services"]["db"]["image"].startswith("postgres:18")
    assert dev["services"]["db"]["image"].startswith("postgres:18")


def test_dev_ports_bind_to_loopback_only(dev: dict[str, Any]) -> None:
    for name, svc in dev["services"].items():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} exposes {port} beyond loopback"
