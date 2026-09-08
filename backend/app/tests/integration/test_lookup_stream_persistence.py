"""Regression test for a severe bug found via live E2E testing: every lookup
ever created was stuck at status=RUNNING forever, even though provider
results/correlation edges/evidence rows all persisted fine and the SSE stream
itself emitted `final_assessment` and `done` events correctly.

Root cause: the route's `Depends(get_db)` session is torn down by FastAPI's
dependency exit-stack as soon as the route function *returns* the
StreamingResponse object -- but event_stream() is a generator that Starlette
doesn't actually drive until after that return (generators are lazy). By the
time the generator mutated `lookup.status`, the session had already closed
and detached that ORM object, so the mutation was silently dropped on the
next commit (fresh db.add()s still "worked" since they create new objects in
an implicit new transaction, which is why provider/correlation/evidence rows
looked fine while the lookup's own completion status never did).

Fix: app/api/routes/lookup.py's event_stream() now opens its own session via
app.core.db.new_session() for the generator's entire lifetime, and re-fetches
the IOCLookup row through THAT session before mutating it.

This test exercises the real route (via ASGI transport, real Postgres on the
docker-compose-published port) with a fake provider (no real network calls)
and a stubbed AI client (no real Ollama dependency), then asserts the DB row
actually reaches COMPLETED with a final_verdict/risk_score set -- the exact
thing that was silently broken.
"""
import asyncio
import os
import socket

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
    """Prefer the real in-docker-network hostname (`postgres`/`redis`, on
    their normal 5432/6379 ports) -- reachable when this test runs INSIDE the
    backend container via `docker compose exec`, which is both this
    project's documented dev workflow and its own CI's "integration-docker"
    job. Falls back to the docker-compose HOST-published port
    (localhost:5433/6379) for a developer invoking pytest directly on the
    bare host, outside any container.

    Bug this fixes: this module used to hardcode ONLY the host-published
    localhost:5433/6379 pair. Inside the backend container, "localhost" is
    the container's OWN loopback -- nothing listens there on 5433/6379 (only
    the in-network `postgres`/`redis` hostnames route to the real
    datastores from inside the container; confirmed live via a direct
    socket.connect from inside the running backend container). That made
    the skipif below always evaluate to True whenever this file was run the
    documented way (`docker compose exec backend python -m pytest ...`), so
    every test in it silently skipped there -- never actually executing
    anywhere in the automated pipeline.
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
    """Settings.database_url/redis_url default to the in-network `postgres`/
    `redis` hostnames; override to the host-published ports for this
    out-of-container test process, mirroring test_lookup_flow.py's REDIS_URL
    override pattern. The lookup route's rate limiter (app/core/cache.py)
    talks to Redis directly, so both overrides are needed for a real request.

    app.core.db builds its engine/session-factory at MODULE IMPORT time from
    whatever settings.database_url resolved to then -- if another test module
    (or app.main's own import chain) imported it first with the in-network
    hostname, only mutating os.environ + clearing the settings cache here
    would have no effect on that already-built engine. Rebuilding the
    module's _engine/_SessionLocal directly makes this override reliable
    regardless of test collection/import order.
    """
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
    """Both app.core.db's engine/pool and app.core.cache's Redis pool are
    bound to whichever asyncio event loop was running when their connections
    were first opened; pytest-asyncio gives each test function its own event
    loop, so reusing pooled connections across tests raises "Event loop is
    closed" during connection teardown (same root cause test_lookup_flow.py's
    clean_redis_cache fixture works around for the Redis pool alone -- this
    test also opens real Postgres connections, so both need resetting).
    """
    yield
    import app.core.cache as cache_module
    from app.core.db import _engine

    await _engine.dispose()
    if cache_module._pool is not None:
        await cache_module._pool.aclose()
        cache_module._pool = None


async def _delete_lookup_and_dependents(db_session, lookup) -> None:
    """FinalAssessmentRecord deliberately has no cascade from IOCLookup (every
    assessment ever generated is kept even if something else about the lookup
    changes -- see app/models/lookup.py), so it's never auto-deleted with the
    lookup; clear it explicitly first, matching the pattern already
    established in test_security_assessment_api.py's _cleanup_lookup(). Every
    test in this file used to skip this step and leave every lookup it
    created permanently undeletable (confirmed live: re-running this suite
    hit "update or delete on ioc_lookups violates foreign key constraint
    final_assessment_records_lookup_id_fkey" on a lookup from the prior run)."""
    from sqlalchemy import delete

    from app.models.lookup import FinalAssessmentRecord

    await db_session.execute(delete(FinalAssessmentRecord).where(FinalAssessmentRecord.lookup_id == lookup.id))
    await db_session.commit()
    await db_session.delete(lookup)
    await db_session.commit()


@pytest_asyncio.fixture
async def db_session():
    # Imported after the DATABASE_URL override above takes effect, and after
    # cache_clear(), so app.core.db builds its engine against the overridden
    # settings rather than a module-load-time cached one.
    from app.core.db import new_session

    async with new_session() as session:
        yield session


async def _purge_stream_persistence_test_user() -> None:
    """Deletes any pre-existing 'stream-persistence-test@example.test' user
    (this file's fixed, not per-test-unique, email) and everything that
    still references it, via its own brand-new session.

    This fixture uses the same fixed email across every test in the file --
    so relying solely on a bare `delete(user); commit()` at THIS fixture's
    OWN teardown is not enough on its own: if the test that just ran
    failed/errored before reaching its own full cleanup (an IOCLookup's
    _delete_lookup_and_dependents(), or test_startup_recovers_orphaned_
    pentest_rows's own explicit child-then-parent pentest deletes), whatever
    it created referencing this user's id survives, the teardown's delete
    raises IntegrityError, and -- confirmed live -- the user row is left
    behind permanently, cascading into every LATER test in the file failing
    at setup with a UniqueViolationError on this same fixed email, unrelated
    to whatever they actually test.

    Called from test_user's own setup (not only its teardown): confirmed
    live that at least one test in this file (test_provider_result_is_
    committed_before_next_provider_runs) leaves its OWN event loop/session
    in a state where a later, unrelated await in that SAME test's teardown
    phase fails outright (a MissingGreenlet error) -- so a cleanup attempt
    at THAT test's own teardown can itself be unreliable. Re-running this
    same purge at the START of every subsequent test's setup instead means
    the file self-heals from any prior test's incomplete teardown
    regardless of why that teardown failed, rather than depending on it
    succeeding.
    """
    from sqlalchemy import delete, select

    from app.core.db import new_session
    from app.models.lookup import IOCLookup
    from app.models.pentest import PentestAssessment, PentestExploitAttempt, PentestFinding, PentestTarget
    from app.models.user import User

    async with new_session() as cleanup_db:
        user = (
            await cleanup_db.execute(select(User).where(User.email == "stream-persistence-test@example.test"))
        ).scalar_one_or_none()
        if user is None:
            return

        # Reuses _delete_lookup_and_dependents (not a bulk Core delete()) on
        # purpose: IOCLookup.provider_results/ai_summaries/correlation_edges
        # are all `cascade="all, delete-orphan"` ORM relationships (see
        # app/models/lookup.py), which only fire for a session-tracked
        # `db_session.delete(<object>)` -- a bulk `delete(IOCLookup)...`
        # Core statement bypasses the ORM entirely and does not cascade,
        # leaving e.g. ai_summaries rows behind to violate
        # ai_summaries_lookup_id_fkey (confirmed live) the moment this
        # defensive sweep tried that instead.
        stray_lookups = (
            (await cleanup_db.execute(select(IOCLookup).where(IOCLookup.requested_by == user.id))).scalars().all()
        )
        for stray_lookup in stray_lookups:
            await _delete_lookup_and_dependents(cleanup_db, stray_lookup)

        stray_assessment_ids = (
            (await cleanup_db.execute(select(PentestAssessment.id).where(PentestAssessment.created_by == user.id)))
            .scalars()
            .all()
        )
        if stray_assessment_ids:
            await cleanup_db.execute(
                delete(PentestExploitAttempt).where(PentestExploitAttempt.assessment_id.in_(stray_assessment_ids))
            )
            await cleanup_db.execute(
                delete(PentestFinding).where(PentestFinding.assessment_id.in_(stray_assessment_ids))
            )
            await cleanup_db.execute(
                delete(PentestTarget).where(PentestTarget.assessment_id.in_(stray_assessment_ids))
            )
            await cleanup_db.execute(
                delete(PentestAssessment).where(PentestAssessment.id.in_(stray_assessment_ids))
            )
            await cleanup_db.commit()
        # Any exploit attempt this user requested against an assessment
        # created by someone ELSE (not the case anywhere in this file today,
        # but cheap to close off) would otherwise still dangle after the
        # sweep above.
        await cleanup_db.execute(delete(PentestExploitAttempt).where(PentestExploitAttempt.requested_by == user.id))
        await cleanup_db.commit()

        await cleanup_db.delete(user)
        await cleanup_db.commit()


@pytest_asyncio.fixture
async def test_user(db_session):
    from app.auth.security import hash_password
    from app.models.user import Role, User

    await _purge_stream_persistence_test_user()

    user = User(
        email="stream-persistence-test@example.test",
        hashed_password=hash_password("irrelevant"),
        full_name="Stream Persistence Test",
        role=Role.ANALYST,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    # Best-effort here -- see _purge_stream_persistence_test_user()'s own
    # docstring for why the NEXT test's setup, not this teardown, is this
    # file's real safety net. Swallowing a failure here (logging it rather
    # than letting it become an opaque "ERROR at teardown" that masks
    # whatever this test's own body actually did) is deliberate: this
    # fixture's contract is "this user exists for the duration of the test
    # it's requested in," which was already satisfied by the time we get
    # here.
    try:
        await db_session.delete(user)
        await db_session.commit()
    except Exception as exc:  # noqa: BLE001 -- see docstring above
        import logging

        logging.getLogger(__name__).warning(
            "test_user teardown could not delete %s directly (%r) -- "
            "the next test's setup will purge it instead.",
            user.email, exc,
        )


@pytest.fixture
def auth_headers(test_user):
    from app.auth.security import create_access_token

    token = create_access_token(test_user.email, test_user.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def fake_provider_and_ai(monkeypatch):
    """Replaces the real provider fan-out and AI backend so this test hits
    neither the network nor a local Ollama server -- only Postgres is real.

    The stub AI response below uses final_verdict="suspicious", not
    "malicious" -- see test_completed_lookup_persists_ai_outcome_success_on_final_assessment_record's
    docstring (point 2) for the full explanation: a single, uncorroborated
    provider vote deterministically scores malicious_probability=26.0
    (app/scoring/engine.py), which generate_final_assessment() swaps in
    before re-validating, and 26.0 is below _verdict_must_agree_with_risk's
    threshold for "malicious". "suspicious" is outside both
    _MALICIOUS_VERDICTS and _BENIGN_VERDICTS, so it agrees with any risk
    score and keeps this fixture consistent with the real scoring engine
    it runs against, instead of relying on an AI-invented probability
    (90) that never actually reaches the persisted row."""
    from app.ai import schemas as ai_schemas
    from app.ai import service as ai_service
    from app.ioc.types import IOCType
    from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus

    async def fake_run_all_providers(ioc_value, ioc_type, candidate_providers=None):
        yield ProviderResult(
            provider_id="fake_stream_test",
            provider_name="Fake Stream Test Provider",
            category=ProviderCategory.THREAT_INTEL,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data={"verdict": "malicious", "detection_ratio": "10/70"},
        )

    monkeypatch.setattr("app.api.routes.lookup.run_all_providers", fake_run_all_providers)

    class _StubAIClient:
        is_configured = True

        async def call_claude_json(self, system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None):
            if tool_name == "emit_provider_summary":
                return {
                    "provider_id": "fake_stream_test",
                    "what_it_knows": "Flagged as malicious.",
                    "reputation": "malicious",
                    "detection_status": "10/70",
                    "threat_level": "high",
                    "confidence": "high",
                    "interesting_findings": ["High detection ratio"],
                }
            return {
                "executive_summary": "Test executive summary.",
                "technical_summary": "Test technical summary.",
                "threat_assessment": "Test threat assessment.",
                "relationships_summary": "No relationships discovered.",
                "risk": {
                    "overall_risk_score": 85,
                    "confidence_score": 80,
                    "severity": "high",
                    "reputation": "malicious",
                    "malicious_probability": 90,
                    "analyst_confidence": "high",
                },
                "final_verdict": "suspicious",
                "verdict_rationale": "High detection ratio across providers.",
            }

    async def _stub_get_ai_client(backend_override=None):
        return _StubAIClient(), "ollama", "stub-model"

    monkeypatch.setattr(ai_service, "_get_ai_client", _stub_get_ai_client)
    yield


@pytest.mark.asyncio
async def test_completed_lookup_persists_completed_status_and_verdict(
    fake_provider_and_ai, auth_headers, db_session
):
    from app.main import app
    from app.models.lookup import IOCLookup

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/v1/lookup/stream",
            json={"value": "203.0.113.99"},
            headers=auth_headers,
            timeout=30.0,
        ) as response:
            assert response.status_code == 200
            events = []
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    events.append(line.removeprefix("event: "))

    assert "done" in events
    assert "error" not in events

    lookup = (
        await db_session.execute(select(IOCLookup).where(IOCLookup.ioc_value == "203.0.113.99"))
    ).scalar_one_or_none()
    assert lookup is not None, "lookup row was never created"
    # This is the exact assertion that was failing before the fix -- status
    # stayed "running" forever despite a clean `done` event on the stream.
    assert lookup.status.value == "completed"
    assert lookup.final_verdict is not None
    assert lookup.final_verdict.value == "suspicious"
    # 26.0, not the AI stub's invented 85 -- generate_final_assessment()
    # always swaps in the real deterministic score (app/scoring/engine.py)
    # before persisting, regardless of what the AI's own risk.overall_risk_score
    # claimed. See fake_provider_and_ai's docstring above for why 26.0 is the
    # correct value for this fixture's single, uncorroborated provider vote.
    assert lookup.risk_score == 26.0

    await _delete_lookup_and_dependents(db_session, lookup)


@pytest.mark.asyncio
async def test_completed_lookup_persists_ai_outcome_success_on_final_assessment_record(
    db_session, monkeypatch
):
    """End-to-end confirmation of the new ai_outcome column (app/models/lookup.py's
    FinalAssessmentRecord, backed by alembic/versions/6716ed40b9f2): a real
    lookup that goes through the actual success path (the stubbed AI client
    below returns a fully valid FinalAssessment payload that survives
    generate_final_assessment's post-validation swap-in of the deterministic
    score, so the success branch runs to completion, not either fallback)
    must persist ai_outcome="success" on the FinalAssessmentRecord row --
    not just in-memory on the FinalAssessment object (already covered by
    test_ai_service.py's unit tests), but the actual mapped column a future
    KPI query would read without deserializing the JSONB `assessment` blob.

    Deliberately self-contained rather than reusing this module's shared
    fake_provider_and_ai/test_user/auth_headers fixtures, for two independent
    reasons found while writing this test:

    1. test_user/auth_headers share one hardcoded email
       (stream-persistence-test@example.test). This file's own other tests
       demonstrate that a single test erroring before its teardown runs (a
       pre-existing test-isolation gap, not something this migration
       introduces) leaves that row stuck in the live, shared Postgres
       instance, which then makes EVERY later test sharing that fixture
       error on a duplicate-key violation for the rest of the run. A
       uuid-suffixed, locally-created user sidesteps that entirely.

    2. fake_provider_and_ai's stub AI hardcodes final_verdict="malicious"
       with its OWN invented malicious_probability=90 -- but a single
       provider vote with no correlation edges can deterministically reach
       AT MOST 26.0 (app/scoring/engine.py's _corroboration_factor caps a
       lone, uncorroborated vote at 0.40 of the provider weight; confirmed
       directly: `score_investigation([that exact fake ProviderResult],
       empty_correlation)` returns malicious_probability=26.0). Since
       generate_final_assessment() swaps in the REAL 26.0 before
       re-validating, and 26.0 < 30 fails _verdict_must_agree_with_risk for
       a "malicious" verdict, that fixture's stub AI response actually
       always gets rejected on both attempts and falls through to the
       ai_outcome="failed" fallback -- a latent, pre-existing mismatch
       between that shared fixture and the deterministic-scoring validator
       added in an earlier workstream, invisible until now because issue #1
       above always errored those tests before they reached that far. Using
       final_verdict="suspicious" below (outside both _MALICIOUS_VERDICTS
       and _BENIGN_VERDICTS, per app/ai/schemas.py's
       _verdict_must_agree_with_risk) sidesteps it without needing to touch
       that shared fixture or the scoring engine, neither of which is this
       migration's job to fix.
    """
    import uuid as _uuid

    from app.ai import service as ai_service
    from app.auth.security import create_access_token, hash_password
    from app.main import app
    from app.models.lookup import FinalAssessmentRecord, IOCLookup
    from app.models.user import Role, User
    from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus

    async def fake_run_all_providers(ioc_value, ioc_type, candidate_providers=None):
        yield ProviderResult(
            provider_id="fake_ai_outcome_provider",
            provider_name="Fake AI Outcome Provider",
            category=ProviderCategory.THREAT_INTEL,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data={"verdict": "suspicious", "detection_ratio": "3/70"},
        )

    monkeypatch.setattr("app.api.routes.lookup.run_all_providers", fake_run_all_providers)

    class _StubAIClient:
        is_configured = True

        async def call_claude_json(self, system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None):
            if tool_name == "emit_provider_summary":
                return {
                    "provider_id": "fake_ai_outcome_provider",
                    "what_it_knows": "Possibly suspicious.",
                    "reputation": "suspicious",
                    "detection_status": "3/70",
                    "threat_level": "low",
                    "confidence": "low",
                    "interesting_findings": [],
                }
            return {
                "executive_summary": "Test executive summary.",
                "technical_summary": "Test technical summary.",
                "threat_assessment": "Test threat assessment.",
                "relationships_summary": "No relationships discovered.",
                "risk": {
                    "overall_risk_score": 10,
                    "confidence_score": 30,
                    "severity": "low",
                    "reputation": "suspicious",
                    "malicious_probability": 10,
                    "analyst_confidence": "low",
                },
                # Neither _MALICIOUS_VERDICTS nor _BENIGN_VERDICTS (see
                # app/ai/schemas.py's _verdict_must_agree_with_risk) --
                # survives the deterministic-score swap-and-revalidate step
                # regardless of the real computed malicious_probability.
                "final_verdict": "suspicious",
                "verdict_rationale": "Low-confidence single-provider signal.",
            }

    async def _stub_get_ai_client(backend_override=None):
        return _StubAIClient(), "ollama", "stub-model"

    monkeypatch.setattr(ai_service, "_get_ai_client", _stub_get_ai_client)

    unique = _uuid.uuid4().hex[:12]
    user = User(
        email=f"ai-outcome-verify-{unique}@example.test",
        hashed_password=hash_password("irrelevant"),
        full_name="AI Outcome Verify Test",
        role=Role.ANALYST,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    auth_headers = {"Authorization": f"Bearer {create_access_token(user.email, user.role.value)}"}
    ioc_value = f"203.0.113.{200 + (int(unique, 16) % 50)}"

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with client.stream(
                "POST",
                "/api/v1/lookup/stream",
                json={"value": ioc_value},
                headers=auth_headers,
                timeout=30.0,
            ) as response:
                assert response.status_code == 200
                events = []
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        events.append(line.removeprefix("event: "))

        assert "done" in events
        assert "error" not in events

        lookup = (
            await db_session.execute(select(IOCLookup).where(IOCLookup.ioc_value == ioc_value))
        ).scalar_one_or_none()
        assert lookup is not None, "lookup row was never created"
        assert lookup.status.value == "completed"
        assert lookup.final_verdict is not None
        assert lookup.final_verdict.value == "suspicious"

        record = (
            await db_session.execute(
                select(FinalAssessmentRecord).where(FinalAssessmentRecord.lookup_id == lookup.id)
            )
        ).scalar_one()
        assert record.ai_backend == "ollama"
        assert record.ai_outcome == "success"

        await _delete_lookup_and_dependents(db_session, lookup)
    finally:
        await db_session.delete(user)
        await db_session.commit()


@pytest.mark.asyncio
async def test_completed_lookup_has_readable_evidence_via_analysis_endpoint(
    fake_provider_and_ai, auth_headers, db_session
):
    """The whole point of fixing the persistence bug: analysis-layer routes
    that gate on status=="completed" (backend/app/api/routes/analysis.py)
    must actually become reachable once a real lookup finishes."""
    from app.main import app
    from app.models.lookup import IOCLookup

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/v1/lookup/stream",
            json={"value": "203.0.113.100"},
            headers=auth_headers,
            timeout=30.0,
        ) as response:
            async for _ in response.aiter_lines():
                pass

        lookup = (
            await db_session.execute(select(IOCLookup).where(IOCLookup.ioc_value == "203.0.113.100"))
        ).scalar_one_or_none()
        assert lookup is not None
        assert lookup.status.value == "completed"

        evidence_response = await client.get(
            f"/api/v1/lookup/{lookup.id}/analysis/evidence", headers=auth_headers
        )
        assert evidence_response.status_code == 200
        evidence = evidence_response.json()
        assert len(evidence) > 0
        assert any(e["source_label"] == "Fake Stream Test Provider" for e in evidence)

    await _delete_lookup_and_dependents(db_session, lookup)


@pytest_asyncio.fixture
async def slow_multi_provider_and_ai(monkeypatch):
    """Like fake_provider_and_ai, but yields two providers with a delay
    between them, so a test can disconnect after the first result is on the
    wire but before the second is even fetched."""
    from app.ai import service as ai_service
    from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus

    async def fake_run_all_providers(ioc_value, ioc_type, candidate_providers=None):
        yield ProviderResult(
            provider_id="fake_slow_provider_1",
            provider_name="Fake Slow Provider 1",
            category=ProviderCategory.THREAT_INTEL,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data={"verdict": "clean"},
        )
        await asyncio.sleep(2)
        yield ProviderResult(
            provider_id="fake_slow_provider_2",
            provider_name="Fake Slow Provider 2",
            category=ProviderCategory.THREAT_INTEL,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data={"verdict": "clean"},
        )

    monkeypatch.setattr("app.api.routes.lookup.run_all_providers", fake_run_all_providers)

    class _StubAIClient:
        is_configured = True

        async def call_claude_json(self, system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None):
            if tool_name == "emit_provider_summary":
                return {
                    "provider_id": "fake_slow_provider",
                    "what_it_knows": "Clean.",
                    "reputation": "clean",
                    "detection_status": "ok",
                    "threat_level": "low",
                    "confidence": "high",
                    "interesting_findings": [],
                }
            return {
                "executive_summary": "Test.",
                "technical_summary": "Test.",
                "threat_assessment": "Test.",
                "relationships_summary": "None.",
                "risk": {
                    "overall_risk_score": 0,
                    "confidence_score": 100,
                    "severity": "none",
                    "reputation": "clean",
                    "malicious_probability": 0,
                    "analyst_confidence": "high",
                },
                "final_verdict": "benign",
                "verdict_rationale": "Clean.",
            }

    async def _stub_get_ai_client(backend_override=None):
        return _StubAIClient(), "ollama", "stub-model"

    monkeypatch.setattr(ai_service, "_get_ai_client", _stub_get_ai_client)
    yield


@pytest.mark.asyncio
async def test_provider_result_is_committed_before_next_provider_runs(
    slow_multi_provider_and_ai, auth_headers, db_session
):
    """Regression test for a bug found via live E2E testing: disconnecting
    mid-investigation (page refresh, tab close, or a client-side timeout)
    correctly flipped the lookup to FAILED (the GeneratorExit-handling fix
    documented in event_stream()'s `finally` block), but every
    ProviderResultRecord/AISummaryRecord fetched before the disconnect was
    silently lost -- GET /lookup/{id} came back with provider_results: []
    even though real provider calls (confirmed live: 7 of them, including a
    real Spamhaus hit) had already completed and been streamed to the client
    over SSE. Root cause: the provider loop only called stream_db.commit()
    once, after the entire loop finished -- everything added via
    stream_db.add() inside the loop was still an uncommitted transaction
    when GeneratorExit tore the session down.

    httpx's ASGITransport runs the server-side generator to completion
    in-process rather than emulating a real dropped TCP connection, so a
    literal "disconnect mid-stream" repro isn't reliable here. This instead
    verifies the actual mechanism of the fix directly: while the server is
    still awaiting the deliberately-delayed second provider (the 2s
    asyncio.sleep in slow_multi_provider_and_ai), the first provider's
    result must already be visible to an independent DB connection --
    proving it was committed immediately rather than sitting in an
    uncommitted transaction until the whole loop finishes.
    """
    from app.main import app
    from app.models.lookup import IOCLookup
    from app.models.lookup import ProviderResultRecord

    async def run_stream():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with client.stream(
                "POST",
                "/api/v1/lookup/stream",
                json={"value": "203.0.113.102"},
                headers=auth_headers,
                timeout=30.0,
            ) as response:
                async for _ in response.aiter_lines():
                    pass

    stream_task = asyncio.create_task(run_stream())
    try:
        # The first provider result should commit almost immediately; the
        # second is deliberately delayed by 2s. Polling at 0.5s gives ample
        # margin on both sides without hardcoding a fragile exact timing.
        await asyncio.sleep(0.5)

        db_session.expire_all()
        lookup = (
            await db_session.execute(select(IOCLookup).where(IOCLookup.ioc_value == "203.0.113.102"))
        ).scalar_one_or_none()
        assert lookup is not None, "lookup row was never created"
        assert lookup.status.value == "running", (
            "expected the lookup to still be mid-flight (second provider not yet fetched) "
            "at this point in the test"
        )

        persisted = (
            await db_session.execute(
                select(ProviderResultRecord).where(ProviderResultRecord.lookup_id == lookup.id)
            )
        ).scalars().all()
        # This is the exact assertion that was failing before the fix: the
        # first provider's result must be durably committed well before the
        # whole loop (and its single end-of-loop commit) finishes.
        assert len(persisted) == 1, "first provider's result was not committed before the second provider ran"
        assert persisted[0].provider_id == "fake_slow_provider_1"
    finally:
        await stream_task

    # db_session uses expire_on_commit=False, so the `lookup` object fetched
    # above is cached in this session's identity map -- re-querying without
    # expiring first would just hand back that same stale Python object.
    db_session.expire_all()
    lookup = (
        await db_session.execute(select(IOCLookup).where(IOCLookup.ioc_value == "203.0.113.102"))
    ).scalar_one_or_none()
    assert lookup.status.value == "completed"
    await _delete_lookup_and_dependents(db_session, lookup)


_AI_CALL_DELAY_SECONDS = 1.5


@pytest_asyncio.fixture
async def concurrent_summary_providers_and_slow_ai(monkeypatch):
    """Three providers that all return OK essentially instantly (unlike
    slow_multi_provider_and_ai above, there is deliberately NO delay between
    provider results themselves -- the delay this fixture injects is entirely
    inside the AI summarization call), paired with an AI stub whose
    call_claude_json() sleeps _AI_CALL_DELAY_SECONDS before returning
    whenever it's asked for a per-provider summary (tool_name ==
    "emit_provider_summary") -- simulating real per-call AI latency (e.g. an
    Ollama backend queuing concurrent requests) without depending on any real
    AI backend being up.
    """
    from app.ai import service as ai_service
    from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus

    async def fake_run_all_providers(ioc_value, ioc_type, candidate_providers=None):
        for i in range(1, 4):
            yield ProviderResult(
                provider_id=f"fake_concurrent_provider_{i}",
                provider_name=f"Fake Concurrent Provider {i}",
                category=ProviderCategory.THREAT_INTEL,
                status=ProviderStatus.OK,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                data={"verdict": "clean"},
            )

    monkeypatch.setattr("app.api.routes.lookup.run_all_providers", fake_run_all_providers)

    class _SlowStubAIClient:
        is_configured = True

        async def call_claude_json(self, system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None):
            if tool_name == "emit_provider_summary":
                await asyncio.sleep(_AI_CALL_DELAY_SECONDS)
                return {
                    # Overwritten by summarize_provider() with the real
                    # result.provider_id before validation either way -- see
                    # app/ai/service.py -- so the exact value here is
                    # irrelevant, matching every other stub in this file.
                    "provider_id": "irrelevant-overwritten-by-caller",
                    "what_it_knows": "Clean.",
                    "reputation": "clean",
                    "detection_status": "ok",
                    "threat_level": "low",
                    "confidence": "high",
                    "interesting_findings": [],
                }
            return {
                "executive_summary": "Test.",
                "technical_summary": "Test.",
                "threat_assessment": "Test.",
                "relationships_summary": "None.",
                "risk": {
                    "overall_risk_score": 0,
                    "confidence_score": 100,
                    "severity": "none",
                    "reputation": "clean",
                    "malicious_probability": 0,
                    "analyst_confidence": "high",
                },
                "final_verdict": "benign",
                "verdict_rationale": "Clean.",
            }

    async def _stub_get_ai_client(backend_override=None):
        return _SlowStubAIClient(), "ollama", "stub-model"

    monkeypatch.setattr(ai_service, "_get_ai_client", _stub_get_ai_client)
    yield


@pytest.mark.asyncio
async def test_provider_summaries_are_generated_concurrently_not_serially(
    concurrent_summary_providers_and_slow_ai, auth_headers, db_session
):
    """Regression test for a real P2 latency bug found via live testing:
    summarize_provider() (an AI call) used to be `await`ed synchronously, one
    provider at a time, INSIDE the `async for result in run_all_providers(...)`
    loop in event_stream() (app/api/routes/lookup.py) -- so even though
    run_all_providers() already fans every provider's network fetch out
    concurrently, total investigation time scaled with
    (number of OK providers) x (AI-call latency) instead of being bounded by
    the slowest single call. Confirmed live: a lookup with several OK
    providers took minutes even though every individual provider fetch
    completed in ~1s, purely because each provider's AI summary had to finish
    before the next provider's summary could even start.

    This test uses 3 providers that all return OK essentially instantly, each
    paired with an AI stub whose call_claude_json() sleeps
    _AI_CALL_DELAY_SECONDS before returning a provider summary. Serial
    summarization (the bug) would take at least
    3 x _AI_CALL_DELAY_SECONDS just for the summarization phase; concurrent
    dispatch (the fix) completes the whole stream in well under
    2 x _AI_CALL_DELAY_SECONDS regardless of how many providers returned OK.
    """
    import time

    from app.main import app
    from app.models.lookup import IOCLookup

    transport = httpx.ASGITransport(app=app)
    started = time.monotonic()
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/v1/lookup/stream",
            json={"value": "203.0.113.109"},
            headers=auth_headers,
            timeout=30.0,
        ) as response:
            assert response.status_code == 200
            events = []
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    events.append(line.removeprefix("event: "))
    elapsed = time.monotonic() - started

    assert "done" in events
    assert "error" not in events
    assert events.count("provider_result") == 3
    assert events.count("provider_summary") == 3

    # This is the exact assertion that would fail before the fix: 3 serial
    # AI calls at _AI_CALL_DELAY_SECONDS each take >= 3 x that long just for
    # the summarization phase. A generous multiplier (2x one call's delay,
    # not 3x) keeps this robust against ordinary test-runner/event-loop
    # jitter while still failing hard against a serial regression.
    assert elapsed < _AI_CALL_DELAY_SECONDS * 2, (
        f"stream took {elapsed:.2f}s for 3 OK providers each with a "
        f"{_AI_CALL_DELAY_SECONDS}s AI summary call -- looks like provider "
        "summarization regressed to running serially instead of concurrently"
    )

    lookup = (
        await db_session.execute(select(IOCLookup).where(IOCLookup.ioc_value == "203.0.113.109"))
    ).scalar_one_or_none()
    assert lookup is not None, "lookup row was never created"
    assert lookup.status.value == "completed"

    await _delete_lookup_and_dependents(db_session, lookup)


@pytest_asyncio.fixture
async def oversized_source_url_provider_and_ai(monkeypatch):
    """A provider that builds source_url the same unsafe way several real
    providers do (interpolating ioc_value with no length cap) -- verifies the
    fix in app/providers/base.py's ProviderResult.__post_init__ rather than
    depending on any one specific provider's own URL format."""
    from app.ai import service as ai_service
    from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus

    async def fake_run_all_providers(ioc_value, ioc_type, candidate_providers=None):
        yield ProviderResult(
            provider_id="fake_oversized_url",
            provider_name="Fake Oversized URL Provider",
            category=ProviderCategory.THREAT_INTEL,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data={"verdict": "clean"},
            source_url=f"https://example.test/indicator/{ioc_value}",
        )

    monkeypatch.setattr("app.api.routes.lookup.run_all_providers", fake_run_all_providers)

    class _StubAIClient:
        is_configured = True

        async def call_claude_json(self, system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None):
            if tool_name == "emit_provider_summary":
                return {
                    "provider_id": "fake_oversized_url", "what_it_knows": "Clean.", "reputation": "clean",
                    "detection_status": "ok", "threat_level": "low", "confidence": "high", "interesting_findings": [],
                }
            return {
                "executive_summary": "Test.", "technical_summary": "Test.", "threat_assessment": "Test.",
                "relationships_summary": "None.",
                "risk": {"overall_risk_score": 0, "confidence_score": 100, "severity": "none",
                         "reputation": "clean", "malicious_probability": 0, "analyst_confidence": "high"},
                "final_verdict": "benign", "verdict_rationale": "Clean.",
            }

    async def _stub_get_ai_client(backend_override=None):
        return _StubAIClient(), "ollama", "stub-model"

    monkeypatch.setattr(ai_service, "_get_ai_client", _stub_get_ai_client)
    yield


@pytest.mark.asyncio
async def test_oversized_source_url_does_not_crash_and_lookup_completes(
    oversized_source_url_provider_and_ai, auth_headers, db_session
):
    """Regression test for a real bug found via enterprise QA red-teaming:
    provider_results.source_url / evidence_items.source_url are both
    VARCHAR(2048); several real providers (otx.py, virustotal.py,
    abuseipdb.py, malwarebazaar.py, nvd.py) build this URL by interpolating
    ioc_value with no length cap. An IOC value long enough to push the built
    URL past 2048 chars raised an uncaught StringDataRightTruncationError at
    insert time -- and a second bug in the except-block's error handling (see
    test_provider_pipeline_exception_marks_lookup_failed_not_stuck_running
    below) meant that failure was never persisted, leaving the lookup stuck
    at status=running forever. Fixed at the single choke point every provider
    and every persistence call site shares: ProviderResult.__post_init__ in
    app/providers/base.py now truncates source_url to fit the column.

    This ioc_value (~2035 chars) combined with this fake provider's URL
    prefix reproduces the exact overflow that broke otx.py's real URL
    construction, without depending on otx.py itself or a real network call.
    """
    from app.main import app
    from app.models.lookup import IOCLookup, ProviderResultRecord

    oversized_value = "http://example.com/" + "A" * 2020

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/v1/lookup/stream",
            json={"value": oversized_value},
            headers=auth_headers,
            timeout=30.0,
        ) as response:
            assert response.status_code == 200
            events = []
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    events.append(line.removeprefix("event: "))

    assert "done" in events
    assert "error" not in events

    lookup = (
        await db_session.execute(select(IOCLookup).where(IOCLookup.ioc_value == oversized_value))
    ).scalar_one_or_none()
    assert lookup is not None
    # This is the exact assertion that failed before the fix: the lookup must
    # not be left permanently stuck at "running".
    assert lookup.status.value == "completed"

    record = (
        await db_session.execute(
            select(ProviderResultRecord).where(ProviderResultRecord.lookup_id == lookup.id)
        )
    ).scalar_one()
    assert record.source_url is not None
    assert len(record.source_url) <= 2048

    await _delete_lookup_and_dependents(db_session, lookup)


@pytest_asyncio.fixture
async def exploding_pipeline_and_ai(monkeypatch):
    """Unlike ExplodingFakeProvider in test_lookup_flow.py (which raises
    inside a single provider's fetch() and is normalized to ProviderStatus.
    ERROR by BaseProvider.run() before it ever reaches the stream route), this
    raises directly out of the async generator the route itself iterates --
    exercising event_stream()'s own `except Exception` handler in
    app/api/routes/lookup.py."""
    async def fake_run_all_providers_that_explodes(ioc_value, ioc_type, candidate_providers=None):
        raise RuntimeError("simulated unrecoverable pipeline failure")
        yield  # pragma: no cover -- makes this an async generator function

    monkeypatch.setattr("app.api.routes.lookup.run_all_providers", fake_run_all_providers_that_explodes)
    yield


@pytest.mark.asyncio
async def test_provider_pipeline_exception_marks_lookup_failed_not_stuck_running(
    exploding_pipeline_and_ai, auth_headers, db_session
):
    """Regression test for a real bug found via enterprise QA red-teaming:
    event_stream()'s `except Exception` handler used to mutate
    stream_lookup_row.status = FAILED in memory and then call
    await stream_db.commit() on the SAME session the triggering exception
    came from -- if that exception originated in a failed flush/commit, the
    session requires an explicit rollback before it can run anything else, so
    this second commit raised an unhandled PendingRollbackError that escaped
    the except block entirely. That escape meant the in-memory status
    mutation was never actually persisted, while the `finally` block's own
    recovery check (`if stream_lookup_row.status == RUNNING`) saw the
    already-mutated-but-unpersisted FAILED value and concluded, wrongly, that
    recovery had already happened -- so nothing ever wrote FAILED to the DB,
    and the lookup stayed "running" forever.

    Fixed by having the except block use a brand-new, independent session for
    the FAILED write (matching the pattern already proven correct in the
    `finally` block below it), so it no longer matters whether the session
    that raised the original exception is still usable.

    This test doesn't need to reproduce a broken-session flush failure
    specifically -- any exception escaping the try block exercises the same
    fixed code path, since the except block now always uses a fresh session
    regardless of the original session's state.
    """
    from app.main import app
    from app.models.lookup import IOCLookup

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/v1/lookup/stream",
            json={"value": "203.0.113.103"},
            headers=auth_headers,
            timeout=30.0,
        ) as response:
            assert response.status_code == 200
            events = []
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    events.append(line.removeprefix("event: "))

    assert "error" in events
    assert "done" not in events

    lookup = (
        await db_session.execute(select(IOCLookup).where(IOCLookup.ioc_value == "203.0.113.103"))
    ).scalar_one_or_none()
    assert lookup is not None
    # This is the exact assertion that failed before the fix: the lookup was
    # left stuck at "running" instead of transitioning to "failed".
    assert lookup.status.value == "failed"

    await _delete_lookup_and_dependents(db_session, lookup)


@pytest.mark.asyncio
async def test_completed_lookup_returns_rebuilt_correlation_graph(
    fake_provider_and_ai, auth_headers, db_session
):
    """Regression test for a bug found via live E2E testing: GET /lookup/{id}
    omitted the `correlation` field entirely, so the relationship graph
    rendered fine during the live SSE stream (which emits a `correlation`
    event directly) but came back empty on every later revisit -- even though
    CorrelationEdgeRecord rows are persisted specifically so, per that model's
    own docstring, "a lookup's graph can be rebuilt from Postgres alone."

    This fake provider produces no relationship edges (it's a single flat
    ProviderResult with no related IOCs), so this asserts the zero-edge case
    specifically: the seed IOC must still appear as a node so "no
    relationships found" is distinguishable from "graph data unavailable."
    """
    from app.main import app
    from app.models.lookup import IOCLookup

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/api/v1/lookup/stream",
            json={"value": "203.0.113.101"},
            headers=auth_headers,
            timeout=30.0,
        ) as response:
            async for _ in response.aiter_lines():
                pass

        lookup = (
            await db_session.execute(select(IOCLookup).where(IOCLookup.ioc_value == "203.0.113.101"))
        ).scalar_one_or_none()
        assert lookup is not None
        assert lookup.status.value == "completed"

        detail_response = await client.get(f"/api/v1/lookup/{lookup.id}", headers=auth_headers)
        assert detail_response.status_code == 200
        detail = detail_response.json()

        assert "correlation" in detail
        correlation = detail["correlation"]
        assert correlation is not None
        assert correlation["edges"] == []
        assert correlation["nodes"] == [
            {"node_id": "ipv4:203.0.113.101", "ioc_type": "ipv4", "value": "203.0.113.101", "labels": []}
        ]

    await _delete_lookup_and_dependents(db_session, lookup)


@pytest.mark.asyncio
async def test_startup_recovers_lookups_orphaned_by_a_hard_kill(db_session):
    """Regression test for a real bug found via enterprise QA chaos testing:
    a hard process kill (`docker kill`, OOM-kill, power loss) gives the
    process zero chance to run any Python cleanup -- confirmed live that a
    lookup whose investigation was genuinely in flight during a SIGKILL
    stayed status=RUNNING forever, even after the backend container came
    back up cleanly. Neither event_stream()'s `except` block nor its
    `finally` block's GeneratorExit-based recovery can run in this scenario,
    since the process is gone before any of that code executes.

    Fixed by app/main.py's _recover_orphaned_running_lookups() startup hook:
    since a freshly-started process cannot yet be handling any request, any
    row already RUNNING at that point is necessarily orphaned from a
    previous process instance. This test seeds exactly that state directly
    (no real kill needed to prove the recovery logic) and calls the hook
    itself, the same way FastAPI's startup event does.
    """
    from app.core.db import new_session
    from app.main import _recover_orphaned_running_lookups
    from app.models.lookup import IOCLookup, LookupStatus

    lookup = IOCLookup(ioc_value="203.0.113.104", ioc_type="ipv4", status=LookupStatus.RUNNING)
    db_session.add(lookup)
    await db_session.commit()
    await db_session.refresh(lookup)
    lookup_id = lookup.id

    await _recover_orphaned_running_lookups()

    # A fresh session (rather than re-querying db_session, whose identity map
    # still holds the pre-recovery object) avoids an unrelated SQLAlchemy
    # async-greenlet quirk around refreshing an expired attribute on an
    # object modified by a DIFFERENT session.
    async with new_session() as verify_db:
        recovered = (
            await verify_db.execute(select(IOCLookup).where(IOCLookup.id == lookup_id))
        ).scalar_one()
        assert recovered.status.value == "failed"
        await verify_db.delete(recovered)
        await verify_db.commit()


@pytest.mark.asyncio
async def test_startup_recovers_orphaned_security_assessment_runs(db_session):
    """Regression test for a real bug found via the enterprise QA red-team
    round: SecurityAssessmentRun uses the exact same detached-background-
    task pattern as IOCLookup (app/core/security_assessment.py's
    _spawn_background), but the original _recover_orphaned_running_lookups()
    startup hook only swept ioc_lookups -- confirmed live that a hard kill
    mid-scan left a SecurityAssessmentRun permanently status=running, with
    no cron/cancel-endpoint/startup-hook anywhere able to ever recover it.

    Also covers PENDING: a crash in the narrow window between start_run()'s
    initial commit (status=PENDING) and _execute_run()'s first RUNNING write
    would otherwise leave a row stuck PENDING forever too.

    Seeds both states directly (no real kill needed) and calls the hook
    itself, the same way FastAPI's startup event does.
    """
    from datetime import datetime, timezone

    from app.core.db import new_session
    from app.main import _recover_orphaned_running_lookups
    from app.models.lookup import IOCLookup, LookupStatus
    from app.models.security_assessment import SecurityAssessmentRun, SecurityAssessmentRunStatus

    lookup = IOCLookup(ioc_value="203.0.113.105", ioc_type="ipv4", status=LookupStatus.COMPLETED)
    db_session.add(lookup)
    await db_session.commit()
    await db_session.refresh(lookup)
    lookup_id = lookup.id

    running_run = SecurityAssessmentRun(
        lookup_id=lookup_id, target="203.0.113.105", tool_ids=["nmap"], profile="quick",
        status=SecurityAssessmentRunStatus.RUNNING, authorization_confirmed_at=datetime.now(timezone.utc),
    )
    pending_run = SecurityAssessmentRun(
        lookup_id=lookup_id, target="203.0.113.105", tool_ids=["dns"], profile="quick",
        status=SecurityAssessmentRunStatus.PENDING, authorization_confirmed_at=datetime.now(timezone.utc),
    )
    db_session.add_all([running_run, pending_run])
    await db_session.commit()
    running_id, pending_id = running_run.id, pending_run.id

    await _recover_orphaned_running_lookups()

    async with new_session() as verify_db:
        recovered_running = (
            await verify_db.execute(select(SecurityAssessmentRun).where(SecurityAssessmentRun.id == running_id))
        ).scalar_one()
        recovered_pending = (
            await verify_db.execute(select(SecurityAssessmentRun).where(SecurityAssessmentRun.id == pending_id))
        ).scalar_one()
        assert recovered_running.status.value == "failed"
        assert recovered_pending.status.value == "failed"
        await verify_db.delete(recovered_running)
        await verify_db.delete(recovered_pending)
        await verify_db.commit()

    await _delete_lookup_and_dependents(db_session, lookup)


@pytest.mark.asyncio
async def test_startup_recovers_orphaned_pentest_rows(db_session, test_user):
    """Regression test for the same orphan-recovery gap as the two tests
    above, for the Pentest Suite: app/pentest/orchestrator.py's
    start_assessment/resume_assessment spawn a detached asyncio.Task tracked
    only in the in-process `_assessment_tasks` dict -- empty on every fresh
    process start, identical to the pattern already fixed for IOCLookup and
    SecurityAssessmentRun. A hard kill while an assessment is ACTIVE used to
    leave it (and any mid-phase target, and any in-flight exploit attempt)
    stuck forever: start_assessment only accepts DRAFT/PAUSED and
    resume_assessment only accepts PAUSED, so an orphaned ACTIVE row was a
    dead end with no automatic recovery anywhere.

    Also proves the sweep is properly SCOPED, not a blanket status sweep:
    - A target left PENDING under a PAUSED assessment is a perfectly normal
      resting state (pause_assessment/resume_assessment intentionally reset
      not-yet-completed targets to PENDING while awaiting a future resume)
      and must be left untouched.
    - A RUNNING exploit attempt is swept regardless of its parent
      assessment's status, since exploit.py's run_module() drives it
      synchronously per-request (never via `_assessment_tasks`) and is
      deliberately allowed even against a COMPLETED assessment.
    """
    from app.core.db import new_session
    from app.main import _recover_orphaned_running_lookups
    from app.models.pentest import (
        PentestAssessment,
        PentestAssessmentStatus,
        PentestExploitAttempt,
        PentestExploitMode,
        PentestExploitStatus,
        PentestFinding,
        PentestFindingConfidence,
        PentestFindingStatus,
        PentestProfile,
        PentestTarget,
        PentestTargetStatus,
    )

    active_assessment = PentestAssessment(
        name="orphan-recovery active", profile=PentestProfile.PASSIVE,
        scope_definition={"cidrs": ["203.0.113.0/24"]}, status=PentestAssessmentStatus.ACTIVE,
        created_by=test_user.id,
    )
    paused_assessment = PentestAssessment(
        name="orphan-recovery paused", profile=PentestProfile.PASSIVE,
        scope_definition={"cidrs": ["203.0.113.0/24"]}, status=PentestAssessmentStatus.PAUSED,
        created_by=test_user.id,
    )
    db_session.add_all([active_assessment, paused_assessment])
    await db_session.commit()
    await db_session.refresh(active_assessment)
    await db_session.refresh(paused_assessment)
    active_id, paused_id = active_assessment.id, paused_assessment.id

    stuck_target = PentestTarget(
        assessment_id=active_id, target_type="ipv4", value="203.0.113.106",
        status=PentestTargetStatus.ENUMERATING,
    )
    pending_target_under_active = PentestTarget(
        assessment_id=active_id, target_type="ipv4", value="203.0.113.107",
        status=PentestTargetStatus.PENDING,
    )
    legitimately_pending_target = PentestTarget(
        assessment_id=paused_id, target_type="ipv4", value="203.0.113.108",
        status=PentestTargetStatus.PENDING,
    )
    db_session.add_all([stuck_target, pending_target_under_active, legitimately_pending_target])
    await db_session.commit()
    await db_session.refresh(stuck_target)
    await db_session.refresh(pending_target_under_active)
    await db_session.refresh(legitimately_pending_target)

    finding = PentestFinding(
        assessment_id=active_id, target_id=stuck_target.id, tool_id="nmap", finding_type="open_port",
        severity="high", confidence=PentestFindingConfidence.LIKELY, title="test finding",
        status=PentestFindingStatus.OPEN,
    )
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)

    stuck_exploit_attempt = PentestExploitAttempt(
        assessment_id=active_id, finding_id=finding.id, target_id=stuck_target.id,
        module_fullname="auxiliary/scanner/smb/smb_ms17_010", mode=PentestExploitMode.CHECK,
        status=PentestExploitStatus.RUNNING, requested_by=test_user.id,
    )
    db_session.add(stuck_exploit_attempt)
    await db_session.commit()
    await db_session.refresh(stuck_exploit_attempt)
    exploit_attempt_id = stuck_exploit_attempt.id

    await _recover_orphaned_running_lookups()

    # Fresh session -- same identity-map caveat as the tests above.
    async with new_session() as verify_db:
        recovered_active_assessment = await verify_db.get(PentestAssessment, active_id)
        recovered_paused_assessment = await verify_db.get(PentestAssessment, paused_id)
        recovered_stuck_target = await verify_db.get(PentestTarget, stuck_target.id)
        recovered_pending_under_active = await verify_db.get(PentestTarget, pending_target_under_active.id)
        recovered_legit_pending = await verify_db.get(PentestTarget, legitimately_pending_target.id)
        recovered_exploit_attempt = await verify_db.get(PentestExploitAttempt, exploit_attempt_id)

        assert recovered_active_assessment.status == PentestAssessmentStatus.CANCELLED
        assert recovered_stuck_target.status == PentestTargetStatus.FAILED
        assert recovered_pending_under_active.status == PentestTargetStatus.FAILED
        assert recovered_exploit_attempt.status == PentestExploitStatus.ERROR

        # Untouched: a PAUSED assessment and its normally-PENDING target are
        # not orphaned and must survive the sweep unchanged.
        assert recovered_paused_assessment.status == PentestAssessmentStatus.PAUSED
        assert recovered_legit_pending.status == PentestTargetStatus.PENDING

        # Explicit child-then-parent deletes rather than relying on the ORM
        # relationship cascade, matching this file's own established
        # pattern (see _delete_lookup_and_dependents above).
        from sqlalchemy import delete

        both_ids = [active_id, paused_id]
        await verify_db.execute(delete(PentestExploitAttempt).where(PentestExploitAttempt.assessment_id.in_(both_ids)))
        await verify_db.execute(delete(PentestFinding).where(PentestFinding.assessment_id.in_(both_ids)))
        await verify_db.execute(delete(PentestTarget).where(PentestTarget.assessment_id.in_(both_ids)))
        await verify_db.execute(delete(PentestAssessment).where(PentestAssessment.id.in_(both_ids)))
        await verify_db.commit()
