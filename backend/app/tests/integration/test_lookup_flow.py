"""Docker-compose-backed integration test for the provider fan-out pipeline.

Exercises app.providers.orchestrator.run_all_providers /
run_all_providers_collected end-to-end against fake BaseProvider subclasses
(NOT the real provider connectors, which are being built concurrently by
other agents and may not exist/import cleanly yet -- see
app/providers/registry.py). We register our fakes via the `providers=`
override parameter both functions accept, so the real registry (and the
real network-hitting connectors it wires up) is never imported or touched.

httpx provider calls are mocked with respx so nothing here hits a real
external API. The only real infrastructure dependency is Redis, started via
the repo's docker-compose.yml (`docker compose up -d redis`), because
run_all_providers's cache-check/populate path is part of what we want to
exercise for real; if Redis isn't reachable the whole module is skipped.
"""
import asyncio
import os
import time

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
import respx

from app.core.config import get_settings
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus
from app.providers.orchestrator import run_all_providers, run_all_providers_collected

REDIS_HOST = "localhost"
REDIS_PORT = 6379


def _redis_reachable() -> bool:
    """Best-effort real TCP probe -- distinct from app.core.cache, which lazily
    opens its connection on first use and would not fail fast here."""
    import socket

    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(),
    reason=f"Redis not reachable at {REDIS_HOST}:{REDIS_PORT} -- run `docker compose up -d redis` first.",
)


# --------------------------------------------------------------------------
# Fake providers (in-test only -- deliberately do not import anything from
# app/providers/{virustotal,otx,...}.py or app/providers/registry.py).
# --------------------------------------------------------------------------


class SlowFakeProvider(BaseProvider):
    """Simulates network latency via asyncio.sleep(); still performs (a mocked)
    httpx call so respx has something to intercept and this stays representative
    of a real connector's fetch()."""

    provider_id = "fake_slow"
    provider_name = "Fake Slow Provider"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.IPV4, IOCType.DOMAIN}
    requires_key = False
    configured = True
    base_url = "https://fake-slow.example.test"
    delay_seconds = 0.6

    async def fetch(
        self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient
    ) -> ProviderResult:
        await asyncio.sleep(self.delay_seconds)
        response = await client.get(f"{self.base_url}/lookup/{ioc_value}")
        response.raise_for_status()
        payload = response.json()
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=payload,
            source_url=f"{self.base_url}/lookup/{ioc_value}",
        )


class FastFakeProvider(BaseProvider):
    provider_id = "fake_fast"
    provider_name = "Fake Fast Provider"
    category = ProviderCategory.OSINT
    supported_types = {IOCType.IPV4, IOCType.DOMAIN}
    requires_key = False
    configured = True
    base_url = "https://fake-fast.example.test"
    delay_seconds = 0.1

    async def fetch(
        self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient
    ) -> ProviderResult:
        await asyncio.sleep(self.delay_seconds)
        response = await client.get(f"{self.base_url}/lookup/{ioc_value}")
        response.raise_for_status()
        payload = response.json()
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=payload,
            source_url=f"{self.base_url}/lookup/{ioc_value}",
        )


class MediumFakeProvider(BaseProvider):
    """A third independent OK-path fake, used only by the concurrency timing
    test so we can compare N equal-delay providers running in parallel
    against N * delay (sequential) with a wide, environment-robust margin --
    two providers with a small delay gap (e.g. 0.6s vs 0.1s) leaves too
    little room once fixed per-call overhead (this machine's
    httpx.AsyncClient() construction alone costs ~0.2s) is accounted for."""

    provider_id = "fake_medium"
    provider_name = "Fake Medium Provider"
    category = ProviderCategory.PASSIVE_DNS
    supported_types = {IOCType.IPV4, IOCType.DOMAIN}
    requires_key = False
    configured = True
    base_url = "https://fake-medium.example.test"
    delay_seconds = 0.4

    async def fetch(
        self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient
    ) -> ProviderResult:
        await asyncio.sleep(self.delay_seconds)
        response = await client.get(f"{self.base_url}/lookup/{ioc_value}")
        response.raise_for_status()
        payload = response.json()
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=payload,
            source_url=f"{self.base_url}/lookup/{ioc_value}",
        )


class ExplodingFakeProvider(BaseProvider):
    """Raises an unhandled exception inside fetch() -- BaseProvider.run() must
    normalize this into a ProviderStatus.ERROR result rather than letting it
    propagate and take down the other providers' tasks."""

    provider_id = "fake_exploding"
    provider_name = "Fake Exploding Provider"
    category = ProviderCategory.SANDBOX
    supported_types = {IOCType.IPV4, IOCType.DOMAIN}
    requires_key = False
    configured = True
    delay_seconds = 0.2

    async def fetch(
        self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient
    ) -> ProviderResult:
        await asyncio.sleep(self.delay_seconds)
        raise RuntimeError("simulated connector crash (e.g. malformed upstream response)")


def make_fakes(delay_slow: float = 0.6, delay_fast: float = 0.1, delay_exploding: float = 0.2):
    slow = SlowFakeProvider()
    slow.delay_seconds = delay_slow
    fast = FastFakeProvider()
    fast.delay_seconds = delay_fast
    exploding = ExplodingFakeProvider()
    exploding.delay_seconds = delay_exploding
    return slow, fast, exploding


IOC_VALUE = "203.0.113.42"
IOC_TYPE = IOCType.IPV4


def _mock_ok_routes(respx_mock: respx.MockRouter) -> None:
    """Registers routes for the two OK-path fakes used by most tests.
    (assert_all_called=True is used with this helper, so it must only mock
    routes that the providers actually passed into a given test will hit --
    see _mock_ok_routes_with_medium for tests that also dispatch
    MediumFakeProvider.)
    """
    respx_mock.get(f"https://fake-slow.example.test/lookup/{IOC_VALUE}").mock(
        return_value=httpx.Response(200, json={"verdict": "malicious", "source": "fake_slow"})
    )
    respx_mock.get(f"https://fake-fast.example.test/lookup/{IOC_VALUE}").mock(
        return_value=httpx.Response(200, json={"verdict": "clean", "source": "fake_fast"})
    )


def _mock_ok_routes_with_medium(respx_mock: respx.MockRouter) -> None:
    _mock_ok_routes(respx_mock)
    respx_mock.get(f"https://fake-medium.example.test/lookup/{IOC_VALUE}").mock(
        return_value=httpx.Response(200, json={"verdict": "suspicious", "source": "fake_medium"})
    )


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def _point_app_settings_at_host_redis():
    """app.core.config.Settings.redis_url defaults to redis://redis:6379/0 --
    the hostname used *inside* the docker-compose network. From this test
    process (running on the host, not in a container) that hostname doesn't
    resolve, so we override REDIS_URL to point at the port docker-compose
    publishes on localhost and invalidate the lru_cache'd Settings singleton
    so app.core.cache.get_redis() picks up the override on next use.
    """
    previous = os.environ.get("REDIS_URL")
    os.environ["REDIS_URL"] = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
    get_settings.cache_clear()
    yield
    if previous is None:
        os.environ.pop("REDIS_URL", None)
    else:
        os.environ["REDIS_URL"] = previous
    get_settings.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def clean_redis_cache():
    """Flush only the provider_cache:fake_* keys our fakes may have written,
    before and after each test, so tests are hermetic and order-independent
    even though they share the real Redis started by docker-compose.

    Also resets app.core.cache's module-global connection pool. That pool is
    created lazily and bound to whatever asyncio event loop was running when
    get_redis() was first called; since pytest-asyncio (in strict/function
    mode) gives each test function its own event loop, a pool created in one
    test would otherwise be reused -- against a now-closed loop -- by the
    next test, raising "RuntimeError: Event loop is closed" deep inside
    redis-py. Clearing it here forces a fresh client per test.
    """
    import app.core.cache as cache_module

    cache_module._pool = None

    client = aioredis.from_url(f"redis://{REDIS_HOST}:{REDIS_PORT}/0", decode_responses=True)

    async def _flush():
        keys = [k async for k in client.scan_iter(match="provider_cache:fake_*")]
        if keys:
            await client.delete(*keys)

    await _flush()
    yield
    await _flush()
    await client.aclose()
    cache_module._pool = None


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_providers_run_concurrently_not_sequentially():
    """Wall-clock time for the batch must track max(delay), not sum(delays).

    Three providers each sleeping ~0.35s in fetch(): run sequentially that's
    >=1.05s; run concurrently (as run_all_providers_collected's
    asyncio.create_task fan-out does) it should stay close to a single
    provider's delay (~0.35s) plus fixed overhead (e.g. constructing the
    shared httpx.AsyncClient once). Using three *equal* delays rather than
    one slow + one fast provider gives a much wider, environment-robust gap
    between the "sequential" and "concurrent" expectations than trying to
    tune the margin against fixed per-call overhead.
    """
    delay = 0.35
    slow = SlowFakeProvider()
    slow.delay_seconds = delay
    fast = FastFakeProvider()
    fast.delay_seconds = delay
    medium = MediumFakeProvider()
    medium.delay_seconds = delay

    with respx.mock(assert_all_called=True) as respx_mock:
        _mock_ok_routes_with_medium(respx_mock)

        start = time.monotonic()
        results = await run_all_providers_collected(
            IOC_VALUE, IOC_TYPE, providers=[slow, fast, medium]
        )
        elapsed = time.monotonic() - start

    assert len(results) == 3
    by_id = {r.provider_id: r for r in results}
    assert by_id["fake_slow"].status == ProviderStatus.OK
    assert by_id["fake_fast"].status == ProviderStatus.OK
    assert by_id["fake_medium"].status == ProviderStatus.OK

    num_providers = 3
    sequential_floor = num_providers * delay  # 1.05s if run one-after-another
    # Concurrent execution should land near one delay, not scale with the
    # provider count. Generous upper bound absorbs client-construction /
    # scheduler overhead without masking a regression to sequential execution.
    assert elapsed < sequential_floor - 0.2, (
        f"elapsed={elapsed:.3f}s scales with provider count (sequential floor "
        f"is {sequential_floor:.2f}s); providers are not running concurrently"
    )
    assert elapsed < delay + 0.5, (
        f"elapsed={elapsed:.3f}s is far beyond a single provider's delay "
        f"({delay}s); unexpected extra overhead"
    )


@pytest.mark.asyncio
async def test_partial_failure_does_not_block_other_providers():
    """A provider whose fetch() raises must surface as a normalized ERROR
    result (per BaseProvider.run()'s except-and-normalize behaviour) without
    preventing sibling providers from completing successfully."""
    slow, fast, exploding = make_fakes(delay_slow=0.3, delay_fast=0.05, delay_exploding=0.1)

    with respx.mock(assert_all_called=True) as respx_mock:
        _mock_ok_routes(respx_mock)

        results = await run_all_providers_collected(
            IOC_VALUE, IOC_TYPE, providers=[slow, fast, exploding]
        )

    assert len(results) == 3
    by_id = {r.provider_id: r for r in results}

    assert by_id["fake_slow"].status == ProviderStatus.OK
    assert by_id["fake_fast"].status == ProviderStatus.OK

    exploded = by_id["fake_exploding"]
    assert exploded.status == ProviderStatus.ERROR
    assert exploded.error_message is not None
    assert "simulated connector crash" in exploded.error_message


@pytest.mark.asyncio
async def test_streaming_variant_yields_as_completed_and_isolates_failure():
    """run_all_providers (the async-generator streaming variant used by the
    SSE lookup endpoint) must also yield every provider's result -- including
    the normalized error from the crashing provider -- without one provider's
    failure aborting the generator early."""
    slow, fast, exploding = make_fakes(delay_slow=0.3, delay_fast=0.05, delay_exploding=0.1)

    seen_ids = []
    with respx.mock(assert_all_called=True) as respx_mock:
        _mock_ok_routes(respx_mock)

        async for result in run_all_providers(IOC_VALUE, IOC_TYPE, providers=[slow, fast, exploding]):
            seen_ids.append(result.provider_id)

    assert set(seen_ids) == {"fake_slow", "fake_fast", "fake_exploding"}


@pytest.mark.asyncio
async def test_second_lookup_is_served_from_cache_and_skips_http_call():
    """First run populates the Redis cache (real Redis via docker-compose,
    exercising app.core.cache.get_cached_result/set_cached_result for real
    rather than mocking them away); the second run for the identical
    (provider_id, ioc_type, ioc_value) key must short-circuit on the cache hit
    and never re-issue the HTTP call -- enforced by respx only mocking the
    route once and asserting it was called exactly once across both runs.
    """
    fast = FastFakeProvider()
    fast.delay_seconds = 0.05

    with respx.mock(assert_all_called=True) as respx_mock:
        route = respx_mock.get(f"https://fake-fast.example.test/lookup/{IOC_VALUE}").mock(
            return_value=httpx.Response(200, json={"verdict": "clean", "source": "fake_fast"})
        )

        first = await run_all_providers_collected(IOC_VALUE, IOC_TYPE, providers=[fast])
        assert route.call_count == 1
        assert first[0].status == ProviderStatus.OK
        assert first[0].from_cache is False

        second = await run_all_providers_collected(IOC_VALUE, IOC_TYPE, providers=[fast])
        assert route.call_count == 1, "cached lookup must not re-issue the HTTP call"
        assert second[0].status == ProviderStatus.OK
        assert second[0].from_cache is True
        assert second[0].data == first[0].data
        # Regression: cache rehydration must restore enum fields, not leave them
        # as the raw strings ProviderResult.to_dict() serialized -- a live bug
        # where `.category` stayed a str crashed the API layer's `.category.value`.
        assert second[0].category == ProviderCategory.OSINT
        assert isinstance(second[0].category, ProviderCategory)
        assert second[0].ioc_type == IOC_TYPE
        assert isinstance(second[0].ioc_type, IOCType)
        assert second[0].status == first[0].status
        assert isinstance(second[0].status, ProviderStatus)


@pytest.mark.asyncio
async def test_unsupported_ioc_type_is_filtered_before_dispatch():
    """A provider that doesn't support the requested ioc_type must be excluded
    entirely from dispatch (per run_all_providers's docstring) rather than
    appear in the results as UNSUPPORTED_IOC."""

    class DomainOnlyProvider(BaseProvider):
        provider_id = "fake_domain_only"
        provider_name = "Fake Domain-Only Provider"
        category = ProviderCategory.WHOIS
        supported_types = {IOCType.DOMAIN}
        requires_key = False
        configured = True

        async def fetch(self, ioc_value, ioc_type, client):
            raise AssertionError("fetch() must never be called for an unsupported ioc_type")

    results = await run_all_providers_collected(IOC_VALUE, IOC_TYPE, providers=[DomainOnlyProvider()])
    assert results == []


@pytest.mark.asyncio
async def test_not_configured_provider_short_circuits_without_http_call():
    """requires_key=True + configured=False must produce a NOT_CONFIGURED
    result without ever reaching fetch() / issuing an HTTP call."""

    class UnconfiguredProvider(BaseProvider):
        provider_id = "fake_unconfigured"
        provider_name = "Fake Unconfigured Provider"
        category = ProviderCategory.THREAT_INTEL
        supported_types = {IOCType.IPV4}
        requires_key = True
        configured = False

        async def fetch(self, ioc_value, ioc_type, client):
            raise AssertionError("fetch() must never be called when not configured")

    with respx.mock(assert_all_called=False) as respx_mock:
        results = await run_all_providers_collected(
            IOC_VALUE, IOC_TYPE, providers=[UnconfiguredProvider()]
        )
        assert respx_mock.calls.call_count == 0

    assert len(results) == 1
    assert results[0].status == ProviderStatus.NOT_CONFIGURED
