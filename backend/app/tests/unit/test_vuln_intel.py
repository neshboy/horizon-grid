"""Unit tests for app/security_assessment/vuln_intel.py.

Real, confirmed bug #1 (live-reproduced against a Pentest Suite scan of
127.0.0.1:8000, this backend's own Uvicorn port): search_cves_by_service()
never read NVD's own `vulnStatus` field on each returned CVE record, so a
formally REJECTED/withdrawn candidate number (confirmed live against NVD's
real API: CVE-2025-15603 has vulnStatus "Rejected" and a description
literally starting "** REJECT ** DO NOT USE THIS CANDIDATE NUMBER ...") that
still keyword-matched the scanned service was returned identically to a
real, accepted vulnerability -- inflating the finding's CVE count/title,
bumping its severity (nmap_tool.py's _severity_for_cves) and confidence
(pentest/orchestrator.py's _confidence_for_finding to LIKELY), and
propagating into the correlation engine's 'exploits' relationship edges
(app/correlation/engine.py reads straight off this same data). All HTTP is
mocked with respx, matching the pattern used in app/tests/unit/test_nvd_provider.py.

Real, confirmed bug #2 (same live scan, same NVD keyword search of
"Uvicorn" alone -- confirmed against NVD's real API on 2026-09-07):
search_cves_by_service() passed `keywordSearch` straight through with no
relevance check at all beyond the Rejected-status filter above, so it also
returned CVE-2025-27519 (a path-traversal RCE in TrueFoundry's completely
unrelated "Cognita" RAG framework, whose advisory merely mentions "the
docker environment sets up the backend uvicorn server") and CVE-2026-26209
(a DoS in the unrelated `cbor2` CBOR library, whose advisory merely notes it
can crash "web application servers (e.g. Gunicorn, Uvicorn)") -- neither
CVE is about Uvicorn itself, both are just NVD free-text keyword hits on
CVE records that happen to mention it in passing. NVD's own CPE
`configurations` on each CVE record is its curated, structured statement of
which product(s) that CVE actually applies to (the two real Uvicorn CVEs
each carry a `cpe:2.3:a:encode:uvicorn:...` match; Cognita and cbor2 do
not), so search_cves_by_service() must cross-check that before treating a
keyword hit as real evidence.
"""
import httpx
import pytest
import respx

from app.security_assessment.vuln_intel import search_cves_by_service

_NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"


@pytest.fixture
def client():
    return httpx.AsyncClient()


def _cve_entry(
    cve_id: str,
    vuln_status: str,
    description: str,
    score: float | None = None,
    cpe: str | list[str] | None = None,
) -> dict:
    entry = {
        "cve": {
            "id": cve_id,
            "vulnStatus": vuln_status,
            "descriptions": [{"lang": "en", "value": description}],
            "metrics": {},
        }
    }
    if score is not None:
        entry["cve"]["metrics"] = {
            "cvssMetricV31": [{"type": "Primary", "cvssData": {"baseScore": score, "baseSeverity": "HIGH"}}]
        }
    if cpe is not None:
        cpe_list = [cpe] if isinstance(cpe, str) else cpe
        entry["cve"]["configurations"] = [
            {"nodes": [{"cpeMatch": [{"vulnerable": True, "criteria": c} for c in cpe_list]}]}
        ]
    return entry


@pytest.mark.asyncio
@respx.mock
async def test_rejected_cve_is_excluded_from_results(client):
    """The exact bug, reproduced end-to-end: a REJECTED NVD candidate number
    that still keyword-matches the scanned service must never be surfaced as
    a real vulnerability match."""
    payload = {
        "vulnerabilities": [
            _cve_entry(
                "CVE-2025-15603",
                "Rejected",
                "** REJECT ** DO NOT USE THIS CANDIDATE NUMBER. ... it was not a security issue.",
            ),
            _cve_entry(
                "CVE-2024-9999",
                "Analyzed",
                "A real Uvicorn vulnerability.",
                score=8.1,
                cpe="cpe:2.3:a:encode:uvicorn:*:*:*:*:*:*:*:*",
            ),
        ]
    }
    respx.get(_NVD_URL).mock(return_value=httpx.Response(200, json=payload))

    results = await search_cves_by_service(client, "Uvicorn", "1.0", limit=5)

    cve_ids = [r["cve_id"] for r in results]
    assert "CVE-2025-15603" not in cve_ids
    assert cve_ids == ["CVE-2024-9999"]


@pytest.mark.asyncio
@respx.mock
async def test_non_rejected_statuses_are_still_included(client):
    """Guards against an overly-aggressive fix: every other real NVD status
    (not just "Analyzed") must still be treated as a genuine CVE match, as
    long as NVD's own CPE data confirms the scanned product is what the CVE
    actually applies to."""
    someservice_cpe = "cpe:2.3:a:vendor:someservice:*:*:*:*:*:*:*:*"
    payload = {
        "vulnerabilities": [
            _cve_entry("CVE-2024-1001", "Awaiting Analysis", "desc one", score=5.0, cpe=someservice_cpe),
            _cve_entry("CVE-2024-1002", "Undergoing Analysis", "desc two", score=6.0, cpe=someservice_cpe),
            _cve_entry("CVE-2024-1003", "Modified", "desc three", score=7.0, cpe=someservice_cpe),
        ]
    }
    respx.get(_NVD_URL).mock(return_value=httpx.Response(200, json=payload))

    results = await search_cves_by_service(client, "SomeService", None, limit=5)

    assert {r["cve_id"] for r in results} == {"CVE-2024-1001", "CVE-2024-1002", "CVE-2024-1003"}


@pytest.mark.asyncio
@respx.mock
async def test_limit_is_still_respected_after_filtering_rejected(client):
    """The `limit` cap must apply to genuine matches, not just to the raw
    (pre-filter) page returned by NVD -- otherwise a rejected entry could
    silently displace a real one within the same page."""
    someservice_cpe = "cpe:2.3:a:vendor:someservice:*:*:*:*:*:*:*:*"
    payload = {
        "vulnerabilities": [
            _cve_entry("CVE-2025-15603", "Rejected", "rejected candidate"),
            _cve_entry("CVE-2024-2001", "Analyzed", "real one", score=4.0, cpe=someservice_cpe),
            _cve_entry("CVE-2024-2002", "Analyzed", "real two", score=5.0, cpe=someservice_cpe),
        ]
    }
    respx.get(_NVD_URL).mock(return_value=httpx.Response(200, json=payload))

    results = await search_cves_by_service(client, "SomeService", None, limit=2)

    cve_ids = [r["cve_id"] for r in results]
    assert cve_ids == ["CVE-2024-2001", "CVE-2024-2002"]


@pytest.mark.asyncio
@respx.mock
async def test_all_rejected_yields_empty_results(client):
    payload = {"vulnerabilities": [_cve_entry("CVE-2025-15603", "Rejected", "rejected candidate")]}
    respx.get(_NVD_URL).mock(return_value=httpx.Response(200, json=payload))

    results = await search_cves_by_service(client, "Uvicorn", None, limit=5)

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_unrelated_product_mentioned_in_passing_is_excluded(client):
    """The exact second bug, reproduced end-to-end with the real live data:
    a non-Rejected, genuinely real CVE (CVE-2025-27519, Cognita's path-
    traversal RCE, status "Deferred" -- i.e. not yet CPE-tagged by NVD) and
    another real CVE for a totally different product that DOES have CPE
    data (CVE-2026-26209, cbor2's DoS, tagged `agronholm:cbor2`) both
    keyword-matched "Uvicorn" purely because their advisory text mentions
    it in passing ("the backend uvicorn server", "e.g. Gunicorn, Uvicorn").
    Neither is evidence of a Uvicorn vulnerability and neither must be
    surfaced for a Uvicorn finding -- only the CVE whose own NVD CPE data
    actually names Uvicorn should come back."""
    payload = {
        "vulnerabilities": [
            _cve_entry(
                "CVE-2020-7694",
                "Modified",
                "This affects all versions of package uvicorn ...",
                score=7.5,
                cpe="cpe:2.3:a:encode:uvicorn:-:*:*:*:*:*:*:*",
            ),
            _cve_entry(
                "CVE-2025-27519",
                "Deferred",
                "Cognita is a RAG Framework ... the backend uvicorn server ...",
            ),
            _cve_entry(
                "CVE-2026-26209",
                "Analyzed",
                "cbor2 ... can crash worker processes (e.g. Gunicorn, Uvicorn) ...",
                score=7.5,
                cpe="cpe:2.3:a:agronholm:cbor2:*:*:*:*:*:python:*:*",
            ),
        ]
    }
    respx.get(_NVD_URL).mock(return_value=httpx.Response(200, json=payload))

    results = await search_cves_by_service(client, "Uvicorn", None, limit=5)

    cve_ids = [r["cve_id"] for r in results]
    assert cve_ids == ["CVE-2020-7694"]


@pytest.mark.asyncio
@respx.mock
async def test_cpe_match_is_case_and_punctuation_insensitive(client):
    """Guards against an overly-strict fix: Nmap's own banner casing/spacing
    ("Apache httpd") never matches NVD's CPE slug format
    (`apache:http_server`) verbatim, so the comparison must normalize both
    sides rather than requiring an exact string match -- otherwise real
    vulnerabilities for extremely common products would be silently dropped
    (a false negative at least as damaging as the false positive being
    fixed here)."""
    payload = {
        "vulnerabilities": [
            _cve_entry(
                "CVE-2021-44224",
                "Modified",
                "Apache HTTP Server ... possible SSRF ...",
                score=8.2,
                cpe="cpe:2.3:a:apache:http_server:*:*:*:*:*:*:*:*",
            ),
        ]
    }
    respx.get(_NVD_URL).mock(return_value=httpx.Response(200, json=payload))

    results = await search_cves_by_service(client, "Apache httpd", "2.4.7", limit=5)

    assert [r["cve_id"] for r in results] == ["CVE-2021-44224"]


@pytest.mark.asyncio
@respx.mock
async def test_mismatched_cpe_product_is_excluded(client):
    """A CVE that keyword-matched but whose own CPE configuration names a
    different product entirely (not merely "no CPE data yet") must also be
    excluded -- confirmed live against CVE-2026-2652 (an MLflow auth-bypass
    advisory that mentions "served via uvicorn (ASGI)" but is tagged
    `lfprojects:mlflow`, not Uvicorn, in NVD's own configurations)."""
    payload = {
        "vulnerabilities": [
            _cve_entry(
                "CVE-2026-2652",
                "Analyzed",
                "... served via uvicorn (ASGI) ...",
                score=9.1,
                cpe="cpe:2.3:a:lfprojects:mlflow:*:*:*:*:*:*:*:*",
            ),
        ]
    }
    respx.get(_NVD_URL).mock(return_value=httpx.Response(200, json=payload))

    results = await search_cves_by_service(client, "Uvicorn", None, limit=5)

    assert results == []
