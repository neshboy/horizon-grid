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

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.security import create_access_token
from app.core.config import get_settings
from app.core.db import new_session
from app.core import runtime_config as runtime_config_module
from app.core.runtime_config import (
    AI_BACKENDS,
    get_ai_config,
    record_ai_test_result,
    record_ioc_test_result,
    set_active_ai_backend,
    set_ioc_provider_enabled,
    upsert_ai_provider,
    upsert_ioc_provider,
)
from app.core.users import create_user
from app.main import app
from app.models.runtime_config import ProviderKind, ProviderRuntimeConfig
from app.models.user import Role

API = get_settings().api_v1_prefix


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
async def test_upsert_ioc_provider_rejects_undeclared_credential_field_end_to_end():
    """Regression test for a real, live-reproduced bug: POSTing
    {"credentials": {"totally_made_up_field": "junk"}} to
    POST /api/v1/runtime/ioc-providers/virustotal (whose only declared
    field is api_key, per IOC_PROVIDER_CREDENTIAL_FIELDS) returned 200 and
    permanently persisted `totally_made_up_field` into that row's encrypted
    credential JSON alongside the real api_key -- a field the settings
    UI's ProviderConfigRow.tsx never renders (it only renders
    `credential_fields` for the provider), so it could never again be seen
    or removed once saved.

    Uses the real "virustotal" provider_id (not a synthetic one) since the
    fix is specifically scoped to provider_ids that declare a field list in
    IOC_PROVIDER_CREDENTIAL_FIELDS -- snapshots and restores whatever was
    already configured so this doesn't leave the shared dev DB's real
    virustotal row any different than it found it."""
    from app.core.runtime_config import get_ioc_provider_snapshot

    before_snapshot = (await get_ioc_provider_snapshot()).get("virustotal", {})
    before_creds = dict(before_snapshot.get("credentials") or {})

    try:
        with pytest.raises(ValueError, match="totally_made_up_field"):
            await upsert_ioc_provider("virustotal", "VirusTotal", {"totally_made_up_field": "junkvalue123"})

        after_snapshot = (await get_ioc_provider_snapshot()).get("virustotal", {})
        assert after_snapshot.get("credentials") == before_creds, (
            "a rejected save must not mutate the already-stored virustotal credentials"
        )
    finally:
        if before_creds:
            await upsert_ioc_provider("virustotal", "VirusTotal", before_creds)


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
async def test_plaintext_credential_field_is_not_masked():
    """Real bug found live: Ollama's base_url is plain config, not a secret,
    but was masked identically to every real credential -- leaving the
    frontend no way to pre-fill it for re-testing an already-configured
    connection without the operator retyping the exact URL from memory (a
    blank retype sent an empty base_url, producing a false "both required"
    error against a genuinely-configured, working connection). Uses a
    synthetic provider_id registered into _PLAINTEXT_CREDENTIAL_FIELDS for
    the duration of this test only, rather than touching the real "ollama"
    row this app actually uses."""
    provider_id = _unique_provider_id("qa-plaintext")
    original = dict(runtime_config_module._PLAINTEXT_CREDENTIAL_FIELDS)
    runtime_config_module._PLAINTEXT_CREDENTIAL_FIELDS = {**original, provider_id: {"base_url"}}
    try:
        result = await upsert_ai_provider(
            provider_id, {"base_url": "http://host.docker.internal:11434", "api_key": "real-secret"}, "some-model"
        )
        assert result["masked_credentials"]["base_url"] == "http://host.docker.internal:11434"
        assert result["masked_credentials"]["api_key"] != "real-secret"
    finally:
        runtime_config_module._PLAINTEXT_CREDENTIAL_FIELDS = original
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


@pytest.mark.asyncio
async def test_upsert_ai_provider_rejects_a_link_local_ollama_base_url():
    """Regression test for a real SSRF gap found during a mission-critical-
    readiness review: this save path (the one every real Ollama config
    change actually goes through -- app/api/routes/runtime.py's
    configure_ai_provider) previously persisted an operator-supplied
    base_url with zero validation, even though app/core/url_safety.py's
    assert_safe_outbound_url() already existed -- it was just never called
    from here, only from the separate Test-Connection convenience path.

    Deliberately targets the real "ollama" backend id, since the new guard
    is gated on that literal string, not an arbitrary test-only provider_id
    -- but the whole point of the guard is to raise BEFORE any DB write
    happens, so this must leave whatever was already configured untouched.
    The pre-existing config is snapshotted and restored regardless, as a
    second line of defense against that assumption ever being wrong."""
    before = await get_ai_config("ollama")

    try:
        with pytest.raises(ValueError, match="link-local"):
            await upsert_ai_provider("ollama", {"base_url": "http://169.254.169.254:11434"}, None)

        after = await get_ai_config("ollama")
        assert after == before, "a rejected save must not mutate the already-stored Ollama config"
    finally:
        if before is not None:
            await upsert_ai_provider("ollama", before["credentials"], before["model_id"])
        else:
            await _cleanup("ollama", ProviderKind.AI)


@pytest.mark.asyncio
async def test_set_active_ai_backend_locks_the_rows_it_reads():
    """Regression test for BUG-01-sibling: unlike upsert_ai_provider/
    upsert_ioc_provider (see test_upsert_ioc_provider_locks_the_row_it_reads
    above), set_active_ai_backend used to read every AI provider row with a
    plain, unlocked SELECT, flip `is_active` on each row in a Python loop,
    and commit. Two concurrent calls (e.g. one admin picking 'openai' while
    another picks 'groq' at the same moment) could each read the same
    "currently active" snapshot before either commits, each independently
    decide which rows should now be True/False, and both commits succeed --
    leaving TWO rows with is_active=True, violating this table's own
    documented invariant ("exactly one AI row should have is_active=True at
    a time") and making get_active_ai_config()'s .scalar_one_or_none() raise
    an unhandled MultipleResultsFound for every AI-assisted feature
    platform-wide.

    Per this file's own documented lessons learned on
    test_upsert_ioc_provider_locks_the_row_it_reads above (three different
    real-concurrency approaches for this exact class of race each proved
    unreliable or tested the wrong thing against a local Postgres), this
    verifies the fix's own defining characteristic directly: capture the
    real SQL set_active_ai_backend() sends to Postgres and confirm the
    SELECT against provider_runtime_configs includes `FOR UPDATE`. That is
    what actually serializes concurrent callers (the second caller's SELECT
    blocks until the first's transaction commits, so it re-reads the
    first's already-applied result before applying its own) -- a passing
    test here is not a proxy for the fix, it verifies the fix's own
    mechanism.

    Uses a synthetic backend id temporarily added to AI_BACKENDS (mirroring
    test_plaintext_credential_field_is_not_masked's pattern above) so this
    never touches any of the app's real, already-configured AI provider
    rows (which other agents/tests may be relying on concurrently in this
    shared dev DB)."""
    from sqlalchemy import event

    from app.core.db import _engine

    backend_id = _unique_provider_id("qa-ai-lock")
    original_backends = list(runtime_config_module.AI_BACKENDS)
    runtime_config_module.AI_BACKENDS = original_backends + [backend_id]
    captured_statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        if "provider_runtime_configs" in statement and statement.strip().upper().startswith("SELECT"):
            captured_statements.append(statement)

    event.listen(_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        await set_active_ai_backend(backend_id)
    finally:
        event.remove(_engine.sync_engine, "before_cursor_execute", _capture)
        runtime_config_module.AI_BACKENDS = original_backends
        await _cleanup(backend_id, ProviderKind.AI)

    assert captured_statements, "set_active_ai_backend must issue a SELECT against provider_runtime_configs"
    assert any("FOR UPDATE" in s.upper() for s in captured_statements), (
        "set_active_ai_backend's read of every AI provider row must use SELECT ... FOR UPDATE -- "
        f"captured statements: {captured_statements}"
    )


# --- Regression tests: record_ai_test_result / record_ioc_test_result /
# set_ioc_provider_enabled never got the same SELECT-then-INSERT-if-None
# race protection as upsert_ai_provider/upsert_ioc_provider above.
#
# Live reproduction that motivated these (see PR description): calling any
# of these three functions concurrently for the same brand-new provider_id
# (no ProviderRuntimeConfig row yet -- e.g. a custom AI backend, or any IOC
# provider added after this install's original seed_from_env_if_empty() ran)
# reliably raised an unhandled sqlalchemy.exc.IntegrityError
# (asyncpg.exceptions.UniqueViolationError on uq_provider_runtime_kind_id)
# out of one of the concurrent calls -- surfacing as a bare HTTP 500 from
# POST /api/v1/runtime/ai-providers/{backend}/record-test,
# POST /api/v1/runtime/ioc-providers/{provider_id}/record-test, and
# POST /api/v1/runtime/ioc-providers/{provider_id}/enabled respectively.
#
# Per this file's own documented lessons learned above (test_upsert_ioc_provider_
# locks_the_row_it_reads's docstring), a bare asyncio.gather() of two real
# calls against a fast local Postgres is not a reliable way to force this
# race in a test. These reuse the same commit-patching technique as
# test_first_time_save_recovers_from_a_concurrent_insert_collision above:
# force the FIRST commit() to raise IntegrityError (simulating "a concurrent
# request's INSERT for this same brand-new provider_id won"), and confirm
# each function retries its whole read-modify-write instead of propagating
# the error to the caller.


@pytest.mark.asyncio
async def test_record_ai_test_result_first_time_recovers_from_a_concurrent_insert_collision():
    from sqlalchemy.ext.asyncio import AsyncSession

    backend = _unique_provider_id("qa-ai-test-race")
    original_commit = AsyncSession.commit
    call_count = {"value": 0}

    async def _fail_first_commit(self, *args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise IntegrityError("simulated concurrent INSERT collision", params=None, orig=Exception())
        return await original_commit(self, *args, **kwargs)

    row = None
    AsyncSession.commit = _fail_first_commit
    try:
        await record_ai_test_result(backend, True, "ok")
        async with new_session() as db:
            row = (
                await db.execute(
                    select(ProviderRuntimeConfig).where(
                        ProviderRuntimeConfig.kind == ProviderKind.AI, ProviderRuntimeConfig.provider_id == backend
                    )
                )
            ).scalar_one_or_none()
    finally:
        AsyncSession.commit = original_commit
        await _cleanup(backend, ProviderKind.AI)

    # >= 2 rather than == 2 for the same reason as the upsert_ioc_provider
    # version above: this patches AsyncSession.commit() globally, so it also
    # counts record_audit()'s own unrelated commit after
    # record_ai_test_result returns.
    assert call_count["value"] >= 2, "must retry after the simulated collision, not propagate it"
    assert row is not None and row.last_test_ok is True


@pytest.mark.asyncio
async def test_record_ioc_test_result_first_time_recovers_from_a_concurrent_insert_collision():
    from sqlalchemy.ext.asyncio import AsyncSession

    provider_id = _unique_provider_id("qa-ioc-test-race")
    original_commit = AsyncSession.commit
    call_count = {"value": 0}

    async def _fail_first_commit(self, *args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise IntegrityError("simulated concurrent INSERT collision", params=None, orig=Exception())
        return await original_commit(self, *args, **kwargs)

    row = None
    AsyncSession.commit = _fail_first_commit
    try:
        await record_ioc_test_result(provider_id, True, "ok")
        async with new_session() as db:
            row = (
                await db.execute(
                    select(ProviderRuntimeConfig).where(
                        ProviderRuntimeConfig.kind == ProviderKind.IOC, ProviderRuntimeConfig.provider_id == provider_id
                    )
                )
            ).scalar_one_or_none()
    finally:
        AsyncSession.commit = original_commit
        await _cleanup(provider_id, ProviderKind.IOC)

    assert call_count["value"] >= 2, "must retry after the simulated collision, not propagate it"
    assert row is not None and row.last_test_ok is True


@pytest.mark.asyncio
async def test_set_ioc_provider_enabled_first_time_recovers_from_a_concurrent_insert_collision():
    from sqlalchemy.ext.asyncio import AsyncSession

    provider_id = _unique_provider_id("qa-ioc-enable-race")
    original_commit = AsyncSession.commit
    call_count = {"value": 0}

    async def _fail_first_commit(self, *args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise IntegrityError("simulated concurrent INSERT collision", params=None, orig=Exception())
        return await original_commit(self, *args, **kwargs)

    row = None
    AsyncSession.commit = _fail_first_commit
    try:
        await set_ioc_provider_enabled(provider_id, False)
        async with new_session() as db:
            row = (
                await db.execute(
                    select(ProviderRuntimeConfig).where(
                        ProviderRuntimeConfig.kind == ProviderKind.IOC, ProviderRuntimeConfig.provider_id == provider_id
                    )
                )
            ).scalar_one_or_none()
    finally:
        AsyncSession.commit = original_commit
        await _cleanup(provider_id, ProviderKind.IOC)

    assert call_count["value"] >= 2, "must retry after the simulated collision, not propagate it"
    assert row is not None and row.enabled is False


@pytest.mark.asyncio
async def test_list_ai_providers_route_includes_every_known_backend_even_with_no_db_rows():
    """Real gap found live during overnight QA: GET /runtime/ai-providers
    used to be a bare passthrough to the DB query -- unlike GET
    /runtime/ioc-providers, which merges the DB against the live provider
    registry so a provider added to the code after this install's one-time
    seed ran is still visible. A new AI backend added to AI_BACKENDS after
    an existing install's first boot was permanently unreachable from this
    route (and therefore from the Admin UI panel that renders from it).
    Deletes every AI row first so this reproduces the worst case: an
    upgraded install where the DB has learned about NONE of the current
    AI_BACKENDS yet."""
    async with new_session() as db:
        rows = (await db.execute(select(ProviderRuntimeConfig).where(ProviderRuntimeConfig.kind == ProviderKind.AI))).scalars().all()
        snapshot = [(r.provider_id, r) for r in rows]
        for _, r in snapshot:
            await db.delete(r)
        await db.commit()

    email = f"ai-provider-list-test-{uuid.uuid4().hex[:10]}@qa.test"
    try:
        created = await create_user(email, "pw-1", "AI Provider List Test", Role.ADMIN, None, "actor@qa.test")
        token = create_access_token(email, Role.ADMIN.value)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(
                f"{API}/runtime/ai-providers",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        returned_ids = {row["provider_id"] for row in resp.json()}
        assert returned_ids == set(AI_BACKENDS), (
            f"missing from the merged list: {set(AI_BACKENDS) - returned_ids}"
        )
        # Every synthesized placeholder must be a sane, non-crashing default.
        for row in resp.json():
            assert row["configured"] is False
            assert row["enabled"] is True

        from app.core.db import new_session as _new_session
        from app.models.user import User

        async with _new_session() as db:
            u = await db.get(User, created["id"])
            if u is not None:
                await db.delete(u)
                await db.commit()
    finally:
        # Restore whatever AI provider rows existed before this test ran.
        async with new_session() as db:
            for provider_id, row in snapshot:
                db.add(
                    ProviderRuntimeConfig(
                        kind=ProviderKind.AI,
                        provider_id=row.provider_id,
                        provider_name=row.provider_name,
                        enabled=row.enabled,
                        is_active=row.is_active,
                        encrypted_credentials=row.encrypted_credentials,
                        model_id=row.model_id,
                    )
                )
            await db.commit()
