"""GitHub code + repository search via the public GitHub Search API.

Uses the unauthenticated GitHub REST search endpoints
(https://api.github.com/search/repositories and /search/code), which is
sufficient for the low query volume this scaffold generates. Unauthenticated
requests are capped at 10 req/min for the Search API; setting a `GITHUB_TOKEN`
environment variable (optional, not required) is picked up automatically and
raises that ceiling to 30 req/min -- it is intentionally NOT added to
app/core/config.py since the platform must work fully without it.
"""
from __future__ import annotations

import logging
import os

import httpx

from app.core.config import get_settings
from app.crawler.sources.errors import SourceRateLimitedError
from app.crawler.sources.rate_limit import github_limiter

logger = logging.getLogger(__name__)

_REPO_SEARCH_URL = "https://api.github.com/search/repositories"
_CODE_SEARCH_URL = "https://api.github.com/search/code"


def _headers() -> dict[str, str]:
    settings = get_settings()
    headers = {
        "Accept": "application/vnd.github.text-match+json",
        "User-Agent": settings.crawler_user_agent,
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _search_repositories(query: str, client: httpx.AsyncClient, limit: int) -> list[dict]:
    try:
        await github_limiter.wait()
        response = await client.get(
            _REPO_SEARCH_URL,
            params={"q": query, "per_page": limit, "sort": "updated"},
            headers=_headers(),
            timeout=get_settings().crawler_request_timeout_seconds,
        )
        if response.status_code in (403, 429):
            # GitHub's Search API uses 403 for rate limiting, not just auth failure.
            logger.info("GitHub repo search rate-limited (HTTP %s) for query %r", response.status_code, query)
            raise SourceRateLimitedError("github", response.status_code)
        if response.status_code != 200:
            logger.info("GitHub repo search returned HTTP %s for query %r", response.status_code, query)
            return []
        items = response.json().get("items", [])
    except SourceRateLimitedError:
        raise
    except Exception:  # noqa: BLE001 -- best-effort source, never raise (except rate-limit, see above)
        logger.exception("GitHub repository search failed for query %r", query)
        return []

    results = []
    for item in items[:limit]:
        results.append(
            {
                "title": item.get("full_name") or item.get("name") or "GitHub repository",
                "url": item.get("html_url", ""),
                "snippet": item.get("description") or "",
                "published_at": item.get("pushed_at") or item.get("updated_at"),
                "source": "github",
            }
        )
    return results


async def _search_code(query: str, client: httpx.AsyncClient, limit: int) -> list[dict]:
    try:
        await github_limiter.wait()
        response = await client.get(
            _CODE_SEARCH_URL,
            params={"q": query, "per_page": limit},
            headers=_headers(),
            timeout=get_settings().crawler_request_timeout_seconds,
        )
        if response.status_code in (403, 429):
            logger.info("GitHub code search rate-limited (HTTP %s) for query %r", response.status_code, query)
            raise SourceRateLimitedError("github", response.status_code)
        if response.status_code != 200:
            logger.info("GitHub code search returned HTTP %s for query %r", response.status_code, query)
            return []
        items = response.json().get("items", [])
    except SourceRateLimitedError:
        raise
    except Exception:  # noqa: BLE001 -- best-effort source, never raise (except rate-limit, see above)
        logger.exception("GitHub code search failed for query %r", query)
        return []

    results = []
    for item in items[:limit]:
        repo_name = (item.get("repository") or {}).get("full_name", "")
        snippet = ""
        text_matches = item.get("text_matches") or []
        if text_matches:
            snippet = text_matches[0].get("fragment", "")
        results.append(
            {
                "title": f"{repo_name}/{item.get('path', '')}".strip("/") or item.get("name", "GitHub code result"),
                "url": item.get("html_url", ""),
                "snippet": snippet or item.get("path", ""),
                # GitHub's code search API does not surface a commit/push date on the item itself.
                "published_at": None,
                "source": "github",
            }
        )
    return results


async def search(query: str, client: httpx.AsyncClient, limit: int) -> list[dict]:
    """Search GitHub repositories and code for `query`, merged and capped at `limit`."""
    repo_results = await _search_repositories(query, client, limit)
    code_results = await _search_code(query, client, limit)
    combined = repo_results + code_results
    return combined[:limit]
