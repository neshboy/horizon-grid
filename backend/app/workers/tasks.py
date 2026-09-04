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

import app.core.db as db_module
from app.core.cache import set_cached_result
from app.core.config import get_settings
from app.core.db import new_session
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


async def _crawl_one(ioc_value: str, ioc_type_str: str, client: httpx.AsyncClient) -> bool:
    """Returns whether this IOC's cache entry was actually refreshed -- the
    caller uses this to report a real success count, not just an attempt
    count (see _run_osint_crawl_async's own comment)."""
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
        return True
    return False


async def _run_osint_crawl_async() -> int:
    # Real gap found live during overnight QA: run_osint_crawl() (below)
    # calls asyncio.run() fresh every hourly Celery Beat tick -- each tick
    # gets a BRAND NEW event loop, but app/core/db.py's engine/connection
    # pool is a module-level singleton that persists for the worker
    # process's whole lifetime, bound to whichever loop first actually used
    # it. Every tick after the first would try to reuse a pool whose
    # connections belong to an already-closed loop. Disposing it in this
    # finally, while its OWN loop is still open (on every exit path -- an
    # early return, a normal return, or an exception), closes every pooled
    # connection cleanly -- the next tick's fresh event loop then creates
    # brand new connections on first use, exactly as if Postgres was never
    # touched by a previous, now-dead loop at all.
    try:
        targets = await _recent_crawlable_iocs()
        if not targets:
            logger.info("Scheduled OSINT crawl: no recently-investigated crawlable IOCs, nothing to do")
            return 0

        # Real gap found live during overnight QA: this used to report
        # len(targets) -- the number of IOCs ATTEMPTED, not the number
        # actually cached. A provider outage or a run of individually-
        # failing targets would still log/return "refreshed cache for N
        # IOC(s)", silently overstating how much real work happened.
        refreshed = 0
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for ioc_value, ioc_type_str in targets:
                try:
                    if await _crawl_one(ioc_value, ioc_type_str, client):
                        refreshed += 1
                except Exception:  # noqa: BLE001 -- one bad target must not abort the whole run
                    logger.warning("Scheduled OSINT crawl failed for %r (%s)", ioc_value, ioc_type_str, exc_info=True)

        logger.info(
            "Scheduled OSINT crawl: refreshed cache for %d of %d attempted IOC(s)", refreshed, len(targets)
        )
        return refreshed
    finally:
        await db_module._engine.dispose()


@celery_app.task(name="app.workers.tasks.run_osint_crawl")
def run_osint_crawl() -> int:
    """Entry point Celery Beat calls hourly (see celery_app.py's beat_schedule).
    Returns the number of IOCs refreshed, for visibility in Celery's result backend/logs.
    """
    return asyncio.run(_run_osint_crawl_async())
