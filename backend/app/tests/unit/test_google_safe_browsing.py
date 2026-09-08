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
import logging

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
async def test_network_error_propagates_for_orchestrator_retry(provider, client):
    # Real bug fixed: httpx.ConnectError is one of base.py's
    # RETRYABLE_EXCEPTIONS, which BaseProvider.run() is specifically designed
    # to re-raise (rather than normalize) so the orchestrator's tenacity
    # retry loop can retry a transient connection blip -- see base.py's
    # RETRYABLE_EXCEPTIONS comment and app/tests/unit/test_orchestrator_retry.py.
    # fetch() must let it propagate instead of swallowing it into a terminal
    # ProviderResult here, or that retry policy never engages for this
    # provider. Non-retryable httpx errors (bad status codes, malformed
    # bodies, generic timeouts) still map to ProviderStatus.ERROR/TIMEOUT via
    # the other tests in this file -- only this specific exception type must
    # now raise instead of being caught.
    respx.post(_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    with pytest.raises(httpx.ConnectError):
        await provider.fetch("http://evil.test/", IOCType.URL, client)


@pytest.mark.asyncio
@respx.mock
async def test_network_error_propagates_through_run_for_orchestrator_retry(provider, client):
    # Once fetch() lets the ConnectError propagate, BaseProvider.run() (see
    # base.py) must also re-raise it rather than normalizing it into a
    # ProviderResult, so orchestrator.py's retry wrapper (_run_with_policy,
    # exercised end-to-end in test_orchestrator_retry.py) is the only layer
    # that eventually turns it into a terminal ProviderResult, and only
    # after retries are exhausted.
    respx.post(_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    with pytest.raises(httpx.ConnectError):
        await provider.run("http://evil.test/", IOCType.URL, client)


@pytest.mark.asyncio
@respx.mock
async def test_api_key_is_sent_as_header_not_query_param(provider, client):
    """Regression test for the API key leaking into application logs.

    httpx's default per-request INFO log line includes the full request URL
    (method + URL + status) but never header values -- see
    app/main.py:54-58, which configures the root logger (and therefore the
    'httpx' logger, since it is never suppressed anywhere) at INFO. If the
    key were sent as a `?key=...` query parameter (as Google's docs show,
    and as this connector used to do), it would appear in plain text in
    every log line this connector produces. It must instead be sent via a
    header, which httpx's request log line never includes.
    """
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json={}))

    # fetch() reads the key via get_credential()/get_settings(), not from an
    # attribute on the provider -- patch get_credential the same way the key
    # actually flows through fetch() in production.
    import app.providers.google_safe_browsing as gsb_module

    original_get_credential = gsb_module.get_credential
    gsb_module.get_credential = lambda *a, **k: "PLAINTEXT_SECRET_KEY_ABC123"
    try:
        result = await provider.fetch("http://evil.test/", IOCType.URL, client)
    finally:
        gsb_module.get_credential = original_get_credential

    assert result.status == ProviderStatus.OK

    sent_request = route.calls.last.request
    # The key must never appear in the request URL/query string...
    assert "PLAINTEXT_SECRET_KEY_ABC123" not in str(sent_request.url)
    assert "key=" not in str(sent_request.url)
    # ...it must be carried in a header instead.
    assert sent_request.headers.get("x-goog-api-key") == "PLAINTEXT_SECRET_KEY_ABC123"


@pytest.mark.asyncio
@respx.mock
async def test_api_key_never_appears_in_httpx_info_log(provider, client, caplog):
    """End-to-end proof of the fix, exercised through the real fetch() code
    path (not a hand-built request): with the 'httpx' logger at INFO (the
    app's real configuration -- see app/main.py:54-58), the key must not
    show up anywhere in the log line httpx emits for this request. httpx
    logs "HTTP Request: <method> <url> ..." from AsyncClient._send_single_
    request() regardless of the (respx-mocked) transport, so this reproduces
    the exact leak the live repro demonstrated: before the fix (key sent via
    `params={"key": api_key}`), this log line contained the plaintext key in
    the request URL.
    """
    respx.post(_URL).mock(return_value=httpx.Response(200, json={}))
    api_key = "PLAINTEXT_SECRET_KEY_ABC123"

    import app.providers.google_safe_browsing as gsb_module

    original_get_credential = gsb_module.get_credential
    gsb_module.get_credential = lambda *a, **k: api_key
    try:
        with caplog.at_level(logging.INFO, logger="httpx"):
            result = await provider.fetch("http://evil.test/", IOCType.URL, client)
    finally:
        gsb_module.get_credential = original_get_credential

    assert result.status == ProviderStatus.OK
    assert api_key not in caplog.text
