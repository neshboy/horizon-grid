"""Unit tests for app/providers/nvd.py.

Real, confirmed bug: NVD's real API returns HTTP 404 specifically for a
request-level error -- an invalid/expired apiKey or a malformed cveId --
never for a genuinely nonexistent CVE (a real, nonexistent CVE returns HTTP
200 with vulnerabilities: [], confirmed live and covered below by
test_genuinely_nonexistent_cve_maps_to_no_data). The 404 branch previously
mapped straight to ProviderStatus.NO_DATA with no error_message, so a
bad/expired NVD API key silently looked identical to "this CVE does not
exist" -- hiding real vulnerability data (e.g. Log4Shell) from the analyst
with zero indication the key was misconfigured. All HTTP is mocked with
respx, matching the pattern used in app/tests/unit/test_urlscan_io.py.
"""
import httpx
import pytest
import respx

from app.ioc.types import IOCType
from app.providers.base import ProviderStatus
from app.providers.nvd import NVDProvider


@pytest.fixture
def provider():
    return NVDProvider()


@pytest.fixture
def client():
    return httpx.AsyncClient()


@pytest.mark.asyncio
@respx.mock
async def test_invalid_api_key_404_maps_to_error_not_no_data(provider, client):
    """The exact bug, reproduced end-to-end: a bad/expired NVD apiKey must
    surface as a visible error, not collapse into "no vulnerability found"."""
    from app.core.runtime_context import set_provider_overrides

    respx.get("https://services.nvd.nist.gov/rest/json/cves/2.0").mock(
        return_value=httpx.Response(404, headers={"message": "Invalid apiKey."})
    )

    set_provider_overrides({"nvd": {"enabled": True, "configured": True, "credentials": {"api_key": "totally-invalid-key-123"}}})
    try:
        result = await provider.fetch("CVE-2021-44228", IOCType.CVE, client)
    finally:
        set_provider_overrides({})

    assert result.status == ProviderStatus.ERROR
    assert result.status != ProviderStatus.NO_DATA
    assert result.error_message
    assert "apikey" in result.error_message.lower() or "invalid" in result.error_message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_malformed_cve_id_404_maps_to_error_without_api_key(provider, client):
    respx.get("https://services.nvd.nist.gov/rest/json/cves/2.0").mock(
        return_value=httpx.Response(404, headers={"message": "Invalid cveId parameter"})
    )

    result = await provider.fetch("not-a-real-cve-id", IOCType.CVE, client)

    assert result.status == ProviderStatus.ERROR
    assert result.error_message


@pytest.mark.asyncio
@respx.mock
async def test_genuinely_nonexistent_cve_maps_to_no_data(provider, client):
    """The case the old 404 branch was (wrongly) written for -- NVD's real
    behavior for a genuinely nonexistent CVE is HTTP 200 with an empty
    vulnerabilities array, not 404."""
    respx.get("https://services.nvd.nist.gov/rest/json/cves/2.0").mock(
        return_value=httpx.Response(200, json={"vulnerabilities": []})
    )

    result = await provider.fetch("CVE-1999-9999", IOCType.CVE, client)

    assert result.status == ProviderStatus.NO_DATA
    assert result.error_message is None


@pytest.mark.asyncio
@respx.mock
async def test_successful_lookup_still_maps_to_ok(provider, client):
    payload = {
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2021-44228",
                    "descriptions": [{"lang": "en", "value": "Log4Shell"}],
                    "metrics": {
                        "cvssMetricV31": [
                            {"type": "Primary", "cvssData": {"baseScore": 10.0, "baseSeverity": "CRITICAL", "vectorString": "AV:N"}}
                        ]
                    },
                    "vulnStatus": "Analyzed",
                }
            }
        ]
    }
    respx.get("https://services.nvd.nist.gov/rest/json/cves/2.0").mock(return_value=httpx.Response(200, json=payload))

    result = await provider.fetch("CVE-2021-44228", IOCType.CVE, client)

    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "malicious"
    assert result.data["cve_id"] == "CVE-2021-44228"
