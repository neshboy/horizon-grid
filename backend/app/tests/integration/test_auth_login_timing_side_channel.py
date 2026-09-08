"""Regression coverage for a P2 timing side-channel in POST /auth/login
(app/api/routes/auth.py's login()), found live during a mission-critical-
readiness review.

Root cause: `if not user or not verify_password(payload.password,
user.hashed_password):` relied on Python's `or` short-circuiting, so
verify_password() -- a deliberately slow bcrypt comparison -- only ever ran
when a matching User row was found. A login attempt against a nonexistent
email returned right after the SELECT (no bcrypt work), while an attempt
against a real email with a wrong password paid the full bcrypt cost too.
Live timing against the running stack showed a stable ~400-500ms gap
(~350-390ms for nonexistent emails vs ~750-910ms for real ones), letting an
unauthenticated caller enumerate which emails have real accounts using only
a handful of timed samples per address -- no credentials or rate-limit
bypass required.

Rather than asserting on wall-clock timing (flaky under CI/shared-stack
load), this test asserts on the actual root cause directly: verify_password
must be invoked exactly once by login(), with the same effective cost,
whether or not a matching user was found. That is the property that makes
the two response times indistinguishable.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import auth as auth_routes
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
    # Mirrors test_auth_login_rate_limit.py's identical fixture: RateLimiter's
    # module-level pool is lazily bound to whichever event loop was running
    # when it was first used, and pytest-asyncio gives each test its own
    # fresh loop.
    cache_module._pool = None
    yield
    await db_module._engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _delete_user(user_id: uuid.UUID) -> None:
    from sqlalchemy import delete

    from app.core.db import new_session
    from app.models.runtime_config import ConfigAuditLog

    async with new_session() as db:
        await db.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor_user_id == user_id))
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
        await db.commit()


@pytest.mark.asyncio
async def test_verify_password_runs_even_when_no_user_is_found(client, monkeypatch):
    """Before the fix, verify_password() was never called at all for a
    nonexistent email -- `not user` short-circuited the `or` before
    verify_password's bcrypt comparison ran. This is the exact defect that
    created the timing gap: no bcrypt call means a fast response for
    "no such account", vs. a slow one for "account exists, wrong password".
    """
    calls = []
    real_verify_password = auth_routes.verify_password

    def _spy(plain_password, hashed_password):
        calls.append(hashed_password)
        return real_verify_password(plain_password, hashed_password)

    monkeypatch.setattr(auth_routes, "verify_password", _spy)

    nonexistent_email = _unique_email("qa-timing-nonexistent")
    response = await client.post(
        f"{API}/auth/login", json={"email": nonexistent_email, "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert len(calls) == 1, (
        "verify_password must run exactly once even when no matching user "
        "row exists, otherwise 'no such account' responses skip the bcrypt "
        "cost that 'account exists, wrong password' responses pay, "
        "reopening the email-enumeration timing side-channel"
    )
    # Compared against the precomputed dummy hash, not None/empty -- proves
    # real bcrypt work happens, not a cheap short-circuit.
    assert calls[0] == auth_routes._DUMMY_PASSWORD_HASH


@pytest.mark.asyncio
async def test_nonexistent_and_existing_email_pay_the_same_bcrypt_cost(client, monkeypatch):
    """Directly compares the two populations from the live finding: a
    nonexistent email vs. a real email with a wrong password. Both must
    invoke verify_password exactly once, so neither path can be
    distinguished by the presence/absence of the expensive bcrypt call.
    """
    calls = []
    real_verify_password = auth_routes.verify_password

    def _spy(plain_password, hashed_password):
        calls.append(hashed_password)
        return real_verify_password(plain_password, hashed_password)

    monkeypatch.setattr(auth_routes, "verify_password", _spy)

    real_email = _unique_email("qa-timing-real")
    created = await create_user(real_email, "the-real-password-1", "QA Timing", Role.ANALYST, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        nonexistent_email = _unique_email("qa-timing-nonexistent-2")

        resp_nonexistent = await client.post(
            f"{API}/auth/login", json={"email": nonexistent_email, "password": "wrong-password"}
        )
        resp_existing_wrong_password = await client.post(
            f"{API}/auth/login", json={"email": real_email, "password": "wrong-password"}
        )

        assert resp_nonexistent.status_code == 401
        assert resp_existing_wrong_password.status_code == 401
        # Both branches must have called verify_password exactly once each
        # (two calls total) -- neither response short-circuited past the
        # bcrypt comparison.
        assert len(calls) == 2, (
            "both a nonexistent email and an existing email with a wrong "
            "password must invoke verify_password exactly once each"
        )
    finally:
        await _delete_user(user_id)
