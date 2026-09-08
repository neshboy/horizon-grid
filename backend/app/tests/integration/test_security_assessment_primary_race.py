"""Regression test for a confirmed P2 finding: _refresh_lookup_assessment()'s
UPDATE-then-INSERT pair that maintains the "at most one is_primary=True
FinalAssessmentRecord per lookup_id" invariant (app/core/security_assessment.py)
had no lock/serialization point across concurrent callers. Two concurrent
security-assessment runs finishing close together for the SAME lookup_id
could each flip the (already-stale) existing primary row to False and then
unconditionally INSERT their own new is_primary=True row, leaving TWO rows
both marked is_primary=True for one lookup -- violating the invariant
documented on FinalAssessmentRecord ("IOCLookup.final_assessment/
final_verdict/risk_score remain the PRIMARY assessment shown by default") and,
per frontend/components/dashboard/AiComparisonPanel.tsx, showing two rows
both labeled "Original" in the UI instead of one "Original" + one
"Comparison".

Live-reproduced before the fix by seeding a real ioc_lookups row and one
existing is_primary=True final_assessment_records row, then opening two
concurrent transactions that each replay the exact statement sequence
_refresh_lookup_assessment issues (`UPDATE final_assessment_records SET
is_primary=false WHERE lookup_id=$1 AND is_primary=true` followed, after a
short delay standing in for the real AI-call gap between the read and this
write, by an `INSERT ... is_primary=true`) and running them via
asyncio.gather -- final observed state: 2 rows with is_primary=True.

This test reproduces the exact same race through the real function itself
rather than a hand-rolled copy of its SQL: two concurrent calls to
_refresh_lookup_assessment() for the same lookup_id, via asyncio.gather.
AsyncSession.get() is patched to add a short delay every time it's asked for
the IOCLookup row -- that's a real await point _refresh_lookup_assessment
already has both up front and, critically, INSIDE its final UPDATE-then-
INSERT transaction (`lookup = await db.get(IOCLookup, lookup_id)`, between
the UPDATE and the commit that flushes the pending INSERT) -- widening that
existing, real gap to a size a natural docker-network round trip won't
reliably hit on its own is exactly the "short delay standing in for the real
AI-call gap" the live reproduction used, applied at the same real code path
instead of a separate copy of it.

Fixed by acquiring a Postgres advisory lock (pg_advisory_xact_lock, keyed on
lookup_id) at the top of that final transaction, serializing concurrent
callers for the same lookup_id -- a plain in-process asyncio.Lock would not
be enough since this backend runs multiple replicas in k8s (see
k8s/base/backend-deployment.yaml)."""
import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.security_assessment as sa_service
from app.ai.schemas import FinalAssessment, RiskAssessment
from app.core.config import get_settings
from app.models.lookup import FinalAssessmentRecord, IOCLookup, LookupStatus, Verdict


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    # Each pytest-asyncio test function runs its own event loop; a pooled
    # asyncpg connection created in a previous test's loop cannot be reused
    # in this test's loop ("Future attached to a different loop"). Matches
    # test_security_assessment_api.py's own fixture of the same name/shape.
    import app.core.db as db_module

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)
    yield
    await db_module._engine.dispose()


async def _make_lookup(ioc_value: str, ioc_type: str) -> uuid.UUID:
    from app.core.db import new_session

    async with new_session() as db:
        lookup = IOCLookup(ioc_value=ioc_value, ioc_type=ioc_type, status=LookupStatus.COMPLETED)
        db.add(lookup)
        await db.commit()
        await db.refresh(lookup)
        return lookup.id


async def _cleanup_lookup(lookup_id: uuid.UUID) -> None:
    from sqlalchemy import delete

    from app.core.db import new_session

    async with new_session() as db:
        await db.execute(delete(FinalAssessmentRecord).where(FinalAssessmentRecord.lookup_id == lookup_id))
        await db.commit()
    async with new_session() as db:
        lookup = await db.get(IOCLookup, lookup_id)
        if lookup is not None:
            await db.delete(lookup)
            await db.commit()


def _final(tag: str) -> FinalAssessment:
    return FinalAssessment(
        ioc_value="127.0.0.1",
        ioc_type="ipv4",
        executive_summary=f"test-{tag}",
        technical_summary="test",
        threat_assessment="test",
        relationships_summary="test",
        risk=RiskAssessment(
            overall_risk_score=10, confidence_score=50, severity="low",
            reputation="unknown", malicious_probability=10, analyst_confidence="low",
        ),
        final_verdict=Verdict.UNKNOWN,
        verdict_rationale="test",
        ai_backend=f"backend-{tag}",
        ai_model=f"model-{tag}",
    )


@pytest.mark.asyncio
async def test_concurrent_refreshes_for_the_same_lookup_leave_exactly_one_primary_row(monkeypatch):
    lookup_id = await _make_lookup("127.0.0.1", "ipv4")
    try:
        from app.core.db import new_session

        # Mirrors the state after a lookup's original investigation: one
        # pre-existing is_primary=True row (e.g. the original "ollama" run).
        async with new_session() as db:
            db.add(
                FinalAssessmentRecord(
                    lookup_id=lookup_id, ai_backend="ollama", ai_model="llama3",
                    ai_outcome="success", is_primary=True, assessment=_final("original").model_dump(),
                )
            )
            await db.commit()

        call_count = {"value": 0}

        async def _fake_generate(ioc_value, ioc_type, summaries, correlation, scoring, unavailable_providers=None):
            call_count["value"] += 1
            return _final(f"run-{call_count['value']}")

        monkeypatch.setattr(sa_service, "generate_final_assessment", _fake_generate)

        # Widen the real await point _refresh_lookup_assessment already has
        # (its own `await db.get(IOCLookup, lookup_id)` calls) so two
        # concurrent invocations' transactions genuinely overlap instead of
        # racing to finish first on a sub-millisecond local docker network --
        # see this module's docstring for why this is the real code's own
        # existing gap, not an artificial one invented for the test.
        original_get = AsyncSession.get

        async def _slow_get(self, entity, ident, *args, **kwargs):
            result = await original_get(self, entity, ident, *args, **kwargs)
            if entity is IOCLookup and ident == lookup_id:
                await asyncio.sleep(0.3)
            return result

        monkeypatch.setattr(AsyncSession, "get", _slow_get)

        await asyncio.gather(
            sa_service._refresh_lookup_assessment(lookup_id, "127.0.0.1", [], None),
            sa_service._refresh_lookup_assessment(lookup_id, "127.0.0.1", [], None),
        )

        async with new_session() as db:
            rows = (
                await db.execute(select(FinalAssessmentRecord).where(FinalAssessmentRecord.lookup_id == lookup_id))
            ).scalars().all()
        primary_rows = [r for r in rows if r.is_primary]
        assert len(rows) == 3, (
            f"expected the original row plus 2 new rows from the 2 concurrent refreshes, got {len(rows)}"
        )
        assert len(primary_rows) == 1, (
            "expected exactly ONE is_primary=True row after 2 concurrent refreshes of the same lookup "
            f"(the 'at most one PRIMARY assessment per lookup' invariant), got {len(primary_rows)}: "
            f"{[(r.ai_backend, r.is_primary) for r in rows]}"
        )

        # And the IOCLookup convenience columns must reflect whichever run
        # actually ended up primary, not be left pointing at neither/both.
        async with new_session() as db:
            lookup = await db.get(IOCLookup, lookup_id)
        assert lookup.final_assessment["ai_backend"] == primary_rows[0].ai_backend
    finally:
        await _cleanup_lookup(lookup_id)
