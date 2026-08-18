"""Integration tests for app.core.runtime_config's real, DB-backed upsert
functions -- not the pure _merge_credentials helper (see
app/tests/unit/test_runtime_config.py for that).

Regression tests for two real gaps found via adversarial re-verification of
BUG-01's fix:

1. The unit-level test only ever exercised `_merge_credentials` against a
   `SimpleNamespace` fake -- nothing verified the actual integration lines
   in `upsert_ioc_provider`/`upsert_ai_provider` (the merge result being
   correctly assigned to `row.encrypted_credentials`, `extra_config`/
   `model_id` None-guards) against a real DB session. A regression in that
   wiring (e.g. merge result computed but never assigned) would have passed
   the unit suite untouched.

2. `upsert_ioc_provider`/`upsert_ai_provider` did a plain read-modify-write
   with no row lock -- two concurrent saves to the SAME existing provider
   could each read the same pre-update credentials, merge independently,
   and the second commit would silently drop the first request's field.
   Fixed with `.with_for_update()` on the existing-row SELECT.

Runs against the real Postgres via app.core.db.new_session() -- intended to
run inside the backend container (`docker exec app-backend-1 python -m
pytest app/tests/integration`), where DATABASE_URL already resolves to the
real in-network `postgres` host with no override needed.
"""
import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import new_session
from app.core.runtime_config import upsert_ai_provider, upsert_ioc_provider
from app.models.runtime_config import ProviderKind, ProviderRuntimeConfig


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    """app.core.db's module-level engine/session-factory is created once,
    lazily, on first real use -- its asyncpg connection pool holds
    connections bound to whichever event loop was running at that moment.
    Each async test function here gets its OWN fresh event loop (standard
    pytest-asyncio per-function scope), so reusing the same already-pooled
    connection across test functions raises a cross-loop error on the
    second test onward (confirmed live: the first test in a run passes,
    the rest fail with an asyncpg ping error inside connection checkout).
    Rebuilding the engine at the start of every test, mirroring
    test_lookup_stream_persistence.py's identical defensive pattern, keeps
    it bound to the CURRENT test's loop. No URL override needed here (only
    that other file's fixture needs one, for its out-of-container use) --
    this suite runs inside the backend container where settings.database_url
    already resolves correctly."""
    import app.core.db as db_module
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import get_settings

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)
    yield
    await db_module._engine.dispose()


def _unique_provider_id(prefix: str) -> str:
    # A real, unused-elsewhere provider_id per test run -- never touches any
    # of the app's real, already-configured provider rows.
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _cleanup(provider_id: str, kind: ProviderKind) -> None:
    async with new_session() as db:
        row = (
            await db.execute(
                select(ProviderRuntimeConfig).where(
                    ProviderRuntimeConfig.kind == kind, ProviderRuntimeConfig.provider_id == provider_id
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_upsert_ioc_provider_empty_save_preserves_credential_end_to_end():
    provider_id = _unique_provider_id("qa-ioc")
    try:
        await upsert_ioc_provider(provider_id, "QA Test Provider", {"api_key": "real-value"})
        result = await upsert_ioc_provider(provider_id, "QA Test Provider", {})
        assert result["configured"] is True
        assert result["masked_credentials"].get("api_key")
    finally:
        await _cleanup(provider_id, ProviderKind.IOC)


@pytest.mark.asyncio
async def test_upsert_ai_provider_empty_save_preserves_credential_end_to_end():
    provider_id = _unique_provider_id("qa-ai")
    try:
        await upsert_ai_provider(provider_id, {"api_key": "real-value"}, None)
        result = await upsert_ai_provider(provider_id, {}, None)
        assert result["configured"] is True
        assert result["masked_credentials"].get("api_key")
    finally:
        await _cleanup(provider_id, ProviderKind.AI)


@pytest.mark.asyncio
async def test_upsert_ioc_provider_locks_the_row_it_reads():
    """Regression test for the race the row lock closes: two concurrent
    saves to the same existing provider, each updating a different field,
    would otherwise both read the same pre-update row and the second
    commit would silently drop the first's change.

    Three earlier versions of a timing/concurrency-based test for this were
    each wrong in a different way, confirmed live by deliberately reverting
    the fix and rerunning: a bare asyncio.gather() of two real calls passed
    even with the lock removed (two round-trips to a local Postgres
    complete too fast for asyncio to reliably interleave them without an
    explicit synchronization point); a hand-rolled second `SELECT ... FOR
    UPDATE` query written directly in the test proved Postgres's locking
    primitive works, not that upsert_ioc_provider() itself uses one, and
    passed unchanged after reverting the fix; and injecting an async delay
    into `_merge_credentials` failed outright because that function is
    synchronous (upsert_ioc_provider calls it without `await`), so an
    async replacement returned an unawaited coroutine into
    `json.dumps()`.

    This version sidesteps all three failure modes by asserting on the
    actual mechanism directly: capture the real SQL upsert_ioc_provider()
    sends to Postgres (via SQLAlchemy's before_cursor_execute event) and
    confirm the SELECT against provider_runtime_configs includes `FOR
    UPDATE`. This is what actually prevents the race -- a passing test here
    is not a proxy for the fix, it verifies the fix's own defining
    characteristic."""
    from sqlalchemy import event

    from app.core.db import _engine

    provider_id = _unique_provider_id("qa-lock")
    captured_statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        if "provider_runtime_configs" in statement and statement.strip().upper().startswith("SELECT"):
            captured_statements.append(statement)

    event.listen(_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        await upsert_ioc_provider(provider_id, "QA Lock Provider", {"api_key": "value"})
    finally:
        event.remove(_engine.sync_engine, "before_cursor_execute", _capture)
        await _cleanup(provider_id, ProviderKind.IOC)

    assert captured_statements, "upsert_ioc_provider must issue a SELECT against provider_runtime_configs"
    assert any("FOR UPDATE" in s.upper() for s in captured_statements), (
        "upsert_ioc_provider's read of the existing row must use SELECT ... FOR UPDATE -- "
        f"captured statements: {captured_statements}"
    )


@pytest.mark.asyncio
async def test_first_time_save_recovers_from_a_concurrent_insert_collision():
    """Regression test for a real, narrower gap left by the row-lock fix
    above: .with_for_update() only protects an EXISTING row. Two concurrent
    FIRST-EVER saves to the same brand-new, never-configured provider each
    find row=None and each try to INSERT -- the table's (kind, provider_id)
    unique constraint lets exactly one of those commits through, and the
    other used to raise IntegrityError straight to the caller (a visible
    500 on what should be an ordinary save, not silent data loss, but still
    a real bug).

    A first attempt at this test tried to force the actual two-request race
    via asyncio.gather() + an artificial delay in _merge_credentials, and
    failed for the same reason a similar attempt failed in the lock test
    above: _merge_credentials is synchronous (upsert_ioc_provider calls it
    without `await`), so an async replacement returns an unawaited
    coroutine into json.dumps() instead of actually delaying anything.

    This version tests the retry loop directly instead of trying to
    reproduce the exact race through real concurrency: makes the FIRST
    commit() raise IntegrityError (simulating "the other request's INSERT
    won"), and confirms upsert_ioc_provider retries the whole read-modify-
    write -- which, on the second attempt, finds the row a concurrent
    request would have just created -- rather than propagating the error."""
    from sqlalchemy.ext.asyncio import AsyncSession

    provider_id = _unique_provider_id("qa-race")
    original_commit = AsyncSession.commit
    call_count = {"value": 0}

    async def _fail_first_commit(self, *args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise IntegrityError("simulated concurrent INSERT collision", params=None, orig=Exception())
        return await original_commit(self, *args, **kwargs)

    AsyncSession.commit = _fail_first_commit
    try:
        result = await upsert_ioc_provider(provider_id, "QA Race Provider", {"api_key": "value"})
    finally:
        AsyncSession.commit = original_commit
        await _cleanup(provider_id, ProviderKind.IOC)

    # call_count is patched at the AsyncSession class level, so it also
    # counts record_audit()'s own unrelated commit after upsert_ioc_provider
    # returns -- >= 2 (not == 2) is the correct assertion: it confirms a
    # retry actually happened after the simulated collision, without being
    # brittle to how many other legitimate commits happen elsewhere in the
    # same call chain.
    assert call_count["value"] >= 2, "must retry after the simulated collision, not propagate it"
    assert result["configured"] is True
