"""NIST NVD (National Vulnerability Database) CVE API v2.0 connector.

Works without an API key (rate-limited to ~5 req/30s); if
settings.nvd_api_key is configured, it is sent via the "apiKey" header for a
much higher rate limit (~50 req/30s). See app/providers/base.py for the
BaseProvider contract and app/providers/virustotal.py for the reference
connector style.
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class NVDProvider(BaseProvider):
    provider_id = "nvd"
    provider_name = "NIST NVD"
    category = ProviderCategory.VULNERABILITY
    supported_types = {IOCType.CVE}
    requires_key = False
    base_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    def __init__(self) -> None:
        super().__init__()
        # NVD works unauthenticated -- an apiKey only raises the rate limit.
        self.configured = True

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        settings = get_settings()
        api_key = get_credential("nvd", "api_key", settings.nvd_api_key)
        headers = {}
        if api_key:
            headers["apiKey"] = api_key

        response = await client.get(self.base_url, headers=headers, params={"cveId": ioc_value})
        if response.status_code == 404:
            # NVD's real API only ever returns HTTP 404 for a request-level
            # error -- an invalid/expired apiKey or a malformed cveId -- never
            # for a genuinely nonexistent CVE (confirmed live: a real,
            # nonexistent CVE returns HTTP 200 with vulnerabilities: [],
            # already handled correctly below). Treating 404 as NO_DATA would
            # silently misreport a bad/expired NVD key as "nothing found for
            # this CVE", hiding real vulnerability data with no indication
            # anything is misconfigured.
            detail = response.headers.get("message") or response.text or "no further detail provided"
            reason = "invalid/expired NVD apiKey" if api_key else "malformed cveId or rejected request"
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.ERROR,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                error_message=f"NVD API request rejected ({reason}): {detail}",
                source_url=f"https://nvd.nist.gov/vuln/detail/{ioc_value}",
            )
        response.raise_for_status()
        payload = response.json()

        vulnerabilities = payload.get("vulnerabilities") or []
        if not vulnerabilities:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                raw=payload,
                source_url=f"https://nvd.nist.gov/vuln/detail/{ioc_value}",
            )

        cve = vulnerabilities[0].get("cve") or {}
        data = self._map(cve)

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=payload,
            source_url=f"https://nvd.nist.gov/vuln/detail/{ioc_value}",
        )

    @staticmethod
    def _best_metric(metrics: dict) -> tuple[float | None, str | None, str | None]:
        """Prefers CVSS v3.1, falls back to v3.0, then v2 -- returns (score, severity, vector)."""
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            entries = metrics.get(key) or []
            if not entries:
                continue
            # Prefer the "Primary" scoring source if present.
            entry = next((e for e in entries if e.get("type") == "Primary"), entries[0])
            cvss_data = entry.get("cvssData") or {}
            score = cvss_data.get("baseScore")
            severity = cvss_data.get("baseSeverity") or entry.get("baseSeverity")
            vector = cvss_data.get("vectorString")
            return score, severity, vector
        return None, None, None

    @staticmethod
    def _severity_to_verdict(severity: str | None) -> str:
        if not severity:
            return "unknown"
        severity = severity.upper()
        if severity in ("CRITICAL", "HIGH"):
            return "malicious"
        if severity in ("MEDIUM", "LOW"):
            return "suspicious"
        return "unknown"

    def _map(self, cve: dict) -> dict:
        descriptions = cve.get("descriptions") or []
        description = next((d.get("value") for d in descriptions if d.get("lang") == "en"), None)

        metrics = cve.get("metrics") or {}
        score, severity, vector = self._best_metric(metrics)

        cwes = sorted(
            {
                desc.get("value")
                for weakness in (cve.get("weaknesses") or [])
                for desc in (weakness.get("description") or [])
                if desc.get("value") and desc.get("value") != "NVD-CWE-noinfo"
            }
        )

        references = [ref.get("url") for ref in (cve.get("references") or []) if ref.get("url")]

        return {
            "verdict": self._severity_to_verdict(severity),
            "cve_id": cve.get("id"),
            "cvss_score": score,
            "cvss_severity": severity,
            "cvss_vector": vector,
            "description": description,
            "vuln_status": cve.get("vulnStatus"),
            "cwes": cwes,
            "references": references,
            "configurations": cve.get("configurations") or [],
            "first_seen": cve.get("published"),
            "last_seen": cve.get("lastModified"),
        }


nvd_provider = NVDProvider()
