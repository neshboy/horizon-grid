"""Regression test for a real bug found via live/runtime testing:
POST /api/v1/runtime/ioc-providers/{provider_id}/enabled (app/api/routes/
runtime.py's set_ioc_provider_enabled) and POST /api/v1/runtime/
ioc-providers/{provider_id}/record-test (record_ioc_test) never validated
`provider_id` against the real provider registry (app.providers.registry.
get_all_providers()), unlike their sibling POST /ioc-providers/{provider_id}
(configure_ioc_provider), which already rejects an unknown provider_id with
a 404.

Live-reproduced against the real running stack before this fix: POSTing to
either endpoint with an arbitrary, made-up provider_id (e.g.
"qa-repro-fake-ioc-provider") returned 200 and permanently created a real
provider_runtime_configs row for it -- app.core.runtime_config's
set_ioc_provider_enabled()/record_ioc_test_result() both do a plain
get-or-create with no allow-list check of their own, exactly like
record_ai_test_result() did before its own, separately-fixed validation gap
(see test_ai_provider_record_test_backend_validation.py in this same
directory). Unlike the AI-provider version of this bug, the orphan IOC row
is invisible via GET /api/v1/runtime/ioc-providers (that listing is keyed
off the real provider registry, not the DB table -- see list_ioc_providers),
so this is silent DB pollution rather than a visible UI defect, but it is
still a real, permanent, un-removable row with no DELETE endpoint anywhere
to clean it up.

Fix: both routes now validate `provider_id` against
{p.provider_id for p in get_all_providers()} the same way
configure_ioc_provider already does, rejecting with 404 BEFORE
svc.set_ioc_provider_enabled()/svc.record_ioc_test_result() ever run -- so
no row is created for an unknown provider_id at all.

Deliberately fixed at the router layer (app/api/routes/runtime.py), not
inside app.core.runtime_config's service functions themselves: those lower-
level functions are also exercised directly, with intentionally-unknown
synthetic provider_ids, by test_runtime_config_persistence.py's
test_record_ioc_test_result_first_time_recovers_from_a_concurrent_insert_collision
and test_set_ioc_provider_enabled_first_time_recovers_from_a_concurrent_insert_collision
to test their own, unrelated get-or-create race-recovery behavior -- those
lower-level functions must keep accepting any provider_id for those tests
to remain valid; the allow-list check belongs at the HTTP boundary, exactly
where configure_ioc_provider already puts it.

Driven through real HTTP requests against the real FastAPI app and real
database, following test_ai_provider_record_test_backend_validation.py's
pattern in this same directory -- intended to run inside the backend
container (`docker compose exec backend python -m pytest
app/tests/integration`).
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import create_access_token
from app.core.config import get_settings
from app.core.db import new_session
from app.core.users import create_user
from app.main import app
from app.models.runtime_config import ConfigAuditLog, ProviderKind, ProviderRuntimeConfig
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


def _unique_provider_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _make_admin() -> tuple[uuid.UUID, str]:
    email = _unique_email("qa-iocvalid-admin")
    created = await create_user(email, "pw-1", "qa-iocvalid", Role.ADMIN, None, "actor@qa.test")
    token = create_access_token(email, Role.ADMIN.value)
    return uuid.UUID(created["id"]), token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _delete_user(user_id: uuid.UUID) -> None:
    """Deletes the test admin/analyst user, first purging any
    config_audit_log rows this test's own actions left pointing at it (the
    positive-control test below performs a real, allow-listed
    set_ioc_provider_enabled call, which -- unlike record_ai_test_result/
    record_ioc_test_result -- does pass actor_user_id into record_audit) --
    otherwise the plain user delete fails on
    config_audit_log_actor_user_id_fkey."""
    from app.models.user import User

    async with new_session() as db:
        await db.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor_user_id == user_id))
        await db.commit()
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
                    ProviderRuntimeConfig.kind == ProviderKind.IOC,
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
                    ProviderRuntimeConfig.kind == ProviderKind.IOC,
                    ProviderRuntimeConfig.provider_id == provider_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_set_enabled_rejects_unknown_provider_and_creates_no_row(client):
    """The actual bug: an unknown provider_id must be rejected with 404,
    exactly like its sibling POST /ioc-providers/{provider_id} (configure)
    already does -- and, crucially, must never create a
    provider_runtime_configs row at all."""
    user_id, token = await _make_admin()
    provider_id = _unique_provider_id("qa-garbage-ioc")
    try:
        response = await client.post(
            f"/api/v1/runtime/ioc-providers/{provider_id}/enabled",
            json={"enabled": True},
            headers=_auth(token),
        )
        assert response.status_code == 404, (
            "an unknown IOC provider must be rejected with 404, matching "
            f"configure_ioc_provider's existing behavior -- got {response.status_code}: {response.text}"
        )
        assert "Unknown IOC provider" in response.text

        assert not await _row_exists(provider_id), (
            "set_ioc_provider_enabled for an unknown provider_id must not create a "
            "provider_runtime_configs row -- this is exactly the permanent, "
            "un-removable garbage-row bug this test guards against"
        )
    finally:
        await _cleanup_provider(provider_id)
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_record_test_rejects_unknown_provider_and_creates_no_row(client):
    """Same bug, sibling route: POST /ioc-providers/{provider_id}/record-test."""
    user_id, token = await _make_admin()
    provider_id = _unique_provider_id("qa-garbage-ioc-test")
    try:
        response = await client.post(
            f"/api/v1/runtime/ioc-providers/{provider_id}/record-test",
            json={"ok": True, "message": "should never be persisted"},
            headers=_auth(token),
        )
        assert response.status_code == 404, (
            "an unknown IOC provider must be rejected with 404, matching "
            f"configure_ioc_provider's existing behavior -- got {response.status_code}: {response.text}"
        )
        assert "Unknown IOC provider" in response.text

        assert not await _row_exists(provider_id), (
            "record_ioc_test for an unknown provider_id must not create a "
            "provider_runtime_configs row -- this is exactly the permanent, "
            "silent DB-pollution bug this test guards against"
        )
    finally:
        await _cleanup_provider(provider_id)
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_set_enabled_and_record_test_still_work_for_a_real_registered_provider(client):
    """Positive control: the fix must not break the legitimate case. Uses
    the real "virustotal" provider_id (a genuine entry in
    app.providers.registry.get_all_providers()), following
    test_upsert_ioc_provider_rejects_undeclared_credential_field_end_to_end's
    established pattern of snapshotting/restoring the real row's state so
    this doesn't leave the shared dev DB's virustotal row any different than
    it found it."""
    from app.core.runtime_config import get_ioc_provider_snapshot

    user_id, token = await _make_admin()
    before_snapshot = (await get_ioc_provider_snapshot()).get("virustotal", {})
    before_enabled = before_snapshot.get("enabled", True)
    try:
        response = await client.post(
            "/api/v1/runtime/ioc-providers/virustotal/enabled",
            json={"enabled": before_enabled},
            headers=_auth(token),
        )
        assert response.status_code == 200, f"got {response.status_code}: {response.text}"
        assert response.json() == {"provider_id": "virustotal", "enabled": before_enabled}

        response = await client.post(
            "/api/v1/runtime/ioc-providers/virustotal/record-test",
            json={"ok": True, "message": "connected fine"},
            headers=_auth(token),
        )
        assert response.status_code == 200, f"got {response.status_code}: {response.text}"
        assert response.json() == {"recorded": True}
    finally:
        await client.post(
            "/api/v1/runtime/ioc-providers/virustotal/enabled",
            json={"enabled": before_enabled},
            headers=_auth(token),
        )
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_set_enabled_and_record_test_still_require_provider_manage_permission(client):
    """Control: the new validation must not accidentally loosen or bypass
    the existing "provider:manage" RBAC gate on these routes -- ANALYST (who
    only holds lookup:read/lookup:create) must still get 403, even for an
    otherwise-valid, real provider_id."""
    email = _unique_email("qa-iocvalid-analyst")
    created = await create_user(email, "pw-1", "qa-iocvalid", Role.ANALYST, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    token = create_access_token(email, Role.ANALYST.value)
    try:
        response = await client.post(
            "/api/v1/runtime/ioc-providers/virustotal/enabled",
            json={"enabled": True},
            headers=_auth(token),
        )
        assert response.status_code == 403

        response = await client.post(
            "/api/v1/runtime/ioc-providers/virustotal/record-test",
            json={"ok": True, "message": "x"},
            headers=_auth(token),
        )
        assert response.status_code == 403
    finally:
        await _delete_user(user_id)
