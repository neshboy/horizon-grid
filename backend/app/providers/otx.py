"""AlienVault OTX (Open Threat Exchange) connector.

Requires a free OTX API key, sent via the "X-OTX-API-KEY" header. See
app/providers/base.py for the BaseProvider contract and
app/providers/virustotal.py for the reference connector style.
"""
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import HASH_TYPES, IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus

# Maps our IOCType to the OTX indicator "section" used in the URL path.
_SECTION_BY_TYPE: dict[IOCType, str] = {
    IOCType.IPV4: "IPv4",
    IOCType.IPV6: "IPv6",
    IOCType.DOMAIN: "domain",
    IOCType.HOSTNAME: "hostname",
    IOCType.URL: "url",
}


class OTXProvider(BaseProvider):
    provider_id = "otx"
    provider_name = "AlienVault OTX"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.IPV4, IOCType.IPV6, IOCType.DOMAIN, IOCType.HOSTNAME, IOCType.URL} | HASH_TYPES
    requires_key = True
    base_url = "https://otx.alienvault.com/api/v1"

    def __init__(self) -> None:
        super().__init__()
        self.configured = bool(get_settings().otx_api_key)

    @staticmethod
    def _section(ioc_type: IOCType) -> str:
        if ioc_type in HASH_TYPES:
            return "file"
        return _SECTION_BY_TYPE[ioc_type]

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        api_key = get_credential("otx", "api_key", settings.otx_api_key)
        headers = {"X-OTX-API-KEY": api_key}
        section = self._section(ioc_type)
        indicator = quote(ioc_value, safe="")
        url = f"{self.base_url}/indicators/{section}/{indicator}/general"

        response = await client.get(url, headers=headers)
        if response.status_code == 404:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url=f"https://otx.alienvault.com/indicator/{section}/{ioc_value}",
            )
        response.raise_for_status()
        payload = response.json()

        pulse_info = payload.get("pulse_info") or {}
        pulses = pulse_info.get("pulses") or []
        pulse_count = pulse_info.get("count", len(pulses))

        if not pulse_count:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                raw=payload,
                source_url=f"https://otx.alienvault.com/indicator/{section}/{ioc_value}",
            )

        data = self._map(payload, pulses, pulse_count, ioc_type)

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=payload,
            source_url=f"https://otx.alienvault.com/indicator/{section}/{ioc_value}",
        )

    @staticmethod
    def _name_of(entry) -> str | None:
        if isinstance(entry, str):
            return entry or None
        if isinstance(entry, dict):
            return entry.get("display_name") or entry.get("name")
        return None

    def _map(self, payload: dict, pulses: list[dict], pulse_count: int, ioc_type: IOCType) -> dict:
        malware_families = sorted(
            {
                name
                for pulse in pulses
                for name in (self._name_of(mf) for mf in (pulse.get("malware_families") or []))
                if name
            }
        )
        threat_actors = sorted(
            {pulse.get("adversary") for pulse in pulses if pulse.get("adversary")}
        )
        campaigns = sorted({pulse.get("name") for pulse in pulses if pulse.get("name")})
        tags = sorted({tag for pulse in pulses for tag in (pulse.get("tags") or []) if tag})
        references = [ref for pulse in pulses for ref in (pulse.get("references") or []) if ref][:25]

        created_dates = sorted(p.get("created") for p in pulses if p.get("created"))
        modified_dates = sorted(p.get("modified") for p in pulses if p.get("modified"))

        data: dict = {
            "verdict": "malicious" if pulse_count > 0 else "unknown",
            "pulse_count": pulse_count,
            "malware_families": malware_families,
            "threat_actors": threat_actors,
            "campaigns": campaigns,
            "tags": tags,
            "references": references,
            "reputation": payload.get("reputation"),
            "first_seen": created_dates[0] if created_dates else None,
            "last_seen": modified_dates[-1] if modified_dates else None,
        }

        if ioc_type in (IOCType.IPV4, IOCType.IPV6):
            data.update(
                {
                    "asn": payload.get("asn"),
                    "country": payload.get("country_name") or payload.get("country_code"),
                }
            )
        elif ioc_type in (IOCType.DOMAIN, IOCType.HOSTNAME):
            data.update(
                {
                    "alexa": payload.get("alexa"),
                    "whois": payload.get("whois"),
                }
            )
        elif ioc_type == IOCType.URL:
            data.update(
                {
                    "resolved_domains": [payload.get("domain")] if payload.get("domain") else [],
                    "hostname": payload.get("hostname"),
                }
            )
        elif ioc_type in HASH_TYPES:
            data.update(
                {
                    "file_type": payload.get("type"),
                }
            )

        return data


otx_provider = OTXProvider()
