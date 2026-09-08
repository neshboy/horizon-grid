"""Regression test for BUG-023: POST /api/v1/lookup/{id}/export was gated on
`Depends(require_permission("lookup:read"))` instead of the already-defined
`lookup:export` permission (see ROLE_PERMISSIONS in app/models/user.py --
ADMIN and ANALYST have it, VIEWER does not). Because VIEWER already holds
`lookup:read`, a VIEWER-role token could successfully call the export
endpoint and download real PDF/CSV files, despite the permission matrix
explicitly reserving export for ADMIN/ANALYST.

Exercises the real route (via ASGI transport, real Postgres) the same way
test_admin_rbac_api.py does for the admin console, and overrides
DATABASE_URL/REDIS_URL to the host-published docker-compose ports the same
way test_lookup_stream_persistence.py does, since this test runs from the
host against the dev tree (not via `docker exec` against the separately
installed copy -- see the project's dual-source-tree note).
"""
import os
import socket
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import get_settings

def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _resolve_infra_host_port(in_network_host, in_network_port, published_host, published_port):
    """See test_lookup_stream_persistence.py's function of the same name for
    the full rationale: prefer the real in-docker-network hostname
    (`postgres`/`redis`), reachable when this test runs INSIDE the backend
    container (the documented dev/CI way to run it); fall back to the
    docker-compose HOST-published port for an out-of-container host run.
    """
    if _reachable(in_network_host, in_network_port):
        return in_network_host, in_network_port
    return published_host, published_port


POSTGRES_HOST, POSTGRES_PORT = _resolve_infra_host_port("postgres", 5432, "localhost", 5433)
REDIS_HOST, REDIS_PORT = _resolve_infra_host_port("redis", 6379, "localhost", 6379)


pytestmark = pytest.mark.skipif(
    not (_reachable(POSTGRES_HOST, POSTGRES_PORT) and _reachable(REDIS_HOST, REDIS_PORT)),
    reason="Postgres/Redis not reachable via either the in-network postgres/redis "
    "hostnames or the docker-compose host-published localhost:5433/6379 ports -- "
    "run `docker compose up -d postgres redis` first.",
)


@pytest.fixture(scope="module", autouse=True)
def _point_app_settings_at_host_infra():
    """See test_lookup_stream_persistence.py's fixture of the same name for
    the full rationale -- Settings.database_url/redis_url default to the
    in-network `postgres`/`redis` hostnames, which don't resolve from this
    out-of-container host test process, so both the env vars and the
    already-imported app.core.db engine/session-factory need to be rebuilt
    against the host-published ports."""
    import app.core.cache as cache_module
    import app.core.db as db_module
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    previous_db_url = os.environ.get("DATABASE_URL")
    previous_redis_url = os.environ.get("REDIS_URL")
    # Reads real POSTGRES_USER/PASSWORD/DB from the environment (rather than
    # hardcoding "ioc:ioc") -- inside the backend container these are already
    # set correctly (docker-compose's env_file: .env passes them through),
    # and may legitimately differ from the "ioc"/"ioc" defaults if an
    # operator rotated POSTGRES_PASSWORD away from its default.
    _pg_user = os.environ.get("POSTGRES_USER", "ioc")
    _pg_password = os.environ.get("POSTGRES_PASSWORD", "ioc")
    _pg_db = os.environ.get("POSTGRES_DB", "ioc_intel")
    os.environ["DATABASE_URL"] = f"postgresql+asyncpg://{_pg_user}:{_pg_password}@{POSTGRES_HOST}:{POSTGRES_PORT}/{_pg_db}"
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
    """Same event-loop-per-test issue documented in
    test_lookup_stream_persistence.py -- pooled connections opened under one
    test's event loop must not be reused by the next."""
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
    email = _unique_email(f"qa-export-{role_enum.value}")
    created = await create_user(email, "pw-1", "Export Test User", role_enum, None, "actor@qa.test")
    token = create_access_token(email, role_enum.value)
    return uuid.UUID(created["id"]), email, token


async def _delete_user(user_id: uuid.UUID) -> None:
    from app.core.db import new_session
    from app.models.user import User

    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


@pytest_asyncio.fixture
async def bare_lookup():
    """A minimal, real IOCLookup row -- export doesn't require a finished
    investigation (both _render_csv/_render_pdf already handle empty
    provider_results/no final_assessment gracefully, per
    test_lookup_export.py's own fakes-based tests), so a bare RUNNING row
    with no relations is sufficient to reach the permission check."""
    from app.core.db import new_session
    from app.models.lookup import IOCLookup, LookupStatus

    async with new_session() as db:
        lookup = IOCLookup(ioc_value="203.0.113.200", ioc_type="ipv4", status=LookupStatus.RUNNING)
        db.add(lookup)
        await db.commit()
        await db.refresh(lookup)
        lookup_id = lookup.id

    yield lookup_id

    async with new_session() as db:
        from app.models.lookup import FinalAssessmentRecord
        from sqlalchemy import delete

        await db.execute(delete(FinalAssessmentRecord).where(FinalAssessmentRecord.lookup_id == lookup_id))
        await db.commit()
        row = await db.get(IOCLookup, lookup_id)
        if row is not None:
            await db.delete(row)
            await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_viewer_gets_403_on_export_csv(bare_lookup):
    from app.main import app
    from app.models.user import Role

    user_id, _, token = await _make_user(Role.VIEWER)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/v1/lookup/{bare_lookup}/export?format=csv", headers=_auth(token)
            )
        assert response.status_code == 403, (
            "VIEWER holds lookup:read but not lookup:export -- BUG-024's fix must reject this"
        )
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_viewer_gets_403_on_export_pdf(bare_lookup):
    from app.main import app
    from app.models.user import Role

    user_id, _, token = await _make_user(Role.VIEWER)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/v1/lookup/{bare_lookup}/export?format=pdf", headers=_auth(token)
            )
        assert response.status_code == 403
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_viewer_can_still_read_the_lookup_directly(bare_lookup):
    """Control: VIEWER's pre-existing lookup:read access to GET /{id} itself
    must be unaffected by BUG-024's fix -- only the export endpoint's gate
    changed."""
    from app.main import app
    from app.models.user import Role

    user_id, _, token = await _make_user(Role.VIEWER)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/lookup/{bare_lookup}", headers=_auth(token))
        assert response.status_code == 200
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_analyst_can_export_csv(bare_lookup):
    """Positive control: confirms the fix didn't accidentally lock out a
    role that should have export access -- ANALYST holds lookup:export in
    ROLE_PERMISSIONS and must still get a real CSV file, not a 403."""
    from app.main import app
    from app.models.user import Role

    user_id, _, token = await _make_user(Role.ANALYST)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/v1/lookup/{bare_lookup}/export?format=csv", headers=_auth(token)
            )
        assert response.status_code == 200
        assert b"ioc_value" in response.content
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_admin_can_export_pdf(bare_lookup):
    """Positive control for ADMIN, the other role holding lookup:export."""
    from app.main import app
    from app.models.user import Role

    user_id, _, token = await _make_user(Role.ADMIN)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/v1/lookup/{bare_lookup}/export?format=pdf", headers=_auth(token)
            )
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")
    finally:
        await _delete_user(user_id)
