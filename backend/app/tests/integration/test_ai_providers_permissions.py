"""Regression test for the AiComparisonPanel bug: GET /api/v1/runtime/ai-
providers (app/api/routes/runtime.py's list_ai_providers) was gated on
`Depends(require_permission("provider:manage"))` -- an ADMIN-only
permission -- even though it is a read-only listing (see
app/core/runtime_config.py's `_row_to_public_dict`: only masked credentials
are ever returned, never a raw secret) that ANALYST needs in order to
populate frontend/components/dashboard/AiComparisonPanel.tsx's AI-backend
picker dropdown for the "Analyze with a different AI" comparison feature.

ANALYST already holds "lookup:create" and can successfully call POST
/{lookup_id}/reanalyze (see app/api/routes/lookup.py), so the feature is
supposed to work for that role -- but AiComparisonPanel's own
`.catch(() => setProviders([]))` silently swallowed the resulting 403,
leaving the dropdown permanently empty with no visible error, ever. The
fix lowers list_ai_providers' gate to "lookup:read" (the same, already-
established lower-privilege choice made for the sibling GET /ai-active
endpoint in the same file), while every provider-config-MUTATING route
(POST /ai-providers/{backend}, /ai-active, /record-test, and the
IOC-provider equivalents) remains "provider:manage"-only.

Driven through real HTTP requests against the real FastAPI app and real
database, following test_admin_rbac_api.py's pattern in this same
directory -- intended to run inside the backend container (`docker compose
exec backend python -m pytest app/tests/integration`), where
get_settings().database_url already resolves to the real in-network
`postgres` host with no override needed.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import create_access_token
from app.core.config import get_settings
from app.core.users import create_user
from app.main import app
from app.models.user import Role


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    """Each async test function gets its own fresh event loop (standard
    pytest-asyncio per-function scope); rebuilding the engine per test keeps
    its connection pool bound to the CURRENT test's loop, matching
    test_admin_rbac_api.py's identical fixture in this same directory."""
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


async def _make_user(role: Role, prefix: str) -> tuple[uuid.UUID, str, str]:
    email = _unique_email(prefix)
    created = await create_user(email, "pw-1", prefix, role, None, "actor@qa.test")
    token = create_access_token(email, role.value)
    return uuid.UUID(created["id"]), email, token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _delete_user(user_id: uuid.UUID) -> None:
    from sqlalchemy import select

    from app.core.db import new_session
    from app.models.user import User

    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


@pytest.mark.asyncio
async def test_analyst_can_list_ai_providers(client):
    """The actual bug: ANALYST holds "lookup:create" (so POST
    /{lookup_id}/reanalyze already works for them) but was rejected with a
    403 from GET /ai-providers before the fix, leaving
    AiComparisonPanel's dropdown permanently empty. Must be 200 now."""
    user_id, _, token = await _make_user(Role.ANALYST, "qa-aiprov-analyst")
    try:
        response = await client.get("/api/v1/runtime/ai-providers", headers=_auth(token))
        assert response.status_code == 200, (
            "ANALYST holds lookup:read/lookup:create and must be able to list AI providers "
            f"to populate AiComparisonPanel's dropdown -- got {response.status_code}: {response.text}"
        )
        assert isinstance(response.json(), list)
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_viewer_can_list_ai_providers(client):
    """Positive control: VIEWER holds lookup:read too, and the listing is
    read-only (masked credentials only -- see _row_to_public_dict), so it
    should be readable, matching the sibling GET /ai-active endpoint's
    already-established "lookup:read" gate."""
    user_id, _, token = await _make_user(Role.VIEWER, "qa-aiprov-viewer")
    try:
        response = await client.get("/api/v1/runtime/ai-providers", headers=_auth(token))
        assert response.status_code == 200
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_admin_can_list_ai_providers(client):
    """Positive control for ADMIN, confirming the fix didn't break the
    role that always worked."""
    user_id, _, token = await _make_user(Role.ADMIN, "qa-aiprov-admin")
    try:
        response = await client.get("/api/v1/runtime/ai-providers", headers=_auth(token))
        assert response.status_code == 200
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_analyst_still_gets_403_configuring_an_ai_provider(client):
    """Control: the fix must only lower the GATE on the read-only GET --
    ANALYST must still be rejected from actually WRITING provider config
    (POST /ai-providers/{backend}), which remains "provider:manage"-only.
    Uses a real, already-known backend id (`anthropic`) with empty
    credentials -- the permission check happens before any DB write
    either way, so this never touches the real stored config for it."""
    user_id, _, token = await _make_user(Role.ANALYST, "qa-aiprov-write")
    try:
        response = await client.post(
            "/api/v1/runtime/ai-providers/anthropic",
            json={"credentials": {}, "model_id": None},
            headers=_auth(token),
        )
        assert response.status_code == 403, (
            "ANALYST must still lack provider:manage for WRITE routes -- "
            f"got {response.status_code}: {response.text}"
        )
    finally:
        await _delete_user(user_id)
