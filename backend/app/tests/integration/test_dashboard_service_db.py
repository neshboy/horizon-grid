"""DB-fixture-backed tests for app.core.dashboard's two aggregation
functions (get_kpis / get_provider_health_history) against the real,
shared, already-populated dev Postgres instance -- following the exact
host-infra-override + per-test-engine-dispose pattern established by
test_lookup_export_permissions.py / test_deterministic_scoring.py (see
either for the full rationale; there is no shared conftest.py in this repo).

This is a genuinely SHARED, already-populated database (confirmed live:
get_kpis() returns nonzero KPIs and get_provider_health_history() shows real
provider history before this file's fixtures ever run) -- so tests here
follow test_deterministic_scoring.py's own pattern of computing an
INDEPENDENT ground truth from the real DB rather than asserting hardcoded
absolute numbers, wherever a metric isn't already isolated by construction.

get_provider_health_history() IS naturally isolated per-provider (every
query is scoped by `ProviderResultRecord.provider_id == provider.provider_id`),
so tests of it monkeypatch app.core.dashboard.get_all_providers() to return
only a single fake provider with a fresh uuid-suffixed provider_id that no
real row can ever match -- giving exact-value assertions with zero risk of
shared-DB contamination, while still exercising the real function/query
end-to-end.

get_kpis()'s provider_health_percentage/ai_success_rate are NOT scoped by
provider/backend, so those tests instead prove exclusion by independently
computing both the CORRECT (excluding) and a deliberately WRONG (including)
percentage from the real DB and asserting get_kpis() matches the correct one
and NOT the wrong one -- valid regardless of whatever unrelated data already
exists in this shared instance.
"""
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.providers.base import ProviderCategory

POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5433
REDIS_HOST = "localhost"
REDIS_PORT = 6379


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


@pytest_asyncio.fixture
async def fixture_lookup():
    """A bare, real IOCLookup row -- ProviderResultRecord/FinalAssessmentRecord
    both have a NOT NULL FK to ioc_lookups.id, so every fixture row in this
    file needs a real parent to attach to. No DB-level ON DELETE CASCADE
    exists here (see test_deterministic_scoring.py's
    _delete_lookup_and_dependents for the same observation), so teardown
    deletes children before the parent."""
    from app.core.db import new_session
    from app.models.lookup import IOCLookup, LookupStatus

    async with new_session() as db:
        lookup = IOCLookup(
            ioc_value=f"qa-dashboard-fixture-{uuid.uuid4().hex[:12]}.example.test",
            ioc_type="domain",
            status=LookupStatus.COMPLETED,
        )
        db.add(lookup)
        await db.commit()
        await db.refresh(lookup)
        lookup_id = lookup.id

    yield lookup_id

    from app.models.lookup import FinalAssessmentRecord, ProviderResultRecord

    async with new_session() as db:
        await db.execute(delete(ProviderResultRecord).where(ProviderResultRecord.lookup_id == lookup_id))
        await db.execute(delete(FinalAssessmentRecord).where(FinalAssessmentRecord.lookup_id == lookup_id))
        await db.commit()
        row = await db.get(IOCLookup, lookup_id)
        if row is not None:
            await db.delete(row)
            await db.commit()


async def _add_provider_result(
    lookup_id: uuid.UUID, provider_id: str, status: str, created_at=None, latency_ms=None
) -> None:
    from app.core.db import new_session
    from app.models.lookup import ProviderResultRecord

    async with new_session() as db:
        row = ProviderResultRecord(
            lookup_id=lookup_id,
            provider_id=provider_id,
            provider_name=provider_id,
            category="threat_intel",
            status=status,
            data={},
            latency_ms=latency_ms,
        )
        if created_at is not None:
            row.created_at = created_at
        db.add(row)
        await db.commit()


async def _add_final_assessment(lookup_id: uuid.UUID, ai_outcome: str, created_at=None) -> None:
    from app.core.db import new_session
    from app.models.lookup import FinalAssessmentRecord

    async with new_session() as db:
        row = FinalAssessmentRecord(
            lookup_id=lookup_id,
            ai_backend="ollama",
            ai_model="qa-fixture-model",
            ai_outcome=ai_outcome,
            is_primary=False,
            assessment={"qa": "fixture"},
        )
        if created_at is not None:
            row.created_at = created_at
        db.add(row)
        await db.commit()


class _FakeProvider:
    """Stands in for a real app.providers.base.BaseProvider instance -- only
    the attributes get_provider_health_history() actually reads."""

    def __init__(self, provider_id: str):
        from app.ioc.types import IOCType

        self.provider_id = provider_id
        self.provider_name = f"QA Fixture Provider ({provider_id})"
        self.category = ProviderCategory.THREAT_INTEL
        self.configured = True
        self.requires_key = True
        self.supported_types = [IOCType.IPV4, IOCType.DOMAIN]


def _fresh_fake_provider_id() -> str:
    return f"qa-fixture-provider-{uuid.uuid4().hex[:12]}"


# --- get_kpis(): not_configured/disabled exclusion (provider_health_percentage) --------


@pytest.mark.asyncio
async def test_provider_health_percentage_excludes_not_configured_and_disabled_rows(fixture_lookup):
    from app.core.dashboard import get_kpis
    from app.core.db import new_session
    from app.models.lookup import ProviderResultRecord

    now = datetime.now(timezone.utc)
    provider_id = _fresh_fake_provider_id()
    # 2 real successes, plus 2 rows that must NOT count as real attempts at all.
    await _add_provider_result(fixture_lookup, provider_id, "ok", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "ok", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "not_configured", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "disabled", created_at=now)

    kpis = await get_kpis()

    # Independently compute, from the SAME real (shared, already-populated)
    # table, what the CORRECT (excluding not_configured/disabled) and a
    # deliberately WRONG (including them) 24h percentage would be.
    window_start = now - timedelta(hours=24)
    async with new_session() as db:
        correct_attempts = (
            await db.execute(
                select(func.count())
                .select_from(ProviderResultRecord)
                .where(
                    ProviderResultRecord.created_at >= window_start,
                    ProviderResultRecord.status.notin_(("not_configured", "disabled")),
                )
            )
        ).scalar_one()
        # "ok" alone is NOT the correct ground truth here -- get_kpis() counts
        # no_data/unsupported_ioc as healthy too (see
        # test_provider_health_percentage_counts_no_data_as_healthy for that
        # dedicated test); this query must match get_kpis()'s REAL definition
        # of "healthy" or this test would fail the moment any real no_data
        # row exists anywhere in this shared, ever-growing 24h window --
        # confirmed live: it did, once enough real investigation traffic
        # accumulated in this table over the course of a long session.
        correct_ok = (
            await db.execute(
                select(func.count())
                .select_from(ProviderResultRecord)
                .where(
                    ProviderResultRecord.created_at >= window_start,
                    ProviderResultRecord.status.in_(("ok", "no_data", "unsupported_ioc")),
                )
            )
        ).scalar_one()
        buggy_attempts = (
            await db.execute(
                select(func.count())
                .select_from(ProviderResultRecord)
                .where(ProviderResultRecord.created_at >= window_start)
            )
        ).scalar_one()

    expected_correct_pct = round(correct_ok / correct_attempts * 100, 2)
    expected_buggy_pct = round(correct_ok / buggy_attempts * 100, 2)

    assert kpis["provider_health_percentage"] == expected_correct_pct
    # Sanity check that our fixture rows actually moved the denominator, so
    # this assertion is a real proof of exclusion, not a coincidence.
    assert expected_correct_pct != expected_buggy_pct
    assert kpis["provider_health_percentage"] != expected_buggy_pct


# --- get_kpis(): no_data/unsupported_ioc count as healthy, not failure -----------------


@pytest.mark.asyncio
async def test_provider_health_percentage_counts_no_data_as_healthy(fixture_lookup):
    """Regression test for the same real bug as
    test_no_data_and_unsupported_ioc_count_as_healthy_not_failure, at the KPI
    level: a provider correctly reporting "nothing found" must not drag the
    fleet-wide health percentage down."""
    from app.core.dashboard import get_kpis
    from app.core.db import new_session
    from app.models.lookup import ProviderResultRecord

    now = datetime.now(timezone.utc)
    provider_id = _fresh_fake_provider_id()
    await _add_provider_result(fixture_lookup, provider_id, "no_data", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "no_data", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "unsupported_ioc", created_at=now)

    kpis = await get_kpis()

    window_start = now - timedelta(hours=24)
    async with new_session() as db:
        correct_attempts = (
            await db.execute(
                select(func.count())
                .select_from(ProviderResultRecord)
                .where(
                    ProviderResultRecord.created_at >= window_start,
                    ProviderResultRecord.status.notin_(("not_configured", "disabled")),
                )
            )
        ).scalar_one()
        correct_healthy = (
            await db.execute(
                select(func.count())
                .select_from(ProviderResultRecord)
                .where(
                    ProviderResultRecord.created_at >= window_start,
                    ProviderResultRecord.status.in_(("ok", "no_data", "unsupported_ioc")),
                )
            )
        ).scalar_one()
        buggy_ok_only = (
            await db.execute(
                select(func.count())
                .select_from(ProviderResultRecord)
                .where(ProviderResultRecord.created_at >= window_start, ProviderResultRecord.status == "ok")
            )
        ).scalar_one()

    expected_correct_pct = round(correct_healthy / correct_attempts * 100, 2)
    expected_buggy_pct = round(buggy_ok_only / correct_attempts * 100, 2)

    assert kpis["provider_health_percentage"] == expected_correct_pct
    assert expected_correct_pct != expected_buggy_pct
    assert kpis["provider_health_percentage"] != expected_buggy_pct


# --- get_kpis(): skipped_no_evidence exclusion (ai_success_rate) -----------------------


@pytest.mark.asyncio
async def test_ai_success_rate_excludes_skipped_no_evidence(fixture_lookup):
    from app.core.dashboard import get_kpis
    from app.core.db import new_session
    from app.models.lookup import FinalAssessmentRecord

    now = datetime.now(timezone.utc)
    # 1 success, 1 failed, and a deliberately LARGE number of skipped rows --
    # large enough that if they were ever counted as failures (a plausible
    # bug), the resulting rate would visibly differ from the correct one.
    await _add_final_assessment(fixture_lookup, "success", created_at=now)
    await _add_final_assessment(fixture_lookup, "failed", created_at=now)
    for _ in range(10):
        await _add_final_assessment(fixture_lookup, "skipped_no_evidence", created_at=now)

    kpis = await get_kpis()

    window_start = now - timedelta(days=30)
    async with new_session() as db:
        success = (
            await db.execute(
                select(func.count())
                .select_from(FinalAssessmentRecord)
                .where(FinalAssessmentRecord.ai_outcome == "success", FinalAssessmentRecord.created_at >= window_start)
            )
        ).scalar_one()
        failed = (
            await db.execute(
                select(func.count())
                .select_from(FinalAssessmentRecord)
                .where(FinalAssessmentRecord.ai_outcome == "failed", FinalAssessmentRecord.created_at >= window_start)
            )
        ).scalar_one()
        skipped = (
            await db.execute(
                select(func.count())
                .select_from(FinalAssessmentRecord)
                .where(
                    FinalAssessmentRecord.ai_outcome == "skipped_no_evidence",
                    FinalAssessmentRecord.created_at >= window_start,
                )
            )
        ).scalar_one()

    expected_correct_rate = round(success / (success + failed) * 100, 2)
    # The wrong computation a regression might reintroduce: treating a skip
    # as if it were counted in the denominator (e.g. as a failure).
    expected_wrong_rate = round(success / (success + failed + skipped) * 100, 2)

    assert kpis["ai_success_rate"] == expected_correct_rate
    assert expected_correct_rate != expected_wrong_rate
    assert kpis["ai_success_rate"] != expected_wrong_rate


# --- get_provider_health_history(): isolated per-fake-provider tests -------------------


@pytest.mark.asyncio
async def test_response_still_includes_the_old_static_config_fields(monkeypatch):
    """Regression test for a real bug caught after this endpoint's response
    shape changed: frontend/app/lookup/new/page.tsx's getProviderHealth()
    caller already depends on `supported_types` (to compute how many
    providers are expected to respond for the detected IOC type) and does
    `p.supported_types.includes(iocType)` -- if this field were ever dropped
    again, that would be a live TypeError crash for every real user starting
    a new investigation, not merely a missing feature."""
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    fake = _FakeProvider(provider_id)
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [fake])

    result = await dashboard.get_provider_health_history()
    entry = next(e for e in result if e["provider_id"] == provider_id)

    assert entry["configured"] == fake.configured
    assert entry["requires_key"] == fake.requires_key
    assert entry["supported_types"] == sorted(t.value for t in fake.supported_types)


@pytest.mark.asyncio
async def test_zero_rows_reports_unknown_never_healthy_in_every_window(monkeypatch):
    """THE critical rule, exercised end-to-end: a provider with literally
    zero ProviderResultRecord rows anywhere must report status="unknown" in
    EVERY window, never "healthy" -- and success_rate/avg_latency_ms must be
    None (no data), not 0/some fabricated number."""
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [_FakeProvider(provider_id)])

    result = await dashboard.get_provider_health_history()
    assert len(result) == 1
    entry = result[0]
    assert entry["provider_id"] == provider_id

    for window in ("1h", "24h", "7d", "30d"):
        assert entry[window]["status"] == "unknown"
        assert entry[window]["success_rate"] is None
        assert entry[window]["avg_latency_ms"] is None
        assert entry[window]["consecutive_failures"] == 0
        assert entry[window]["rate_limited_count"] == 0


@pytest.mark.asyncio
async def test_not_configured_and_disabled_rows_are_excluded_from_success_rate_and_status(
    fixture_lookup, monkeypatch
):
    """Without the exclusion, 2 real errors + 2 not_configured/disabled rows
    would read as a 0% success rate ("down"); WITH the exclusion (the
    correct behavior), those 2 non-attempt rows vanish from the denominator
    entirely, leaving 0 real attempts -> "unknown", not "down"."""
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [_FakeProvider(provider_id)])

    now = datetime.now(timezone.utc)
    await _add_provider_result(fixture_lookup, provider_id, "not_configured", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "disabled", created_at=now)

    result = await dashboard.get_provider_health_history()
    entry = next(e for e in result if e["provider_id"] == provider_id)

    for window in ("1h", "24h", "7d", "30d"):
        assert entry[window]["status"] == "unknown", (
            f"{window}: not_configured/disabled rows must not count as real attempts"
        )
        assert entry[window]["success_rate"] is None


@pytest.mark.asyncio
async def test_success_rate_and_status_computed_correctly_once_non_attempt_rows_are_excluded(
    fixture_lookup, monkeypatch
):
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [_FakeProvider(provider_id)])

    now = datetime.now(timezone.utc)
    # 3 ok (latency 100/200/300 -> avg 200), then a not_configured, then the
    # most recent row being the one real error -- distinct, strictly
    # increasing timestamps so the most-recent-first walk below is
    # deterministic (ties on created_at would make row order DB-dependent).
    await _add_provider_result(fixture_lookup, provider_id, "ok", created_at=now - timedelta(minutes=4), latency_ms=100)
    await _add_provider_result(fixture_lookup, provider_id, "ok", created_at=now - timedelta(minutes=3), latency_ms=200)
    await _add_provider_result(fixture_lookup, provider_id, "ok", created_at=now - timedelta(minutes=2), latency_ms=300)
    await _add_provider_result(fixture_lookup, provider_id, "not_configured", created_at=now - timedelta(minutes=1))
    await _add_provider_result(fixture_lookup, provider_id, "error", created_at=now)

    result = await dashboard.get_provider_health_history()
    entry = next(e for e in result if e["provider_id"] == provider_id)

    for window in ("1h", "24h", "7d", "30d"):
        # attempts = 3 ok + 1 error = 4 (not_configured excluded) -> 75%.
        assert entry[window]["success_rate"] == 75.0
        assert entry[window]["status"] == "degraded"  # 75% < 90% healthy threshold
        assert entry[window]["avg_latency_ms"] == 200.0
        assert entry[window]["consecutive_failures"] == 1  # the single 'error', most-recent-first


@pytest.mark.asyncio
async def test_consecutive_failures_skips_non_attempt_rows_without_breaking_the_streak(
    fixture_lookup, monkeypatch
):
    """Insert, oldest to newest: ok, error, not_configured, error, disabled,
    error(most recent). Walking most-recent-first: error(counts=1) ->
    disabled(skip) -> error(counts=2) -> not_configured(skip) ->
    error(counts=3) -> ok(stop). Expected consecutive_failures == 3."""
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [_FakeProvider(provider_id)])

    now = datetime.now(timezone.utc)
    sequence = ["ok", "error", "not_configured", "error", "disabled", "error"]
    for i, status in enumerate(sequence):
        # Strictly increasing created_at so ORDER BY created_at DESC is deterministic.
        await _add_provider_result(fixture_lookup, provider_id, status, created_at=now - timedelta(minutes=len(sequence) - i))

    result = await dashboard.get_provider_health_history()
    entry = next(e for e in result if e["provider_id"] == provider_id)

    # Same all-time streak must show up identically in every window.
    for window in ("1h", "24h", "7d", "30d"):
        assert entry[window]["consecutive_failures"] == 3


@pytest.mark.asyncio
async def test_consecutive_failures_is_not_reset_by_a_window_boundary(fixture_lookup, monkeypatch):
    """The failing rows are all OLDER than every window (>30 days ago), but a
    genuine ongoing failure streak must still be reported -- consecutive_failures
    is explicitly NOT scoped to the window."""
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [_FakeProvider(provider_id)])

    long_ago = datetime.now(timezone.utc) - timedelta(days=45)
    await _add_provider_result(fixture_lookup, provider_id, "ok", created_at=long_ago - timedelta(minutes=2))
    await _add_provider_result(fixture_lookup, provider_id, "error", created_at=long_ago - timedelta(minutes=1))
    await _add_provider_result(fixture_lookup, provider_id, "error", created_at=long_ago)

    result = await dashboard.get_provider_health_history()
    entry = next(e for e in result if e["provider_id"] == provider_id)

    for window in ("1h", "24h", "7d", "30d"):
        # Zero rows fall inside any of these windows -> unknown/no rate --
        # but the all-time failure streak must still be reported.
        assert entry[window]["status"] == "unknown"
        assert entry[window]["consecutive_failures"] == 2


@pytest.mark.asyncio
async def test_no_data_and_unsupported_ioc_count_as_healthy_not_failure(fixture_lookup, monkeypatch):
    """Regression test for a real bug caught by an adversarial review pass:
    NO_DATA means the provider was reached fine and correctly reported
    "nothing on this indicator" -- most real-world IOCs legitimately get this
    from most providers. UNSUPPORTED_IOC means the provider correctly
    recognized it doesn't handle this IOC type. Neither is a failure of the
    provider. Before the fix, both were counted as failures, which would have
    reported a perfectly healthy provider as "down"/"degraded" for doing
    exactly what it's supposed to do."""
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [_FakeProvider(provider_id)])

    now = datetime.now(timezone.utc)
    await _add_provider_result(fixture_lookup, provider_id, "no_data", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "no_data", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "unsupported_ioc", created_at=now)

    result = await dashboard.get_provider_health_history()
    entry = next(e for e in result if e["provider_id"] == provider_id)

    for window in ("1h", "24h", "7d", "30d"):
        assert entry[window]["success_rate"] == 100.0, (
            f"{window}: no_data/unsupported_ioc must count as healthy attempts, not failures"
        )
        assert entry[window]["status"] == "healthy"
        assert entry[window]["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_consecutive_failures_treats_no_data_as_ending_the_streak(fixture_lookup, monkeypatch):
    """Insert, oldest to newest: error, error, no_data(most recent). Before
    the fix, the streak walk only stopped at literal 'ok', so this would have
    reported consecutive_failures == 1 (only skipping non-attempt rows, still
    counting nothing before the no_data since it's the most recent row --
    actually it would have COUNTED the no_data as a failure too, giving 3).
    Correct behavior: no_data ends the streak immediately, like 'ok' does."""
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [_FakeProvider(provider_id)])

    now = datetime.now(timezone.utc)
    await _add_provider_result(fixture_lookup, provider_id, "error", created_at=now - timedelta(minutes=2))
    await _add_provider_result(fixture_lookup, provider_id, "error", created_at=now - timedelta(minutes=1))
    await _add_provider_result(fixture_lookup, provider_id, "no_data", created_at=now)

    result = await dashboard.get_provider_health_history()
    entry = next(e for e in result if e["provider_id"] == provider_id)

    for window in ("1h", "24h", "7d", "30d"):
        assert entry[window]["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_avg_latency_ms_includes_no_data_but_not_unsupported_ioc(fixture_lookup, monkeypatch):
    """no_data represents a completed real network round-trip (worth
    averaging into latency); unsupported_ioc is typically rejected locally
    before any request is made, so it must be excluded from the latency
    average even though it counts as a healthy outcome for success_rate."""
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [_FakeProvider(provider_id)])

    now = datetime.now(timezone.utc)
    await _add_provider_result(fixture_lookup, provider_id, "ok", created_at=now, latency_ms=100)
    await _add_provider_result(fixture_lookup, provider_id, "no_data", created_at=now, latency_ms=300)
    # Should be excluded from the average even though it has a latency value.
    await _add_provider_result(fixture_lookup, provider_id, "unsupported_ioc", created_at=now, latency_ms=999999)

    result = await dashboard.get_provider_health_history()
    entry = next(e for e in result if e["provider_id"] == provider_id)

    for window in ("1h", "24h", "7d", "30d"):
        assert entry[window]["avg_latency_ms"] == 200.0  # mean of 100 and 300 only


@pytest.mark.asyncio
async def test_rate_limited_count_is_scoped_to_each_window(fixture_lookup, monkeypatch):
    import app.core.dashboard as dashboard

    provider_id = _fresh_fake_provider_id()
    monkeypatch.setattr(dashboard, "get_all_providers", lambda: [_FakeProvider(provider_id)])

    now = datetime.now(timezone.utc)
    # 2 recent rate_limited rows (inside every window) + 1 at 10 days ago
    # (inside 30d only, outside 1h/24h/7d).
    await _add_provider_result(fixture_lookup, provider_id, "rate_limited", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "rate_limited", created_at=now)
    await _add_provider_result(fixture_lookup, provider_id, "rate_limited", created_at=now - timedelta(days=10))

    result = await dashboard.get_provider_health_history()
    entry = next(e for e in result if e["provider_id"] == provider_id)

    assert entry["1h"]["rate_limited_count"] == 2
    assert entry["24h"]["rate_limited_count"] == 2
    assert entry["7d"]["rate_limited_count"] == 2
    assert entry["30d"]["rate_limited_count"] == 3
