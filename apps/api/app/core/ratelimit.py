"""Fixed-window counters in Redis for throttling and rate limiting.

Keys are namespaced ``rl:<bucket>:<subject>``. Subjects that contain personal data (email
addresses) are hashed before use so Redis never holds them in clear text.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from redis.asyncio import Redis


def subject_digest(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Limit:
    bucket: str
    max_hits: int
    window_seconds: int


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def _key(limit: Limit, subject: str) -> str:
        return f"rl:{limit.bucket}:{subject}"

    async def hit(self, limit: Limit, subject: str) -> int:
        """Count one hit and return the count in the current window."""
        key = self._key(limit, subject)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, limit.window_seconds, nx=True)
            count, _ = await pipe.execute()
        return int(count)

    async def count(self, limit: Limit, subject: str) -> int:
        value = await self.redis.get(self._key(limit, subject))
        return int(value or 0)

    async def exceeded(self, limit: Limit, subject: str) -> bool:
        return await self.count(limit, subject) >= limit.max_hits

    async def retry_after(self, limit: Limit, subject: str) -> int:
        ttl = await self.redis.ttl(self._key(limit, subject))
        return max(int(ttl), 1)

    async def reset(self, limit: Limit, subject: str) -> None:
        await self.redis.delete(self._key(limit, subject))
