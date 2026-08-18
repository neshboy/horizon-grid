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


async def _fetch_feed(feed_url: str, client: httpx.AsyncClient) -> list[dict]:
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
        return []

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
