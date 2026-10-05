"""Process-wide infrastructure clients (database engine, Redis) and their lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.email import EmailProvider, create_email_provider


@dataclass
class Resources:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    email: EmailProvider

    async def close(self) -> None:
        await self.redis.aclose()
        await self.engine.dispose()


def create_resources(settings: Settings) -> Resources:
    engine = create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        connect_args={"connect_timeout": int(max(1, settings.database_connect_timeout_seconds))},
    )
    redis = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.health_check_timeout_seconds,
        socket_timeout=settings.health_check_timeout_seconds,
        decode_responses=True,
    )
    return Resources(
        engine=engine,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        redis=redis,
        email=create_email_provider(settings),
    )
