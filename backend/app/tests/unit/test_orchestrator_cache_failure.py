"""Regression coverage for a real bug found during a mission-critical-
readiness review: app/providers/orchestrator.py's _run_with_policy() called
get_cached_result() (the Redis cache read) and set_cached_result() (the
Redis cache write) with no exception handling of their own. A transient
Redis failure on either call raised out of the per-provider asyncio.Task,
was swallowed by run_all_providers()'s outer `except Exception:
logger.exception(...)`, and the provider vanished from the investigation
entirely -- no ProviderResult at all, not even ERROR/TIMEOUT. Because the
write-side check runs AFTER a fully successful fetch, this could discard an
already-completed, genuinely malicious verdict purely because Redis
hiccuped on the write.

Confirmed live before the fix: monkeypatching get_cached_result/
set_cached_result to raise (simulating a Redis blip) made
run_all_providers() yield zero results for a provider whose fetch()
returned a real ProviderStatus.OK verdict.
"""
import httpx
import pytest

from app.ioc.types import IOCType
from app.providers import orchestrator as orchestrator_module
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class _GoodProvider(BaseProvider):
    """A provider whose fetch() always succeeds with a real verdict --
    stands in for the "already-completed, genuinely malicious verdict"
    from the live reproduction."""

    provider_id = "cache-blip-test-provider"
    provider_name = "Cache Blip Test Provider"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.IPV4}
    requires_key = False
    configured = True

    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    async def fetch(self, ioc_value, ioc_type, client):
        self.call_count += 1
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data={"ok": True, "verdict": "malicious"},
        )


@pytest.fixture
def client():
    return httpx.AsyncClient()


@pytest.mark.asyncio
async def test_redis_failure_on_cache_read_falls_back_to_a_live_fetch_instead_of_crashing(client, monkeypatch):
    async def _broken_get_cached_result(*args, **kwargs):
        raise ConnectionError("redis down on READ (simulated)")

    monkeypatch.setattr(orchestrator_module, "get_cached_result", _broken_get_cached_result)

    async def _noop_set_cached_result(*args, **kwargs):
        return None

    monkeypatch.setattr(orchestrator_module, "set_cached_result", _noop_set_cached_result)

    provider = _GoodProvider()
    # Before the fix: the ConnectionError from get_cached_result propagated
    # straight out of _run_with_policy, so this await would raise instead of
    # returning a result.
    result = await orchestrator_module._run_with_policy(provider, "1.2.3.4", IOCType.IPV4, client)

    assert result.status == ProviderStatus.OK
    assert result.data == {"ok": True, "verdict": "malicious"}
    assert provider.call_count == 1, "a broken cache read must fall back to a live fetch, not skip it"


@pytest.mark.asyncio
async def test_redis_failure_on_cache_write_does_not_discard_the_already_fetched_result(client, monkeypatch):
    async def _get_cached_result(*args, **kwargs):
        return None

    monkeypatch.setattr(orchestrator_module, "get_cached_result", _get_cached_result)

    async def _broken_set_cached_result(*args, **kwargs):
        raise ConnectionError("redis down on WRITE (simulated)")

    monkeypatch.setattr(orchestrator_module, "set_cached_result", _broken_set_cached_result)

    provider = _GoodProvider()
    # Before the fix: the ConnectionError from set_cached_result propagated
    # out of _run_with_policy AFTER the fetch had already succeeded,
    # discarding the malicious verdict entirely instead of returning it.
    result = await orchestrator_module._run_with_policy(provider, "1.2.3.4", IOCType.IPV4, client)

    assert result.status == ProviderStatus.OK
    assert result.data == {"ok": True, "verdict": "malicious"}


@pytest.mark.asyncio
async def test_run_all_providers_still_yields_the_result_when_the_cache_write_fails(monkeypatch):
    """End-to-end through the public generator: this is what the live
    reproduction actually exercised -- a Redis blip on the write side must
    not make the provider vanish from the investigation with zero results."""

    async def _get_cached_result(*args, **kwargs):
        return None

    monkeypatch.setattr(orchestrator_module, "get_cached_result", _get_cached_result)

    async def _broken_set_cached_result(*args, **kwargs):
        raise ConnectionError("redis down on WRITE (simulated)")

    monkeypatch.setattr(orchestrator_module, "set_cached_result", _broken_set_cached_result)

    from app.core import runtime_config as runtime_config_module

    async def _empty_snapshot():
        return {}

    monkeypatch.setattr(runtime_config_module, "get_ioc_provider_snapshot", _empty_snapshot)
    monkeypatch.setattr(orchestrator_module, "get_ioc_provider_snapshot", _empty_snapshot)

    provider = _GoodProvider()
    results = await orchestrator_module.run_all_providers_collected("1.2.3.4", IOCType.IPV4, [provider])

    assert len(results) == 1, "the provider must not silently disappear from the investigation"
    assert results[0].status == ProviderStatus.OK
    assert results[0].data == {"ok": True, "verdict": "malicious"}
