"""Regression coverage for a real P1 found live during a Redis outage
(`docker compose stop redis` against the running stack):
app/core/cache.py's RateLimiter.allow() called `await r.incr(self._key)`
with no timeout and no exception handling at all. Confirmed live:

  * POST /api/v1/lookup/stream (which calls RateLimiter.allow()
    unconditionally on every call) hung for several seconds and then
    surfaced as a bare, content-free Starlette 500 ("Internal Server
    Error") -- the underlying redis.exceptions.ConnectionError propagated
    straight out of allow() with nothing anywhere between it and FastAPI's
    default handler.
  * POST /api/v1/auth/login's failed-credential branch (also gated by
    RateLimiter.allow()) never returned at all within a 10s client
    timeout.

Both are far worse than this app's own GET /health/detailed docstring,
which documents a Redis outage as merely DEGRADED (rate limiting
"breaks" cleanly, other endpoints keep working) -- in practice it was an
unbounded hang ending in a content-free 500.

The fix bounds every Redis call inside allow() with asyncio.wait_for and
raises RateLimiterUnavailable (caught by an app/main.py exception handler
that returns a clean 503) instead of letting a raw redis.exceptions error
-- or an unbounded hang -- escape.
"""
import asyncio

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

import app.core.cache as cache_module
from app.core.cache import RateLimiter, RateLimiterUnavailable


class _BrokenRedis:
    """Stands in for a real redis.asyncio.Redis client whose underlying
    connection is unreachable -- mirrors the exact live failure mode
    (redis.exceptions.ConnectionError raised out of incr())."""

    async def incr(self, key):
        raise RedisConnectionError("Error -2 connecting to redis:6379. Name or service not known.")

    async def expire(self, key, ttl):
        raise AssertionError("expire() must not be called when incr() itself already failed")


class _HangingRedis:
    """Stands in for a Redis call that never returns at all (the exact
    shape of the live login hang -- past a 10s client timeout with no
    response whatsoever) rather than failing fast with a clean error."""

    async def incr(self, key):
        await asyncio.sleep(3600)  # "never" for test purposes

    async def expire(self, key, ttl):
        raise AssertionError("expire() must not be called when incr() never returned")


@pytest.mark.asyncio
async def test_allow_raises_rate_limiter_unavailable_instead_of_a_raw_redis_error(monkeypatch):
    monkeypatch.setattr(cache_module, "get_redis", lambda: _BrokenRedis())

    limiter = RateLimiter("outage-test-connection-error", max_calls=5, window_seconds=60)

    # Before the fix: this raised redis.exceptions.ConnectionError straight
    # out of allow(), uncaught anywhere -- confirmed live to surface as a
    # bare Starlette 500 with no actionable detail.
    with pytest.raises(RateLimiterUnavailable):
        await limiter.allow()


@pytest.mark.asyncio
async def test_allow_times_out_instead_of_hanging_forever_when_redis_never_responds(monkeypatch):
    monkeypatch.setattr(cache_module, "get_redis", lambda: _HangingRedis())
    # Keep the test itself fast -- the real fix's constant is 3s, but the
    # behavior being verified (a bound exists at all) doesn't depend on the
    # exact value.
    monkeypatch.setattr(cache_module, "_REDIS_CALL_TIMEOUT_SECONDS", 0.05)

    limiter = RateLimiter("outage-test-hang", max_calls=5, window_seconds=60)

    # Before the fix: `await r.incr(self._key)` had no asyncio.wait_for
    # around it, so a Redis call that never returns meant allow() never
    # returned either -- confirmed live as a failed /auth/login attempt
    # that outlived a 10s client timeout entirely. This must now raise
    # promptly instead of hanging.
    with pytest.raises(RateLimiterUnavailable):
        await asyncio.wait_for(limiter.allow(), timeout=2.0)


@pytest.mark.asyncio
async def test_allow_still_works_normally_when_redis_is_healthy(monkeypatch):
    """Sanity check: the fix must not change behavior on the happy path."""

    class _HealthyRedis:
        def __init__(self):
            self.calls = []

        async def incr(self, key):
            self.calls.append(key)
            return len(self.calls)

        async def expire(self, key, ttl):
            pass

    fake = _HealthyRedis()
    monkeypatch.setattr(cache_module, "get_redis", lambda: fake)

    limiter = RateLimiter("outage-test-healthy", max_calls=2, window_seconds=60)

    assert await limiter.allow() is True
    assert await limiter.allow() is True
    assert await limiter.allow() is False  # third call exceeds max_calls=2
