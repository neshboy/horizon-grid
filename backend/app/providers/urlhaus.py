"""URLhaus connector (abuse.ch) -- known malware-distribution URL/host lookups.

URLhaus now requires a free abuse.ch account Auth-Key, sent via the
"Auth-Key" header (shared across URLhaus/ThreatFox/MalwareBazaar, see
settings.abusech_auth_key). See app/providers/base.py for the BaseProvider
contract and app/providers/virustotal.py for the reference connector style.
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType
from app.providers.abusech import map_query_status
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class URLhausProvider(BaseProvider):
    provider_id = "urlhaus"
    provider_name = "URLhaus"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.URL, IOCType.DOMAIN, IOCType.IPV4}
    requires_key = True
    base_url = "https://urlhaus-api.abuse.ch/v1"

    def __init__(self) -> None:
        super().__init__()
        self.configured = bool(get_settings().abusech_auth_key)

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        headers = {"Auth-Key": get_credential("urlhaus", "auth_key", settings.abusech_auth_key)}

        if ioc_type == IOCType.URL:
            endpoint = f"{self.base_url}/url/"
            form = {"url": ioc_value}
        else:  # DOMAIN or IPV4 -- URLhaus treats both as "host" lookups
            endpoint = f"{self.base_url}/host/"
            form = {"host": ioc_value}

        response = await client.post(endpoint, data=form, headers=headers)
        if response.status_code == 404:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url="https://urlhaus.abuse.ch/",
            )
        response.raise_for_status()
        payload = response.json()

        query_status = payload.get("query_status")
        if query_status != "ok":
            status, error_message = map_query_status(query_status)
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=status,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                raw=payload,
                error_message=error_message,
                source_url="https://urlhaus.abuse.ch/",
            )

        data = self._map_url(payload) if ioc_type == IOCType.URL else self._map_host(payload)

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=payload,
            source_url=payload.get("urlhaus_reference") or "https://urlhaus.abuse.ch/",
        )

    @staticmethod
    def _map_url(payload: dict) -> dict:
        payloads = payload.get("payloads") or []
        related_hashes = [p.get("sha256_hash") for p in payloads if p.get("sha256_hash")]
        return {
            "verdict": "malicious",
            "query_status": payload.get("query_status"),
            "url_status": payload.get("url_status"),
            "threat": payload.get("threat"),
            "tags": payload.get("tags") or [],
            "host": payload.get("host"),
            "first_seen": payload.get("date_added"),
            "last_seen": payload.get("last_online"),
            "related_hashes": related_hashes,
            "payloads": payloads,
            "blacklists": payload.get("blacklists"),
        }

    @staticmethod
    def _map_host(payload: dict) -> dict:
        urls = payload.get("urls") or []
        related_urls = [u.get("url") for u in urls if u.get("url")]
        tags = sorted({tag for u in urls for tag in (u.get("tags") or [])})
        threats = sorted({u.get("threat") for u in urls if u.get("threat")})
        return {
            "verdict": "malicious" if urls else "unknown",
            "query_status": payload.get("query_status"),
            "url_count": payload.get("url_count"),
            "first_seen": payload.get("firstseen"),
            "related_urls": related_urls,
            "threat": threats[0] if len(threats) == 1 else threats,
            "tags": tags,
            "blacklists": payload.get("blacklists"),
        }


urlhaus_provider = URLhausProvider()
