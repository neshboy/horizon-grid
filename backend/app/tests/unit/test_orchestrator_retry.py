"""Regression coverage for a real dead-retry-code bug found during a
mission-critical-readiness review: app/providers/orchestrator.py's
_run_with_policy() wraps provider.run() in a tenacity retry loop targeting
httpx.ConnectError/ReadTimeout/PoolTimeout, but BaseProvider.run() used to
catch those same exception types in its own generic `except Exception`
before they could ever reach the retry wrapper -- so provider_max_retries
had no real effect for any provider that didn't implement its own network
error handling. Confirmed live before the fix (see app/providers/base.py's
own comment) that fetch() was invoked exactly once despite
provider_max_retries=2. These tests exercise the real orchestrator function
end-to-end (not just base.py in isolation) against a fake provider that
fails a controllable number of times.
"""
import httpx
import pytest

from app.core.config import get_settings
from app.ioc.types import IOCType
from app.providers import orchestrator as orchestrator_module
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class _FlakyProvider(BaseProvider):
    provider_id = "flaky-retry-test"
    provider_name = "Flaky Retry Test Provider"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.IPV4}
    requires_key = False
    configured = True

    def __init__(self, fail_times: int, exc_cls: type[Exception] = httpx.ConnectError) -> None:
        super().__init__()
        self._fail_times = fail_times
        self._exc_cls = exc_cls
        self.call_count = 0

    async def fetch(self, ioc_value, ioc_type, client):
        self.call_count += 1
        if self.call_count <= self._fail_times:
            request = httpx.Request("GET", "https://example.test")
            raise self._exc_cls("connection refused", request=request)
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
        )


@pytest.fixture(autouse=True)
def _no_real_cache(monkeypatch):
    # _run_with_policy checks the Redis cache before ever calling
    # provider.run() -- stubbed out so this test exercises only the
    # retry/timeout policy, with no real Redis dependency.
    async def _get_cached_result(*args, **kwargs):
        return None

    async def _set_cached_result(*args, **kwargs):
        return None

    monkeypatch.setattr(orchestrator_module, "get_cached_result", _get_cached_result)
    monkeypatch.setattr(orchestrator_module, "set_cached_result", _set_cached_result)


@pytest.fixture
def client():
    return httpx.AsyncClient()


@pytest.mark.asyncio
async def test_a_transient_connect_error_is_retried_and_can_still_succeed(client):
    provider = _FlakyProvider(fail_times=1)  # fails once, then succeeds
    result = await orchestrator_module._run_with_policy(provider, "1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.OK
    assert provider.call_count == 2, "must have retried after the first ConnectError instead of giving up immediately"


@pytest.mark.asyncio
async def test_exhausting_every_retry_degrades_cleanly_to_error_not_a_crash(client):
    settings = get_settings()
    provider = _FlakyProvider(fail_times=99)  # never succeeds
    result = await orchestrator_module._run_with_policy(provider, "1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.ERROR
    assert "Connection error after retries" in result.error_message
    assert provider.call_count == settings.provider_max_retries + 1


@pytest.mark.asyncio
async def test_a_connect_timeout_is_retried_and_can_still_succeed(client):
    """Regression test for a real bug: RETRYABLE_EXCEPTIONS in
    app/providers/base.py omitted httpx.ConnectTimeout (and its sibling
    httpx.WriteTimeout), even though it is the exact exception httpx raises
    when a connection attempt itself times out (e.g. against an unreachable
    host) -- confirmed live against 192.0.2.1 (RFC 5737 TEST-NET-1).
    Before the fix, BaseProvider.run()'s generic `except Exception` caught
    ConnectTimeout before the orchestrator's tenacity retry loop ever saw
    it, so fetch() was invoked exactly once instead of being retried up to
    provider_max_retries times. This mirrors
    test_a_transient_connect_error_is_retried_and_can_still_succeed above,
    but for httpx.ConnectTimeout specifically."""
    provider = _FlakyProvider(fail_times=1, exc_cls=httpx.ConnectTimeout)  # fails once, then succeeds
    result = await orchestrator_module._run_with_policy(provider, "1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.OK
    assert provider.call_count == 2, "must have retried after the first ConnectTimeout instead of giving up immediately"
