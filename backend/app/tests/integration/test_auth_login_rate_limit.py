"""Regression coverage for login brute-force rate limiting (app/api/routes/
auth.py's login()): a real gap found during a mission-critical-readiness
review -- failed logins were logged/audited but never throttled at all, so
nothing stopped an unlimited-speed credential-stuffing attempt against any
known email address.

The limiter is keyed on the ATTEMPTED email (case-normalized), checked
BEFORE password verification, so a nonexistent email is enough to exercise
it -- no real user/password needed for the throttling behavior itself. A
separate test confirms a real user's legitimate logins within the limit are
unaffected.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.users import create_user
from app.main import app
from app.models.user import Role, User

API = get_settings().api_v1_prefix


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    import app.core.cache as cache_module
    import app.core.db as db_module

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)
    # This file is the first to exercise RateLimiter (app/core/cache.py)
    # across more than one test function -- its module-level `_pool` is
    # created lazily on first use and bound to whichever event loop was
    # running at that moment. pytest-asyncio gives each test function its
    # own fresh loop, so a second test reusing test 1's already-bound pool
    # fails with "RuntimeError: Event loop is closed" (confirmed live).
    # Resetting it here, mirroring test_dashboard_service_db.py's identical
    # fixture, forces a fresh pool bound to THIS test's loop.
    cache_module._pool = None
    yield
    await db_module._engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _unique_email(prefix: str) -> str:
    # Every email in this file round-trips through the real HTTP endpoint's
    # EmailStr validation (unlike other test files' same-named helper, which
    # mostly feeds create_user() directly, bypassing that check) --
    # email-validator explicitly rejects "*.test" as a reserved special-use
    # TLD, confirmed live (a 422 on every request, not the rate-limit
    # behavior under test), so this uses a real-looking domain instead.
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _delete_user(user_id: uuid.UUID) -> None:
    from sqlalchemy import delete

    from app.core.db import new_session
    from app.models.runtime_config import ConfigAuditLog

    async with new_session() as db:
        # A real, successful /auth/login writes a config_audit_log row with
        # actor_user_id = this user (app/core/users.py's
        # record_login_success) -- config_audit_log_actor_user_id_fkey has
        # no ON DELETE SET NULL at the DB level, despite that column's own
        # docstring saying audit history is meant to survive the actor being
        # deleted later. This is a known, pre-existing, test-only gap (no
        # production route hard-deletes a user), not something this test is
        # about -- deleting this test user's own audit rows first is the
        # pragmatic cleanup, not a workaround for anything this test asserts.
        await db.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor_user_id == user_id))
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
        await db.commit()


@pytest.mark.asyncio
async def test_repeated_failed_logins_are_rate_limited_after_the_configured_max(client):
    settings = get_settings()
    email = _unique_email("qa-login-throttle")

    for _ in range(settings.login_rate_limit_max_attempts):
        response = await client.post(f"{API}/auth/login", json={"email": email, "password": "wrong-password"})
        assert response.status_code == 401

    blocked = await client.post(f"{API}/auth/login", json={"email": email, "password": "wrong-password"})
    assert blocked.status_code == 429
    assert "Too many login attempts" in blocked.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limit_is_keyed_per_email_not_shared_globally(client):
    settings = get_settings()
    exhausted_email = _unique_email("qa-login-throttle-a")
    other_email = _unique_email("qa-login-throttle-b")

    for _ in range(settings.login_rate_limit_max_attempts):
        response = await client.post(
            f"{API}/auth/login", json={"email": exhausted_email, "password": "wrong-password"}
        )
        assert response.status_code == 401
    blocked = await client.post(f"{API}/auth/login", json={"email": exhausted_email, "password": "wrong-password"})
    assert blocked.status_code == 429

    unaffected = await client.post(f"{API}/auth/login", json={"email": other_email, "password": "wrong-password"})
    assert unaffected.status_code == 401, "a different email must have its own, unaffected budget"


@pytest.mark.asyncio
async def test_legitimate_logins_within_the_limit_are_unaffected(client):
    settings = get_settings()
    email = _unique_email("qa-login-legit")
    created = await create_user(email, "correct-password-1", "QA Legit", Role.ANALYST, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        assert settings.login_rate_limit_max_attempts >= 3, "test assumes headroom under the real configured limit"
        for _ in range(3):
            response = await client.post(f"{API}/auth/login", json={"email": email, "password": "correct-password-1"})
            assert response.status_code == 200
            assert "access_token" in response.json()
    finally:
        await _delete_user(user_id)
