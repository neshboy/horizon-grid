"""Regression test for a confirmed P3 finding: POST /api/v1/basket's
add_to_basket() deduplicated an existing basket entry with

    existing = SELECT ... WHERE owner_id = ? AND ioc_value = ?

a byte-for-byte comparison against `ioc_value = payload.ioc_value.strip()`,
which only normalizes whitespace, never case. The DB's own
UniqueConstraint("owner_id", "ioc_value") (uq_basket_owner_ioc, see
app/models/basket.py) is equally case-sensitive.

Live-reproduced before the fix: POST {"ioc_value": "EXAMPLE.COM"} followed by
POST {"ioc_value": "example.com"} as the same user created two distinct
basket_items rows (both ioc_type "domain"), both visible in GET /basket,
instead of the second call recognizing the first row and returning it -- the
same behavior the endpoint already has for an exact (same-case) re-add.

This is inconsistent with app/correlation/engine.py's own _node_id(), which
does `value.strip().lower()` specifically so the same IOC in different
casing dedupes to a single graph node.

Fixed by comparing case-insensitively in the pre-insert dedup SELECT
(`func.lower(BasketItem.ioc_value) == ioc_value.lower()`) rather than
rewriting the stored value -- whichever casing was entered first is kept,
and a later add in different casing returns that existing row unchanged.

Runs against the real app (ASGI transport) and the real Postgres this
docker-compose stack's backend container already talks to, matching
test_basket_add_race.py's pattern.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

CANONICAL_IOC_VALUE = "EXAMPLE-CASE-DEDUP-QA.COM"
DIFFERENT_CASE_IOC_VALUE = "example-case-dedup-qa.com"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test():
    # Each pytest-asyncio test function runs its own event loop; a pooled
    # asyncpg connection created in a previous test's loop cannot be reused
    # in this test's loop ("Future attached to a different loop"). Matches
    # test_security_assessment_api.py's/test_basket_compare_status_filter.py's
    # own fixture of the same name/shape.
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

    email = _unique_email("qa-basket-case-dedup")
    created = await create_user(email, "pw-1", "Basket Case Dedup Test User", Role.ANALYST, None, "actor@qa.test")
    token = create_access_token(email, Role.ANALYST.value)
    return uuid.UUID(created["id"]), token


async def _cleanup(user_id: uuid.UUID) -> None:
    from app.core.db import new_session
    from app.models.basket import BasketItem
    from app.models.user import User

    async with new_session() as db:
        items = (await db.execute(select(BasketItem).where(BasketItem.owner_id == user_id))).scalars().all()
        for item in items:
            await db.delete(item)
        await db.commit()
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_add_to_basket_dedupes_same_ioc_in_different_casing():
    """Adding 'example-case-dedup-qa.com' after 'EXAMPLE-CASE-DEDUP-QA.COM'
    must return the existing item (same id, original casing preserved), not
    create a second basket_items row."""
    from app.main import app
    from app.core.db import new_session
    from app.models.basket import BasketItem

    user_id, token = await _make_analyst()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first = await client.post(
                "/api/v1/basket",
                json={"ioc_value": CANONICAL_IOC_VALUE, "ioc_type_hint": "domain"},
                headers=_auth(token),
            )
            assert first.status_code == 201, first.text
            first_body = first.json()

            second = await client.post(
                "/api/v1/basket",
                json={"ioc_value": DIFFERENT_CASE_IOC_VALUE, "ioc_type_hint": "domain"},
                headers=_auth(token),
            )

        assert second.status_code == 201, second.text
        second_body = second.json()

        assert second_body["id"] == first_body["id"], (
            "adding the same IOC in different casing must return the existing basket item, "
            f"not create a new one; first={first_body}, second={second_body}"
        )
        assert second_body["ioc_value"] == CANONICAL_IOC_VALUE, (
            "the existing entry's original casing must be preserved, not overwritten by the "
            "later differently-cased add"
        )

        async with new_session() as db:
            rows = (
                await db.execute(select(BasketItem).where(BasketItem.owner_id == user_id))
            ).scalars().all()
        assert len(rows) == 1, (
            "exactly one basket_items row must exist for the same logical IOC regardless of "
            f"casing, found {len(rows)}"
        )
    finally:
        await _cleanup(user_id)
