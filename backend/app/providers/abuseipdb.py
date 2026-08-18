"""AbuseIPDB connector (v2 API, free tier: 1000 checks/day).

Requires a free AbuseIPDB API key, sent via the "Key" header. See
app/providers/base.py for the BaseProvider contract and
app/providers/virustotal.py for the reference connector style.
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class AbuseIPDBProvider(BaseProvider):
    provider_id = "abuseipdb"
    provider_name = "AbuseIPDB"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.IPV4, IOCType.IPV6}
    requires_key = True
    base_url = "https://api.abuseipdb.com/api/v2"

    def __init__(self) -> None:
        super().__init__()
        self.configured = bool(get_settings().abuseipdb_api_key)

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        api_key = get_credential("abuseipdb", "api_key", settings.abuseipdb_api_key)
        headers = {"Key": api_key, "Accept": "application/json"}
        params = {"ipAddress": ioc_value, "maxAgeInDays": 90, "verbose": ""}

        response = await client.get(f"{self.base_url}/check", headers=headers, params=params)
        if response.status_code == 404:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url=f"https://www.abuseipdb.com/check/{ioc_value}",
            )
        response.raise_for_status()
        payload = response.json()
        entry = payload.get("data") or {}

        if not entry:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                raw=payload,
                source_url=f"https://www.abuseipdb.com/check/{ioc_value}",
            )

        score = entry.get("abuseConfidenceScore", 0)
        total_reports = entry.get("totalReports", 0)

        if score > 25:
            verdict = "malicious"
        elif total_reports == 0:
            verdict = "unknown"
        else:
            verdict = "clean"

        data = {
            "verdict": verdict,
            "reputation_score": score,
            "abuse_confidence_score": score,
            "total_reports": total_reports,
            "num_distinct_users": entry.get("numDistinctUsers"),
            "is_whitelisted": entry.get("isWhitelisted"),
            "usage_type": entry.get("usageType"),
            "country_code": entry.get("countryCode"),
            "isp": entry.get("isp"),
            "domain": entry.get("domain"),
            "hostnames": entry.get("hostnames") or [],
            "is_tor": entry.get("isTor"),
            "last_seen": entry.get("lastReportedAt"),
            "reports": entry.get("reports") or [],
        }

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=payload,
            source_url=f"https://www.abuseipdb.com/check/{ioc_value}",
        )


abuseipdb_provider = AbuseIPDBProvider()
