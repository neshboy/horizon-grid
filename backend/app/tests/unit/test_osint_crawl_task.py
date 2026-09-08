"""Unit tests for app.workers.tasks's scheduled OSINT crawl -- no real DB,
Redis, or network I/O; every boundary (_recent_crawlable_iocs, the crawler
provider, set_cached_result, the DB engine) is mocked.

Real gaps found live during overnight QA:
1. The reported/returned "refreshed" count was the number of IOCs
   ATTEMPTED, not the number actually cached -- a provider outage would
   still report full success.
2. app/core/db.py's module-level engine/connection pool is bound to
   whichever event loop first used it and persists for the whole worker
   process -- but run_osint_crawl() (the real Celery entry point) calls
   asyncio.run() fresh every hourly tick, each getting a brand new loop.
   Without disposing the pool at the end of each run (while its own loop
   is still open), every tick after the first would try to reuse
   connections bound to an already-closed loop.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.ioc.types import IOCType
from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus
from app.workers import tasks as tasks_module


def _result(ioc_value: str, ioc_type: IOCType, status: ProviderStatus) -> ProviderResult:
    return ProviderResult(
        provider_id="internet_intelligence",
        provider_name="Internet Intelligence Collector",
        category=ProviderCategory.OSINT,
        status=status,
        ioc_value=ioc_value,
        ioc_type=ioc_type,
        data={"hits": []} if status == ProviderStatus.OK else {},
    )


@pytest.mark.asyncio
async def test_refreshed_count_reflects_actual_cache_writes_not_attempts():
    """2 targets attempted, only 1 actually succeeds (OK) -- the returned
    count must be 1, not 2."""
    targets = [("evil.example", "domain"), ("also-evil.example", "domain")]

    async def fake_run(ioc_value, ioc_type, client):
        if ioc_value == "evil.example":
            return _result(ioc_value, ioc_type, ProviderStatus.OK)
        return _result(ioc_value, ioc_type, ProviderStatus.ERROR)

    with (
        patch.object(tasks_module, "_recent_crawlable_iocs", AsyncMock(return_value=targets)),
        patch.object(tasks_module.internet_intelligence_provider, "run", side_effect=fake_run),
        patch.object(tasks_module, "set_cached_result", AsyncMock()) as mock_set_cached,
        patch.object(tasks_module.db_module, "_engine", AsyncMock()),
    ):
        refreshed = await tasks_module._run_osint_crawl_async()

    assert refreshed == 1
    mock_set_cached.assert_awaited_once()  # only the OK result gets cached


@pytest.mark.asyncio
async def test_a_crawl_exception_does_not_inflate_the_refreshed_count_or_abort_the_run():
    targets = [("crashes.example", "domain"), ("fine.example", "domain")]

    async def fake_run(ioc_value, ioc_type, client):
        if ioc_value == "crashes.example":
            raise RuntimeError("boom")
        return _result(ioc_value, ioc_type, ProviderStatus.OK)

    with (
        patch.object(tasks_module, "_recent_crawlable_iocs", AsyncMock(return_value=targets)),
        patch.object(tasks_module.internet_intelligence_provider, "run", side_effect=fake_run),
        patch.object(tasks_module, "set_cached_result", AsyncMock()),
        patch.object(tasks_module.db_module, "_engine", AsyncMock()),
    ):
        refreshed = await tasks_module._run_osint_crawl_async()

    assert refreshed == 1


@pytest.mark.asyncio
async def test_engine_is_disposed_after_a_normal_run_with_targets():
    """Real gap found live during overnight QA: without this, the second
    and every subsequent hourly Celery Beat tick (each getting a brand new
    event loop via asyncio.run()) would try to reuse Postgres connections
    bound to the FIRST tick's already-closed loop."""
    targets = [("evil.example", "domain")]

    async def fake_run(ioc_value, ioc_type, client):
        return _result(ioc_value, ioc_type, ProviderStatus.OK)

    fake_engine = AsyncMock()
    with (
        patch.object(tasks_module, "_recent_crawlable_iocs", AsyncMock(return_value=targets)),
        patch.object(tasks_module.internet_intelligence_provider, "run", side_effect=fake_run),
        patch.object(tasks_module, "set_cached_result", AsyncMock()),
        patch.object(tasks_module.db_module, "_engine", fake_engine),
    ):
        await tasks_module._run_osint_crawl_async()

    fake_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_engine_is_disposed_even_when_there_are_no_targets():
    fake_engine = AsyncMock()
    with (
        patch.object(tasks_module, "_recent_crawlable_iocs", AsyncMock(return_value=[])),
        patch.object(tasks_module.db_module, "_engine", fake_engine),
    ):
        refreshed = await tasks_module._run_osint_crawl_async()

    assert refreshed == 0
    fake_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_engine_is_disposed_even_when_recent_crawlable_iocs_itself_raises():
    fake_engine = AsyncMock()
    with (
        patch.object(tasks_module, "_recent_crawlable_iocs", AsyncMock(side_effect=RuntimeError("db down"))),
        patch.object(tasks_module.db_module, "_engine", fake_engine),
    ):
        with pytest.raises(RuntimeError):
            await tasks_module._run_osint_crawl_async()

    fake_engine.dispose.assert_awaited_once()
