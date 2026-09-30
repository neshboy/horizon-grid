"""Security-news / DFIR RSS aggregator, keyword-filtered by query.

Fetches a fixed list of well-known public security-news and threat-research
RSS feeds concurrently (via httpx so the fetch is async), parses each feed's
raw bytes with `feedparser` (which is itself synchronous -- feedparser has no
async API -- but parsing an already-downloaded feed is CPU-bound/fast enough
that running it inline is acceptable for this scaffold), and keyword-filters
entries whose title or summary contains `query` as a case-insensitive
substring. This is intentionally simple; a production version would use a
proper search/ranking index instead of substring matching.
"""
from __future__ import annotations

import asyncio
import logging
import time

import feedparser
import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# A handful of well-known public security-news / DFIR RSS feeds.
FEED_URLS = [
    "https://www.bleepingcomputer.com/feed/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://krebsonsecurity.com/feed/",
    "https://blog.talosintelligence.com/rss/",
    "https://cloud.google.com/blog/topics/threat-intelligence/rss/",
    "https://www.microsoft.com/en-us/security/blog/feed/",
    "https://www.crowdstrike.com/blog/feed/",
    "https://unit42.paloaltonetworks.com/feed/",
]

# The feeds themselves don't change more than a few times per hour, but
# search() is called once per crawler-eligible IOC lookup (plus once per IOC
# in the hourly OSINT crawl task, up to 25/run) -- without a cache, every one
# of those independently re-downloads+re-parses all 8 feeds. Mirrors
# app/providers/mitre_attack.py's own process-wide cache pattern: a per-feed
# entry cache keyed by URL with a short TTL, guarded by a per-feed
# asyncio.Lock so concurrent callers during a cold/expired cache don't each
# trigger their own simultaneous refetch of the same feed.
_CACHE_TTL_SECONDS = 600  # refresh at most once per 10 minutes
_cache_entries: dict[str, list[dict]] = {}
_cache_fetched_at: dict[str, float] = {}
_cache_locks: dict[str, asyncio.Lock] = {feed_url: asyncio.Lock() for feed_url in FEED_URLS}


async def _fetch_feed(feed_url: str, client: httpx.AsyncClient) -> list[dict]:
    now = time.monotonic()
    if feed_url in _cache_entries and (now - _cache_fetched_at.get(feed_url, 0.0)) < _CACHE_TTL_SECONDS:
        return _cache_entries[feed_url]

    lock = _cache_locks.setdefault(feed_url, asyncio.Lock())
    async with lock:
        # Re-check after acquiring the lock -- another task may have just
        # refreshed this feed while we were waiting, in which case we
        # should not refetch again.
        now = time.monotonic()
        if feed_url in _cache_entries and (now - _cache_fetched_at.get(feed_url, 0.0)) < _CACHE_TTL_SECONDS:
            return _cache_entries[feed_url]

        settings = get_settings()
        try:
            response = await client.get(
                feed_url,
                headers={"User-Agent": settings.crawler_user_agent},
                timeout=settings.crawler_request_timeout_seconds,
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
        except Exception:  # noqa: BLE001 -- one bad feed should never break the rest
            logger.info("Failed to fetch/parse RSS feed %s", feed_url, exc_info=True)
            return _cache_entries.get(feed_url, [])

        entries = []
        for entry in parsed.entries:
            entries.append(
                {
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "snippet": entry.get("summary", "") or entry.get("description", ""),
                    "published_at": entry.get("published") or entry.get("updated"),
                    "source": "rss_news",
                }
            )

        _cache_entries[feed_url] = entries
        _cache_fetched_at[feed_url] = time.monotonic()
        return entries


async def search(query: str, client: httpx.AsyncClient, limit: int) -> list[dict]:
    """Fetch all configured feeds concurrently, keyword-filter by `query`, cap at `limit`."""
    fetches = await asyncio.gather(
        *(_fetch_feed(feed_url, client) for feed_url in FEED_URLS), return_exceptions=True
    )

    needle = query.lower()
    matches: list[dict] = []
    for result in fetches:
        if isinstance(result, Exception):
            continue
        for entry in result:
            haystack = f"{entry.get('title', '')} {entry.get('snippet', '')}".lower()
            if needle in haystack:
                matches.append(entry)

    return matches[:limit]
