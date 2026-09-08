"""Regression coverage for a real P1 found live during a genuine Redis
outage (`docker compose stop redis` against the running dev stack):
POST /api/v1/auth/login's failed-credential branch calls
app/core/cache.py's RateLimiter.allow(), which used to call Redis with no
timeout and no exception handling. Confirmed live: a wrong-password login
attempt during the outage never returned at all within a 10s client
timeout (curl HTTP_CODE=000), instead of the normal 401.

This test simulates the same outage at the RateLimiter's Redis client
(rather than actually stopping the shared dev-stack Redis container, which
would be flaky/disruptive for a unit-style CI run) and asserts the route
now fails fast with a clean 503 instead of hanging or leaking a raw 500.
"""
import httpx
import pytest
import pytest_asyncio
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.cache as cache_module
from app.core.config import get_settings
from app.main import app

API = get_settings().api_v1_prefix


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    import app.core.db as db_module

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)
    cache_module._pool = None
    yield
    await db_module._engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class _RedisDownDuringOutage:
    """Every call raises exactly the exception confirmed live in the
    backend logs during the real outage: redis.exceptions.ConnectionError
    ("Error -2 connecting to redis:6379. Name or service not known")."""

    async def incr(self, key):
        raise RedisConnectionError("Error -2 connecting to redis:6379. Name or service not known.")

    async def expire(self, key, ttl):
        raise AssertionError("expire() must not be reached when incr() already failed")


@pytest.mark.asyncio
async def test_failed_login_returns_a_clean_503_during_a_redis_outage_instead_of_hanging(client, monkeypatch):
    monkeypatch.setattr(cache_module, "get_redis", lambda: _RedisDownDuringOutage())

    # Before the fix: this call either hung indefinitely (confirmed live,
    # past a 10s client timeout with zero response) or, once something
    # eventually surfaced, came back as a bare, content-free Starlette 500
    # -- never the clear, actionable error a caller can retry on.
    response = await client.post(
        f"{API}/auth/login",
        json={"email": "nonexistent-user-for-outage-test@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Rate limiting temporarily unavailable, please retry."}
