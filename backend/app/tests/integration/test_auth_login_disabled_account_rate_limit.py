"""Regression coverage for a P2 found live during overnight QA against
app/api/routes/auth.py's login(): the disabled-account branch
(`if not user.is_active: raise HTTPException(403, "Account disabled")`) is
only reached AFTER the correct password has already been verified, but it
never consulted or incremented the per-account RateLimiter that every other
failure branch of this endpoint uses.

That meant a caller who already holds a valid (e.g. leaked, or belonging to
a just-offboarded/suspected-compromised employee) credential for a disabled
account could hit this endpoint at unlimited speed, forcing a full bcrypt
verify_password() computation on every single request forever, with zero
throttling -- an unauthenticated CPU-exhaustion amplification vector.

This mirrors test_auth_login_rate_limit.py's fixtures/conventions exactly,
but exercises the correct-password/disabled-account branch specifically.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.users import create_user, set_user_active
from app.main import app
from app.models.user import Role, User

API = get_settings().api_v1_prefix


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    import app.core.cache as cache_module
    import app.core.db as db_module

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)
    # Same rationale as test_auth_login_rate_limit.py's identical fixture:
    # RateLimiter's module-level _pool is bound to whichever event loop was
    # running when it was first created, and pytest-asyncio gives each test
    # function its own fresh loop.
    cache_module._pool = None
    yield
    await db_module._engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _unique_email(prefix: str) -> str:
    # See test_auth_login_rate_limit.py's identical helper: every email here
    # round-trips through the real HTTP endpoint's EmailStr validation, which
    # rejects "*.test" as a reserved special-use TLD.
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _delete_user(user_id: uuid.UUID) -> None:
    from sqlalchemy import delete

    from app.core.db import new_session
    from app.models.runtime_config import ConfigAuditLog

    async with new_session() as db:
        # See test_auth_login_rate_limit.py's identical cleanup helper for
        # why config_audit_log rows are deleted first.
        await db.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor_user_id == user_id))
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
        await db.commit()


@pytest.mark.asyncio
async def test_correct_password_against_disabled_account_is_rate_limited_after_the_configured_max(client):
    """Reproduces the P2 exactly: the SAME correct password against a
    disabled account, sent past the configured max attempts, must
    eventually be throttled with a 429 -- not return 403 forever."""
    settings = get_settings()
    email = _unique_email("qa-login-disabled-throttle")
    created = await create_user(email, "the-real-password-1", "QA Disabled", Role.ANALYST, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        await set_user_active(user_id, False, None, "actor@qa.test")

        for _ in range(settings.login_rate_limit_max_attempts):
            response = await client.post(
                f"{API}/auth/login", json={"email": email, "password": "the-real-password-1"}
            )
            assert response.status_code == 403
            assert response.json()["detail"] == "Account disabled"

        blocked = await client.post(
            f"{API}/auth/login", json={"email": email, "password": "the-real-password-1"}
        )
        assert blocked.status_code == 429, (
            "a correct password against a disabled account can never succeed regardless of "
            "request rate, so it must be bounded by the same per-account limiter as every "
            "other branch of this endpoint that cannot result in a usable session"
        )
        assert "Too many login attempts" in blocked.json()["detail"]
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_disabled_account_and_wrong_password_share_the_same_per_account_budget(client):
    """The disabled-account (correct password) branch and the
    wrong-password branch must consume the SAME per-account rate-limit
    budget, since both are keyed on the same attempted email. Mixing the
    two attempt types must still trip the shared limiter."""
    settings = get_settings()
    email = _unique_email("qa-login-disabled-mixed")
    created = await create_user(email, "the-real-password-1", "QA Disabled Mixed", Role.ANALYST, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        await set_user_active(user_id, False, None, "actor@qa.test")

        half = settings.login_rate_limit_max_attempts // 2
        for _ in range(half):
            response = await client.post(
                f"{API}/auth/login", json={"email": email, "password": "the-real-password-1"}
            )
            assert response.status_code == 403
        for _ in range(settings.login_rate_limit_max_attempts - half):
            response = await client.post(f"{API}/auth/login", json={"email": email, "password": "wrong-password"})
            assert response.status_code == 401

        blocked = await client.post(f"{API}/auth/login", json={"email": email, "password": "the-real-password-1"})
        assert blocked.status_code == 429, "correct-password and wrong-password attempts must share one budget"
    finally:
        await _delete_user(user_id)
