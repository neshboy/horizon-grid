"""Unit tests for app/providers/google_safe_browsing.py -- the Safe Browsing
Lookup API v4 (threatMatches:find) connector. All HTTP is mocked with respx,
matching the pattern already used in app/tests/unit/test_connection_test.py.

The critical, non-negotiable property this file pins down (per the module's
own docstring): a "clean" verdict may ONLY come from a confirmed HTTP 200
response whose `matches` field is genuinely absent or empty. Every failure
path -- bad key, rate limit, malformed body, timeout, network error -- must
produce data whose "verdict" is "unknown", never "clean"/"safe". The
`test_*_never_looks_like_safe` tests below assert this explicitly for each
failure mode, not just that the status is non-OK.
"""
import httpx
import pytest
import respx

from app.ioc.types import IOCType
from app.providers.base import ProviderStatus
from app.providers.google_safe_browsing import GoogleSafeBrowsingProvider

_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"


@pytest.fixture
def provider():
    p = GoogleSafeBrowsingProvider()
    p.configured = True
    return p


@pytest.fixture
def client():
    return httpx.AsyncClient()


def _assert_never_looks_safe(result):
    """The core defensive-design assertion this whole test file exists to
    prove: no failure path may produce data resembling a clean/safe
    verdict."""
    assert result.status != ProviderStatus.OK
    assert result.data.get("verdict") != "clean"
    assert result.data.get("verdict") != "safe"
    assert result.data.get("verdict") == "unknown"


@pytest.mark.asyncio
@respx.mock
async def test_empty_matches_object_maps_to_clean(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(200, json={}))

    result = await provider.fetch("http://benign.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "clean"
    assert result.data["matches"] == []


@pytest.mark.asyncio
@respx.mock
async def test_explicit_empty_matches_list_maps_to_clean(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(200, json={"matches": []}))

    result = await provider.fetch("http://benign.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "clean"


@pytest.mark.asyncio
@respx.mock
async def test_matches_present_maps_to_malicious(provider, client):
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "threatType": "SOCIAL_ENGINEERING",
                        "platformType": "ANY_PLATFORM",
                        "threat": {"url": "http://evil.test/"},
                        "cacheDuration": "300s",
                    }
                ]
            },
        )
    )

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "malicious"
    assert result.data["threat_types"] == ["SOCIAL_ENGINEERING"]
    assert result.data["match_count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_domain_ioc_type_is_submitted_as_a_url(provider, client):
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json={}))

    result = await provider.fetch("evil.test", IOCType.DOMAIN, client)

    assert result.status == ProviderStatus.OK
    sent_body = route.calls.last.request.content
    assert b"http://evil.test" in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_401_maps_to_error_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(401))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    _assert_never_looks_safe(result)


@pytest.mark.asyncio
@respx.mock
async def test_403_maps_to_error_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(403))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    _assert_never_looks_safe(result)


@pytest.mark.asyncio
@respx.mock
async def test_400_maps_to_error_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(400, json={"error": {"message": "API key not valid"}}))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    _assert_never_looks_safe(result)


@pytest.mark.asyncio
@respx.mock
async def test_429_maps_to_rate_limited_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(429))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.RATE_LIMITED
    _assert_never_looks_safe(result)


@pytest.mark.asyncio
@respx.mock
async def test_500_maps_to_error_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(500))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    _assert_never_looks_safe(result)


@pytest.mark.asyncio
@respx.mock
async def test_malformed_json_maps_to_error_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(200, content=b"not json"))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    _assert_never_looks_safe(result)


@pytest.mark.asyncio
@respx.mock
async def test_non_object_response_maps_to_error_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(200, json=["unexpected", "list"]))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    _assert_never_looks_safe(result)


@pytest.mark.asyncio
@respx.mock
async def test_malformed_matches_field_maps_to_error_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(return_value=httpx.Response(200, json={"matches": "not-a-list"}))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    _assert_never_looks_safe(result)


@pytest.mark.asyncio
@respx.mock
async def test_timeout_maps_to_timeout_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(side_effect=httpx.TimeoutException("timed out"))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.TIMEOUT
    _assert_never_looks_safe(result)


@pytest.mark.asyncio
@respx.mock
async def test_network_error_maps_to_error_never_looks_like_safe(provider, client):
    respx.post(_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    _assert_never_looks_safe(result)
