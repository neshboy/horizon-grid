"""Celery tasks. Currently one: the hourly OSINT crawl referenced by
app/workers/celery_app.py's beat_schedule (`app.workers.tasks.run_osint_crawl`).

Design note on what "crawl OSINT sources hourly" means with no fixed target
list: rather than invent an arbitrary hardcoded set of search terms, this
re-runs the crawler for IOCs that were actually looked up recently (the
crawler-eligible types only -- domain/ipv4/malware_family/threat_actor/
campaign/cve/file_name, see app/crawler/collector.py's _SUPPORTED_TYPES) and
writes fresh results into the same Redis cache the interactive lookup path
reads from (app/core/cache.py). This keeps OSINT findings warm for whatever
the platform's users are actually investigating, rather than crawling
something nobody asked about.

Celery tasks are sync; the crawler and DB layer are async-only, so each task
run gets its own asyncio event loop via asyncio.run() -- there is no running
loop in a Celery worker process to piggyback on.
"""
import asyncio
import logging

import httpx
from sqlalchemy import select

from app.core.cache import set_cached_result
from app.core.config import get_settings
from app.core.db import _engine, new_session
from app.crawler.collector import internet_intelligence_provider
from app.ioc.types import IOCType
from app.models.lookup import IOCLookup
from app.providers.base import ProviderStatus
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Must match app/crawler/collector.py's _SUPPORTED_TYPES -- only these IOC
# types produce meaningful crawler hits (free-text search on e.g. a raw hash
# or IP is nearly always noise, same reasoning as the crawler itself).
_CRAWLABLE_TYPES = {
    IOCType.DOMAIN.value,
    IOCType.IPV4.value,
    IOCType.MALWARE_FAMILY.value,
    IOCType.THREAT_ACTOR.value,
    IOCType.CAMPAIGN.value,
    IOCType.CVE.value,
    IOCType.FILE_NAME.value,
}

# How far back to look for "recently investigated" IOCs, and how many to
# refresh per run -- bounds a single beat tick to a fixed amount of work
# regardless of how much lookup volume the platform sees.
_LOOKBACK_HOURS = 24
_MAX_IOCS_PER_RUN = 25


async def _recent_crawlable_iocs() -> list[tuple[str, str]]:
    from datetime import datetime, timedelta, timezone

    # Postgres rejects `SELECT DISTINCT ... ORDER BY created_at` when
    # created_at isn't in the select list, so dedupe in Python instead --
    # fetch a wider raw window (repeat lookups of the same IOC are the only
    # thing that inflates the row count past _MAX_IOCS_PER_RUN) and keep
    # only the first (most recent) occurrence of each (value, type) pair.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_LOOKBACK_HOURS)
    async with new_session() as db:
        rows = (
            await db.execute(
                select(IOCLookup.ioc_value, IOCLookup.ioc_type)
                .where(IOCLookup.ioc_type.in_(_CRAWLABLE_TYPES))
                .where(IOCLookup.created_at >= cutoff)
                .order_by(IOCLookup.created_at.desc())
                .limit(_MAX_IOCS_PER_RUN * 10)
            )
        ).all()

    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for row in rows:
        key = (row.ioc_value, row.ioc_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
        if len(deduped) >= _MAX_IOCS_PER_RUN:
            break
    return deduped


async def _crawl_one(ioc_value: str, ioc_type_str: str, client: httpx.AsyncClient) -> None:
    settings = get_settings()
    ioc_type = IOCType(ioc_type_str)
    result = await internet_intelligence_provider.run(ioc_value, ioc_type, client)
    if result.status == ProviderStatus.OK:
        await set_cached_result(
            internet_intelligence_provider.provider_id,
            ioc_type.value,
            ioc_value,
            result.to_dict(),
            settings.provider_cache_ttl_seconds,
        )


async def _run_osint_crawl_async() -> int:
    try:
        targets = await _recent_crawlable_iocs()
        if not targets:
            logger.info("Scheduled OSINT crawl: no recently-investigated crawlable IOCs, nothing to do")
            return 0

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for ioc_value, ioc_type_str in targets:
                try:
                    await _crawl_one(ioc_value, ioc_type_str, client)
                except Exception:  # noqa: BLE001 -- one bad target must not abort the whole run
                    logger.warning("Scheduled OSINT crawl failed for %r (%s)", ioc_value, ioc_type_str, exc_info=True)

        logger.info("Scheduled OSINT crawl: refreshed cache for %d IOC(s)", len(targets))
        return len(targets)
    finally:
        # Real bug found live (reproduced deterministically by calling this
        # coroutine via asyncio.run() twice in the same process): run_osint_crawl()
        # below wraps this in a *fresh* asyncio.run() every invocation, but
        # app/core/db.py's `_engine` (and its connection pool) is a process-wide
        # singleton reused across every one of those invocations. asyncpg binds
        # each pooled connection to the event loop that created it, so once
        # asyncio.run() closes this run's loop, any connection left sitting idle
        # in the pool is now attached to a dead loop. The *next* run's pre-ping
        # check (or any use of that connection) then blows up with exactly
        # "RuntimeError: Event loop is closed" / "Future ... attached to a
        # different loop" instead of completing or failing cleanly.
        # dispose() only drains/closes the pool's connections -- `_engine` itself
        # is untouched and reused fine next run, opening fresh connections under
        # whatever loop that run's asyncio.run() creates.
        await _engine.dispose()


@celery_app.task(name="app.workers.tasks.run_osint_crawl")
def run_osint_crawl() -> int:
    """Entry point Celery Beat calls hourly (see celery_app.py's beat_schedule).
    Returns the number of IOCs refreshed, for visibility in Celery's result backend/logs.
    """
    return asyncio.run(_run_osint_crawl_async())
