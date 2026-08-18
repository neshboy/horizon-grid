"""crt.sh connector -- Certificate Transparency log search, no API key required.

Queries crt.sh's JSON search endpoint for a domain and maps each certificate
entry into `data["certificates"]`, capped at the 25 most recent, plus any
subdomains discovered in `name_value` into `data["related_domains"]`. See
app/providers/base.py for the BaseProvider contract and
app/providers/virustotal.py for the reference connector style.

crt.sh is a free community service backed by a Postgres instance that is
sometimes slow/flaky and has been known to emit malformed JSON (duplicate
key ordering issues, or truncated output under load) -- a parse failure is
treated as ProviderStatus.NO_DATA rather than propagating, per the CERTIFICATE_INTEL
connector contract.
"""
import json

import httpx

from app.core.config import get_settings
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus

_MAX_CERTIFICATES = 25


class CrtShProvider(BaseProvider):
    provider_id = "crtsh"
    provider_name = "crt.sh"
    category = ProviderCategory.CERTIFICATE_INTEL
    supported_types = {IOCType.DOMAIN, IOCType.TLS_CERTIFICATE}
    requires_key = False
    base_url = "https://crt.sh"

    def __init__(self) -> None:
        super().__init__()
        self.configured = True

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        headers = {"User-Agent": settings.crawler_user_agent}
        source_url = f"https://crt.sh/?q={ioc_value}"

        response = await client.get(
            f"{self.base_url}/", params={"q": ioc_value, "output": "json"}, headers=headers
        )
        if response.status_code == 404:
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

        # crt.sh occasionally returns an empty body or malformed/truncated JSON
        # (concatenated objects without a valid enclosing array) under load --
        # guard the parse and degrade to NO_DATA rather than raising.
        try:
            entries = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                error_message="crt.sh returned malformed JSON",
                source_url=source_url,
            )

        if not entries or not isinstance(entries, list):
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url=source_url,
            )

        data = self._map(entries, ioc_value)

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=entries,
            source_url=source_url,
        )

    @staticmethod
    def _map(entries: list[dict], ioc_value: str) -> dict:
        # Most recent first, by entry_timestamp (falls back to id ordering if absent).
        def _sort_key(entry: dict):
            return entry.get("entry_timestamp") or ""

        sorted_entries = sorted(entries, key=_sort_key, reverse=True)

        certificates: list[dict] = []
        related_domains: set[str] = set()
        seed = ioc_value.strip().lower()

        for entry in sorted_entries[:_MAX_CERTIFICATES]:
            name_value = entry.get("name_value") or ""
            names = sorted({n.strip().lower() for n in name_value.split("\n") if n.strip()})

            certificates.append(
                {
                    "issuer_name": entry.get("issuer_name"),
                    "common_name": entry.get("common_name"),
                    "name_value": names,
                    "not_before": entry.get("not_before"),
                    "not_after": entry.get("not_after"),
                    "serial_number": entry.get("serial_number"),
                    "id": entry.get("id"),
                    "entry_timestamp": entry.get("entry_timestamp"),
                }
            )

            for name in names:
                candidate = name.lstrip("*.")
                if candidate and candidate != seed:
                    related_domains.add(candidate)

        return {
            "certificates": certificates,
            "certificate_count": len(entries),
            "related_domains": sorted(related_domains),
        }


crtsh_provider = CrtShProvider()
