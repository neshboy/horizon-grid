"""VirusTotal connector (public API v3, free tier: 4 req/min, 500/day).

Reference implementation for the BaseProvider contract -- see
app/providers/base.py for the interface every connector implements, and
docs/ARCHITECTURE.md#normalized-fields for the `data` keys the correlation
engine expects (resolved_ips, related_hashes, verdict, detection_ratio, etc).
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType, HASH_TYPES
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class VirusTotalProvider(BaseProvider):
    provider_id = "virustotal"
    provider_name = "VirusTotal"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.IPV4, IOCType.IPV6, IOCType.DOMAIN, IOCType.URL} | HASH_TYPES
    requires_key = True
    base_url = "https://www.virustotal.com/api/v3"

    def __init__(self) -> None:
        super().__init__()
        self.configured = bool(get_settings().virustotal_api_key)

    def _endpoint(self, ioc_value: str, ioc_type: IOCType) -> str:
        if ioc_type in HASH_TYPES:
            return f"{self.base_url}/files/{ioc_value}"
        if ioc_type == IOCType.IPV4 or ioc_type == IOCType.IPV6:
            return f"{self.base_url}/ip_addresses/{ioc_value}"
        if ioc_type == IOCType.DOMAIN:
            return f"{self.base_url}/domains/{ioc_value}"
        if ioc_type == IOCType.URL:
            import base64

            encoded = base64.urlsafe_b64encode(ioc_value.encode()).decode().strip("=")
            return f"{self.base_url}/urls/{encoded}"
        raise ValueError(f"Unsupported IOC type for VirusTotal: {ioc_type}")

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        api_key = get_credential("virustotal", "api_key", settings.virustotal_api_key)
        headers = {"x-apikey": api_key}
        url = self._endpoint(ioc_value, ioc_type)

        response = await client.get(url, headers=headers)
        if response.status_code == 404:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url=f"https://www.virustotal.com/gui/search/{ioc_value}",
            )
        response.raise_for_status()
        payload = response.json()
        attributes = payload.get("data", {}).get("attributes", {})

        stats = attributes.get("last_analysis_stats", {})
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        total = sum(stats.values()) if stats else 0

        verdict = "unknown"
        if total:
            if malicious > 0:
                verdict = "malicious"
            elif suspicious > 0:
                verdict = "suspicious"
            else:
                verdict = "clean"

        data: dict = {
            "verdict": verdict,
            "detection_ratio": f"{malicious + suspicious}/{total}" if total else "0/0",
            "malicious_count": malicious,
            "suspicious_count": suspicious,
            "total_engines": total,
            "reputation_score": attributes.get("reputation"),
            "last_analysis_date": attributes.get("last_analysis_date"),
            "tags": attributes.get("tags", []),
        }

        if ioc_type in HASH_TYPES:
            data.update(
                {
                    "file_type": attributes.get("type_description"),
                    "file_names": attributes.get("names", [])[:10],
                    "md5": attributes.get("md5"),
                    "sha1": attributes.get("sha1"),
                    "sha256": attributes.get("sha256"),
                    "first_seen": attributes.get("first_submission_date"),
                    "last_seen": attributes.get("last_submission_date"),
                    "malware_families": [
                        v for v in attributes.get("popular_threat_classification", {})
                        .get("suggested_threat_label", "")
                        .split("/")
                        if v
                    ],
                }
            )
        elif ioc_type in (IOCType.IPV4, IOCType.IPV6):
            data.update(
                {
                    "asn": attributes.get("asn"),
                    "as_owner": attributes.get("as_owner"),
                    "country": attributes.get("country"),
                    "network": attributes.get("network"),
                }
            )
        elif ioc_type == IOCType.DOMAIN:
            data.update(
                {
                    "resolved_ips": [
                        r.get("value")
                        for r in attributes.get("last_dns_records", [])
                        if r.get("type") in ("A", "AAAA") and r.get("value")
                    ],
                    "registrar": attributes.get("registrar"),
                    "creation_date": attributes.get("creation_date"),
                }
            )
        elif ioc_type == IOCType.URL:
            data.update(
                {
                    "final_url": attributes.get("last_final_url"),
                    "title": attributes.get("title"),
                }
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
            source_url=f"https://www.virustotal.com/gui/search/{ioc_value}",
        )


virustotal_provider = VirusTotalProvider()
