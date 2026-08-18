"""ThreatFox connector (abuse.ch) -- IOC-to-malware-family threat intel.

Requires a free abuse.ch account Auth-Key, sent via the "Auth-Key" header
(shared across URLhaus/ThreatFox/MalwareBazaar, see settings.abusech_auth_key).
See app/providers/base.py for the BaseProvider contract and
app/providers/virustotal.py for the reference connector style.
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType
from app.providers.abusech import map_query_status
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class ThreatFoxProvider(BaseProvider):
    provider_id = "threatfox"
    provider_name = "ThreatFox"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {
        IOCType.IPV4,
        IOCType.IPV6,
        IOCType.DOMAIN,
        IOCType.URL,
        IOCType.MD5,
        IOCType.SHA256,
    }
    requires_key = True
    base_url = "https://threatfox-api.abuse.ch/api/v1/"

    def __init__(self) -> None:
        super().__init__()
        self.configured = bool(get_settings().abusech_auth_key)

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        headers = {"Auth-Key": get_credential("threatfox", "auth_key", settings.abusech_auth_key)}
        body = {"query": "search_ioc", "search_term": ioc_value}

        response = await client.post(self.base_url, json=body, headers=headers)
        if response.status_code == 404:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url="https://threatfox.abuse.ch/browse/",
            )
        response.raise_for_status()
        payload = response.json()

        query_status = payload.get("query_status")
        entries = payload.get("data") or []
        if query_status != "ok" or not entries:
            status, error_message = map_query_status(query_status)
            if status == ProviderStatus.OK:
                # "ok" with zero entries is a genuine empty result, not an error.
                status = ProviderStatus.NO_DATA
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=status,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                raw=payload,
                error_message=error_message,
                source_url="https://threatfox.abuse.ch/browse/",
            )

        data = self._map(entries)

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=payload,
            source_url="https://threatfox.abuse.ch/browse/",
        )

    @staticmethod
    def _map(entries: list[dict]) -> dict:
        malware_families = sorted(
            {e.get("malware_printable") or e.get("malware") for e in entries if e.get("malware") or e.get("malware_printable")}
        )
        threat_types = sorted({e.get("threat_type") for e in entries if e.get("threat_type")})
        tags = sorted({tag for e in entries for tag in (e.get("tags") or []) if tag})
        references = [e.get("reference") for e in entries if e.get("reference")]
        first_seen_values = sorted(e.get("first_seen") for e in entries if e.get("first_seen"))
        last_seen_values = sorted(e.get("last_seen") for e in entries if e.get("last_seen"))
        confidence_levels = [e.get("confidence_level") for e in entries if e.get("confidence_level") is not None]

        return {
            "verdict": "malicious",
            "ioc_type": entries[0].get("ioc_type"),
            "threat_type": threat_types[0] if len(threat_types) == 1 else threat_types,
            "malware_families": malware_families,
            "confidence_level": max(confidence_levels) if confidence_levels else None,
            "first_seen": first_seen_values[0] if first_seen_values else None,
            "last_seen": last_seen_values[-1] if last_seen_values else None,
            "tags": tags,
            "reference": references[0] if references else None,
            "matches": entries,
        }


threatfox_provider = ThreatFoxProvider()
