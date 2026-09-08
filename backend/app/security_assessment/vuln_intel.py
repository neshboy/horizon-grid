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
import re

import httpx

from app.core.config import get_settings
from app.core.runtime_context import get_credential

_NVD_BASE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"


def _normalize_token(value: str) -> str:
    """Collapses a CPE vendor/product slug or an Nmap-detected product name
    down to bare lowercase alphanumerics for a forgiving comparison -- CPE
    slugs use underscores where a real-world banner uses spaces/mixed case
    (e.g. Nmap's "Apache httpd" banner vs. NVD's own `apache:http_server`
    CPE), so an exact string compare would wrongly reject a real match on
    formatting alone."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _cve_applies_to_product(cve: dict, product: str) -> bool:
    """Real, confirmed bug (live-reproduced against this backend's own
    Uvicorn port): NVD's `keywordSearch` is a loose free-text match against
    the WHOLE CVE record (description, references, etc.), not just its
    actual affected product -- it happily returned CVE-2025-27519 (a path-
    traversal RCE in TrueFoundry's unrelated "Cognita" RAG framework, whose
    advisory merely mentions "the docker environment sets up the backend
    uvicorn server") and CVE-2026-26209 (a DoS in the unrelated `cbor2`
    CBOR library, whose advisory merely says it can crash "web application
    servers (e.g. Gunicorn, Uvicorn)") for a keyword search of "Uvicorn"
    alone.

    NVD's own CPE `configurations` on that SAME CVE record is its curated,
    structured statement of which product(s) the CVE actually applies to
    (confirmed live: the two real Uvicorn CVEs carry a
    `cpe:2.3:a:encode:uvicorn:...` match; Cognita and cbor2 do not), so
    require the scanned product to match a `vulnerable` CPE entry's vendor
    or product component there before treating the CVE as real evidence
    for this service. A CVE with no configuration data at all (not yet
    CPE-tagged by NVD -- e.g. a brand-new "Deferred"/"Awaiting Analysis"
    candidate, which is exactly how the unrelated Cognita CVE above showed
    up) can't be confirmed this way either and is excluded for the same
    reason: an unconfirmable keyword hit must never be handed to an
    analyst as applicability evidence."""
    target = _normalize_token(product)
    if not target:
        return False
    for node in cve.get("configurations") or []:
        for sub in node.get("nodes") or []:
            for cpe_match in sub.get("cpeMatch") or []:
                if not cpe_match.get("vulnerable", True):
                    continue
                parts = (cpe_match.get("criteria") or "").split(":")
                if len(parts) <= 4:
                    continue
                vendor, cpe_product = _normalize_token(parts[3]), _normalize_token(parts[4])
                for candidate in (vendor, cpe_product):
                    if candidate and (candidate in target or target in candidate):
                        return True
    return False


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
    for entry in payload.get("vulnerabilities") or []:
        cve = entry.get("cve") or {}
        cve_id = cve.get("id")
        if not cve_id:
            continue
        # NVD's own vulnStatus marks a candidate number that was withdrawn
        # by its CNA / never a real security issue as "Rejected" -- it still
        # keyword-matches (the rejection notice text itself often contains
        # the product name) but is not a vulnerability at all, and must
        # never be counted as one. Every other status (Received, Awaiting
        # Analysis, Undergoing Analysis, Analyzed, Modified, Deferred) still
        # represents a real, if not yet fully scored, CVE record and is kept.
        if (cve.get("vulnStatus") or "").strip().lower() == "rejected":
            continue
        if not _cve_applies_to_product(cve, product):
            continue
        descriptions = cve.get("descriptions") or []
        description = next((d.get("value") for d in descriptions if d.get("lang") == "en"), None)
        score, severity = _best_cvss(cve.get("metrics") or {})
        results.append(
            {"cve_id": cve_id, "cvss_score": score, "cvss_severity": severity, "description": description}
        )
        if len(results) >= limit:
            break
    return results
