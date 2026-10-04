"""Liveness, readiness and version endpoints.

* ``/health/live``  - the process is up and serving. Never touches dependencies, so a
  database outage does not cause the orchestrator to restart healthy API containers.
* ``/health/ready`` - PostgreSQL and Redis are reachable. Returns 503 otherwise, which
  takes the instance out of rotation without killing it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import Settings
from app.core.resources import Resources

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "error"]


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class DependencyCheck(BaseModel):
    status: CheckStatus
    latency_ms: float


class ReadyResponse(BaseModel):
    status: CheckStatus
    checks: dict[str, DependencyCheck]


class VersionResponse(BaseModel):
    name: str
    version: str
    git_sha: str
    environment: str


async def _check_database(resources: Resources) -> None:
    async with resources.engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        if result.scalar_one() != 1:
            raise RuntimeError("unexpected SELECT 1 result")


async def _check_redis(resources: Resources) -> None:
    if not await resources.redis.ping():
        raise RuntimeError("redis ping returned falsy")


async def _timed(
    name: str, check: Awaitable[None], limit_seconds: float
) -> tuple[str, DependencyCheck]:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(limit_seconds):
            await check
        outcome: CheckStatus = "ok"
    except Exception:
        # Details go to logs only; the public response must not leak hostnames or DSNs.
        logger.warning("readiness check failed", extra={"check": name}, exc_info=True)
        outcome = "error"
    return name, DependencyCheck(
        status=outcome, latency_ms=round((time.perf_counter() - started) * 1000, 2)
    )


@router.get("/health/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse()


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
async def ready(request: Request, response: Response) -> ReadyResponse:
    resources: Resources = request.app.state.resources
    settings: Settings = request.app.state.settings
    timeout = settings.health_check_timeout_seconds
    results = await asyncio.gather(
        _timed("database", _check_database(resources), timeout),
        _timed("redis", _check_redis(resources), timeout),
    )
    checks = dict(results)
    healthy = all(check.status == "ok" for check in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="ok" if healthy else "error", checks=checks)


@router.get("/version", response_model=VersionResponse)
async def version(request: Request) -> VersionResponse:
    settings: Settings = request.app.state.settings
    return VersionResponse(
        name=settings.app_name,
        version=settings.app_version,
        git_sha=settings.git_sha,
        environment=settings.app_env.value,
    )
