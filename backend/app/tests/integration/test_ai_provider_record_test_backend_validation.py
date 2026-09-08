"""Regression test for a real bug found via live/runtime testing:
POST /api/v1/runtime/ai-providers/{backend}/record-test (app/api/routes/
runtime.py's record_ai_test) never validated `backend` against
app.core.runtime_config.AI_BACKENDS, unlike its siblings POST
/ai-providers/{backend} (configure_ai_provider) and POST /ai-active
(set_active_ai_backend, via a ValueError raised inside the service layer)
-- both of which already reject an unknown backend with a 400.

Live-reproduced against the real running stack before this fix: POSTing
any arbitrary string (e.g. "qa-repro-garbage-backend-xyz") to this endpoint
returned 200 {"recorded": true} and permanently created a real
provider_runtime_configs row for it (record_ai_test_result() does a plain
get-or-create with no allow-list check of its own). That row then
unconditionally showed up in GET /api/v1/runtime/ai-providers -- and
therefore the Manage Providers -> AI Providers tab, which renders every
entry in that list as a normal-looking provider card -- with no DELETE
endpoint anywhere to remove it. Since Save/Set Active on such a row DO
correctly reject with "Unknown AI backend" (they already had the
allow-list check), the row could never corrupt real data or go active --
it was purely permanent, un-removable UI clutter indistinguishable from a
broken/unfinished feature.

Fix: record_ai_test now validates `backend` against svc.AI_BACKENDS the
same way configure_ai_provider already does, rejecting with 400 BEFORE
svc.record_ai_test_result() ever runs -- so no row is created for an
unknown backend at all.

Deliberately fixed at the router layer (app/api/routes/runtime.py), not
inside app.core.runtime_config.record_ai_test_result() itself: that
service function is also exercised directly, with an intentionally-unknown
synthetic provider_id, by
test_runtime_config_persistence.py::test_record_ai_test_result_first_time_recovers_from_a_concurrent_insert_collision
to test its own, unrelated get-or-create race-recovery behavior --
that lower-level function must keep accepting any provider_id for that
test to remain valid; the allow-list check belongs at the HTTP boundary,
exactly where its two siblings already put it.

Driven through real HTTP requests against the real FastAPI app and real
database, following test_ai_providers_permissions.py's pattern in this
same directory -- intended to run inside the backend container
(`docker compose exec backend python -m pytest app/tests/integration`).
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import create_access_token
from app.core import runtime_config as runtime_config_module
from app.core.config import get_settings
from app.core.db import new_session
from app.core.users import create_user
from app.main import app
from app.models.runtime_config import ProviderKind, ProviderRuntimeConfig
from app.models.user import Role


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    """Same per-function engine rebuild as test_ai_providers_permissions.py
    and test_runtime_config_persistence.py in this suite -- keeps the async
    engine's connection pool bound to the current test's event loop."""
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


def _unique_backend_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _make_admin() -> tuple[uuid.UUID, str]:
    email = _unique_email("qa-recordtest-admin")
    created = await create_user(email, "pw-1", "qa-recordtest", Role.ADMIN, None, "actor@qa.test")
    token = create_access_token(email, Role.ADMIN.value)
    return uuid.UUID(created["id"]), token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _delete_user(user_id: uuid.UUID) -> None:
    from app.models.user import User

    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _row_exists(provider_id: str) -> bool:
    async with new_session() as db:
        row = (
            await db.execute(
                select(ProviderRuntimeConfig).where(
                    ProviderRuntimeConfig.kind == ProviderKind.AI,
                    ProviderRuntimeConfig.provider_id == provider_id,
                )
            )
        ).scalar_one_or_none()
        return row is not None


async def _cleanup_provider(provider_id: str) -> None:
    async with new_session() as db:
        row = (
            await db.execute(
                select(ProviderRuntimeConfig).where(
                    ProviderRuntimeConfig.kind == ProviderKind.AI,
                    ProviderRuntimeConfig.provider_id == provider_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_record_test_rejects_unknown_backend_and_creates_no_row(client):
    """The actual bug: an unknown backend must be rejected with 400, exactly
    like its sibling POST /ai-providers/{backend} already does -- and,
    crucially, must never create a provider_runtime_configs row at all."""
    user_id, token = await _make_admin()
    backend_id = _unique_backend_id("qa-garbage-backend")
    try:
        response = await client.post(
            f"/api/v1/runtime/ai-providers/{backend_id}/record-test",
            json={"ok": True, "message": "should never be persisted"},
            headers=_auth(token),
        )
        assert response.status_code == 400, (
            "an unknown AI backend must be rejected with 400, matching "
            f"configure_ai_provider's existing behavior -- got {response.status_code}: {response.text}"
        )
        assert "Unknown AI backend" in response.text

        assert not await _row_exists(backend_id), (
            "record-test for an unknown backend must not create a "
            "provider_runtime_configs row -- this is exactly the permanent, "
            "un-removable garbage-row bug this test guards against"
        )

        # Also must not show up in the listing the Manage Providers page reads.
        listing = await client.get("/api/v1/runtime/ai-providers", headers=_auth(token))
        assert listing.status_code == 200
        assert backend_id not in {row["provider_id"] for row in listing.json()}
    finally:
        await _cleanup_provider(backend_id)
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_record_test_still_works_for_a_real_allow_listed_backend(client):
    """Positive control: the fix must not break the legitimate case. Uses a
    synthetic id temporarily added to AI_BACKENDS (mirroring
    test_set_active_ai_backend_locks_the_rows_it_reads's established pattern
    in test_runtime_config_persistence.py) rather than touching any of this
    app's real, already-configured AI provider rows."""
    user_id, token = await _make_admin()
    backend_id = _unique_backend_id("qa-allowlisted-backend")
    original_backends = list(runtime_config_module.AI_BACKENDS)
    runtime_config_module.AI_BACKENDS = original_backends + [backend_id]
    try:
        response = await client.post(
            f"/api/v1/runtime/ai-providers/{backend_id}/record-test",
            json={"ok": True, "message": "connected fine"},
            headers=_auth(token),
        )
        assert response.status_code == 200, f"got {response.status_code}: {response.text}"
        assert response.json() == {"recorded": True}
        assert await _row_exists(backend_id)
    finally:
        runtime_config_module.AI_BACKENDS = original_backends
        await _cleanup_provider(backend_id)
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_record_test_requires_provider_manage_permission(client):
    """Control: the new validation must not accidentally loosen or bypass
    the existing "provider:manage" RBAC gate on this route -- ANALYST (who
    only holds lookup:read/lookup:create) must still get 403, even for an
    otherwise-valid, real backend id."""
    email = _unique_email("qa-recordtest-analyst")
    created = await create_user(email, "pw-1", "qa-recordtest", Role.ANALYST, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    token = create_access_token(email, Role.ANALYST.value)
    try:
        response = await client.post(
            "/api/v1/runtime/ai-providers/anthropic/record-test",
            json={"ok": True, "message": "x"},
            headers=_auth(token),
        )
        assert response.status_code == 403
    finally:
        await _delete_user(user_id)
