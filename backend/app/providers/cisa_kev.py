"""CISA Known Exploited Vulnerabilities (KEV) catalog connector.

Works without a key. The full catalog (~1MB JSON) is fetched and cached
in-memory, refreshed at most once per hour, since a single lookup only needs
one row out of thousands -- fetching the whole file per-request would be
wasteful under concurrent lookups. See app/providers/mitre_attack.py for the
same caching pattern applied to a much larger bundle.
"""
import time
from asyncio import Lock

import httpx

from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus

_CATALOG_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
_CACHE_TTL_SECONDS = 3600

_cache: dict[str, dict] = {}
_cache_fetched_at: float = 0.0
_cache_lock = Lock()


class CisaKevProvider(BaseProvider):
    provider_id = "cisa_kev"
    provider_name = "CISA Known Exploited Vulnerabilities"
    category = ProviderCategory.VULNERABILITY
    supported_types = {IOCType.CVE}
    requires_key = False
    base_url = _CATALOG_URL

    def __init__(self) -> None:
        super().__init__()
        self.configured = True

    async def _get_catalog(self, client: httpx.AsyncClient) -> dict[str, dict]:
        global _cache, _cache_fetched_at
        now = time.monotonic()
        if _cache and (now - _cache_fetched_at) < _CACHE_TTL_SECONDS:
            return _cache

        async with _cache_lock:
            # Re-check after acquiring the lock in case another task just refreshed it.
            now = time.monotonic()
            if _cache and (now - _cache_fetched_at) < _CACHE_TTL_SECONDS:
                return _cache

            response = await client.get(_CATALOG_URL)
            response.raise_for_status()
            payload = response.json()
            vulnerabilities = payload.get("vulnerabilities") or []
            _cache = {v["cveID"].upper(): v for v in vulnerabilities if v.get("cveID")}
            _cache_fetched_at = time.monotonic()
            return _cache

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        catalog = await self._get_catalog(client)
        entry = catalog.get(ioc_value.upper())

        if not entry:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
            )

        data = {
            "verdict": "malicious",
            "vulnerability_name": entry.get("vulnerabilityName"),
            "vendor_project": entry.get("vendorProject"),
            "product": entry.get("product"),
            "date_added": entry.get("dateAdded"),
            "short_description": entry.get("shortDescription"),
            "required_action": entry.get("requiredAction"),
            "due_date": entry.get("dueDate"),
            "known_ransomware_campaign_use": entry.get("knownRansomwareCampaignUse"),
            "notes": entry.get("notes"),
            "first_seen": entry.get("dateAdded"),
        }

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=entry,
            source_url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        )


cisa_kev_provider = CisaKevProvider()
