"""Regression test for a confirmed P3 finding: POST /api/v1/cases/{case_id}
/iocs's add_case_ioc() had no uniqueness constraint and no existing-row
check at all, unlike the analogous, more carefully hardened
app/api/routes/basket.py's add_to_basket() (uq_basket_owner_ioc +
IntegrityError-race handling, see test_basket_add_race.py and
test_basket_add_case_insensitive_dedup.py).

Live-reproduced before the fix: 3 concurrent POST
/api/v1/cases/{case_id}/iocs requests with the identical body
{"ioc_value": "198.51.100.148", "ioc_type": "ipv4"} against the same case
each returned 201, leaving 3 distinct case_iocs rows with the same
ioc_value/ioc_type and near-identical created_at timestamps behind --
CaseIOC had no unique constraint on (case_id, ioc_value) at all, and
add_case_ioc() did an unconditional INSERT with no pre-insert dedup check.

Fixed by:
  - adding UniqueConstraint("case_id", "ioc_value", name=
    "uq_case_ioc_case_value") to CaseIOC (app/models/case.py; see migration
    401e725fa85f_add_case_ioc_uniqueness_constraint.py), mirroring
    BasketItem's uq_basket_owner_ioc.
  - adding a case-insensitive pre-insert dedup SELECT plus IntegrityError
    handling around the commit in add_case_ioc() (app/api/routes/cases.py),
    mirroring add_to_basket()'s own handling of exactly this class of bug.

This test covers two angles:
  1. The genuine check-then-insert race, deterministic via the same
     monkeypatched-commit technique as test_basket_add_race.py: the
     request's own commit() raises IntegrityError because a real
     concurrently-committed row (via a second, unpatched session) already
     exists for the same (case_id, ioc_value).
  2. A same-casing sequential re-add (the common double-click/retry case),
     confirming it also collapses to one row without needing the race path.

Runs against the real app (ASGI transport) and the real Postgres this
docker-compose stack's backend container already talks to, matching
test_basket_add_race.py's pattern.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

RACE_IOC_VALUE = "198.51.100.148"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    # Each pytest-asyncio test function runs its own event loop; a pooled
    # asyncpg connection created in a previous test's loop cannot be reused
    # in this test's loop ("Future attached to a different loop"). Matches
    # test_basket_add_race.py's own fixture of the same name/shape.
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

    email = _unique_email("qa-case-ioc-race")
    created = await create_user(email, "pw-1", "Case IOC Race Test User", Role.ANALYST, None, "actor@qa.test")
    token = create_access_token(email, Role.ANALYST.value)
    return uuid.UUID(created["id"]), token


async def _cleanup(user_id: uuid.UUID) -> None:
    from app.core.db import new_session
    from app.models.case import Case, CaseIOC
    from app.models.user import User

    async with new_session() as db:
        cases = (await db.execute(select(Case).where(Case.analyst_id == user_id))).scalars().all()
        for case in cases:
            iocs = (await db.execute(select(CaseIOC).where(CaseIOC.case_id == case.id))).scalars().all()
            for ioc in iocs:
                await db.delete(ioc)
            await db.delete(case)
        await db.commit()
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_add_case_ioc_collapses_existing_row_instead_of_500_on_insert_race():
    """The exact live repro, deterministically triggered: the request's own
    commit() raises IntegrityError (because a real competing row -- the
    'other' concurrent request's winning INSERT -- already exists for the
    same (case_id, ioc_value)). Must respond 201 with the case intact, not
    an unhandled 500, and must leave exactly one case_iocs row behind."""
    from app.main import app
    from app.core.db import new_session
    from app.models.case import CaseIOC

    user_id, token = await _make_analyst()
    original_commit = AsyncSession.commit
    call_count = {"value": 0}

    async def _fail_first_commit(self, *args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return await original_commit(self, *args, **kwargs)
        if call_count["value"] == 2:
            # Simulate the winning side of the race committing first, via a
            # second session that bypasses this patch entirely (calls the
            # real, unpatched commit directly) -- this is a genuinely
            # committed, real conflicting row, not a mocked return value.
            async with new_session() as winner_db:
                winner_db.add(
                    CaseIOC(
                        case_id=case_id_holder["value"],
                        ioc_value=RACE_IOC_VALUE,
                        ioc_type="ipv4",
                        added_by=user_id,
                    )
                )
                await original_commit(winner_db)
            raise IntegrityError(
                'duplicate key value violates unique constraint "uq_case_ioc_case_value"',
                params=None,
                orig=Exception("simulated concurrent INSERT collision"),
            )
        return await original_commit(self, *args, **kwargs)

    case_id_holder = {"value": None}
    AsyncSession.commit = _fail_first_commit
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            case_resp = await client.post(
                "/api/v1/cases", json={"title": "IOC race regression case"}, headers=_auth(token)
            )
            assert case_resp.status_code == 201, case_resp.text
            case_id = case_resp.json()["id"]
            case_id_holder["value"] = uuid.UUID(case_id)

            response = await client.post(
                f"/api/v1/cases/{case_id}/iocs",
                json={"ioc_value": RACE_IOC_VALUE, "ioc_type": "ipv4"},
                headers=_auth(token),
            )
    finally:
        AsyncSession.commit = original_commit

    try:
        assert response.status_code == 201, (
            "the losing side of a check-then-insert race must still return 201 with the case "
            f"intact, not propagate the IntegrityError as a 500; got {response.status_code}: {response.text}"
        )
        body = response.json()
        matching = [i for i in body["iocs"] if i["ioc_value"] == RACE_IOC_VALUE]
        assert len(matching) == 1, (
            f"exactly one matching IOC must be reflected in the case response, got {len(matching)}"
        )
        assert call_count["value"] >= 2, "the request must actually have gone through the patched commit()"

        async with new_session() as db:
            rows = (
                await db.execute(
                    select(CaseIOC).where(
                        CaseIOC.case_id == case_id_holder["value"], CaseIOC.ioc_value == RACE_IOC_VALUE
                    )
                )
            ).scalars().all()
        assert len(rows) == 1, "exactly one case_iocs row must exist after the race, not zero or two"
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_add_case_ioc_sequential_duplicate_does_not_create_second_row():
    """The common double-click/retry case, no monkeypatching needed: adding
    the exact same (case_id, ioc_value, ioc_type) a second time must not
    create a second case_iocs row."""
    from app.main import app
    from app.core.db import new_session
    from app.models.case import CaseIOC

    user_id, token = await _make_analyst()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            case_resp = await client.post(
                "/api/v1/cases", json={"title": "IOC sequential dup regression case"}, headers=_auth(token)
            )
            assert case_resp.status_code == 201, case_resp.text
            case_id = case_resp.json()["id"]

            first = await client.post(
                f"/api/v1/cases/{case_id}/iocs",
                json={"ioc_value": "203.0.113.99", "ioc_type": "ipv4"},
                headers=_auth(token),
            )
            assert first.status_code == 201, first.text

            second = await client.post(
                f"/api/v1/cases/{case_id}/iocs",
                json={"ioc_value": "203.0.113.99", "ioc_type": "ipv4"},
                headers=_auth(token),
            )
            assert second.status_code == 201, second.text

            # A genuinely different value in the same case must still add
            # normally -- the fix must not be so strict it breaks that.
            third = await client.post(
                f"/api/v1/cases/{case_id}/iocs",
                json={"ioc_value": "203.0.113.100", "ioc_type": "ipv4"},
                headers=_auth(token),
            )
            assert third.status_code == 201, third.text
            assert len(third.json()["iocs"]) == 2, (
                "the duplicate add must not have created a second row, and the genuinely "
                f"different value must have; got iocs={third.json()['iocs']}"
            )

        async with new_session() as db:
            rows = (
                await db.execute(
                    select(CaseIOC).where(CaseIOC.case_id == uuid.UUID(case_id), CaseIOC.ioc_value == "203.0.113.99")
                )
            ).scalars().all()
        assert len(rows) == 1, f"exactly one case_iocs row must exist for the duplicated value, found {len(rows)}"
    finally:
        await _cleanup(user_id)
