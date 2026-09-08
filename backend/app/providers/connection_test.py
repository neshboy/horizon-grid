"""Live "does this API key actually work" check for the Windows setup wizard
(and any future in-app provider-settings UI). Deliberately separate from the
BaseProvider.fetch() code path: those methods read the *global* Settings
singleton (app/core/config.py's @lru_cache'd get_settings()), which is fixed
for the life of the running backend process, so there is no safe way to test
a key the user just typed into a form without either restarting the process
or mutating shared global state out from under concurrent requests.

Each check here makes one minimal, real HTTP call using the *candidate* key
passed in the request body -- mirroring the exact auth header/base_url each
connector already uses (see the matching app/providers/*.py file for each
provider_id) -- against a safe, fixed test indicator, and reports whether the
provider accepted the credential. It never touches get_settings() and never
persists the tested key; the wizard's own step writes the confirmed-good key
into request.env afterward via app/api/routes/providers.py's other endpoints.
"""
import time
from dataclasses import dataclass
from typing import Optional

import httpx

# A real, safe, non-sensitive indicator per provider family -- picked to
# match each connector's supported_types (app/providers/*.py) so a 404/
# "not found" response (a valid, working credential) isn't mistaken for an
# auth failure. IPs/domains/hashes are well-known, intentionally benign.
_TEST_IP = "8.8.8.8"
_TEST_DOMAIN = "google.com"
_TEST_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # sha256("")
_TEST_CVE = "CVE-2021-44228"  # real, published (Log4Shell)


@dataclass
class TestResult:
    ok: bool
    message: str
    latency_ms: Optional[int] = None


async def _timed(coro_factory):
    start = time.monotonic()
    try:
        result = await coro_factory()
        return result, int((time.monotonic() - start) * 1000)
    except httpx.TimeoutException:
        return TestResult(ok=False, message="Request timed out."), int((time.monotonic() - start) * 1000)
    except httpx.HTTPError as exc:
        return TestResult(ok=False, message=f"Network error: {exc}"), int((time.monotonic() - start) * 1000)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the UI as a message, never a raw traceback.
        # Covers e.g. a malformed/non-JSON HTTP 200 body (a WAF/CDN outage
        # page, etc.) tripping r.json()'s json.JSONDecodeError in
        # _check_abusech -- that's a ValueError, not an httpx.HTTPError, so
        # it isn't caught above. Mirrors app/ai/connection_test.py's _timed.
        return TestResult(ok=False, message=f"Unexpected response ({exc})."), int((time.monotonic() - start) * 1000)


async def _check_virustotal(api_key: str) -> TestResult:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"https://www.virustotal.com/api/v3/ip_addresses/{_TEST_IP}",
            headers={"x-apikey": api_key},
        )
    if r.status_code == 200:
        return TestResult(ok=True, message="Connected. Key is valid.")
    if r.status_code == 401:
        return TestResult(ok=False, message="Authentication failed -- check your API key.")
    if r.status_code == 429:
        return TestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")


async def _check_abuseipdb(api_key: str) -> TestResult:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://api.abuseipdb.com/api/v2/check",
            headers={"Key": api_key, "Accept": "application/json"},
            params={"ipAddress": _TEST_IP, "maxAgeInDays": 1},
        )
    if r.status_code == 200:
        return TestResult(ok=True, message="Connected. Key is valid.")
    if r.status_code in (401, 403):
        return TestResult(ok=False, message="Authentication failed -- check your API key.")
    if r.status_code == 429:
        return TestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")


async def _check_otx(api_key: str) -> TestResult:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"https://otx.alienvault.com/api/v1/indicators/IPv4/{_TEST_IP}/general",
            headers={"X-OTX-API-KEY": api_key},
        )
    if r.status_code == 200:
        return TestResult(ok=True, message="Connected. Key is valid.")
    if r.status_code in (401, 403):
        return TestResult(ok=False, message="Authentication failed -- check your API key.")
    return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")


async def _check_abusech(auth_key: str) -> TestResult:
    # Shared by urlhaus/threatfox/malwarebazaar -- test against ThreatFox,
    # the lightest of the three, using its documented query_status field
    # rather than HTTP status (abuse.ch APIs return 200 even on bad auth).
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://threatfox-api.abuse.ch/api/v1/",
            json={"query": "search_ioc", "search_term": _TEST_IP},
            headers={"Auth-Key": auth_key},
        )
    if r.status_code != 200:
        return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")
    payload = r.json()
    status = payload.get("query_status")
    if status in ("no_api_key", "invalid_api_key", "unauthorized"):
        return TestResult(ok=False, message=f"Authentication failed ({status}) -- check your Auth-Key.")
    return TestResult(ok=True, message="Connected. Key is valid.")


async def _check_nvd(api_key: str) -> TestResult:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://services.nvd.nist.gov/rest/json/cves/2.0",
            headers={"apiKey": api_key} if api_key else {},
            params={"cveId": _TEST_CVE},
        )
    if r.status_code == 200:
        return TestResult(ok=True, message="Connected. Key is valid.")
    if r.status_code == 403:
        return TestResult(ok=False, message="Authentication failed -- check your API key.")
    if r.status_code == 429:
        return TestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")


async def _check_hybrid_analysis(api_key: str) -> TestResult:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            # www. permanently redirects (HTTP 301) to the bare domain --
            # see app/providers/stubs/hybrid_analysis.py for the same fix.
            f"https://hybrid-analysis.com/api/v2/overview/{_TEST_SHA256}/summary",
            headers={"api-key": api_key, "User-Agent": "Falcon Sandbox"},
        )
    if r.status_code in (200, 404):
        return TestResult(ok=True, message="Connected. Key is valid.")
    if r.status_code in (401, 403):
        return TestResult(ok=False, message="Authentication failed -- check your API key.")
    return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")


async def _check_censys(personal_access_token: str, organization_id: str) -> TestResult:
    if not organization_id:
        return TestResult(ok=False, message="Organization ID is required in addition to the access token.")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"https://platform.censys.io/v3/global/asset/host/{_TEST_IP}",
            headers={"Authorization": f"Bearer {personal_access_token}", "X-Organization-ID": organization_id},
        )
    if r.status_code in (200, 404):
        return TestResult(ok=True, message="Connected. Credentials are valid.")
    if r.status_code in (401, 403):
        return TestResult(ok=False, message="Authentication failed -- check your access token and organization ID.")
    return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")


async def _check_phishtank(api_key: str) -> TestResult:
    # PhishTank never requires a key (see app/providers/stubs/phishtank.py) --
    # the key only raises rate limits. Observed live: PhishTank's checkurl
    # endpoint can return 403 to any generic HTTP client (including the
    # platform's own production connector, which uses this exact request
    # shape) independent of whether an app_key is supplied or valid -- so a
    # 403 here does not necessarily mean a bad key, only that this specific
    # request was blocked. Report it as inconclusive rather than a hard
    # failure, since no key is ever actually required for this provider.
    form = {"url": f"http://{_TEST_DOMAIN}/", "format": "json"}
    if api_key:
        form["app_key"] = api_key
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post("https://checkurl.phishtank.com/checkurl/", data=form)
    if r.status_code == 200:
        return TestResult(ok=True, message="Connected." + (" Key accepted." if api_key else " No key required."))
    if r.status_code == 509:
        return TestResult(ok=False, message="Rate limited by PhishTank -- try again later.")
    if r.status_code == 403:
        return TestResult(
            ok=True,
            message="PhishTank blocked this test request (HTTP 403), which can happen to any client independent "
            "of your key. No key is required for this provider, so this is not necessarily an error -- "
            "the platform will still query PhishTank normally during real investigations.",
        )
    return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")


async def _check_google_safe_browsing(api_key: str) -> TestResult:
    # Mirrors app/providers/google_safe_browsing.py::fetch() exactly (same
    # endpoint, same key placement, same threatTypes list) against the same
    # safe, well-known benign domain every other check here uses.
    body = {
        "client": {"clientId": "horizon-grid", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": f"http://{_TEST_DOMAIN}/"}],
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        # Key goes in the x-goog-api-key header, not the ?key= query string --
        # httpx logs the full request URL at INFO level, which would
        # otherwise put the candidate key in plain text in the logs on every
        # Test Connection click. Mirrors the fix in
        # app/providers/google_safe_browsing.py::fetch() and
        # app/ai/connection_test.py's _check_gemini.
        r = await client.post(
            "https://safebrowsing.googleapis.com/v4/threatMatches:find",
            headers={"x-goog-api-key": api_key},
            json=body,
        )
    if r.status_code == 200:
        return TestResult(ok=True, message="Connected. Key is valid.")
    if r.status_code in (400, 401, 403):
        return TestResult(ok=False, message=f"Google Safe Browsing rejected the request (HTTP {r.status_code}) -- check your API key.")
    if r.status_code == 429:
        return TestResult(ok=False, message="Google Safe Browsing rate limit/quota exceeded.")
    return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")


async def _check_urlscan(api_key: str) -> TestResult:
    # Mirrors app/providers/urlscan_io.py::fetch()'s submission call exactly
    # (same endpoint, same API-Key header, same "unlisted" visibility) --
    # only checks the submission response, does not poll for scan
    # completion, since this is a credential check, not a real investigation.
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://urlscan.io/api/v1/scan/",
            headers={"API-Key": api_key, "Content-Type": "application/json"},
            json={"url": f"https://{_TEST_DOMAIN}/", "visibility": "unlisted"},
        )
    if r.status_code in (200, 201):
        return TestResult(ok=True, message="Connected. Key is valid.")
    if r.status_code in (401, 403):
        return TestResult(ok=False, message=f"urlscan.io rejected the API key (HTTP {r.status_code}).")
    if r.status_code == 429:
        return TestResult(ok=False, message="urlscan.io rate limit exceeded.")
    return TestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}).")


async def test_provider_connection(provider_id: str, credentials: dict[str, str]) -> TestResult:
    """credentials keys vary by provider_id: most use "api_key"; censys uses
    "personal_access_token" + "organization_id"; abusech-backed providers
    (urlhaus/threatfox/malwarebazaar) use "auth_key"."""
    handlers = {
        "virustotal": lambda: _check_virustotal(credentials.get("api_key", "")),
        "abuseipdb": lambda: _check_abuseipdb(credentials.get("api_key", "")),
        "otx": lambda: _check_otx(credentials.get("api_key", "")),
        "urlhaus": lambda: _check_abusech(credentials.get("auth_key", "")),
        "threatfox": lambda: _check_abusech(credentials.get("auth_key", "")),
        "malwarebazaar": lambda: _check_abusech(credentials.get("auth_key", "")),
        "nvd": lambda: _check_nvd(credentials.get("api_key", "")),
        "hybrid_analysis": lambda: _check_hybrid_analysis(credentials.get("api_key", "")),
        "censys": lambda: _check_censys(
            credentials.get("personal_access_token", ""), credentials.get("organization_id", "")
        ),
        "phishtank": lambda: _check_phishtank(credentials.get("api_key", "")),
        "google_safe_browsing": lambda: _check_google_safe_browsing(credentials.get("api_key", "")),
        "urlscan": lambda: _check_urlscan(credentials.get("api_key", "")),
    }
    handler = handlers.get(provider_id)
    if handler is None:
        return TestResult(ok=False, message=f"'{provider_id}' has no live connection test (it may require no key, e.g. Spamhaus, crt.sh, CISA KEV, MITRE ATT&CK, WHOIS/RDAP).")

    result, elapsed_ms = await _timed(handler)
    result.latency_ms = elapsed_ms
    return result
