"""Lightweight in-process rate limiter for crawler sources.

Distinct-IOC lookups fan out to GitHub/Reddit/pastebin on every call (unlike
provider connectors, which get a Redis cache keyed by IOC), so without this a
burst of investigations can exceed GitHub's unauthenticated 10 req/min search
cap within seconds. This is process-local (not Redis-backed like
app/core/cache.py's RateLimiter) since the crawler already runs inside a
single backend process per replica -- correctness only requires bounding this
process's own outbound request rate, not a global cross-replica limit.
"""
from __future__ import annotations

import asyncio
import time


class AsyncMinIntervalLimiter:
    """Serializes callers so no two proceed less than `min_interval_seconds`
    apart -- a simple, dependency-free token-bucket-of-one."""

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_call_at: float = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call_at
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call_at = time.monotonic()


# GitHub Search API: 10 req/min unauthenticated (30 req/min with a token) --
# spacing calls 6s apart keeps two calls (repo + code search) per crawl
# comfortably under that even for back-to-back distinct-IOC lookups.
github_limiter = AsyncMinIntervalLimiter(min_interval_seconds=6.0)

# Reddit's public JSON search endpoint has no single documented number, but
# community-observed practice is roughly 1 req/sec sustained for anonymous
# clients before 429s start -- 1.1s is a small safety margin.
reddit_limiter = AsyncMinIntervalLimiter(min_interval_seconds=1.1)
