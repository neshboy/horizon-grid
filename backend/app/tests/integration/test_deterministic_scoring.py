"""Integration test for the deterministic threat-scoring engine's end-to-end
wiring: a full investigation's persisted `IOCLookup.risk_score` (and the
`final_assessment["risk"]` block) must equal what
app/scoring/engine.py::score_investigation() actually computes from the
provider evidence -- NOT whatever number the AI backend happened to invent,
even when the (stubbed) AI backend deliberately ignores the "these numbers
are given" instruction and emits a self-contradictory pair of its own.

Exercises the real route (via ASGI transport, real Postgres/Redis over the
host-published docker-compose ports) with a fake provider and a stubbed AI
client, following the exact pattern already established by
test_lookup_stream_persistence.py and test_lookup_export_permissions.py --
see either for the full rationale behind the host-infra override fixtures
duplicated below (there is no shared conftest.py in this repo; see
docs/TESTING.md).

Uses a per-run unique test-user email (matching test_security_assessment_api.
py's `_unique_email` pattern) rather than a fixed hardcoded one -- a fixed
email left over from an interrupted prior run of a DIFFERENT test file
(test_lookup_stream_persistence.py's "stream-persistence-test@example.test")
was confirmed, while writing this test, to leave that other file's fixtures
permanently failing with a UniqueViolationError until manually cleaned up.
A unique email per run makes this file immune to that whole class of
cross-run pollution.
"""
import os
import socket
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.correlation.engine import CorrelationResult, GraphNode
from app.core.config import get_settings
from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus
from app.scoring.engine import score_investigation

# A provider result with a single, uncorroborated "malicious" verdict and no
# engine-count granularity -- deliberately simple, so the expected score is
# trivially reproducible by calling score_investigation() directly with an
# equivalent ProviderResult, without needing to reimplement any of the
# engine's own weighting math in this test.
_FAKE_VERDICT_DATA = {"verdict": "malicious", "detection_ratio": "1/1"}

# The stubbed AI deliberately invents numbers that do NOT match what the
# deterministic engine will compute for _FAKE_VERDICT_DATA above (see the
# assertion at the bottom of the test) -- if the wiring in
# app/ai/service.py::generate_final_assessment() ever regressed to trusting
# the AI's own numbers instead of overwriting them, this specific mismatch
# is what would catch it. final_verdict="suspicious" is deliberately used
# because it is in neither `_MALICIOUS_VERDICTS` nor `_BENIGN_VERDICTS` (see
# app/ai/schemas.py), so FinalAssessment's own _verdict_must_agree_with_risk
# validator imposes no constraint on it regardless of which
# malicious_probability ends up attached -- this test is about the NUMBERS
# being overwritten correctly, not about exercising that separate validator/
# retry mechanism (see app/tests/unit/test_ai_service.py for dedicated
# coverage of that).
_AI_INVENTED_RISK = {
    "overall_risk_score": 99,
    "confidence_score": 99,
    "severity": "critical",
    "reputation": "malicious",
    "malicious_probability": 99,
    "analyst_confidence": "high",
}


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _resolve_infra_host_port(in_network_host, in_network_port, published_host, published_port):
    """See test_lookup_stream_persistence.py's function of the same name for
    the full rationale: prefer the real in-docker-network hostname
    (`postgres`/`redis`), reachable when this test runs INSIDE the backend
    container (the documented dev/CI way to run it); fall back to the
    docker-compose HOST-published port for an out-of-container host run.
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
    """See test_lookup_stream_persistence.py's fixture of the same name for
    the full rationale."""
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
    """See test_lookup_stream_persistence.py's fixture of the same name."""
    yield
    import app.core.cache as cache_module
    from app.core.db import _engine

    await _engine.dispose()
    if cache_module._pool is not None:
        await cache_module._pool.aclose()
        cache_module._pool = None


@pytest_asyncio.fixture
async def db_session():
    from app.core.db import new_session

    async with new_session() as session:
        yield session


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.test"


@pytest_asyncio.fixture
async def test_user(db_session):
    from app.auth.security import hash_password
    from app.models.user import Role, User

    user = User(
        email=_unique_email("deterministic-scoring-test"),
        hashed_password=hash_password("irrelevant"),
        full_name="Deterministic Scoring Test",
        role=Role.ANALYST,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest.fixture
def auth_headers(test_user):
    from app.auth.security import create_access_token

    token = create_access_token(test_user.email, test_user.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def fake_provider_and_noncompliant_ai(monkeypatch):
    """Fake provider (no network) with a known, simple verdict, plus a
    stubbed AI client that deliberately emits risk numbers that do NOT match
    what the deterministic engine will compute from that provider's data --
    see module docstring for why."""
    from app.ai import service as ai_service
    from app.ioc.types import IOCType

    async def fake_run_all_providers(ioc_value, ioc_type, candidate_providers=None):
        yield ProviderResult(
            provider_id="fake_deterministic_scoring_test",
            provider_name="Fake Deterministic Scoring Test Provider",
            category=ProviderCategory.THREAT_INTEL,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=dict(_FAKE_VERDICT_DATA),
        )

    monkeypatch.setattr("app.api.routes.lookup.run_all_providers", fake_run_all_providers)

    class _NoncompliantAIClient:
        is_configured = True

        async def call_claude_json(self, system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None):
            if tool_name == "emit_provider_summary":
                return {
                    "provider_id": "fake_deterministic_scoring_test",
                    "what_it_knows": "Flagged as malicious.",
                    "reputation": "malicious",
                    "detection_status": "1/1",
                    "threat_level": "high",
                    "confidence": "high",
                    "interesting_findings": ["Flagged by the fake provider"],
                }
            return {
                "executive_summary": "Test executive summary.",
                "technical_summary": "Test technical summary.",
                "threat_assessment": "Test threat assessment.",
                "relationships_summary": "No relationships discovered.",
                "risk": dict(_AI_INVENTED_RISK),
                "final_verdict": "suspicious",
                "verdict_rationale": "Deliberately invented, ignoring the given deterministic numbers.",
            }

    async def _stub_get_ai_client(backend_override=None):
        return _NoncompliantAIClient(), "ollama", "stub-model"

    monkeypatch.setattr(ai_service, "_get_ai_client", _stub_get_ai_client)
    yield IOCType


async def _delete_lookup_and_dependents(db_session, lookup) -> None:
    from sqlalchemy import delete

    from app.models.lookup import FinalAssessmentRecord

    await db_session.execute(delete(FinalAssessmentRecord).where(FinalAssessmentRecord.lookup_id == lookup.id))
    await db_session.commit()
    await db_session.delete(lookup)
    await db_session.commit()


@pytest.mark.asyncio
async def test_persisted_risk_score_matches_deterministic_engine_not_the_ai(
    fake_provider_and_noncompliant_ai, auth_headers, db_session
):
    from app.main import app
    from app.models.lookup import IOCLookup

    # A random-suffixed domain, not a fixed RFC-5737 TEST-NET address like
    # "203.0.113.x" -- confirmed live, while writing this test, that several
    # such fixed addresses already had leftover IOCLookup rows from earlier
    # (unrelated) test runs against this same shared Postgres instance,
    # which broke `scalar_one_or_none()` below with MultipleResultsFound.
    # A fresh random value every run makes this collision structurally
    # impossible rather than just unlikely.
    ioc_value = f"deterministic-scoring-{uuid.uuid4().hex[:12]}.example.test"
    ioc_type = fake_provider_and_noncompliant_ai  # IOCType, yielded by the fixture

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST", "/api/v1/lookup/stream", json={"value": ioc_value}, headers=auth_headers, timeout=30.0
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
    assert lookup is not None
    assert lookup.status.value == "completed"

    # Independently compute what the deterministic engine SHOULD have produced from the exact
    # same evidence the fake provider supplied -- this is the ground truth this test checks the
    # persisted row against, not a hardcoded magic number.
    seed_type = ioc_type.DOMAIN
    fake_result = ProviderResult(
        provider_id="fake_deterministic_scoring_test",
        provider_name="Fake Deterministic Scoring Test Provider",
        category=ProviderCategory.THREAT_INTEL,
        status=ProviderStatus.OK,
        ioc_value=ioc_value,
        ioc_type=seed_type,
        data=dict(_FAKE_VERDICT_DATA),
    )
    expected = score_investigation(
        [fake_result],
        CorrelationResult(
            nodes=[GraphNode(node_id=f"domain:{ioc_value}", ioc_type="domain", value=ioc_value)],
            edges=[],
            deduplicated_facts={},
            provider_agreement={},
        ),
    )

    # The actual point of this test: the persisted score is the REAL deterministic value, not the
    # AI's invented 99/99/99/critical.
    assert lookup.risk_score == expected.overall_risk_score
    assert lookup.confidence_score == expected.confidence_score
    assert lookup.risk_score != _AI_INVENTED_RISK["overall_risk_score"]

    assert lookup.final_assessment["risk"]["overall_risk_score"] == expected.overall_risk_score
    assert lookup.final_assessment["risk"]["confidence_score"] == expected.confidence_score
    assert lookup.final_assessment["risk"]["malicious_probability"] == expected.malicious_probability
    assert lookup.final_assessment["risk"]["severity"] == expected.severity
    assert lookup.final_assessment["risk"]["malicious_probability"] != _AI_INVENTED_RISK["malicious_probability"]

    # The AI's own verdict choice ("suspicious") is still respected -- overwriting the risk
    # NUMBERS does not mean overwriting the AI's prose/verdict too; only the numbers this engine
    # is now responsible for are forced.
    assert lookup.final_verdict.value == "suspicious"

    await _delete_lookup_and_dependents(db_session, lookup)
