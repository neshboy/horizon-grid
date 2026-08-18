"""Redis-backed cache for provider results, keyed by (provider_id, ioc_type, ioc_value).

Provider connectors are pure and stateless; caching lives entirely in the
orchestrator layer so no individual connector needs to know about Redis.
"""
import hashlib
import json
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import get_settings

_pool: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _pool


def cache_key(provider_id: str, ioc_type: str, ioc_value: str) -> str:
    digest = hashlib.sha256(ioc_value.encode("utf-8")).hexdigest()
    return f"provider_cache:{provider_id}:{ioc_type}:{digest}"


async def get_cached_result(provider_id: str, ioc_type: str, ioc_value: str) -> Optional[dict[str, Any]]:
    raw = await get_redis().get(cache_key(provider_id, ioc_type, ioc_value))
    return json.loads(raw) if raw else None


async def set_cached_result(
    provider_id: str, ioc_type: str, ioc_value: str, payload: dict[str, Any], ttl_seconds: int
) -> None:
    await get_redis().set(
        cache_key(provider_id, ioc_type, ioc_value), json.dumps(payload, default=str), ex=ttl_seconds
    )


class RateLimiter:
    """Simple fixed-window limiter, one window key per provider, stored in Redis
    so limits are enforced across all workers, not just the current process."""

    def __init__(self, provider_id: str, max_calls: int, window_seconds: int) -> None:
        self._key = f"rate_limit:{provider_id}"
        self._max_calls = max_calls
        self._window_seconds = window_seconds

    async def allow(self) -> bool:
        r = get_redis()
        current = await r.incr(self._key)
        if current == 1:
            await r.expire(self._key, self._window_seconds)
        return current <= self._max_calls
