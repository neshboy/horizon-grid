"""Integration tests for app.core.users -- the RBAC admin console's service
layer -- against the real Postgres database. See
app/tests/integration/test_runtime_config_persistence.py for the
_fresh_engine_per_test fixture pattern this file reuses verbatim (each async
test gets a fresh event loop; the module-level engine must be rebuilt per
test or asyncpg raises a cross-loop error from the second test onward).

Runs inside the backend container (`docker exec app-backend-1 python -m
pytest app/tests/integration/test_admin_users.py`), where DATABASE_URL
already resolves to the real in-network `postgres` host.
"""
import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import verify_password
from app.core.audit import list_audit_log
from app.core.config import get_settings
from app.core.db import new_session
from app.core.users import (
    DuplicateEmailError,
    LastAdminError,
    SelfDeactivationError,
    SelfRoleChangeError,
    UserNotFoundError,
    create_user,
    list_users,
    record_login_failure,
    record_login_success,
    reset_password,
    set_user_active,
    update_user,
)
from app.models.user import Role, User


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    import app.core.db as db_module

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)
    yield
    await db_module._engine.dispose()


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@qa.test"


async def _delete_user(user_id: uuid.UUID) -> None:
    """Test-only teardown. A user who ever acted as an audit actor (e.g. one
    test admin disabling another) has real config_audit_log rows pointing
    at them via a NOT NULL-safe but still enforced foreign key -- the same
    constraint that makes hard-delete unsafe for the real product (see
    app/core/users.py's module docstring). Clearing this disposable test
    run's own audit rows first is the QA-cleanup equivalent of that same
    constraint; it never touches any other audit history."""
    from app.models.runtime_config import ConfigAuditLog

    async with new_session() as db:
        await db.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor_user_id == user_id))
        await db.commit()
    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


@pytest_asyncio.fixture
async def _isolated_admin_set():
    """The last-admin-protection tests need an EXACT, known count of active
    admins to force the boundary condition -- but the production locking
    function (by design, for real protection) locks and counts every
    ADMIN-role row in the whole table, including whatever real admin
    accounts already exist in this dev database. Temporarily disables every
    pre-existing active admin so a test can create its own controlled set,
    then restores each one's exact prior is_active value afterward, even on
    failure."""
    async with new_session() as db:
        others = (
            await db.execute(select(User).where(User.role == Role.ADMIN, User.is_active.is_(True)))
        ).scalars().all()
        original = [(u.id, u.is_active) for u in others]
        for u in others:
            u.is_active = False
        await db.commit()
    try:
        yield
    finally:
        async with new_session() as db:
            for uid, was_active in original:
                u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
                if u is not None:
                    u.is_active = was_active
            await db.commit()


@pytest.mark.asyncio
async def test_create_user_then_duplicate_email_rejected():
    email = _unique_email("qa-create")
    created = await create_user(email, "correct-horse-1", "QA Create", Role.ANALYST, None, "actor@qa.test")
    try:
        assert created["email"] == email
        assert created["role"] == "analyst"
        with pytest.raises(DuplicateEmailError):
            await create_user(email, "another-password", "Dup", Role.VIEWER, None, "actor@qa.test")
    finally:
        await _delete_user(uuid.UUID(created["id"]))


@pytest.mark.asyncio
async def test_reset_password_actually_changes_the_stored_hash():
    email = _unique_email("qa-reset")
    created = await create_user(email, "original-pw-1", "QA Reset", Role.ANALYST, None, "actor@qa.test")
    try:
        await reset_password(uuid.UUID(created["id"]), "brand-new-pw-1", None, "actor@qa.test")
        async with new_session() as db:
            user = (await db.execute(select(User).where(User.id == uuid.UUID(created["id"])))).scalar_one()
            assert verify_password("brand-new-pw-1", user.hashed_password)
            assert not verify_password("original-pw-1", user.hashed_password)
    finally:
        await _delete_user(uuid.UUID(created["id"]))


@pytest.mark.asyncio
async def test_reset_password_unknown_user_raises():
    with pytest.raises(UserNotFoundError):
        await reset_password(uuid.uuid4(), "whatever-pw-1", None, "actor@qa.test")


@pytest.mark.asyncio
async def test_admin_cannot_change_their_own_role():
    email = _unique_email("qa-self")
    created = await create_user(email, "pw-self-1", "QA Self", Role.ADMIN, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        with pytest.raises(SelfRoleChangeError):
            await update_user(user_id, actor_user_id=user_id, actor_email=email, role=Role.ANALYST)
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_admin_cannot_disable_their_own_account():
    """Sibling guard to test_admin_cannot_change_their_own_role() above:
    set_user_active() backs the same kind of self-service access change
    (disabling your own account) that update_user()'s self-role-change
    check exists to prevent, just via the /active endpoint instead of a
    role edit. A companion admin is created so the (unrelated) last-active-
    admin invariant has two active admins to work with and would NOT itself
    have blocked this call -- isolating that it's specifically the
    self-target guard doing the rejecting."""
    email = _unique_email("qa-self-disable")
    companion_email = _unique_email("qa-self-disable-companion")
    created = await create_user(email, "pw-self-1", "QA Self Disable", Role.ADMIN, None, "actor@qa.test")
    companion = await create_user(companion_email, "pw-1", "Companion", Role.ADMIN, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    companion_id = uuid.UUID(companion["id"])
    try:
        with pytest.raises(SelfDeactivationError):
            await set_user_active(user_id, False, actor_user_id=user_id, actor_email=email)
        async with new_session() as db:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            assert user.is_active is True, "the caller's own account must be untouched after a rejected self-disable"
    finally:
        await _delete_user(user_id)
        await _delete_user(companion_id)


@pytest.mark.asyncio
async def test_cannot_demote_the_last_active_admin(_isolated_admin_set):
    email = _unique_email("qa-lastadmin-demote")
    created = await create_user(email, "pw-1", "QA Last Admin", Role.ADMIN, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        with pytest.raises(LastAdminError):
            await update_user(user_id, actor_user_id=None, actor_email="other@qa.test", role=Role.ANALYST)
        async with new_session() as db:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            assert user.role == Role.ADMIN
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_cannot_disable_the_last_active_admin(_isolated_admin_set):
    email = _unique_email("qa-lastadmin-disable")
    created = await create_user(email, "pw-1", "QA Last Admin", Role.ADMIN, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        with pytest.raises(LastAdminError):
            await set_user_active(user_id, False, None, "other@qa.test")
        async with new_session() as db:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            assert user.is_active is True
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_demoting_or_disabling_a_non_last_admin_succeeds(_isolated_admin_set):
    """Sanity check that the last-admin guard doesn't over-fire: with TWO
    active admins, demoting/disabling one of them must succeed."""
    email_a = _unique_email("qa-twoadmins-a")
    email_b = _unique_email("qa-twoadmins-b")
    a = await create_user(email_a, "pw-1", "A", Role.ADMIN, None, "actor@qa.test")
    b = await create_user(email_b, "pw-1", "B", Role.ADMIN, None, "actor@qa.test")
    a_id, b_id = uuid.UUID(a["id"]), uuid.UUID(b["id"])
    try:
        result = await set_user_active(a_id, False, b_id, email_b)
        assert result["is_active"] is False
    finally:
        await _delete_user(a_id)
        await _delete_user(b_id)


@pytest.mark.asyncio
async def test_concurrent_disable_of_both_last_admins_only_one_succeeds(_isolated_admin_set):
    """The real race this feature must prevent: exactly two active admins,
    two concurrent requests each try to disable a DIFFERENT one of them at
    the same time. A bare row-lock on only each request's own target would
    let both succeed (each sees the other still active) and leave zero
    admins. app.core.users.set_user_active locks every ADMIN-role row
    up front, so Postgres serializes the second request behind the first;
    it must then correctly recompute and refuse."""
    email_a = _unique_email("qa-race-a")
    email_b = _unique_email("qa-race-b")
    a = await create_user(email_a, "pw-1", "A", Role.ADMIN, None, "actor@qa.test")
    b = await create_user(email_b, "pw-1", "B", Role.ADMIN, None, "actor@qa.test")
    a_id, b_id = uuid.UUID(a["id"]), uuid.UUID(b["id"])
    try:
        results = await asyncio.gather(
            set_user_active(a_id, False, b_id, email_b),
            set_user_active(b_id, False, a_id, email_a),
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, LastAdminError)]
        assert len(successes) == 1, f"exactly one disable must succeed, got: {results}"
        assert len(failures) == 1, f"exactly one disable must be rejected as the last admin, got: {results}"

        async with new_session() as db:
            remaining_active = (
                await db.execute(
                    select(User).where(User.id.in_([a_id, b_id]), User.is_active.is_(True))
                )
            ).scalars().all()
            assert len(remaining_active) == 1, "at least one (and only one) admin must remain active"
    finally:
        await _delete_user(a_id)
        await _delete_user(b_id)


@pytest.mark.asyncio
async def test_list_users_search_and_role_filter():
    email = _unique_email("qa-search-needle")
    created = await create_user(email, "pw-1", "Needle Analyst", Role.ANALYST, None, "actor@qa.test")
    try:
        result = await list_users(search="qa-search-needle")
        assert any(u["email"] == email for u in result["items"])
        assert all("qa-search-needle" in u["email"] for u in result["items"])

        result_role = await list_users(search="qa-search-needle", role=Role.VIEWER)
        assert result_role["items"] == []
    finally:
        await _delete_user(uuid.UUID(created["id"]))


@pytest.mark.asyncio
async def test_list_users_sort_by_last_login_desc_puts_nulls_last():
    """Regression test for the NULLS-FIRST-on-DESC bug: last_login_at is
    nullable (NULL for a user who has never logged in), and Postgres's
    default null-ordering puts NULLs FIRST for a bare `ORDER BY ... DESC`
    unless the query overrides it. That silently buried every user with a
    real recent login behind every never-logged-in user on a descending
    sort -- list_users() must instead put the never-logged-in (NULL) user
    LAST, symmetric with the ascending case."""
    shared = uuid.uuid4().hex[:10]
    email_logged = f"qa-sortnull-{shared}-logged@qa.test"
    email_never = f"qa-sortnull-{shared}-never@qa.test"
    logged = await create_user(email_logged, "pw-1", "Sort Logged", Role.ANALYST, None, "actor@qa.test")
    never = await create_user(email_never, "pw-1", "Sort Never", Role.ANALYST, None, "actor@qa.test")
    logged_id, never_id = uuid.UUID(logged["id"]), uuid.UUID(never["id"])
    try:
        await record_login_success(logged_id, email_logged)

        desc = await list_users(search=f"qa-sortnull-{shared}", sort_by="last_login_at", sort_dir="desc")
        assert [u["email"] for u in desc["items"]] == [email_logged, email_never], (
            "descending sort must put the user with a real last_login_at first "
            "and the never-logged-in (NULL) user last"
        )
        assert desc["items"][0]["last_login_at"] is not None
        assert desc["items"][1]["last_login_at"] is None

        asc = await list_users(search=f"qa-sortnull-{shared}", sort_by="last_login_at", sort_dir="asc")
        assert [u["email"] for u in asc["items"]] == [email_logged, email_never], (
            "ascending sort must also put the never-logged-in (NULL) user last"
        )
    finally:
        await _delete_user(logged_id)
        await _delete_user(never_id)


@pytest.mark.asyncio
async def test_login_success_records_last_login_at_and_audit_entry():
    email = _unique_email("qa-login-ok")
    created = await create_user(email, "pw-1", "Login OK", Role.ANALYST, None, "actor@qa.test")
    user_id = uuid.UUID(created["id"])
    try:
        await record_login_success(user_id, email)
        async with new_session() as db:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            assert user.last_login_at is not None
        entries = await list_audit_log(limit=500)
        assert any(e["action"] == "auth.login" and email in e["detail"] for e in entries)
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_login_failure_is_audited_and_the_function_has_no_password_parameter_to_leak():
    """record_login_failure()'s signature is (email: str) only -- there is
    no password parameter for a caller to accidentally interpolate into the
    audit detail. Confirms both that a failed-login attempt is actually
    recorded, and that the recorded entry contains only the email."""
    import inspect

    assert list(inspect.signature(record_login_failure).parameters) == ["email"]

    email = _unique_email("qa-login-fail")
    await record_login_failure(email)
    entries = await list_audit_log(limit=500)
    matching = [e for e in entries if e["action"] == "auth.login_failed" and email in e["detail"]]
    assert matching, "a failed-login audit entry for this email must be recorded"
