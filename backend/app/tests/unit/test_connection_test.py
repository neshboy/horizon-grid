"""Unit tests for app.providers.connection_test -- the live-credential-check
module the Windows setup wizard's "Test Connection" button calls into via
POST /api/v1/providers/{provider_id}/test. All HTTP is mocked with respx;
each check has also been separately run once against real live provider
APIs (see the session's manual verification, not part of this suite) with
both a valid and an invalid credential to confirm the real HTTP behavior
these mocks assume.
"""
import httpx
import pytest
import respx

from app.providers.connection_test import test_provider_connection as check_provider_connection


@pytest.mark.asyncio
async def test_unknown_provider_id_returns_ok_false_with_explanation():
    result = await check_provider_connection("not_a_real_provider", {})
    assert result.ok is False
    assert "no live connection test" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_virustotal_200_is_success():
    respx.get("https://www.virustotal.com/api/v3/ip_addresses/8.8.8.8").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    result = await check_provider_connection("virustotal", {"api_key": "real-key"})
    assert result.ok is True
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_virustotal_401_is_auth_failure():
    respx.get("https://www.virustotal.com/api/v3/ip_addresses/8.8.8.8").mock(
        return_value=httpx.Response(401)
    )
    result = await check_provider_connection("virustotal", {"api_key": "bad-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_virustotal_429_is_rate_limited_not_auth_failure():
    respx.get("https://www.virustotal.com/api/v3/ip_addresses/8.8.8.8").mock(
        return_value=httpx.Response(429)
    )
    result = await check_provider_connection("virustotal", {"api_key": "real-key"})
    assert result.ok is False
    assert "Rate limited" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_abuseipdb_403_is_auth_failure():
    respx.get("https://api.abuseipdb.com/api/v2/check").mock(return_value=httpx.Response(403))
    result = await check_provider_connection("abuseipdb", {"api_key": "bad-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_otx_200_is_success():
    respx.get("https://otx.alienvault.com/api/v1/indicators/IPv4/8.8.8.8/general").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await check_provider_connection("otx", {"api_key": "real-key"})
    assert result.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_abusech_bad_auth_key_query_status_is_failure_despite_http_200():
    # abuse.ch APIs return HTTP 200 even on bad auth -- the real signal is
    # the query_status field, not the status code.
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        return_value=httpx.Response(200, json={"query_status": "no_api_key"})
    )
    result = await check_provider_connection("threatfox", {"auth_key": "bad-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_abusech_ok_query_status_is_success():
    # All three abuse.ch-backed providers (urlhaus/threatfox/malwarebazaar)
    # share one Auth-Key, so _check_abusech tests it once against ThreatFox
    # regardless of which of the three provider_ids is passed in -- this is
    # intentional (see connection_test.py's _check_abusech docstring), not a
    # bug, so this test mocks the ThreatFox endpoint even though it's called
    # via the "malwarebazaar" provider_id.
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        return_value=httpx.Response(200, json={"query_status": "ok", "data": []})
    )
    result = await check_provider_connection("malwarebazaar", {"auth_key": "real-key"})
    assert result.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_abusech_malformed_200_body_is_graceful_failure_not_crash():
    # Regression test: abuse.ch (or a WAF/CDN in front of it) can return
    # HTTP 200 with a non-JSON body (e.g. an HTML error/outage page). Before
    # the fix, _check_abusech's unconditional r.json() raised an uncaught
    # json.JSONDecodeError that propagated all the way out of
    # test_provider_connection() -- _timed() only caught httpx.TimeoutException
    # and httpx.HTTPError, neither of which covers a JSON decode failure --
    # turning a routine "provider had a hiccup" into a bare 500 for the
    # POST /api/v1/providers/{provider_id}/test route (which has no
    # try/except of its own). It must instead resolve to a graceful
    # TestResult(ok=False, ...), like every other failure branch here.
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        return_value=httpx.Response(200, content=b"<html>service unavailable</html>")
    )
    result = await check_provider_connection("urlhaus", {"auth_key": "dummy"})
    assert result.ok is False
    assert result.message
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_nvd_works_with_no_key():
    respx.get("https://services.nvd.nist.gov/rest/json/cves/2.0").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await check_provider_connection("nvd", {"api_key": ""})
    assert result.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_nvd_403_is_auth_failure():
    respx.get("https://services.nvd.nist.gov/rest/json/cves/2.0").mock(
        return_value=httpx.Response(403)
    )
    result = await check_provider_connection("nvd", {"api_key": "bad-key"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_censys_missing_organization_id_fails_before_any_request():
    result = await check_provider_connection("censys", {"personal_access_token": "tok", "organization_id": ""})
    assert result.ok is False
    assert "Organization ID" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_censys_200_is_success():
    respx.get("https://platform.censys.io/v3/global/asset/host/8.8.8.8").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await check_provider_connection("censys", {"personal_access_token": "tok", "organization_id": "org-1"})
    assert result.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_hybrid_analysis_404_is_still_success_valid_key_no_match():
    respx.get(
        "https://hybrid-analysis.com/api/v2/overview/"
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855/summary"
    ).mock(return_value=httpx.Response(404))
    result = await check_provider_connection("hybrid_analysis", {"api_key": "real-key"})
    assert result.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_phishtank_403_is_reported_as_inconclusive_ok():
    respx.post("https://checkurl.phishtank.com/checkurl/").mock(return_value=httpx.Response(403))
    result = await check_provider_connection("phishtank", {"api_key": ""})
    assert result.ok is True
    assert "403" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_timeout_is_reported_cleanly():
    respx.get("https://www.virustotal.com/api/v3/ip_addresses/8.8.8.8").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    result = await check_provider_connection("virustotal", {"api_key": "real-key"})
    assert result.ok is False
    assert "timed out" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_google_safe_browsing_200_is_success():
    respx.post("https://safebrowsing.googleapis.com/v4/threatMatches:find").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await check_provider_connection("google_safe_browsing", {"api_key": "real-key"})
    assert result.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_google_safe_browsing_401_is_auth_failure():
    respx.post("https://safebrowsing.googleapis.com/v4/threatMatches:find").mock(
        return_value=httpx.Response(401)
    )
    result = await check_provider_connection("google_safe_browsing", {"api_key": "bad-key"})
    assert result.ok is False


@pytest.mark.asyncio
@respx.mock
async def test_google_safe_browsing_api_key_is_sent_as_header_not_query_param():
    """Regression test: the "Test Connection" button's candidate key must
    never be sent as a `?key=` query parameter, because httpx logs the full
    request URL (query string included) at INFO level, and the app's root
    logger (which the 'httpx' logger propagates to, unsuppressed) runs at
    INFO -- see app/main.py:54-58. Before the fix, clicking Test Connection
    for this provider put the just-typed, not-yet-saved candidate key in
    plain text into the backend logs. Mirrors the same regression test for
    the real connector in app/tests/unit/test_google_safe_browsing.py.
    """
    route = respx.post("https://safebrowsing.googleapis.com/v4/threatMatches:find").mock(
        return_value=httpx.Response(200, json={})
    )
    api_key = "PLAINTEXT_SECRET_KEY_ABC123"

    result = await check_provider_connection("google_safe_browsing", {"api_key": api_key})

    assert result.ok is True
    sent_request = route.calls.last.request
    assert api_key not in str(sent_request.url)
    assert "key=" not in str(sent_request.url)
    assert sent_request.headers.get("x-goog-api-key") == api_key
