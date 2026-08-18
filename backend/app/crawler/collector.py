"""Internet Intelligence Collector -- the OSINT crawler provider.

Wraps the four crawler sources (GitHub, Reddit, RSS security news, and
best-effort paste-dump search) behind the standard BaseProvider contract so
it flows through the same orchestrator (app/providers/orchestrator.py),
cache, and API surface as every other connector -- the correlation engine
and API layer never need to know this provider crawls the open internet
instead of calling a single vendor API.

Every source module exposes `async def search(query, client, limit) ->
list[dict]` returning {"title", "url", "snippet", "published_at", "source"}
dicts. `fetch()` runs all four concurrently, tolerates individual source
failures, dedupes by URL, and caps the merged result set -- this is the
"crawl the relevant content, extract useful intelligence, and provide the
original source links" requirement: every finding keeps its source url so
nothing is presented without attribution.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.config import get_settings
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus
from app.crawler.sources import github, reddit, rss_news, pastebin_search
from app.crawler.sources.errors import SourceRateLimitedError

logger = logging.getLogger(__name__)

# IOC types that plausibly turn up meaningful hits when searched against
# news/blogs/GitHub/Reddit/paste dumps -- raw network atoms like ja3 hashes or
# mutexes are excluded since free-text search on them is nearly always noise.
_SUPPORTED_TYPES = {
    IOCType.DOMAIN,
    IOCType.IPV4,
    IOCType.MALWARE_FAMILY,
    IOCType.THREAT_ACTOR,
    IOCType.CAMPAIGN,
    IOCType.CVE,
    IOCType.FILE_NAME,
}

_SOURCE_MODULES = (github, reddit, rss_news, pastebin_search)


class InternetIntelligenceCollector(BaseProvider):
    provider_id = "internet_intelligence"
    provider_name = "Internet Intelligence Collector"
    category = ProviderCategory.OSINT
    supported_types = _SUPPORTED_TYPES
    requires_key = False  # every underlying source is unauthenticated / best-effort
    base_url = ""

    def __init__(self) -> None:
        super().__init__()
        self.configured = True

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        per_source_limit = settings.crawler_max_results_per_source

        tasks = [module.search(ioc_value, client, per_source_limit) for module in _SOURCE_MODULES]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        source_count: dict[str, int] = {}
        merged: list[dict] = []
        seen_urls: set[str] = set()
        rate_limited_sources: list[str] = []

        for module, outcome in zip(_SOURCE_MODULES, raw_results):
            source_name = module.__name__.rsplit(".", 1)[-1]
            if isinstance(outcome, SourceRateLimitedError):
                logger.warning("Crawler source %s rate-limited for query %r: %s", source_name, ioc_value, outcome)
                rate_limited_sources.append(source_name)
                source_count[source_name] = 0
                continue
            if isinstance(outcome, Exception):
                logger.warning("Crawler source %s failed for query %r: %s", source_name, ioc_value, outcome)
                source_count[source_name] = 0
                continue
            count = 0
            for finding in outcome:
                url = (finding or {}).get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                merged.append(
                    {
                        "title": finding.get("title", ""),
                        "url": url,
                        "snippet": finding.get("snippet", ""),
                        "published_at": finding.get("published_at"),
                        "source": finding.get("source", source_name),
                    }
                )
                count += 1
            source_count[source_name] = count

        max_total = settings.crawler_max_results_per_source * len(_SOURCE_MODULES)
        merged = merged[:max_total]

        data = {
            "osint_findings": merged,
            "source_count": source_count,
            "total_findings": len(merged),
            "rate_limited_sources": rate_limited_sources,
        }

        if merged:
            status = ProviderStatus.OK
        elif rate_limited_sources:
            # All sources that returned nothing were rate-limited, not genuinely
            # empty -- don't report this as "no findings" (looks like a clean IOC).
            status = ProviderStatus.RATE_LIMITED
        else:
            status = ProviderStatus.NO_DATA
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=status,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            error_message=(
                f"Rate-limited by: {', '.join(rate_limited_sources)}"
                if status == ProviderStatus.RATE_LIMITED
                else None
            ),
            source_url=merged[0]["url"] if merged else None,
        )


internet_intelligence_provider = InternetIntelligenceCollector()
