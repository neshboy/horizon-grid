"""Regression test for a confirmed P2 finding: POST /api/v1/basket's
add_to_basket() had an unguarded check-then-insert race against the
(owner_id, ioc_value) unique constraint (uq_basket_owner_ioc) on
basket_items.

Root cause: the route did

    existing = SELECT ... WHERE owner_id = ? AND ioc_value = ?
    if existing: return existing
    <build item>
    db.add(item)
    await db.commit()

with no synchronization between the SELECT and the INSERT. Two concurrent
POSTs for the same (owner_id, ioc_value) can both pass the SELECT (both see
None), then both attempt the INSERT -- Postgres's unique constraint lets
exactly one commit() through and raises sqlalchemy.exc.IntegrityError to the
other. Unlike app/core/users.py's create_user() (catches IntegrityError ->
DuplicateEmailError) and app/core/runtime_config.py's upsert_ai_provider()/
upsert_ioc_provider() (retry-after-IntegrityError, see their own
docstrings), add_to_basket() had no handler on this path at all, so the
loser got an unhandled 500 instead of the idempotent-add behavior the
pre-insert dedup SELECT was clearly meant to provide (this is an ordinary
double-submit case, not a real conflict -- both callers wanted the exact
same outcome).

Live-reproduced against the running dev stack before the fix: 6 concurrent
POST /api/v1/basket requests with the identical body for the same user
produced 5x 201 and 1x 500, with `docker compose logs backend` showing
sqlalchemy.exc.IntegrityError raised out of `await db.commit()` in
add_to_basket, uncaught.

Fixed by catching IntegrityError around that commit, rolling back the
now-aborted transaction, and re-running the same dedup SELECT to hand back
the row that won the race -- matching this codebase's own established
pattern for this exact class of bug.

This test follows test_runtime_config_persistence.py's
test_first_time_save_recovers_from_a_concurrent_insert_collision precedent
for testing this class of bug: a bare asyncio.gather() of two real HTTP
round-trips against a local Postgres is too fast to reliably interleave
(confirmed by that file's own docstring, describing three earlier failed
attempts at a genuine timing-based race test). Instead, this monkeypatches
AsyncSession.commit so the first call simulates "the other request's
INSERT already won": it commits a real competing row via a second,
unpatched session (so the unique constraint is actually live in the DB,
not just asserted-around), then raises IntegrityError -- letting
add_to_basket()'s own except-block run for real against a genuine
conflicting row, while still deterministically triggering it every run.

Runs against the real app (ASGI transport) and the real Postgres this
docker-compose stack's backend container already talks to, the same way
test_ioc_type_hint_validation.py does.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

RACE_IOC_VALUE = "race-test-domain-example.com"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    # Each pytest-asyncio test function runs its own event loop; a pooled
    # asyncpg connection created in a previous test's loop cannot be reused
    # in this test's loop ("Future attached to a different loop"). Matches
    # test_security_assessment_api.py's/test_basket_compare_status_filter.py's
    # own fixture of the same name/shape -- confirmed live that this file was
    # missing it: running the real app/tests/integration suite in its normal
    # (alphabetical) collection order deterministically failed this file's
    # own test with exactly that RuntimeError, inheriting a connection pool
    # bound to a preceding test file's already-closed event loop.
    import app.core.db as db_module

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)
    yield
    await db_module._engine.dispose()


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@qa.test"


async def _make_analyst():
    from app.auth.security import create_access_token
    from app.core.users import create_user
    from app.models.user import Role

    email = _unique_email("qa-basket-race")
    created = await create_user(email, "pw-1", "Basket Race Test User", Role.ANALYST, None, "actor@qa.test")
    token = create_access_token(email, Role.ANALYST.value)
    return uuid.UUID(created["id"]), token


async def _cleanup(user_id: uuid.UUID) -> None:
    from app.core.db import new_session
    from app.models.basket import BasketItem
    from app.models.user import User

    async with new_session() as db:
        items = (await db.execute(select(BasketItem).where(BasketItem.owner_id == user_id))).scalars().all()
        for item in items:
            await db.delete(item)
        await db.commit()
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_add_to_basket_returns_existing_item_instead_of_500_on_insert_race():
    """The exact live repro, deterministically triggered: the request's own
    commit() raises IntegrityError (because a real competing row -- the
    'other' concurrent request's winning INSERT -- already exists for the
    same (owner_id, ioc_value)). Must respond 201 with that existing item,
    not an unhandled 500, and must leave exactly one basket_items row
    behind."""
    from app.main import app
    from app.core.db import new_session
    from app.models.basket import BasketItem

    user_id, token = await _make_analyst()
    original_commit = AsyncSession.commit
    call_count = {"value": 0}

    async def _fail_first_commit(self, *args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            # Simulate the winning side of the race committing first, via a
            # second session that bypasses this patch entirely (calls the
            # real, unpatched commit directly) -- this is a genuinely
            # committed, real conflicting row, not a mocked return value.
            async with new_session() as winner_db:
                winner_db.add(
                    BasketItem(owner_id=user_id, ioc_value=RACE_IOC_VALUE, ioc_type="domain", note=None)
                )
                await original_commit(winner_db)
            raise IntegrityError(
                'duplicate key value violates unique constraint "uq_basket_owner_ioc"',
                params=None,
                orig=Exception("simulated concurrent INSERT collision"),
            )
        return await original_commit(self, *args, **kwargs)

    AsyncSession.commit = _fail_first_commit
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/basket",
                json={"ioc_value": RACE_IOC_VALUE, "ioc_type_hint": "domain"},
                headers=_auth(token),
            )
    finally:
        AsyncSession.commit = original_commit

    try:
        assert response.status_code == 201, (
            "the losing side of a check-then-insert race must still return 201 with the winner's "
            f"item, not propagate the IntegrityError as a 500; got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body["ioc_value"] == RACE_IOC_VALUE
        assert call_count["value"] >= 1, "the request must actually have gone through the patched commit()"

        async with new_session() as db:
            rows = (
                await db.execute(
                    select(BasketItem).where(
                        BasketItem.owner_id == user_id, BasketItem.ioc_value == RACE_IOC_VALUE
                    )
                )
            ).scalars().all()
        assert len(rows) == 1, "exactly one basket_items row must exist after the race, not zero or two"
        assert body["id"] == str(rows[0].id), "the response must be the winner's row, not a phantom duplicate"
    finally:
        await _cleanup(user_id)
