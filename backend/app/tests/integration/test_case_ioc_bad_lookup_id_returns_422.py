"""Regression test for a confirmed P2 finding: POST /api/v1/cases/{case_id}
/iocs crashed with an unhandled 500 Internal Server Error when the optional
`lookup_id` field was a non-UUID string.

Root cause: app/schemas/case.py's CaseIOCAddRequest.lookup_id was a bare
`Optional[str]` with no format validation, and
app/api/routes/cases.py's add_case_ioc() did
`uuid.UUID(payload.lookup_id) if payload.lookup_id else None` with no
try/except. A malformed lookup_id therefore raised an uncaught
`ValueError: badly formed hexadecimal UUID string`, producing a generic
500 instead of a clean 422 -- unlike every other UUID-bearing field in this
API (e.g. the case_id path param), which FastAPI/Pydantic already validates
automatically.

Confirmed live against the running stack before this fix: POSTing
{"ioc_value": "1.2.3.4", "ioc_type": "ipv4", "lookup_id": "not-a-real-uuid"}
to /api/v1/cases/{case_id}/iocs returned HTTP 500 "Internal Server Error"
with the ValueError visible only in the server log.

Fixed by typing CaseIOCAddRequest.lookup_id as Optional[uuid.UUID] so
pydantic rejects a malformed value with a 422 before the route (or the DB)
ever sees it, and the route now uses payload.lookup_id directly.

Runs against the real app (ASGI transport) and the real Postgres this
docker-compose stack's backend container already talks to, matching
test_basket_add_case_insensitive_dedup.py's pattern.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    # Each pytest-asyncio test function runs its own event loop; a pooled
    # asyncpg connection created in a previous test's loop cannot be reused
    # in this test's loop ("Future attached to a different loop"). Matches
    # test_basket_add_case_insensitive_dedup.py's own fixture of the same
    # name/shape.
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

    email = _unique_email("qa-case-ioc-bad-lookup")
    created = await create_user(email, "pw-1", "Case IOC Bad Lookup Test User", Role.ANALYST, None, "actor@qa.test")
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
async def test_add_case_ioc_with_malformed_lookup_id_returns_422_not_500():
    from app.main import app

    user_id, token = await _make_analyst()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            case_resp = await client.post(
                "/api/v1/cases", json={"title": "Bad lookup_id regression case"}, headers=_auth(token)
            )
            assert case_resp.status_code == 201, case_resp.text
            case_id = case_resp.json()["id"]

            bad_resp = await client.post(
                f"/api/v1/cases/{case_id}/iocs",
                json={"ioc_value": "1.2.3.4", "ioc_type": "ipv4", "lookup_id": "not-a-real-uuid"},
                headers=_auth(token),
            )
            assert bad_resp.status_code == 422, (
                f"malformed lookup_id must be rejected with a clean 422, not crash "
                f"the server; got {bad_resp.status_code}: {bad_resp.text}"
            )

            # The case itself must remain usable afterward -- no partial
            # write, iocs list stays empty.
            get_resp = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(token))
            assert get_resp.status_code == 200, get_resp.text
            assert get_resp.json()["iocs"] == []

            # Omitting lookup_id entirely (the common "manual add, no prior
            # lookup" case) must still work -- the fix must not be so strict
            # it breaks the legitimate case.
            no_lookup_resp = await client.post(
                f"/api/v1/cases/{case_id}/iocs",
                json={"ioc_value": "9.9.9.9", "ioc_type": "ipv4"},
                headers=_auth(token),
            )
            assert no_lookup_resp.status_code == 201, no_lookup_resp.text
    finally:
        await _cleanup(user_id)
