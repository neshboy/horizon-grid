"""Regression coverage for closing public self-registration: once at
least one user exists, POST /auth/register must be rejected outright
(403) rather than silently creating a new Analyst account, and must not
create any row when rejected.

The true "very first user becomes admin" bootstrap path is intentionally
NOT exercised here via a real HTTP call, because these integration tests
run against the same database as normal dev/prod use (see
app/core/config.py's database_url default) -- truncating the users table
to simulate an empty install would destroy real accounts. That branch is
unchanged by this test's scope (the reject path is what's new) and was
already relied upon by the existing Setup Wizard / first-run flow.
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
    return f"{prefix}-{uuid.uuid4().hex[:10]}@qa.test"


async def _delete_user(user_id: uuid.UUID) -> None:
    from app.core.db import new_session

    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


@pytest.mark.asyncio
async def test_register_rejected_once_a_user_already_exists(client):
    existing_email = _unique_email("qa-register-seed")
    seed = await create_user(existing_email, "pw-12345", "Seed", Role.ADMIN, None, "actor@qa.test")
    existing_id = uuid.UUID(seed["id"])

    new_email = f"qa-register-attempt-{uuid.uuid4().hex[:10]}@example.com"
    try:
        response = await client.post(
            f"{API}/auth/register",
            json={"email": new_email, "password": "pw-12345678", "full_name": "Should Not Exist"},
        )
        assert response.status_code == 403
        assert "Administration" in response.json()["detail"]

        from app.core.db import new_session

        async with new_session() as db:
            row = (await db.execute(select(User).where(User.email == new_email))).scalar_one_or_none()
            assert row is None, "a rejected registration attempt must not create a user row"
    finally:
        await _delete_user(existing_id)
