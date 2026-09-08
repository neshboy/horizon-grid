"""Regression test for a confirmed P2 finding: POST /api/v1/lookup/stream and
POST /api/v1/basket both trusted a caller-supplied `ioc_type_hint` with zero
validation that the (stripped) value actually conforms to that type.

Root cause: both routes computed
    ioc_value = <raw value>.strip()
    ioc_type = payload.ioc_type_hint or detect_ioc_type(ioc_value)
    if ioc_type == IOCType.UNKNOWN: raise 422
Pydantic's Field(min_length=1) on the raw payload only guards the value
BEFORE .strip() runs, so a whitespace-only string ("   ") passed that check
and became "" here. detect_ioc_type("") does return IOCType.UNKNOWN, but
that path is only reached when ioc_type_hint is absent -- supplying ANY hint
(e.g. "domain") bypassed the UNKNOWN-rejection safety net entirely, letting
an empty-string IOC (or a garbage value/type pairing like
value="totally-not-an-ip", ioc_type_hint="ipv4") get persisted and run
through the full provider fan-out / correlation / scoring / AI pipeline.

Fixed by rejecting an empty-after-strip value unconditionally, and by
validating any caller-supplied hint against the value's actual shape via
app.ioc.detector.value_matches_ioc_type() before trusting it.

Runs against the real app (ASGI transport) and the real Postgres/Redis this
docker-compose stack's backend container already talks to -- deliberately
does NOT override DATABASE_URL/REDIS_URL to host-published ports (unlike
test_lookup_stream_persistence.py/test_lookup_export_permissions.py, which
are written to run from the host): this file is intended to run the same
way the repo's own test-running instructions do, via
`docker compose exec -T backend python -m pytest`, where the in-network
`postgres`/`redis` hostnames already resolve correctly.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _dispose_pools_after_each_test():
    """app.core.db's engine/pool (and app.core.cache's Redis pool, touched
    indirectly via the rate limiter) are bound to whichever asyncio event
    loop was running when their connections were first opened;
    pytest-asyncio gives each test function its own event loop, so reusing
    pooled connections across tests raises "Event loop is closed"/"attached
    to a different loop" during the next test's connection teardown -- same
    root cause documented on test_lookup_stream_persistence.py's fixture of
    the same name.
    """
    yield
    import app.core.cache as cache_module
    from app.core.db import _engine

    await _engine.dispose()
    if cache_module._pool is not None:
        await cache_module._pool.aclose()
        cache_module._pool = None


async def _delete_lookup_and_dependents(lookup_id) -> None:
    """FinalAssessmentRecord has no cascade from IOCLookup (every assessment
    ever generated is kept even if something else about the lookup changes
    -- see app/models/lookup.py), so it must be cleared explicitly before the
    lookup itself can be deleted, matching the pattern already established in
    test_lookup_stream_persistence.py's own _delete_lookup_and_dependents."""
    from sqlalchemy import delete

    from app.core.db import new_session
    from app.models.lookup import FinalAssessmentRecord, IOCLookup

    async with new_session() as db:
        await db.execute(delete(FinalAssessmentRecord).where(FinalAssessmentRecord.lookup_id == lookup_id))
        await db.commit()
        lookup = await db.get(IOCLookup, lookup_id)
        if lookup is not None:
            await db.delete(lookup)
            await db.commit()


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@qa.test"


async def _make_analyst():
    from app.auth.security import create_access_token
    from app.core.users import create_user
    from app.models.user import Role

    email = _unique_email("qa-ioc-hint")
    created = await create_user(email, "pw-1", "IOC Hint Validation Test User", Role.ANALYST, None, "actor@qa.test")
    token = create_access_token(email, Role.ANALYST.value)
    return uuid.UUID(created["id"]), token


async def _delete_user(user_id: uuid.UUID) -> None:
    from app.core.db import new_session
    from app.models.user import User

    async with new_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_whitespace_only_value_with_domain_hint_is_rejected_not_persisted():
    """The exact live repro: {"value": "   ", "ioc_type_hint": "domain"} used
    to stream a `detected` event with ioc_value="" and create a real
    ioc_lookups row with ioc_value=''. Must now 422 before any row is
    created."""
    from app.main import app
    from app.models.lookup import IOCLookup

    user_id, token = await _make_analyst()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/lookup/stream",
                json={"value": "   ", "ioc_type_hint": "domain"},
                headers=_auth(token),
            )
        assert response.status_code == 422, (
            f"expected a 422 rejection for a whitespace-only value + ioc_type_hint, got "
            f"{response.status_code}: {response.text}"
        )

        from app.core.db import new_session

        async with new_session() as db:
            # Scoped to requested_by == this test's own freshly-created user
            # (not just ioc_value == "") -- this DB is a shared docker-compose
            # instance other agents/manual repro attempts may also be hitting
            # concurrently, including this exact finding's own repro payload,
            # so asserting a global "zero such rows exist" would be flaky.
            rows = (
                await db.execute(
                    select(IOCLookup).where(IOCLookup.ioc_value == "", IOCLookup.requested_by == user_id)
                )
            ).scalars().all()
        assert rows == [], "no ioc_lookups row with ioc_value='' must ever be created for this request"
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_mismatched_value_and_type_hint_is_rejected():
    """value='totally-not-an-ip' paired with ioc_type_hint='ipv4' used to be
    accepted outright, persisted as ioc_type='ipv4', and fanned out to every
    IP-only provider. Must now 422."""
    from app.main import app
    from app.models.lookup import IOCLookup

    user_id, token = await _make_analyst()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/lookup/stream",
                json={"value": "totally-not-an-ip", "ioc_type_hint": "ipv4"},
                headers=_auth(token),
            )
        assert response.status_code == 422, (
            f"expected a 422 rejection for a value that doesn't match its claimed ioc_type_hint, got "
            f"{response.status_code}: {response.text}"
        )

        from app.core.db import new_session

        async with new_session() as db:
            # Scoped to this test's own user for the same reason as the
            # whitespace-value test above.
            rows = (
                await db.execute(
                    select(IOCLookup).where(
                        IOCLookup.ioc_value == "totally-not-an-ip", IOCLookup.requested_by == user_id
                    )
                )
            ).scalars().all()
        assert rows == [], "no ioc_lookups row for the mismatched value/type pairing must ever be created"
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_valid_value_with_matching_hint_is_still_accepted(monkeypatch):
    """Positive control: the fix must not reject a legitimate, matching
    value/hint pairing. Mocks out the provider fan-out and AI backend the
    same way test_lookup_stream_persistence.py's fake_provider_and_ai does --
    NOT to avoid the real pipeline being slow, but because httpx's
    ASGITransport runs the server-side generator to completion in-process
    regardless of whether the client keeps reading (documented on
    test_lookup_stream_persistence.py's exploding_pipeline_and_ai fixture),
    so an unmocked real pipeline here would dispatch every configured
    provider and a real AI call for however long that takes, for no benefit
    to what this test actually checks: that a valid request reaches
    `done`, not `error`, once ioc_value/ioc_type_hint pass validation.
    """
    from app.ai import service as ai_service
    from app.main import app
    from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus

    async def fake_run_all_providers(ioc_value, ioc_type, candidate_providers=None):
        yield ProviderResult(
            provider_id="fake_hint_validation_provider",
            provider_name="Fake Hint Validation Provider",
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
                    "provider_id": "fake_hint_validation_provider",
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

    user_id, token = await _make_analyst()
    ioc_value = f"203.0.113.{(uuid.uuid4().int % 200) + 1}"
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with client.stream(
                "POST",
                "/api/v1/lookup/stream",
                json={"value": ioc_value, "ioc_type_hint": "ipv4"},
                headers=_auth(token),
                timeout=30.0,
            ) as response:
                assert response.status_code == 200
                events = []
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        events.append(line.removeprefix("event: "))
        assert "detected" in events
        assert "done" in events
        assert "error" not in events
    finally:
        from app.core.db import new_session
        from app.models.lookup import IOCLookup

        async with new_session() as db:
            lookup = (
                await db.execute(select(IOCLookup).where(IOCLookup.ioc_value == ioc_value))
            ).scalar_one_or_none()
            lookup_id = lookup.id if lookup is not None else None
        if lookup_id is not None:
            await _delete_lookup_and_dependents(lookup_id)
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_basket_whitespace_only_value_with_hint_is_rejected_not_persisted():
    """Identical bug, identical fix, in POST /api/v1/basket's add_to_basket()."""
    from app.main import app
    from app.models.basket import BasketItem

    user_id, token = await _make_analyst()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/basket",
                json={"ioc_value": "   ", "ioc_type_hint": "domain"},
                headers=_auth(token),
            )
        assert response.status_code == 422, (
            f"expected a 422 rejection for a whitespace-only basket value + ioc_type_hint, got "
            f"{response.status_code}: {response.text}"
        )

        from app.core.db import new_session

        async with new_session() as db:
            rows = (
                await db.execute(select(BasketItem).where(BasketItem.owner_id == user_id))
            ).scalars().all()
        assert rows == [], "no basket_items row must ever be created for an empty/whitespace value"
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_basket_mismatched_value_and_type_hint_is_rejected():
    from app.main import app
    from app.models.basket import BasketItem

    user_id, token = await _make_analyst()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/basket",
                json={"ioc_value": "totally-not-an-ip", "ioc_type_hint": "ipv4"},
                headers=_auth(token),
            )
        assert response.status_code == 422, (
            f"expected a 422 rejection for a mismatched basket value/ioc_type_hint pairing, got "
            f"{response.status_code}: {response.text}"
        )

        from app.core.db import new_session

        async with new_session() as db:
            rows = (
                await db.execute(select(BasketItem).where(BasketItem.owner_id == user_id))
            ).scalars().all()
        assert rows == [], "no basket_items row must ever be created for the mismatched value/type pairing"
    finally:
        await _delete_user(user_id)
