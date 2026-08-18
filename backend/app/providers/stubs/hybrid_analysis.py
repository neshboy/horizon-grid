"""Hybrid Analysis (CrowdStrike Falcon Sandbox) connector -- requires a paid/free-tier API key.

Fully wired to the BaseProvider contract; `configured` is only True once
HYBRID_ANALYSIS_API_KEY is set in the environment.

IMPORTANT: Hybrid Analysis deprecated /api/v2/search/hash (confirmed live,
returns HTTP 410 Gone as of writing). This connector uses the confirmed-
working replacement, GET /api/v2/overview/{sha256}/summary, which only
accepts a SHA256 -- MD5/SHA1 inputs cannot be looked up by this endpoint, so
supported_types is SHA256-only rather than the full HASH_TYPES set.

URL support was removed: the documented /api/v2/search/terms replacement
parameter contract could not be confirmed against the live API (every
plausible field name -- url, domain, term, q, query, host, as both form and
JSON body -- returned "Search terms were not given"). Re-add IOCType.URL
support here once the correct request shape is confirmed against current
Hybrid Analysis API docs or support.
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class HybridAnalysisProvider(BaseProvider):
    provider_id = "hybrid_analysis"
    provider_name = "Hybrid Analysis (Falcon Sandbox)"
    category = ProviderCategory.SANDBOX
    supported_types = {IOCType.SHA256}
    requires_key = True
    # www.hybrid-analysis.com now permanently redirects (HTTP 301) to the
    # bare domain -- confirmed live; httpx does not follow redirects by
    # default, so the www. form silently returned a 301 instead of data.
    base_url = "https://hybrid-analysis.com/api/v2"

    def __init__(self) -> None:
        super().__init__()
        self.configured = bool(get_settings().hybrid_analysis_api_key)

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        headers = {
            "api-key": get_credential("hybrid_analysis", "api_key", settings.hybrid_analysis_api_key),
            # Hybrid Analysis rejects requests without a descriptive user-agent.
            "user-agent": "Falcon Sandbox",
            "accept": "application/json",
        }
        source_url = f"https://hybrid-analysis.com/sample/{ioc_value}"

        response = await client.get(f"{self.base_url}/overview/{ioc_value}/summary", headers=headers)
        if response.status_code in (400, 404):
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url=source_url,
            )
        response.raise_for_status()
        payload = response.json()

        data = self._map(payload)

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=payload,
            source_url=source_url,
        )

    @staticmethod
    def _map(payload: dict) -> dict:
        return {
            "verdict": payload.get("verdict") or "unknown",
            "threat_score": payload.get("threat_score"),
            "av_detect_pct": payload.get("multiscan_result"),
            "sha256": payload.get("sha256"),
            "submitted_at": payload.get("submitted_at"),
            "first_seen": payload.get("submitted_at"),
            "last_seen": payload.get("last_multi_scan"),
        }


hybrid_analysis_provider = HybridAnalysisProvider()
