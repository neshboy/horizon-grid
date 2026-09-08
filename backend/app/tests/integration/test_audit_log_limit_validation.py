"""Regression test for a real bug found via live/runtime testing:
GET /api/v1/runtime/audit-log (app/api/routes/runtime.py's audit_log)
accepted any raw int for `limit`, including negative values, and passed it
straight through to app.core.audit.list_audit_log(), which hands it
unclamped to SQLAlchemy's `.limit(limit)`.

Live-reproduced against the real running stack before this fix:
GET /api/v1/runtime/audit-log?limit=-5 (as an ADMIN, the only role with
audit:read) returned a bare 500 Internal Server Error, with
`docker compose logs backend` showing the request crash all the way through
SQLAlchemy/asyncpg with `asyncpg.exceptions.InvalidRowCountInLimitClauseError:
LIMIT must not be negative` -- Postgres itself rejects a negative LIMIT at
the wire-protocol level, and nothing in the call chain caught it. Contrast
with the sibling case `limit=abc`, which Pydantic's own int-coercion already
correctly rejects with a clean 422 -- only the negative-but-valid-int case
fell through uncaught.

Fix: the route's `limit` query parameter now uses `Query(200, ge=0)` instead
of a plain `int = 200` default, so FastAPI/Pydantic rejects a negative limit
with a 422 before it ever reaches the service layer or the database --
consistent with how `limit=abc` was already handled.

Also live-confirmed as part of the same finding: the route had no upper
bound either -- `limit=999999` returned a bare HTTP 200 with the *entire*
audit table (multiple megabytes) in one response, unlike every other list
endpoint in this codebase (GET /cases, GET /api/v1/lookup) which clamp to
`max(1, min(limit, 200))`. Fixed by adding `le=200` alongside the existing
`ge=0`, so an out-of-range limit on either end gets a clean 422 instead of
either crashing or serving an unbounded response.

Driven through real HTTP requests against the real FastAPI app and real
database, following test_ai_provider_record_test_backend_validation.py's
pattern in this same directory -- intended to run inside the backend
container (`docker compose exec backend python -m pytest app/tests/integration`).
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import create_access_token
from app.core.config import get_settings
from app.core.db import new_session
from app.core.users import create_user
from app.main import app
from app.models.user import Role


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    """Same per-function engine rebuild as the other integration tests in
    this suite (e.g. test_ai_provider_record_test_backend_validation.py) --
    keeps the async engine's connection pool bound to the current test's
    event loop."""
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


async def _make_admin() -> tuple[uuid.UUID, str]:
    email = _unique_email("qa-auditlog-admin")
    created = await create_user(email, "pw-1", "qa-auditlog", Role.ADMIN, None, "actor@qa.test")
    token = create_access_token(email, Role.ADMIN.value)
    return uuid.UUID(created["id"]), token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _delete_user(user_id: uuid.UUID) -> None:
    from sqlalchemy import select

    from app.models.user import User

    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


@pytest.mark.asyncio
async def test_audit_log_rejects_negative_limit_with_422_not_500(client):
    """The actual bug: a negative `limit` must be rejected with a clean 4xx
    validation error, not crash all the way through to an unhandled
    asyncpg InvalidRowCountInLimitClauseError / bare 500."""
    user_id, token = await _make_admin()
    try:
        response = await client.get(
            "/api/v1/runtime/audit-log", params={"limit": -5}, headers=_auth(token)
        )
        assert response.status_code == 422, (
            "a negative limit must be rejected with a 422 validation error, "
            f"not propagate to the database -- got {response.status_code}: {response.text}"
        )
        assert "limit" in response.text
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_audit_log_rejects_limit_above_200(client):
    """The other half of the same finding: `limit` had no upper bound, so a
    huge limit (e.g. 999999) served the entire audit table in one response
    instead of being capped like every sibling list endpoint. `limit=200`
    (the max) must still succeed; `limit=201` and a very large limit must
    both be rejected with a 422, not silently served in full."""
    user_id, token = await _make_admin()
    try:
        at_max_response = await client.get(
            "/api/v1/runtime/audit-log", params={"limit": 200}, headers=_auth(token)
        )
        assert at_max_response.status_code == 200, f"got {at_max_response.status_code}: {at_max_response.text}"

        just_over_response = await client.get(
            "/api/v1/runtime/audit-log", params={"limit": 201}, headers=_auth(token)
        )
        assert just_over_response.status_code == 422, (
            f"limit=201 must be rejected with a 422, not served -- got {just_over_response.status_code}"
        )

        huge_response = await client.get(
            "/api/v1/runtime/audit-log", params={"limit": 999999}, headers=_auth(token)
        )
        assert huge_response.status_code == 422, (
            "a huge limit must not be served in full -- must be rejected with a 422, "
            f"got {huge_response.status_code}: {huge_response.text[:200]}"
        )
        assert "limit" in huge_response.text
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_audit_log_still_works_for_zero_and_positive_limits(client):
    """Positive control: the fix must not break the already-working cases --
    limit=0 (empty page) and an ordinary positive limit."""
    user_id, token = await _make_admin()
    try:
        zero_response = await client.get(
            "/api/v1/runtime/audit-log", params={"limit": 0}, headers=_auth(token)
        )
        assert zero_response.status_code == 200, f"got {zero_response.status_code}: {zero_response.text}"
        assert zero_response.json() == []

        positive_response = await client.get(
            "/api/v1/runtime/audit-log", params={"limit": 5}, headers=_auth(token)
        )
        assert positive_response.status_code == 200, f"got {positive_response.status_code}: {positive_response.text}"
        assert isinstance(positive_response.json(), list)
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_audit_log_requires_audit_read_permission(client):
    """Control: the new validation must not accidentally loosen the existing
    "audit:read" RBAC gate on this route -- ANALYST must still get 403, even
    for an otherwise-valid limit."""
    email = _unique_email("qa-auditlog-analyst")
    created = await create_user(email, "pw-1", "qa-auditlog", Role.ANALYST, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    token = create_access_token(email, Role.ANALYST.value)
    try:
        response = await client.get(
            "/api/v1/runtime/audit-log", params={"limit": 5}, headers=_auth(token)
        )
        assert response.status_code == 403
    finally:
        await _delete_user(user_id)
