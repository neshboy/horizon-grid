"""Central provider registry.

Every connector module exposes a module-level singleton instance; this file
is the only place that imports and lists them, so adding a new provider is a
two-line change (import + append) and never touches the orchestrator, API
routes, or correlation engine.
"""
from app.providers.base import BaseProvider

from app.providers.virustotal import virustotal_provider
from app.providers.abuseipdb import abuseipdb_provider
from app.providers.otx import otx_provider
from app.providers.urlhaus import urlhaus_provider
from app.providers.threatfox import threatfox_provider
from app.providers.malwarebazaar import malwarebazaar_provider
from app.providers.crtsh import crtsh_provider
from app.providers.nvd import nvd_provider
from app.providers.cisa_kev import cisa_kev_provider
from app.providers.mitre_attack import mitre_attack_provider
from app.providers.whois_rdap import whois_provider
from app.providers.urlscan_io import urlscan_provider
from app.providers.google_safe_browsing import google_safe_browsing_provider

from app.providers.stubs.hybrid_analysis import hybrid_analysis_provider
from app.providers.stubs.spamhaus import spamhaus_provider
from app.providers.stubs.phishtank import phishtank_provider
from app.providers.stubs.censys import censys_provider

from app.crawler import internet_intelligence_provider

_ALL_PROVIDERS: list[BaseProvider] = [
    virustotal_provider,
    abuseipdb_provider,
    otx_provider,
    urlhaus_provider,
    threatfox_provider,
    malwarebazaar_provider,
    crtsh_provider,
    nvd_provider,
    cisa_kev_provider,
    mitre_attack_provider,
    whois_provider,
    urlscan_provider,
    google_safe_browsing_provider,
    hybrid_analysis_provider,
    spamhaus_provider,
    phishtank_provider,
    censys_provider,
    internet_intelligence_provider,
]


def get_all_providers() -> list[BaseProvider]:
    return _ALL_PROVIDERS


def get_provider_health() -> list[dict]:
    return [
        {
            "provider_id": p.provider_id,
            "provider_name": p.provider_name,
            "category": p.category.value,
            "configured": p.configured,
            "requires_key": p.requires_key,
            "supported_types": sorted(t.value for t in p.supported_types),
        }
        for p in _ALL_PROVIDERS
    ]
