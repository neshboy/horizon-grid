"""Regression coverage for POST /auth/logout -- a real gap found live
during overnight QA: there was no logout route at all. The frontend's
"Log out" only ever cleared localStorage client-side, so a still-unexpired
access token (up to ~30 min) and its refresh token (up to 7 days) both kept
working indefinitely after "logging out". This confirms the new endpoint
bumps token_version (the same mechanism app/core/users.py's reset_password()
already uses for an admin-initiated revocation) so both the just-used
access token and the refresh token stop working immediately.
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
    import app.core.db as db_module

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)
    yield
    await db_module._engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _unique_email(prefix: str) -> str:
    # Every email in this file round-trips through the real HTTP /auth/login
    # endpoint's EmailStr validation -- email-validator explicitly rejects
    # "*.test" as a reserved special-use TLD (see test_auth_login_rate_limit.py's
    # identical helper/comment, confirmed live the same way here), so this
    # uses a real-looking domain instead.
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _delete_user(user_id: uuid.UUID) -> None:
    from sqlalchemy import delete

    from app.core.db import new_session
    from app.models.runtime_config import ConfigAuditLog

    async with new_session() as db:
        # A real login (exercised by every test in this file) writes a
        # ConfigAuditLog row referencing this user -- must go first, or the
        # user delete below hits a foreign-key violation.
        await db.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor_user_id == user_id))
        await db.commit()
    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


@pytest.mark.asyncio
async def test_logout_invalidates_the_access_token_that_called_it(client):
    email = _unique_email("logout")
    created = await create_user(email, "pw-12345678", "Logout Test", Role.VIEWER, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        login_resp = await client.post(f"{API}/auth/login", json={"email": email, "password": "pw-12345678"})
        access_token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Token works before logout.
        assert (await client.get(f"{API}/auth/me", headers=headers)).status_code == 200

        logout_resp = await client.post(f"{API}/auth/logout", headers=headers)
        assert logout_resp.status_code == 204

        # The exact same access token must be dead immediately after logout.
        after = await client.get(f"{API}/auth/me", headers=headers)
        assert after.status_code == 401
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_logout_invalidates_the_refresh_token_too(client):
    email = _unique_email("logout2")
    created = await create_user(email, "pw-12345678", "Logout Test 2", Role.VIEWER, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        login_resp = await client.post(f"{API}/auth/login", json={"email": email, "password": "pw-12345678"})
        access_token = login_resp.json()["access_token"]
        refresh_token = login_resp.json()["refresh_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        assert (await client.post(f"{API}/auth/logout", headers=headers)).status_code == 204

        refresh_resp = await client.post(f"{API}/auth/refresh", json={"refresh_token": refresh_token})
        assert refresh_resp.status_code == 401
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_logout_requires_authentication(client):
    resp = await client.post(f"{API}/auth/logout")
    assert resp.status_code == 401
