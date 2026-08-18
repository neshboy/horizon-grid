"""Unit tests for app.crawler.sources.rate_limit.AsyncMinIntervalLimiter."""
import time

import pytest

from app.crawler.sources.rate_limit import AsyncMinIntervalLimiter


@pytest.mark.asyncio
async def test_first_call_does_not_wait():
    limiter = AsyncMinIntervalLimiter(min_interval_seconds=0.2)
    start = time.monotonic()
    await limiter.wait()
    assert time.monotonic() - start < 0.05


@pytest.mark.asyncio
async def test_second_call_waits_out_the_remaining_interval():
    limiter = AsyncMinIntervalLimiter(min_interval_seconds=0.15)
    await limiter.wait()
    start = time.monotonic()
    await limiter.wait()
    assert time.monotonic() - start >= 0.1


@pytest.mark.asyncio
async def test_call_after_interval_has_elapsed_does_not_wait():
    import asyncio

    limiter = AsyncMinIntervalLimiter(min_interval_seconds=0.05)
    await limiter.wait()
    await asyncio.sleep(0.1)
    start = time.monotonic()
    await limiter.wait()
    assert time.monotonic() - start < 0.03
