"""Best-effort paste-dump search against psbdmp.ws.

Pastebin's own search requires a paid API, so this queries psbdmp.ws's
public dump-search API (https://psbdmp.ws/api/v3/search/{query}), which
indexes historical Pastebin dumps and requires no authentication. This
third-party service is unofficial, has no uptime/rate-limit guarantees, and
its response shape has been observed to vary -- so every failure mode
(network error, non-200, unexpected JSON shape, missing fields) is caught
here and simply yields an empty result list. This function must never raise.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SEARCH_URL_TEMPLATE = "https://psbdmp.ws/api/v3/search/{query}"


async def search(query: str, client: httpx.AsyncClient, limit: int) -> list[dict]:
    """Best-effort search of historical paste dumps mentioning `query`, capped at `limit`."""
    settings = get_settings()
    try:
        response = await client.get(
            _SEARCH_URL_TEMPLATE.format(query=query),
            headers={"User-Agent": settings.crawler_user_agent},
            timeout=settings.crawler_request_timeout_seconds,
        )
        if response.status_code != 200:
            logger.info("psbdmp search returned HTTP %s for query %r", response.status_code, query)
            return []
        payload = response.json()
    except Exception:  # noqa: BLE001 -- best-effort/unreliable source, never raise
        logger.info("psbdmp search failed for query %r", query, exc_info=True)
        return []

    results: list[dict] = []
    try:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not data:
            return []
        for item in data[:limit]:
            dump_id = item.get("id") if isinstance(item, dict) else None
            if not dump_id:
                continue
            results.append(
                {
                    "title": f"Pastebin dump {dump_id}",
                    "url": f"https://pastebin.com/{dump_id}",
                    "snippet": (item.get("text") or item.get("tags") or "")[:500]
                    if isinstance(item.get("text") or item.get("tags"), str)
                    else "",
                    "published_at": item.get("time") or item.get("date"),
                    "source": "pastebin_search",
                }
            )
    except Exception:  # noqa: BLE001 -- unexpected/undocumented shape from a best-effort source
        logger.info("psbdmp response parsing failed for query %r", query, exc_info=True)
        return []

    return results
