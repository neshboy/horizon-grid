"""Tests for the BaseProvider contract: unsupported IOC types, missing
credentials, and error normalization -- every connector inherits this
behavior from app/providers/base.py, so it's tested once here rather than
duplicated per-connector.
"""
import httpx
import pytest

from app.ioc.types import IOCType
from app.providers.base import RETRYABLE_EXCEPTIONS, BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class _StubProvider(BaseProvider):
    provider_id = "stub"
    provider_name = "Stub Provider"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.IPV4}
    requires_key = True
    configured = True

    def __init__(self, fetch_impl=None, requires_key=True, configured=True):
        super().__init__()
        self.requires_key = requires_key
        self.configured = configured
        self._fetch_impl = fetch_impl

    async def fetch(self, ioc_value, ioc_type, client):
        if self._fetch_impl is not None:
            return await self._fetch_impl(ioc_value, ioc_type, client)
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
        )


@pytest.fixture
def client():
    return httpx.AsyncClient()


@pytest.mark.asyncio
async def test_unsupported_ioc_type_short_circuits(client):
    provider = _StubProvider()
    result = await provider.run("example.com", IOCType.DOMAIN, client)
    assert result.status == ProviderStatus.UNSUPPORTED_IOC
    assert result.latency_ms is not None
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_not_configured_short_circuits(client):
    provider = _StubProvider(requires_key=True, configured=False)
    result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.NOT_CONFIGURED
    assert "not configured" in result.error_message.lower()
    assert result.latency_ms is not None
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_requires_key_false_does_not_short_circuit(client):
    provider = _StubProvider(requires_key=False, configured=False)
    result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.OK


# --- Real P1 bug found live during overnight QA: `effective_configured`
# used to be `override.get("configured", self.configured) if override else
# self.configured` -- since run_all_providers() always supplies an override
# with a "configured" key once ANY runtime_config DB row exists for a
# provider (even a blank one, e.g. created by a Test-Connection click that
# never persists the tested value), that default was never actually
# reached: a provider with a perfectly valid .env credential
# (self.configured=True) got permanently short-circuited to NOT_CONFIGURED
# by an unrelated blank DB row. Confirmed live against the real app with
# otx/virustotal/abuseipdb. Fixed to OR the two together instead of letting
# the DB value always win. ---


@pytest.mark.asyncio
async def test_blank_db_override_falls_back_to_a_working_env_credential(client):
    from app.core.runtime_context import set_provider_overrides

    provider = _StubProvider(requires_key=True, configured=True)  # a real .env credential exists
    set_provider_overrides({"stub": {"enabled": True, "configured": False, "credentials": {}}})
    try:
        result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    finally:
        set_provider_overrides({})
    assert result.status == ProviderStatus.OK  # not short-circuited to NOT_CONFIGURED


@pytest.mark.asyncio
async def test_db_override_configured_true_still_works_with_no_env_credential(client):
    from app.core.runtime_context import set_provider_overrides

    provider = _StubProvider(requires_key=True, configured=False)  # no .env credential
    set_provider_overrides({"stub": {"enabled": True, "configured": True, "credentials": {"api_key": "x"}}})
    try:
        result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    finally:
        set_provider_overrides({})
    assert result.status == ProviderStatus.OK


@pytest.mark.asyncio
async def test_both_db_and_env_unconfigured_still_short_circuits(client):
    from app.core.runtime_context import set_provider_overrides

    provider = _StubProvider(requires_key=True, configured=False)
    set_provider_overrides({"stub": {"enabled": True, "configured": False, "credentials": {}}})
    try:
        result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    finally:
        set_provider_overrides({})
    assert result.status == ProviderStatus.NOT_CONFIGURED


@pytest.mark.asyncio
async def test_http_429_maps_to_rate_limited(client):
    async def fetch_impl(ioc_value, ioc_type, http_client):
        request = httpx.Request("GET", "https://example.test")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    provider = _StubProvider(fetch_impl=fetch_impl)
    result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.RATE_LIMITED
    assert "429" in result.error_message
    assert result.latency_ms is not None
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_http_403_maps_to_rate_limited(client):
    async def fetch_impl(ioc_value, ioc_type, http_client):
        request = httpx.Request("GET", "https://example.test")
        response = httpx.Response(403, request=request)
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    provider = _StubProvider(fetch_impl=fetch_impl)
    result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_http_509_maps_to_rate_limited(client):
    # PhishTank's documented over-limit response code.
    async def fetch_impl(ioc_value, ioc_type, http_client):
        request = httpx.Request("GET", "https://example.test")
        response = httpx.Response(509, request=request)
        raise httpx.HTTPStatusError("bandwidth limit exceeded", request=request, response=response)

    provider = _StubProvider(fetch_impl=fetch_impl)
    result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_http_500_maps_to_error(client):
    async def fetch_impl(ioc_value, ioc_type, http_client):
        request = httpx.Request("GET", "https://example.test")
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    provider = _StubProvider(fetch_impl=fetch_impl)
    result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.ERROR
    assert "500" in result.error_message


@pytest.mark.asyncio
async def test_generic_exception_maps_to_error_with_message_captured(client):
    async def fetch_impl(ioc_value, ioc_type, http_client):
        raise ValueError("boom, connector blew up")

    provider = _StubProvider(fetch_impl=fetch_impl)
    result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.ERROR
    assert result.error_message == "boom, connector blew up"


@pytest.mark.asyncio
async def test_successful_fetch_returns_ok_with_latency(client):
    provider = _StubProvider()
    result = await provider.run("1.2.3.4", IOCType.IPV4, client)
    assert result.status == ProviderStatus.OK
    assert result.latency_ms is not None
    assert result.latency_ms >= 0


@pytest.mark.parametrize(
    "exc_cls",
    [
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    ],
)
@pytest.mark.asyncio
async def test_retryable_exceptions_propagate_out_of_run_instead_of_being_normalized(client, exc_cls):
    """Real bug fixed: run() previously caught these in its own generic
    except Exception, silently normalizing them into ProviderStatus.ERROR
    BEFORE orchestrator.py's retry wrapper (which wraps run(), not fetch())
    ever saw them -- so provider_max_retries had no effect for any provider
    that didn't catch its own httpx errors. These must propagate as real
    exceptions out of run() so the orchestrator's tenacity loop can retry."""

    async def fetch_impl(ioc_value, ioc_type, http_client):
        request = httpx.Request("GET", "https://example.test")
        raise exc_cls("transient network failure", request=request)

    provider = _StubProvider(fetch_impl=fetch_impl)
    with pytest.raises(exc_cls):
        await provider.run("1.2.3.4", IOCType.IPV4, client)


@pytest.mark.asyncio
async def test_retryable_exceptions_tuple_matches_what_run_reraises(client):
    """Guards against base.py and orchestrator.py's copies of this tuple
    drifting apart -- orchestrator.py imports RETRYABLE_EXCEPTIONS from here
    rather than redefining it, but a future edit to either side re-adding a
    local tuple would silently break that sharing without this assertion."""
    assert RETRYABLE_EXCEPTIONS == (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    )


@pytest.mark.asyncio
async def test_latency_is_populated_on_every_path(client):
    scenarios = [
        _StubProvider(),
        _StubProvider(requires_key=True, configured=False),
    ]
    for provider in scenarios:
        result = await provider.run("1.2.3.4", IOCType.IPV4, client)
        assert result.latency_ms is not None
        assert result.latency_ms >= 0

    unsupported_provider = _StubProvider()
    result = await unsupported_provider.run("example.com", IOCType.DOMAIN, client)
    assert result.latency_ms is not None
    assert result.latency_ms >= 0
