"""Regression test for a confirmed P2 finding: GET /api/v1/cases crashed with
an unhandled 500 Internal Server Error when the optional `status_filter`
query parameter was any string that isn't a valid CaseStatus label.

Root cause: app/api/routes/cases.py's list_cases() declared
`status_filter: str | None = None` -- an untyped query param -- so
FastAPI/Pydantic never validated it before the route did
`query.where(Case.status == status_filter)`. That sent the raw,
unvalidated string straight to Postgres as a bind parameter for the native
`casestatus` enum column, and asyncpg/Postgres rejected it with
`InvalidTextRepresentationError: invalid input value for enum casestatus`,
surfacing as an uncaught `sqlalchemy.exc.DBAPIError` -- a generic 500
instead of a clean 422. This is the same class of bug already fixed for
CaseIOCAddRequest.lookup_id (see test_case_ioc_bad_lookup_id_returns_422.py)
and for every other enum field in this API (severity, ioc_type_hint,
CaseUpdateRequest.status), all of which are Pydantic-validated before ever
reaching the DB.

Confirmed live against the running stack before this fix:
GET /api/v1/cases?status_filter=not_a_real_status returned HTTP 500
"Internal Server Error" with the DBAPIError visible only in the server log.

Fixed by typing list_cases()'s status_filter parameter as
`CaseStatus | None = None` so FastAPI/Pydantic rejects an invalid value
with a 422 before the route (or the DB) ever sees it, matching how
CaseUpdateRequest.status is already validated.

Runs against the real app (ASGI transport) and the real Postgres this
docker-compose stack's backend container already talks to, matching
test_case_ioc_bad_lookup_id_returns_422.py's pattern.
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
    # test_case_ioc_bad_lookup_id_returns_422.py's own fixture of the same
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

    email = _unique_email("qa-list-cases-bad-status")
    created = await create_user(email, "pw-1", "List Cases Bad Status Test User", Role.ANALYST, None, "actor@qa.test")
    token = create_access_token(email, Role.ANALYST.value)
    return uuid.UUID(created["id"]), token


async def _cleanup(user_id: uuid.UUID) -> None:
    from app.core.db import new_session
    from app.models.case import Case
    from app.models.user import User

    async with new_session() as db:
        cases = (await db.execute(select(Case).where(Case.analyst_id == user_id))).scalars().all()
        for case in cases:
            await db.delete(case)
        await db.commit()
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_cases_with_invalid_status_filter_returns_422_not_500():
    from app.main import app

    user_id, token = await _make_analyst()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            case_resp = await client.post(
                "/api/v1/cases", json={"title": "Bad status_filter regression case"}, headers=_auth(token)
            )
            assert case_resp.status_code == 201, case_resp.text

            bad_resp = await client.get(
                "/api/v1/cases", params={"status_filter": "not_a_real_status"}, headers=_auth(token)
            )
            assert bad_resp.status_code == 422, (
                f"an invalid status_filter must be rejected with a clean 422, not crash "
                f"the server; got {bad_resp.status_code}: {bad_resp.text}"
            )

            # A valid status_filter value must still work -- the fix must not
            # be so strict it breaks the legitimate case.
            good_resp = await client.get(
                "/api/v1/cases", params={"status_filter": "open"}, headers=_auth(token)
            )
            assert good_resp.status_code == 200, good_resp.text
            assert any(c["title"] == "Bad status_filter regression case" for c in good_resp.json())

            # Omitting status_filter entirely must still work too.
            no_filter_resp = await client.get("/api/v1/cases", headers=_auth(token))
            assert no_filter_resp.status_code == 200, no_filter_resp.text
    finally:
        await _cleanup(user_id)
