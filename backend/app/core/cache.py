"""Redis-backed cache for provider results, keyed by (provider_id, ioc_type, ioc_value).

Provider connectors are pure and stateless; caching lives entirely in the
orchestrator layer so no individual connector needs to know about Redis.
"""
import asyncio
import hashlib
import json
from typing import Any, Optional

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings

_pool: Optional[aioredis.Redis] = None
_pool_loop: Optional[asyncio.AbstractEventLoop] = None

# Mirrors app/main.py's _HEALTH_CHECK_TIMEOUT_SECONDS -- same rationale (bound
# a Redis round-trip to a few seconds instead of whatever redis-py's internal
# connect/retry backoff happens to add up to) applied to the request path
# rather than just the health check.
_REDIS_CALL_TIMEOUT_SECONDS = 3.0


class RateLimiterUnavailable(RuntimeError):
    """Raised by RateLimiter.allow() when Redis cannot be reached (or the
    call times out) instead of letting the underlying redis.exceptions error
    fall all the way out of the route.

    Real P1 found live: allow() previously called r.incr()/r.expire() with no
    timeout and no exception handling at all. During a genuine Redis outage
    (confirmed via `docker compose stop redis`), POST /api/v1/lookup/stream
    hung for several seconds and then surfaced as a bare, content-free
    Starlette 500 ("Internal Server Error"), and POST /api/v1/auth/login's
    failed-credential branch hung indefinitely (never returned within a 10s
    client timeout) -- both far worse than the /health/detailed docstring's
    documented "DEGRADED" contract for a Redis outage. app/main.py registers
    a handler for this exception that turns it into a clean 503 instead.
    """


def get_redis() -> aioredis.Redis:
    """Real bug found live during overnight QA (via a new call site --
    auth.py's register() now also rate-limits through here -- but the
    fragility itself was pre-existing): this cached a single client
    forever at module scope, bound to whichever event loop happened to be
    running the first time it was created. Each pytest-asyncio test
    function/module gets its OWN event loop; once the loop the client was
    created under closes, the cached client's underlying connection is
    unusable and every call raises "RuntimeError: Event loop is closed" --
    reproduced live by running test_auth_login_rate_limit.py (which uses
    this) immediately before test_auth_registration.py's rate-limited
    register() call. Recreating the client whenever the running loop
    differs from the one it was created for closes this for good, not
    just for this one test-file pairing -- a fresh worker process or any
    other loop-recreation scenario gets the same protection."""
    global _pool, _pool_loop
    current_loop = asyncio.get_event_loop()
    if _pool is None or _pool_loop is not current_loop:
        _pool = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        _pool_loop = current_loop
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
        try:
            current = await asyncio.wait_for(r.incr(self._key), timeout=_REDIS_CALL_TIMEOUT_SECONDS)
            if current == 1:
                await asyncio.wait_for(r.expire(self._key, self._window_seconds), timeout=_REDIS_CALL_TIMEOUT_SECONDS)
        except (RedisError, asyncio.TimeoutError) as exc:
            raise RateLimiterUnavailable(f"Redis unavailable for rate limiting: {exc!r}") from exc
        return current <= self._max_calls
