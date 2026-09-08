"""Google Safe Browsing connector (Lookup API v4, threatMatches:find).

See app/providers/base.py for the BaseProvider contract and
app/providers/abuseipdb.py for the reference connector style this follows
(a simple key-based reputation check, one request, no polling).

API reference: https://developers.google.com/safe-browsing/v4/lookup-api --
POST https://safebrowsing.googleapis.com/v4/threatMatches:find. The API
docs show the key as a ?key=<API_KEY> query parameter, but this connector
sends it via the equivalent `x-goog-api-key` header instead (Google's
API-key auth infra accepts either) -- httpx logs the full request URL,
including query strings, at INFO level, so a query-param key would leak
into the application's logs on every request. See _check_gemini in
app/ai/connection_test.py for the same rationale applied elsewhere.

CRITICAL invariant, enforced throughout this module: an empty/missing
`matches` field on a genuine HTTP 200 response is the ONLY input that may
produce a "clean" verdict. Every other outcome -- a non-200 status, a
network error/timeout, or a response body that doesn't parse the way the
API contract promises -- returns early via `_error()`, which always sets
`data={"verdict": "unknown", ...}` on the ProviderResult it builds. There is
no code path from "the request failed" to a result whose `data` looks like
a clean scan; see app/tests/unit/test_google_safe_browsing.py's
`test_*_never_looks_like_safe` tests for the pinned proof of this.
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType
from app.providers.base import (
    RETRYABLE_EXCEPTIONS,
    BaseProvider,
    ProviderCategory,
    ProviderResult,
    ProviderStatus,
)

_THREAT_TYPES = ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"]


class GoogleSafeBrowsingProvider(BaseProvider):
    provider_id = "google_safe_browsing"
    provider_name = "Google Safe Browsing"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.URL, IOCType.DOMAIN}
    requires_key = True
    base_url = "https://safebrowsing.googleapis.com/v4"

    def __init__(self) -> None:
        super().__init__()
        self.configured = bool(get_settings().google_safe_browsing_api_key)

    @staticmethod
    def _target_url(ioc_value: str, ioc_type: IOCType) -> str:
        # threatEntries.url expects a URL; IOCType.DOMAIN values are bare
        # hostnames (see app/ioc/types.py), so a scheme is added.
        if ioc_type == IOCType.DOMAIN:
            return f"http://{ioc_value}"
        return ioc_value

    def _error(self, ioc_value: str, ioc_type: IOCType, status: ProviderStatus, message: str) -> ProviderResult:
        # Every failure path returns an explicitly UNKNOWN-flavored verdict
        # in `data` -- never an empty dict, and never anything that could be
        # mistaken for a genuine clean/safe result downstream (correlation
        # engine, evidence builder, UI).
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=status,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data={"verdict": "unknown", "matches": [], "threat_types": []},
            error_message=message,
        )

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        api_key = get_credential("google_safe_browsing", "api_key", settings.google_safe_browsing_api_key)
        target = self._target_url(ioc_value, ioc_type)

        body = {
            "client": {"clientId": "horizon-grid", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes": _THREAT_TYPES,
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": target}],
            },
        }

        try:
            # Key goes in the x-goog-api-key header, not the ?key= query
            # string -- httpx logs the full request URL (including any query
            # string) at INFO level, which would otherwise put the API key in
            # plain text in the application logs on every request. Google's
            # API-key auth infrastructure (shared across googleapis.com
            # endpoints) accepts the key via this header as an alternative to
            # the query param; see app/ai/connection_test.py's _check_gemini
            # for the same fix applied to the Gemini connector.
            # `api_key or ""` mirrors the old params={"key": api_key}
            # behavior for a missing/None key (httpx's query-param encoder
            # silently turned None into ""); httpx header values, unlike
            # query params, reject None outright with an AttributeError, so
            # this coalesces explicitly to preserve that same tolerance.
            response = await client.post(
                f"{self.base_url}/threatMatches:find", headers={"x-goog-api-key": api_key or ""}, json=body
            )
        except RETRYABLE_EXCEPTIONS:
            # Deliberately NOT normalized here -- these must propagate up to
            # BaseProvider.run()'s dedicated re-raise branch so the
            # orchestrator's tenacity retry loop can retry a transient
            # connection blip, per base.py's own documented design. See
            # app/providers/base.py's RETRYABLE_EXCEPTIONS comment.
            raise
        except httpx.TimeoutException as exc:
            return self._error(ioc_value, ioc_type, ProviderStatus.TIMEOUT, f"Google Safe Browsing request timed out: {exc}")
        except httpx.HTTPError as exc:
            return self._error(ioc_value, ioc_type, ProviderStatus.ERROR, f"Google Safe Browsing network error: {exc}")

        if response.status_code in (400, 401, 403):
            return self._error(
                ioc_value, ioc_type, ProviderStatus.ERROR,
                f"Google Safe Browsing rejected the request (HTTP {response.status_code}) -- check your API key.",
            )
        if response.status_code == 429:
            return self._error(
                ioc_value, ioc_type, ProviderStatus.RATE_LIMITED, "Google Safe Browsing rate limit/quota exceeded."
            )
        if response.status_code != 200:
            return self._error(
                ioc_value, ioc_type, ProviderStatus.ERROR,
                f"Unexpected response from Google Safe Browsing (HTTP {response.status_code}).",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            return self._error(
                ioc_value, ioc_type, ProviderStatus.ERROR, f"Google Safe Browsing returned a malformed response: {exc}"
            )
        if not isinstance(payload, dict):
            return self._error(
                ioc_value, ioc_type, ProviderStatus.ERROR,
                "Google Safe Browsing returned an unexpected (non-object) response.",
            )

        matches = payload.get("matches")
        if matches is None or (isinstance(matches, list) and len(matches) == 0):
            # The only case that may ever produce "clean": a confirmed 200
            # whose `matches` field is genuinely absent or empty.
            data = {"verdict": "clean", "matches": [], "threat_types": []}
        elif isinstance(matches, list):
            threat_types = sorted(
                {m.get("threatType") for m in matches if isinstance(m, dict) and m.get("threatType")}
            )
            data = {
                "verdict": "malicious",
                "matches": matches,
                "threat_types": threat_types,
                "match_count": len(matches),
            }
        else:
            return self._error(
                ioc_value, ioc_type, ProviderStatus.ERROR, "Google Safe Browsing returned a malformed 'matches' field."
            )

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=payload,
            source_url=f"https://transparencyreport.google.com/safe-browsing/search?url={target}",
        )


google_safe_browsing_provider = GoogleSafeBrowsingProvider()
