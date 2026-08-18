"""API-level RBAC tests for the admin console: permission-matrix
enforcement, privilege-escalation/IDOR attempts, and the "role/disable
changes take effect on the very next request" guarantee -- all driven
through real HTTP requests against the real FastAPI app and real database,
never asserting only on frontend behavior ("test the backend, not just the
UI").

Tokens are minted directly via create_access_token() rather than going
through /auth/login -- this suite is testing authorization (what a given
role's token can and can't do), not authentication, and minting avoids
coupling every test to the login flow's own separately-tested behavior.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import create_access_token
from app.core.config import get_settings
from app.core.users import create_user, set_user_active
from app.main import app
from app.models.user import Role

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


# --- Permission matrix / privilege escalation --------------------------------


@pytest.mark.asyncio
async def test_admin_can_list_users_analyst_and_viewer_cannot(client):
    admin_id, _, admin_token = await _make_user(Role.ADMIN, "qa-matrix-admin")
    analyst_id, _, analyst_token = await _make_user(Role.ANALYST, "qa-matrix-analyst")
    viewer_id, _, viewer_token = await _make_user(Role.VIEWER, "qa-matrix-viewer")
    try:
        r_admin = await client.get(f"{API}/admin/users", headers=_auth(admin_token))
        r_analyst = await client.get(f"{API}/admin/users", headers=_auth(analyst_token))
        r_viewer = await client.get(f"{API}/admin/users", headers=_auth(viewer_token))

        assert r_admin.status_code == 200
        assert r_analyst.status_code == 403
        assert r_viewer.status_code == 403
    finally:
        for uid in (admin_id, analyst_id, viewer_id):
            await _delete_user(uid)


@pytest.mark.asyncio
async def test_analyst_cannot_promote_self_to_admin_via_api(client):
    """Direct privilege-escalation attempt: an ANALYST calls the admin PATCH
    endpoint trying to grant themselves ADMIN. Must be rejected at the
    permission-dependency layer (403) before the request-body role value is
    ever inspected -- proves this can't be bypassed by simply calling the
    API directly, i.e. it's not just a hidden frontend button."""
    analyst_id, _, analyst_token = await _make_user(Role.ANALYST, "qa-escalate")
    try:
        response = await client.patch(
            f"{API}/admin/users/{analyst_id}", json={"role": "admin"}, headers=_auth(analyst_token)
        )
        assert response.status_code == 403

        from sqlalchemy import select

        from app.core.db import new_session
        from app.models.user import User

        async with new_session() as db:
            user = (await db.execute(select(User).where(User.id == analyst_id))).scalar_one()
            assert user.role == Role.ANALYST, "role must be unchanged after a rejected escalation attempt"
    finally:
        await _delete_user(analyst_id)


@pytest.mark.asyncio
async def test_viewer_cannot_disable_another_users_account_idor(client):
    """IDOR probe: a VIEWER (no user:manage permission at all) targets an
    arbitrary other user's ID on the disable endpoint. Must be rejected
    before any object-level check even runs."""
    viewer_id, _, viewer_token = await _make_user(Role.VIEWER, "qa-idor-viewer")
    victim_id, victim_email, _ = await _make_user(Role.ANALYST, "qa-idor-victim")
    try:
        response = await client.post(
            f"{API}/admin/users/{victim_id}/active", json={"is_active": False}, headers=_auth(viewer_token)
        )
        assert response.status_code == 403

        from sqlalchemy import select

        from app.core.db import new_session
        from app.models.user import User

        async with new_session() as db:
            victim = (await db.execute(select(User).where(User.id == victim_id))).scalar_one()
            assert victim.is_active is True, "the targeted account must be untouched after a rejected IDOR attempt"
    finally:
        await _delete_user(viewer_id)
        await _delete_user(victim_id)


@pytest.mark.asyncio
async def test_admin_endpoints_reject_an_unauthenticated_request(client):
    response = await client.get(f"{API}/admin/users")
    assert response.status_code in (401, 403)


# --- Immediate effect of role/disable changes ---------------------------------


@pytest.mark.asyncio
async def test_disabling_a_user_immediately_revokes_access_with_their_existing_token(client):
    """The account is disabled mid-"session" -- the already-issued, still
    unexpired access token must stop working on the VERY NEXT request, with
    no separate revocation-list bookkeeping required, because
    get_current_user() re-checks is_active from the database on every
    request rather than trusting the JWT."""
    user_id, email, token = await _make_user(Role.ANALYST, "qa-lockout")
    try:
        before = await client.get(f"{API}/auth/me", headers=_auth(token))
        assert before.status_code == 200

        await set_user_active(user_id, False, None, "actor@qa.test")

        after = await client.get(f"{API}/auth/me", headers=_auth(token))
        assert after.status_code == 401
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_role_downgrade_immediately_revokes_the_old_roles_access(client):
    """A user is promoted to ADMIN, uses their EXISTING token (still
    embedding the OLD role claim from before the promotion) to successfully
    call an admin-only route -- proving role changes take effect
    immediately without a fresh login -- then is demoted back, and the same
    still-unexpired token immediately loses that access again."""
    from app.core.users import update_user

    user_id, email, token = await _make_user(Role.ANALYST, "qa-roleswitch")
    try:
        before = await client.get(f"{API}/admin/users", headers=_auth(token))
        assert before.status_code == 403

        await update_user(user_id, actor_user_id=None, actor_email="actor@qa.test", role=Role.ADMIN)
        promoted = await client.get(f"{API}/admin/users", headers=_auth(token))
        assert promoted.status_code == 200, "the SAME token must gain access the instant the role changes"

        await update_user(user_id, actor_user_id=None, actor_email="actor@qa.test", role=Role.ANALYST)
        demoted = await client.get(f"{API}/admin/users", headers=_auth(token))
        assert demoted.status_code == 403, "the SAME token must lose access the instant the role changes back"
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_password_reset_immediately_invalidates_existing_tokens(client):
    """JWTs are stateless (signature + expiry only) -- without a
    token_version check, an administrator-initiated password reset would
    leave whatever access/refresh tokens the user already held valid until
    they naturally expire, which defeats the point of a security-driven
    reset. A token minted before the reset must stop working on its very
    next use; a token reflecting the new token_version (as a real
    /auth/login after the reset would produce) must keep working."""
    from app.core.users import reset_password

    user_id, email, old_token = await _make_user(Role.ANALYST, "qa-pwreset-session")
    try:
        before = await client.get(f"{API}/auth/me", headers=_auth(old_token))
        assert before.status_code == 200

        await reset_password(user_id, "brand-new-password-1", None, "actor@qa.test")

        after = await client.get(f"{API}/auth/me", headers=_auth(old_token))
        assert after.status_code == 401, "a token minted before the reset must stop working immediately"

        new_token = create_access_token(email, Role.ANALYST.value, token_version=1)
        after_new_login = await client.get(f"{API}/auth/me", headers=_auth(new_token))
        assert after_new_login.status_code == 200, "a token reflecting the post-reset token_version must still work"
    finally:
        await _delete_user(user_id)
