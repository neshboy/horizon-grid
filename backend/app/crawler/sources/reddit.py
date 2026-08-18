"""Reddit search via the public (unauthenticated) JSON search endpoint.

Reddit does not require OAuth for read-only access to `.json` endpoints, but
it aggressively blocks requests carrying a default/generic User-Agent (e.g.
python-requests) -- so every request here explicitly sets
`settings.crawler_user_agent` per Reddit's API rules. Best-effort: any
failure (network error, unexpected payload shape, rate limiting) is caught
and results in an empty list rather than propagating.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings
from app.crawler.sources.errors import SourceRateLimitedError
from app.crawler.sources.rate_limit import reddit_limiter

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.reddit.com/search.json"


async def search(query: str, client: httpx.AsyncClient, limit: int) -> list[dict]:
    """Search Reddit posts for `query`, most relevant first, capped at `limit`."""
    settings = get_settings()
    headers = {"User-Agent": settings.crawler_user_agent}

    try:
        await reddit_limiter.wait()
        response = await client.get(
            _SEARCH_URL,
            params={"q": query, "sort": "relevance", "limit": limit},
            headers=headers,
            timeout=settings.crawler_request_timeout_seconds,
        )
        if response.status_code == 429:
            logger.info("Reddit search rate-limited (HTTP 429) for query %r", query)
            raise SourceRateLimitedError("reddit", response.status_code)
        if response.status_code != 200:
            logger.info("Reddit search returned HTTP %s for query %r", response.status_code, query)
            return []
        payload = response.json()
    except SourceRateLimitedError:
        raise
    except Exception:  # noqa: BLE001 -- best-effort source, never raise (except rate-limit, see above)
        logger.exception("Reddit search failed for query %r", query)
        return []

    results = []
    try:
        children = payload.get("data", {}).get("children", [])
        for child in children[:limit]:
            post = child.get("data", {})
            permalink = post.get("permalink", "")
            results.append(
                {
                    "title": post.get("title", "Reddit post"),
                    "url": f"https://www.reddit.com{permalink}" if permalink else post.get("url", ""),
                    "snippet": (post.get("selftext") or "")[:500],
                    "published_at": (
                        datetime.fromtimestamp(post["created_utc"], tz=timezone.utc).isoformat()
                        if post.get("created_utc")
                        else None
                    ),
                    "source": "reddit",
                }
            )
    except Exception:  # noqa: BLE001 -- malformed payload shouldn't break the collector
        logger.exception("Failed to parse Reddit search payload for query %r", query)
        return []

    return results
