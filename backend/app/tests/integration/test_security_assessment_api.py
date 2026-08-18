"""Integration tests for the Security Assessment Toolkit: RBAC enforcement
via real HTTP, and full run persistence against the real database with a
fake tool substituted in (never invoking a real nmap/network call) and the
AI pipeline stubbed (never calling a real LLM backend). See
app/tests/integration/test_admin_rbac_api.py for the fixture pattern this
file reuses.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.security_assessment as sa_service
from app.ai.schemas import FinalAssessment, ProviderSummary, RiskAssessment
from app.auth.security import create_access_token
from app.core.config import get_settings
from app.core.users import create_user
from app.ioc.types import IOCType
from app.main import app
from app.models.lookup import IOCLookup, LookupStatus
from app.models.security_assessment import SecurityAssessmentRun, SecurityAssessmentRunStatus
from app.models.user import Role
from app.providers.base import ProviderStatus
from app.security_assessment.base import Finding, SecurityAssessmentTool, ToolRunResult

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


async def _make_user(role: Role, prefix: str):
    email = _unique_email(prefix)
    created = await create_user(email, "pw-1", prefix, role, None, "actor@qa.test")
    token = create_access_token(email, role.value)
    return uuid.UUID(created["id"]), email, token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_lookup(ioc_value: str, ioc_type: str) -> uuid.UUID:
    from app.core.db import new_session

    async with new_session() as db:
        lookup = IOCLookup(ioc_value=ioc_value, ioc_type=ioc_type, status=LookupStatus.COMPLETED)
        db.add(lookup)
        await db.commit()
        await db.refresh(lookup)
        return lookup.id


async def _cleanup_lookup(lookup_id: uuid.UUID) -> None:
    """FinalAssessmentRecord deliberately has no cascade from IOCLookup (see
    app/models/lookup.py -- every assessment ever generated is kept even if
    something else about the lookup changes), so it's never auto-deleted
    with the lookup; clear it explicitly first."""
    from sqlalchemy import delete

    from app.core.db import new_session
    from app.models.lookup import FinalAssessmentRecord

    async with new_session() as db:
        await db.execute(delete(FinalAssessmentRecord).where(FinalAssessmentRecord.lookup_id == lookup_id))
        await db.commit()
    async with new_session() as db:
        lookup = await db.get(IOCLookup, lookup_id)
        if lookup is not None:
            await db.delete(lookup)
            await db.commit()


async def _delete_user(user_id: uuid.UUID) -> None:
    """A user who acted as an audit actor (every security_assessment.* run
    action records the requesting analyst as actor_user_id) can't be
    hard-deleted while config_audit_log still references them -- clear this
    disposable test run's own audit rows first, matching the established
    pattern in test_admin_users.py."""
    from sqlalchemy import delete, select

    from app.core.db import new_session
    from app.models.runtime_config import ConfigAuditLog
    from app.models.user import User

    async with new_session() as db:
        await db.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor_user_id == user_id))
        await db.commit()
    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


def _fallback_final_assessment(ioc_value: str, ioc_type: str) -> FinalAssessment:
    from app.models.lookup import Verdict

    return FinalAssessment(
        ioc_value=ioc_value,
        ioc_type=ioc_type,
        executive_summary="test",
        technical_summary="test",
        threat_assessment="test",
        relationships_summary="test",
        risk=RiskAssessment(
            overall_risk_score=10, confidence_score=50, severity="low",
            reputation="unknown", malicious_probability=10, analyst_confidence="low",
        ),
        final_verdict=Verdict.UNKNOWN,
        verdict_rationale="test",
        ai_backend="test-stub",
        ai_model="test-stub-model",
    )


class _FakeTool(SecurityAssessmentTool):
    tool_id = "fake_tool"
    tool_name = "Fake Test Tool"
    supported_types = {IOCType.IPV4}

    async def run(self, target, ioc_type, profile_id):
        return ToolRunResult(
            provider_result=self._result(target, ioc_type, ProviderStatus.OK, data={"fake": True}),
            findings=[
                Finding(
                    tool_id=self.tool_id, finding_type="fake_finding", severity="high",
                    title="Fake high-severity finding", description="A fake finding for testing.",
                )
            ],
        )


@pytest_asyncio.fixture
async def _stub_ai_and_background(monkeypatch):
    async def _fake_summarize(ioc_value, ioc_type, result, backend_override=None):
        return ProviderSummary(
            provider_id=result.provider_id, what_it_knows="test", reputation="unknown",
            detection_status="test", threat_level="none", confidence="low",
        )

    async def _fake_generate(ioc_value, ioc_type, summaries, correlation, backend_override=None, unavailable_providers=None):
        return _fallback_final_assessment(ioc_value, ioc_type)

    monkeypatch.setattr(sa_service, "summarize_provider", _fake_summarize)
    monkeypatch.setattr(sa_service, "generate_final_assessment", _fake_generate)
    monkeypatch.setattr(sa_service, "get_tool", lambda tool_id: _FakeTool() if tool_id == "fake_tool" else None)
    yield


# --- RBAC ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_can_read_profiles_and_tool_health_but_not_run(client):
    viewer_id, _, viewer_token = await _make_user(Role.VIEWER, "qa-sec-viewer")
    lookup_id = await _make_lookup("127.0.0.1", "ipv4")
    try:
        profiles = await client.get(f"{API}/security-assessment/profiles", headers=_auth(viewer_token))
        assert profiles.status_code == 200

        health = await client.get(f"{API}/security-assessment/tool-health", headers=_auth(viewer_token))
        assert health.status_code == 200

        run = await client.post(
            f"{API}/security-assessment/{lookup_id}/run",
            json={"tool_ids": ["nmap"], "profile": "quick", "target_confirmation": "127.0.0.1", "authorization_confirmed": True},
            headers=_auth(viewer_token),
        )
        assert run.status_code == 403
    finally:
        await _cleanup_lookup(lookup_id)
        await _delete_user(viewer_id)


@pytest.mark.asyncio
async def test_analyst_can_run_an_assessment(client):
    """Target is 127.0.0.1 deliberately -- this test does NOT stub the tool,
    so if nmap is installed this spawns a REAL (but local, fast, always-
    authorized) scan in the background. Awaits svc.wait_for_background_runs()
    before returning, so the background task (including its post-completion
    AI-refresh step) never outlives this test's own DB-engine teardown
    (_fresh_engine_per_test) and corrupts whichever test runs next."""
    analyst_id, _, analyst_token = await _make_user(Role.ANALYST, "qa-sec-analyst")
    lookup_id = await _make_lookup("127.0.0.1", "ipv4")
    try:
        run = await client.post(
            f"{API}/security-assessment/{lookup_id}/run",
            json={"tool_ids": ["nmap"], "profile": "quick", "target_confirmation": "127.0.0.1", "authorization_confirmed": True},
            headers=_auth(analyst_token),
        )
        assert run.status_code == 200
        assert run.json()["status"] == "pending"

        await sa_service.wait_for_background_runs()
    finally:
        await _cleanup_lookup(lookup_id)
        await _delete_user(analyst_id)


# --- Scope/authorization gate rejects BEFORE any run is created -----------


@pytest.mark.asyncio
async def test_run_rejects_target_mismatch_and_creates_no_run_row(client):
    analyst_id, _, analyst_token = await _make_user(Role.ANALYST, "qa-sec-mismatch")
    lookup_id = await _make_lookup("127.0.0.1", "ipv4")
    try:
        response = await client.post(
            f"{API}/security-assessment/{lookup_id}/run",
            json={"tool_ids": ["nmap"], "profile": "quick", "target_confirmation": "10.10.10.10", "authorization_confirmed": True},
            headers=_auth(analyst_token),
        )
        assert response.status_code == 400

        from sqlalchemy import select

        from app.core.db import new_session

        async with new_session() as db:
            runs = (await db.execute(select(SecurityAssessmentRun).where(SecurityAssessmentRun.lookup_id == lookup_id))).scalars().all()
            assert runs == [], "a rejected request must never create a run row"
    finally:
        await _cleanup_lookup(lookup_id)
        await _delete_user(analyst_id)


@pytest.mark.asyncio
async def test_run_rejects_unconfirmed_authorization(client):
    analyst_id, _, analyst_token = await _make_user(Role.ANALYST, "qa-sec-unconfirmed")
    lookup_id = await _make_lookup("127.0.0.1", "ipv4")
    try:
        response = await client.post(
            f"{API}/security-assessment/{lookup_id}/run",
            json={"tool_ids": ["nmap"], "profile": "quick", "target_confirmation": "127.0.0.1", "authorization_confirmed": False},
            headers=_auth(analyst_token),
        )
        assert response.status_code == 400
    finally:
        await _cleanup_lookup(lookup_id)
        await _delete_user(analyst_id)


# --- Full run persistence (fake tool, stubbed AI) --------------------------


@pytest.mark.asyncio
async def test_completed_run_persists_findings_and_updates_the_lookup(client, _stub_ai_and_background):
    analyst_id, _, analyst_token = await _make_user(Role.ANALYST, "qa-sec-fullrun")
    lookup_id = await _make_lookup("127.0.0.1", "ipv4")
    try:
        result = await sa_service.start_run(
            lookup_id, ["fake_tool"], "quick", "127.0.0.1", True, analyst_id, "analyst@qa.test"
        )
        run_id = uuid.UUID(result["run_id"])

        await sa_service.wait_for_background_runs()

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.core.db import new_session

        async with new_session() as db:
            run = (
                await db.execute(
                    select(SecurityAssessmentRun)
                    .where(SecurityAssessmentRun.id == run_id)
                    .options(selectinload(SecurityAssessmentRun.findings))
                )
            ).scalar_one()
            assert run.status == SecurityAssessmentRunStatus.COMPLETED
            assert len(run.findings) == 1
            assert run.findings[0].severity.value == "high"
            assert run.findings[0].tool_id == "fake_tool"

            lookup = await db.get(IOCLookup, lookup_id)
            assert lookup.final_verdict is not None
            assert lookup.final_assessment is not None
    finally:
        await _cleanup_lookup(lookup_id)
        await _delete_user(analyst_id)
