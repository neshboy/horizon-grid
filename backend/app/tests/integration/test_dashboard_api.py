"""API-level test for the new "dashboard:read" permission: a VIEWER-role
user (not just ADMIN) must be able to call both GET /dashboard/kpis and the
replaced GET /providers/health -- this is the entire point of the new
permission (ROLE_PERMISSIONS in app/models/user.py grants it to ADMIN,
ANALYST, and VIEWER alike). If a VIEWER gets 403 on either route, the
permission is wired wrong.

Exercises the real route via ASGI transport against real Postgres, the same
way test_admin_rbac_api.py does for the admin console, overriding
DATABASE_URL/REDIS_URL to the host-published docker-compose ports the same
way test_lookup_export_permissions.py does (this file runs from the host
against the dev tree, not via `docker exec`).
"""
import os
import socket
import uuid

import httpx
import pytest
import pytest_asyncio

from app.core.config import get_settings

POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5433
REDIS_HOST = "localhost"
REDIS_PORT = 6379

API = get_settings().api_v1_prefix


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_reachable(POSTGRES_HOST, POSTGRES_PORT) and _reachable(REDIS_HOST, REDIS_PORT)),
    reason="Postgres/Redis not reachable -- run `docker compose up -d postgres redis` first.",
)


@pytest.fixture(scope="module", autouse=True)
def _point_app_settings_at_host_infra():
    """See test_lookup_stream_persistence.py's fixture of the same name for the full rationale."""
    import app.core.cache as cache_module
    import app.core.db as db_module
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    previous_db_url = os.environ.get("DATABASE_URL")
    previous_redis_url = os.environ.get("REDIS_URL")
    os.environ["DATABASE_URL"] = f"postgresql+asyncpg://ioc:ioc@{POSTGRES_HOST}:{POSTGRES_PORT}/ioc_intel"
    os.environ["REDIS_URL"] = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
    get_settings.cache_clear()
    cache_module._pool = None

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)

    yield
    if previous_db_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_db_url
    if previous_redis_url is None:
        os.environ.pop("REDIS_URL", None)
    else:
        os.environ["REDIS_URL"] = previous_redis_url
    get_settings.cache_clear()
    cache_module._pool = None


@pytest_asyncio.fixture(autouse=True)
async def _dispose_pools_after_each_test():
    """See test_lookup_stream_persistence.py's fixture of the same name."""
    yield
    import app.core.cache as cache_module
    from app.core.db import _engine

    await _engine.dispose()
    if cache_module._pool is not None:
        await cache_module._pool.aclose()
        cache_module._pool = None


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@qa.test"


async def _make_user(role):
    from app.auth.security import create_access_token
    from app.core.users import create_user
    from app.models.user import Role

    role_enum = role if isinstance(role, Role) else Role(role)
    email = _unique_email(f"qa-dashboard-{role_enum.value}")
    created = await create_user(email, "pw-1", "Dashboard Test User", role_enum, None, "actor@qa.test")
    token = create_access_token(email, role_enum.value)
    return uuid.UUID(created["id"]), email, token


async def _delete_user(user_id: uuid.UUID) -> None:
    from sqlalchemy import select

    from app.core.db import new_session
    from app.models.user import User

    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_viewer_can_read_dashboard_kpis():
    from app.main import app
    from app.models.user import Role

    user_id, _, token = await _make_user(Role.VIEWER)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"{API}/dashboard/kpis", headers=_auth(token))
        assert response.status_code == 200, response.text
        body = response.json()
        for key in (
            "active_investigations",
            "critical_high_risk_iocs",
            "open_cases",
            "open_critical_cases",
            "avg_threat_score",
            "provider_health_percentage",
            "ai_success_rate",
        ):
            assert key in body
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_viewer_can_read_providers_health():
    from app.main import app
    from app.models.user import Role

    user_id, _, token = await _make_user(Role.VIEWER)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"{API}/providers/health", headers=_auth(token))
        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body, list)
        assert len(body) > 0
        for window in ("1h", "24h", "7d", "30d"):
            assert window in body[0]
            assert "status" in body[0][window]
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected_on_both_routes():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r1 = await client.get(f"{API}/dashboard/kpis")
        r2 = await client.get(f"{API}/providers/health")
    assert r1.status_code in (401, 403)
    assert r2.status_code in (401, 403)


@pytest.mark.asyncio
async def test_viewer_can_read_executive_summary_and_kpis_match_get_kpis():
    """GET /dashboard/executive-summary reuses the same "dashboard:read"
    permission as /dashboard/kpis (no new permission was added) and must
    return "source" (one of the two values app.ai.dashboard_summary.
    generate_executive_summary() can honestly report) plus a "kpis" block
    equal to a fresh get_kpis() call -- so the frontend can render the raw
    numbers alongside the AI narrative without a second request, and they
    can never drift apart from the platform's one source of truth for KPI
    numbers.
    """
    from app.core.dashboard import get_kpis
    from app.main import app
    from app.models.user import Role

    user_id, _, token = await _make_user(Role.VIEWER)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"{API}/dashboard/executive-summary", headers=_auth(token))
        assert response.status_code == 200, response.text
        body = response.json()

        assert "source" in body
        assert body["source"] in ("ai", "template_fallback")
        assert isinstance(body["summary"], str) and len(body["summary"]) > 0

        fresh_kpis = await get_kpis()
        assert body["kpis"] == fresh_kpis
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected_on_executive_summary():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"{API}/dashboard/executive-summary")
    assert response.status_code in (401, 403)
