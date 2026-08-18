"""Provenance-category vocabulary shared by CorrelationEdgeRecord and
EvidenceItem's `provenance_category` columns (app/models/lookup.py,
app/models/evidence.py) -- distinct from CorrelationEdgeRecord.provenance,
which names WHICH provider asserted a fact; this names WHAT KIND of source
it was.

Only THREAT_INTEL and SECURITY_ASSESSMENT are populated by any code today:
- THREAT_INTEL: every existing provider (VirusTotal, WHOIS, NVD, etc.) --
  each queries a third party's already-collected data about the target.
- SECURITY_ASSESSMENT: app/security_assessment/'s tool adapters -- each
  sends real traffic to the target itself (Nmap/DNS/TLS/HTTP-header checks).

LOCAL_OBSERVATION and AI_INTERPRETATION are modeled and reserved for future
use (e.g. an analyst's own manually-asserted case annotation; an AI-inferred
relationship not directly asserted by any provider or tool) -- disclosed
here explicitly rather than silently omitted, since nothing populates them
in this release.
"""
from app.providers.base import ProviderCategory

THREAT_INTEL = "threat_intel"
SECURITY_ASSESSMENT = "security_assessment"
LOCAL_OBSERVATION = "local_observation"
AI_INTERPRETATION = "ai_interpretation"

ALL_CATEGORIES = (THREAT_INTEL, SECURITY_ASSESSMENT, LOCAL_OBSERVATION, AI_INTERPRETATION)


def category_for_provider_category(provider_category: ProviderCategory) -> str:
    """Maps a ProviderResult's ProviderCategory (app/providers/base.py) to
    one of the two provenance categories any code actually populates today."""
    if provider_category == ProviderCategory.SECURITY_ASSESSMENT:
        return SECURITY_ASSESSMENT
    return THREAT_INTEL
