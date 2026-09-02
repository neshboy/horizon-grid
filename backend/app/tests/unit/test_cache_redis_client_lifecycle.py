"""Regression test for app.core.cache.get_redis()'s event-loop-bound
client caching -- found live during overnight QA: running
test_auth_login_rate_limit.py immediately before test_auth_registration.py
(both use Redis-backed rate limiting) consistently crashed the second
file's test with "RuntimeError: Event loop is closed", because the cached
client was created under the first test's now-closed event loop and never
recreated for the new one.
"""
import asyncio

import app.core.cache as cache_module


def test_get_redis_recreates_client_when_the_event_loop_has_changed(monkeypatch):
    created_for_loop = []

    class _FakeLoop:
        pass

    class _FakeRedis:
        pass

    def _fake_from_url(*args, **kwargs):
        return _FakeRedis()

    monkeypatch.setattr(cache_module.aioredis, "from_url", _fake_from_url)

    loop_a = _FakeLoop()
    loop_b = _FakeLoop()
    loops = iter([loop_a, loop_a, loop_b])
    monkeypatch.setattr(asyncio, "get_event_loop", lambda: next(loops))

    cache_module._pool = None
    cache_module._pool_loop = None

    client_1 = cache_module.get_redis()
    client_2 = cache_module.get_redis()
    assert client_1 is client_2  # same loop (loop_a twice) -- must reuse, not recreate

    client_3 = cache_module.get_redis()
    assert client_3 is not client_1  # loop changed (loop_b) -- must recreate, not reuse a dead client
