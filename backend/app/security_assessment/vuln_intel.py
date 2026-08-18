"""Vulnerability-intelligence enrichment: given a detected service name +
version (e.g. from an Nmap banner), finds applicable CVEs.

NOT a reuse of app/providers/nvd.py's NVDProvider unchanged -- that
connector is keyed strictly on an already-known CVE ID (`cveId` query
param), since it only ever runs when the INVESTIGATION's own seed IOC is a
CVE. A port scan's starting point is a service+version, not a CVE ID, so
this module queries the same NVD REST API with `keywordSearch` instead,
sharing the exact same API key setting (`settings.nvd_api_key`) nvd.py
already uses.
"""
import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential

_NVD_BASE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"


def _best_cvss(metrics: dict) -> tuple[float | None, str | None]:
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key) or []
        if not entries:
            continue
        entry = next((e for e in entries if e.get("type") == "Primary"), entries[0])
        cvss_data = entry.get("cvssData") or {}
        return cvss_data.get("baseScore"), (cvss_data.get("baseSeverity") or entry.get("baseSeverity"))
    return None, None


async def search_cves_by_service(
    client: httpx.AsyncClient, product: str, version: str | None, limit: int = 5
) -> list[dict]:
    """Returns up to `limit` CVEs whose description/keyword matches the
    given product (and version, if known), each as
    {"cve_id", "cvss_score", "cvss_severity", "description"}. Never raises
    for an ordinary "no results"/network failure -- returns an empty list,
    since this is an enrichment step a scan finding should degrade
    gracefully without, not a hard dependency."""
    settings = get_settings()
    api_key = get_credential("nvd", "api_key", settings.nvd_api_key)
    headers = {"apiKey": api_key} if api_key else {}
    keyword = f"{product} {version}" if version else product

    try:
        response = await client.get(
            _NVD_BASE_URL,
            headers=headers,
            params={"keywordSearch": keyword, "resultsPerPage": limit},
            timeout=15.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return []

    payload = response.json()
    results = []
    for entry in (payload.get("vulnerabilities") or [])[:limit]:
        cve = entry.get("cve") or {}
        descriptions = cve.get("descriptions") or []
        description = next((d.get("value") for d in descriptions if d.get("lang") == "en"), None)
        score, severity = _best_cvss(cve.get("metrics") or {})
        cve_id = cve.get("id")
        if not cve_id:
            continue
        results.append(
            {"cve_id": cve_id, "cvss_score": score, "cvss_severity": severity, "description": description}
        )
    return results
