"""PhishTank connector -- free community-sourced phishing URL verification.

PhishTank's `checkurl` API works without an API key (`app_key` is optional
and only raises rate limits), so this connector is `requires_key = False`
and always `configured = True`. If `settings.phishtank_api_key` is set it is
sent as the `app_key` form field for a higher rate limit. See
https://www.phishtank.com/api_info.php for the documented request/response
shape.
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class PhishTankProvider(BaseProvider):
    provider_id = "phishtank"
    provider_name = "PhishTank"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.URL}
    requires_key = False
    configured = True
    base_url = "https://checkurl.phishtank.com/checkurl/"

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        api_key = get_credential("phishtank", "api_key", settings.phishtank_api_key)
        form = {"url": ioc_value, "format": "json"}
        if api_key:
            form["app_key"] = api_key

        response = await client.post(self.base_url, data=form)
        if response.status_code == 404:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url="https://www.phishtank.com/",
            )
        response.raise_for_status()
        payload = response.json()

        results = payload.get("results") or {}
        if not results.get("in_database"):
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                raw=payload,
                source_url="https://www.phishtank.com/",
            )

        valid = results.get("valid")
        verdict = "malicious" if valid else "suspicious"

        data = {
            "verdict": verdict,
            "in_database": results.get("in_database", False),
            "valid": valid,
            "verified": results.get("verified"),
            "verified_at": results.get("verified_at"),
            "submission_time": results.get("submission_time"),
            "phish_id": results.get("phish_id"),
            "phish_detail_page": results.get("phish_detail_page"),
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
            source_url=results.get("phish_detail_page") or "https://www.phishtank.com/",
        )


phishtank_provider = PhishTankProvider()
