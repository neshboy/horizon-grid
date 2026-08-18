"""Unit tests for app/providers/urlscan_io.py -- submits a URL/domain for a
live urlscan.io scan, then polls the result endpoint (HTTP 404 while the
scan is still processing, HTTP 200 with the full result once ready). All
HTTP is mocked with respx, matching the pattern already used in
app/tests/unit/test_connection_test.py and test_whois_rdap.py.

Pins down the fix for HTTP 403 -- for urlscan.io, 403 means "bad API key,"
never "rate limited" -- despite app/providers/base.py's generic
HTTPStatusError handler mapping 403 to ProviderStatus.RATE_LIMITED for every
other connector (PhishTank's documented over-limit behavior). This
connector checks status codes explicitly, before any `raise_for_status()`
call, so that generic mapping never applies here.
"""
import httpx
import pytest
import respx

from app.ioc.types import IOCType
from app.providers.base import ProviderStatus
from app.providers.urlscan_io import UrlscanProvider
import app.providers.urlscan_io as urlscan_io


@pytest.fixture
def provider():
    p = UrlscanProvider()
    p.configured = True
    return p


@pytest.fixture
def client():
    return httpx.AsyncClient()


def _result_payload(malicious: bool, score: int = 0) -> dict:
    return {
        "task": {"uuid": "11111111-1111-1111-1111-111111111111", "time": "2026-01-01T00:00:00.000Z"},
        "page": {
            "url": "http://evil.test/",
            "domain": "evil.test",
            "ip": "203.0.113.9",
            "country": "US",
            "asn": "AS64500",
            "server": "nginx",
        },
        "lists": {"ips": ["203.0.113.9"], "domains": ["evil.test"]},
        "verdicts": {
            "overall": {"malicious": malicious, "score": score, "categories": ["phishing"] if malicious else [], "brands": []},
            "urlscan": {"malicious": malicious, "score": score, "categories": [], "brands": []},
        },
    }


@pytest.mark.asyncio
@respx.mock
async def test_successful_clean_result_maps_to_ok(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "11111111-1111-1111-1111-111111111111", "message": "Submission successful"})
    )
    respx.get("https://urlscan.io/api/v1/result/11111111-1111-1111-1111-111111111111/").mock(
        return_value=httpx.Response(200, json=_result_payload(malicious=False))
    )

    result = await provider.fetch("http://benign.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "clean"
    assert result.data["malicious"] is False
    assert result.source_url == "https://urlscan.io/result/11111111-1111-1111-1111-111111111111/"


@pytest.mark.asyncio
@respx.mock
async def test_successful_malicious_result_maps_to_ok_with_malicious_verdict(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "22222222-2222-2222-2222-222222222222"})
    )
    respx.get("https://urlscan.io/api/v1/result/22222222-2222-2222-2222-222222222222/").mock(
        return_value=httpx.Response(200, json=_result_payload(malicious=True, score=90))
    )

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "malicious"
    assert result.data["malicious"] is True
    assert result.data["domain"] == "evil.test"


@pytest.mark.asyncio
@respx.mock
async def test_poll_retries_through_404_until_ready(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "33333333-3333-3333-3333-333333333333"})
    )
    respx.get("https://urlscan.io/api/v1/result/33333333-3333-3333-3333-333333333333/").mock(
        side_effect=[
            httpx.Response(404),
            httpx.Response(404),
            httpx.Response(200, json=_result_payload(malicious=False)),
        ]
    )
    urlscan_io._POLL_INTERVAL_SECONDS = 0.01
    try:
        result = await provider.fetch("http://benign.test/", IOCType.URL, client)
    finally:
        urlscan_io._POLL_INTERVAL_SECONDS = 3

    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "clean"


@pytest.mark.asyncio
@respx.mock
async def test_domain_ioc_type_is_submitted_as_a_url(provider, client):
    submit_route = respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "44444444-4444-4444-4444-444444444444"})
    )
    respx.get("https://urlscan.io/api/v1/result/44444444-4444-4444-4444-444444444444/").mock(
        return_value=httpx.Response(200, json=_result_payload(malicious=False))
    )

    result = await provider.fetch("evil.test", IOCType.DOMAIN, client)

    assert result.status == ProviderStatus.OK
    sent_body = submit_route.calls.last.request.content
    assert b"http://evil.test" in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_submission_401_maps_to_error_not_rate_limited(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(return_value=httpx.Response(401))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    assert "401" in result.error_message


@pytest.mark.asyncio
@respx.mock
async def test_submission_403_maps_to_error_not_rate_limited(provider, client):
    # The important regression case: base.py's generic HTTPStatusError
    # handler maps 403 to RATE_LIMITED for every other connector. urlscan.io
    # must not go through that path for a bad key.
    respx.post("https://urlscan.io/api/v1/scan/").mock(return_value=httpx.Response(403))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    assert "403" in result.error_message


@pytest.mark.asyncio
@respx.mock
async def test_submission_429_maps_to_rate_limited(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(return_value=httpx.Response(429))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.RATE_LIMITED


@pytest.mark.asyncio
@respx.mock
async def test_poll_403_maps_to_error_not_rate_limited(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "55555555-5555-5555-5555-555555555555"})
    )
    respx.get("https://urlscan.io/api/v1/result/55555555-5555-5555-5555-555555555555/").mock(
        return_value=httpx.Response(403)
    )

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR


@pytest.mark.asyncio
@respx.mock
async def test_poll_429_maps_to_rate_limited(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "66666666-6666-6666-6666-666666666666"})
    )
    respx.get("https://urlscan.io/api/v1/result/66666666-6666-6666-6666-666666666666/").mock(
        return_value=httpx.Response(429)
    )

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.RATE_LIMITED


@pytest.mark.asyncio
@respx.mock
async def test_scan_never_ready_maps_to_timeout_not_a_fabricated_result(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "77777777-7777-7777-7777-777777777777"})
    )
    respx.get("https://urlscan.io/api/v1/result/77777777-7777-7777-7777-777777777777/").mock(
        return_value=httpx.Response(404)
    )

    urlscan_io._TIMEOUT_SECONDS = 0.05
    urlscan_io._POLL_INTERVAL_SECONDS = 0.01
    try:
        result = await provider.fetch("http://evil.test/", IOCType.URL, client)
    finally:
        urlscan_io._TIMEOUT_SECONDS = 60
        urlscan_io._POLL_INTERVAL_SECONDS = 3

    assert result.status == ProviderStatus.TIMEOUT
    assert result.data == {}


@pytest.mark.asyncio
@respx.mock
async def test_malformed_submission_response_missing_uuid_maps_to_error(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(return_value=httpx.Response(200, json={"message": "ok"}))

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR
    assert "uuid" in result.error_message


@pytest.mark.asyncio
@respx.mock
async def test_malformed_result_json_maps_to_error(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "88888888-8888-8888-8888-888888888888"})
    )
    respx.get("https://urlscan.io/api/v1/result/88888888-8888-8888-8888-888888888888/").mock(
        return_value=httpx.Response(200, content=b"not json")
    )

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.ERROR


@pytest.mark.asyncio
@respx.mock
async def test_absent_malicious_signal_maps_to_unknown_not_fabricated_clean(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "99999999-9999-9999-9999-999999999999"})
    )
    respx.get("https://urlscan.io/api/v1/result/99999999-9999-9999-9999-999999999999/").mock(
        return_value=httpx.Response(200, json={"task": {"uuid": "99999999-9999-9999-9999-999999999999"}, "page": {}})
    )

    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "unknown"
