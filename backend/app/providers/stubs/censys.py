"""Censys connector -- uses the newer Censys Platform API (platform.censys.io).

Real, documented API (https://platform.censys.io, see
https://docs.censys.com/reference/platform-api): authenticates with a
Bearer Personal Access Token (`settings.censys_personal_access_token`), and
the Platform API additionally requires the organization ID that token
belongs to, sent as the `X-Organization-ID` header
(`settings.censys_organization_id`).
  - GET /v3/global/asset/host/{ip} -- current host view: open services
    (port/protocol/service_name), location, and autonomous_system.

`configured` is only True once both values are set; until then `run()`
short-circuits to ProviderStatus.NOT_CONFIGURED via the BaseProvider contract.
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class CensysProvider(BaseProvider):
    provider_id = "censys"
    provider_name = "Censys"
    category = ProviderCategory.PASSIVE_DNS
    supported_types = {IOCType.IPV4, IOCType.IPV6}
    requires_key = True
    base_url = "https://platform.censys.io"

    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self.configured = bool(
            settings.censys_personal_access_token and settings.censys_organization_id
        )

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        token = get_credential("censys", "personal_access_token", settings.censys_personal_access_token)
        org_id = get_credential("censys", "organization_id", settings.censys_organization_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Organization-ID": org_id,
            "Accept": "application/json",
        }
        source_url = f"https://platform.censys.io/hosts/{ioc_value}"

        response = await client.get(
            f"{self.base_url}/v3/global/asset/host/{ioc_value}", headers=headers
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
        payload = response.json()
        result = payload.get("result", {})

        services = [
            {
                "port": svc.get("port"),
                "protocol": svc.get("transport_protocol") or svc.get("protocol"),
                "service_name": svc.get("service_name") or svc.get("extended_service_name"),
            }
            for svc in result.get("services", [])
        ]

        location = result.get("location", {})
        autonomous_system = result.get("autonomous_system", {})

        data = {
            "verdict": "unknown",
            "services": services,
            "location": {
                "city": location.get("city"),
                "province": location.get("province"),
                "country": location.get("country"),
                "country_code": location.get("country_code"),
            },
            "autonomous_system": autonomous_system,
            "asn": autonomous_system.get("asn"),
            "as_owner": autonomous_system.get("name"),
            "last_seen": result.get("last_updated_at"),
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
            source_url=source_url,
        )


censys_provider = CensysProvider()
