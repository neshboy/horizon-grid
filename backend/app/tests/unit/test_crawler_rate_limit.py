"""Unit tests for app.crawler.sources.rate_limit.AsyncMinIntervalLimiter."""
import asyncio
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
    limiter = AsyncMinIntervalLimiter(min_interval_seconds=0.05)
    await limiter.wait()
    await asyncio.sleep(0.1)
    start = time.monotonic()
    await limiter.wait()
    assert time.monotonic() - start < 0.03


@pytest.mark.asyncio
async def test_concurrent_callers_are_still_spaced_by_min_interval():
    """The docstring promises this limiter serializes callers so no two ever
    proceed less than min_interval_seconds apart. The other tests here only
    ever await sequentially in a single coroutine, which never contends the
    internal lock, so they'd stay green even if the lock were dropped
    entirely. Fire several real concurrent callers to prove the lock (which
    is held across the sleep) actually queues contenders rather than letting
    them race through together."""
    limiter = AsyncMinIntervalLimiter(min_interval_seconds=0.1)
    call_times: list[float] = []

    async def call() -> None:
        await limiter.wait()
        call_times.append(time.monotonic())

    await asyncio.gather(call(), call(), call())

    call_times.sort()
    gaps = [later - earlier for earlier, later in zip(call_times, call_times[1:])]
    assert len(gaps) == 2
    assert all(gap >= 0.08 for gap in gaps)
