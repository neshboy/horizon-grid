"""Regression test for a confirmed P4 finding: POST /api/v1/cases/{case_id}
/iocs accepted an empty-string `ioc_type` and persisted it verbatim on a
real CaseIOC row.

Root cause: app/schemas/case.py's CaseIOCAddRequest.ioc_type had no
`min_length`, unlike its sibling ioc_value (which requires min_length=1 on
the very same schema) and unlike basket/lookup's ioc_type_hint (a real
IOCType enum member, which can never be empty). An empty string therefore
sailed straight past request validation, through add_case_ioc()
(app/api/routes/cases.py), and into the database.

Confirmed live against the running stack before this fix: POSTing
{"ioc_value": "9.9.9.9", "ioc_type": ""} to /api/v1/cases/{case_id}/iocs
returned HTTP 201 Created, and a subsequent GET on the case showed the new
IOC entry with "ioc_type":"" persisted.

Fixed by adding Field(min_length=1) to CaseIOCAddRequest.ioc_type, matching
ioc_value's own min_length=1 requirement on the same schema, so pydantic
now rejects an empty ioc_type with a 422 before the route (or the DB) ever
sees it.

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

    email = _unique_email("qa-case-ioc-empty-type")
    created = await create_user(email, "pw-1", "Case IOC Empty Type Test User", Role.ANALYST, None, "actor@qa.test")
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
async def test_add_case_ioc_with_empty_ioc_type_returns_422_not_persisted():
    from app.main import app

    user_id, token = await _make_analyst()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            case_resp = await client.post(
                "/api/v1/cases", json={"title": "Empty ioc_type regression case"}, headers=_auth(token)
            )
            assert case_resp.status_code == 201, case_resp.text
            case_id = case_resp.json()["id"]

            bad_resp = await client.post(
                f"/api/v1/cases/{case_id}/iocs",
                json={"ioc_value": "9.9.9.9", "ioc_type": ""},
                headers=_auth(token),
            )
            assert bad_resp.status_code == 422, (
                f"empty ioc_type must be rejected with a clean 422, not persisted "
                f"as a real row; got {bad_resp.status_code}: {bad_resp.text}"
            )

            # The case itself must remain usable afterward -- no partial
            # write, iocs list stays empty (no CaseIOC row with ioc_type="").
            get_resp = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(token))
            assert get_resp.status_code == 200, get_resp.text
            assert get_resp.json()["iocs"] == []

            # A non-empty ioc_type for the same ioc_value must still work --
            # the fix must not be so strict it breaks the legitimate case.
            good_resp = await client.post(
                f"/api/v1/cases/{case_id}/iocs",
                json={"ioc_value": "9.9.9.9", "ioc_type": "ipv4"},
                headers=_auth(token),
            )
            assert good_resp.status_code == 201, good_resp.text
    finally:
        await _cleanup(user_id)
