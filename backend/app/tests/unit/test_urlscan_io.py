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
import asyncio
import time

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


@pytest.mark.asyncio
@respx.mock
async def test_a_retryable_connect_error_on_submit_propagates_instead_of_being_swallowed(provider, client):
    """Real gap found live during overnight QA: httpx.ConnectError/
    ReadTimeout/PoolTimeout (app/providers/base.py's RETRYABLE_EXCEPTIONS)
    all inherit from httpx.HTTPError, which this connector's own broad
    `except httpx.HTTPError` used to catch and normalize into an ordinary
    ProviderResult -- so the orchestrator's tenacity retry loop (which only
    fires on an exception it actually sees propagate out of
    BaseProvider.run()) never got a chance to retry a transient blip for
    this provider, unlike every other connector."""
    request = httpx.Request("POST", "https://urlscan.io/api/v1/scan/")
    respx.post("https://urlscan.io/api/v1/scan/").mock(side_effect=httpx.ConnectError("connection refused", request=request))

    with pytest.raises(httpx.ConnectError):
        await provider.fetch("http://evil.test/", IOCType.URL, client)


@pytest.mark.asyncio
@respx.mock
async def test_a_retryable_read_timeout_on_poll_propagates_instead_of_being_swallowed(provider, client):
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "22222222-2222-2222-2222-222222222222"})
    )
    request = httpx.Request("GET", "https://urlscan.io/api/v1/result/22222222-2222-2222-2222-222222222222/")
    respx.get("https://urlscan.io/api/v1/result/22222222-2222-2222-2222-222222222222/").mock(
        side_effect=httpx.ReadTimeout("read timed out", request=request)
    )

    with pytest.raises(httpx.ReadTimeout):
        await provider.fetch("http://evil.test/", IOCType.URL, client)


@pytest.mark.asyncio
@respx.mock
async def test_poll_deadline_is_computed_before_submission_not_fresh_inside_poll(provider, client, monkeypatch):
    """Real gap found live during overnight QA: _TIMEOUT_SECONDS is
    documented as a combined "submit + poll-until-ready" wall-clock budget,
    but the deadline used to be computed fresh INSIDE _poll_for_result --
    called only after submission had already completed -- so the real
    behavior was "however long submission takes, PLUS a full fresh
    _TIMEOUT_SECONDS for polling," not the documented combined cap.
    Asserts _poll_for_result now receives a deadline anchored to BEFORE
    submission started, not one freshly computed at poll time. (Does not
    touch time.monotonic() itself -- asyncio's own event-loop scheduling
    depends on real wall-clock time, so freezing it would hang the test.)"""
    respx.post("https://urlscan.io/api/v1/scan/").mock(
        return_value=httpx.Response(200, json={"uuid": "44444444-4444-4444-4444-444444444444"})
    )

    submit_delay = 0.3  # a real, measurable delay -- big enough to distinguish "before" from "after" submission
    real_post = client.post

    async def delayed_post(*args, **kwargs):
        await asyncio.sleep(submit_delay)
        return await real_post(*args, **kwargs)

    monkeypatch.setattr(client, "post", delayed_post)

    received_deadline = {}

    async def capturing_poll(self, ioc_value, ioc_type, uuid, headers, client, deadline):
        received_deadline["value"] = deadline
        return self._error(ioc_value, ioc_type, ProviderStatus.TIMEOUT, "stubbed for this test")

    monkeypatch.setattr(UrlscanProvider, "_poll_for_result", capturing_poll)

    before_submit = time.monotonic()
    result = await provider.fetch("http://evil.test/", IOCType.URL, client)

    assert result.status == ProviderStatus.TIMEOUT
    # The bug this guards against: the OLD code computed the deadline
    # fresh INSIDE _poll_for_result, i.e. AFTER the (here, artificially
    # delayed) submission completed -- that would put the deadline at
    # roughly before_submit + submit_delay + _TIMEOUT_SECONDS. The FIXED
    # code anchors it at fetch()'s own start, before submission, so it
    # must land close to before_submit + _TIMEOUT_SECONDS instead --
    # clearly earlier than the buggy value by close to submit_delay.
    assert received_deadline["value"] < before_submit + urlscan_io._TIMEOUT_SECONDS + (submit_delay / 2)
