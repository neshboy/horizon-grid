"""Regression test for a confirmed P3 finding: POST /api/v1/basket/compare's
own docstring says "IOCs must already have a completed lookup", but the
per-id loop that built the comparison rows only ever checked
`if not lookup: continue` for an unresolvable/nonexistent lookup_id -- it
never checked `lookup.status`. A lookup that is still pending/running, or
that ended FAILED (e.g. because the analyst aborted the SSE connection
mid-stream, which the app itself flips to FAILED), was silently included in
the comparison table with null risk_score/confidence_score and verdict
"unknown", and fed to the AI narrative step right alongside genuinely
completed investigations -- misrepresenting incomplete data as a real,
comparable row.

Root cause: unlike the analogous guard in reanalyze_lookup()
(app/api/routes/lookup.py: `if lookup.status != LookupStatus.COMPLETED:
raise HTTPException(400, ...)`), compare_basket_iocs()'s loop in
app/api/routes/basket.py resolved each lookup_id to a row and only ever
guarded against the row not existing, never against its status.

Fixed by adding `if lookup.status != LookupStatus.COMPLETED: continue`
immediately after the existing `if not lookup: continue` -- a non-completed
lookup is now skipped the same way an unresolvable/nonexistent lookup_id
already was, rather than being silently included.

Runs against the real app (ASGI transport) and the real Postgres this
docker-compose stack's backend container already talks to, matching
test_basket_add_race.py's pattern. The AI narrative step (compare_iocs) is
monkeypatched so this test doesn't depend on a real AI backend being
configured/reachable in this environment.
"""
import uuid
from typing import Optional

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.analysis_schemas import IOCComparisonNarrative
from app.core.config import get_settings
from app.models.lookup import LookupStatus, Verdict


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


def _unique_ioc(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}.qa-test.example.com"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@qa.test"


async def _make_analyst():
    from app.auth.security import create_access_token
    from app.core.users import create_user
    from app.models.user import Role

    email = _unique_email("qa-basket-compare")
    created = await create_user(email, "pw-1", "Basket Compare Test User", Role.ANALYST, None, "actor@qa.test")
    token = create_access_token(email, Role.ANALYST.value)
    return uuid.UUID(created["id"]), token


async def _make_lookup(
    ioc_value: str,
    status: LookupStatus,
    risk_score: Optional[float] = None,
    confidence_score: Optional[float] = None,
    final_verdict: Optional[Verdict] = None,
) -> uuid.UUID:
    from app.core.db import new_session
    from app.models.lookup import IOCLookup

    async with new_session() as db:
        lookup = IOCLookup(
            ioc_value=ioc_value,
            ioc_type="domain",
            status=status,
            risk_score=risk_score,
            confidence_score=confidence_score,
            final_verdict=final_verdict,
        )
        db.add(lookup)
        await db.commit()
        await db.refresh(lookup)
        return lookup.id


async def _cleanup_lookup(lookup_id: uuid.UUID) -> None:
    from app.core.db import new_session
    from app.models.lookup import IOCLookup

    async with new_session() as db:
        lookup = await db.get(IOCLookup, lookup_id)
        if lookup is not None:
            await db.delete(lookup)
            await db.commit()


async def _cleanup_user(user_id: uuid.UUID) -> None:
    from sqlalchemy import select

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
async def test_compare_skips_non_completed_lookups_instead_of_including_them():
    """Two COMPLETED lookups plus one FAILED lookup are all passed as
    lookup_ids. The response's comparison rows must contain only the two
    COMPLETED IOCs -- the FAILED one must be skipped, exactly like an
    unresolvable/nonexistent lookup_id already is, not included with null
    risk/confidence fields and an 'unknown' verdict."""
    from app.main import app
    import app.api.routes.basket as basket_module

    user_id, token = await _make_analyst()

    completed_a_value = _unique_ioc("completed-a")
    completed_b_value = _unique_ioc("completed-b")
    failed_value = _unique_ioc("failed-c")

    completed_a_id = await _make_lookup(
        completed_a_value,
        LookupStatus.COMPLETED,
        risk_score=80.0,
        confidence_score=90.0,
        final_verdict=Verdict.MALICIOUS,
    )
    completed_b_id = await _make_lookup(
        completed_b_value,
        LookupStatus.COMPLETED,
        risk_score=10.0,
        confidence_score=70.0,
        final_verdict=Verdict.BENIGN,
    )
    failed_id = await _make_lookup(failed_value, LookupStatus.FAILED)

    async def _fake_compare_iocs(rows):
        return IOCComparisonNarrative(narrative="stubbed narrative for test", key_differences=[])

    original_compare_iocs = basket_module.compare_iocs
    basket_module.compare_iocs = _fake_compare_iocs
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/basket/compare",
                json={"lookup_ids": [str(completed_a_id), str(completed_b_id), str(failed_id)]},
                headers=_auth(token),
            )
    finally:
        basket_module.compare_iocs = original_compare_iocs

    try:
        assert response.status_code == 200, response.text
        body = response.json()
        rows = body["rows"]
        ioc_values = {row["ioc_value"] for row in rows}

        assert failed_value not in ioc_values, (
            "a FAILED lookup must never appear in the comparison rows -- it has no trustworthy "
            f"risk/confidence data yet. Rows returned: {rows}"
        )
        assert ioc_values == {completed_a_value, completed_b_value}, (
            f"expected exactly the two COMPLETED lookups' ioc_values, got {ioc_values}"
        )
        assert len(rows) == 2, f"expected exactly 2 comparison rows (only the COMPLETED lookups), got {len(rows)}"

        by_value = {row["ioc_value"]: row for row in rows}
        assert by_value[completed_a_value]["risk_score"] == 80.0
        assert by_value[completed_a_value]["verdict"] == "malicious"
        assert by_value[completed_b_value]["risk_score"] == 10.0
        assert by_value[completed_b_value]["verdict"] == "benign"
    finally:
        await _cleanup_lookup(completed_a_id)
        await _cleanup_lookup(completed_b_id)
        await _cleanup_lookup(failed_id)
        await _cleanup_user(user_id)


@pytest.mark.asyncio
async def test_compare_rejects_when_fewer_than_two_completed_lookups_remain():
    """If, after filtering out non-completed lookups, fewer than 2 rows
    remain, the endpoint must still 422 (its pre-existing behavior for
    unresolvable ids) rather than fall back to comparing incomplete data."""
    from app.main import app

    user_id, token = await _make_analyst()

    completed_value = _unique_ioc("completed-only")
    running_value = _unique_ioc("running-only")

    completed_id = await _make_lookup(
        completed_value,
        LookupStatus.COMPLETED,
        risk_score=50.0,
        confidence_score=50.0,
        final_verdict=Verdict.SUSPICIOUS,
    )
    running_id = await _make_lookup(running_value, LookupStatus.RUNNING)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/basket/compare",
                json={"lookup_ids": [str(completed_id), str(running_id)]},
                headers=_auth(token),
            )

        assert response.status_code == 422, response.text
    finally:
        await _cleanup_lookup(completed_id)
        await _cleanup_lookup(running_id)
        await _cleanup_user(user_id)
