"""MITRE ATT&CK technique reference-data connector.

Looks up ATT&CK technique metadata (name, description, tactics, platforms,
data sources) by technique ID (e.g. "T1059" or "T1059.001") against the
public MITRE CTI STIX 2.1 bundle for the Enterprise ATT&CK matrix. This is
reference data rather than a per-target reputation lookup, so no API key is
required -- `requires_key = False` and `configured` is always True.

The full enterprise-attack.json STIX bundle is ~30MB, so re-fetching it on
every lookup would be wasteful and slow. This module keeps a process-wide
in-memory cache of the parsed technique index with a last-fetched timestamp,
refreshed at most once per hour, guarded by an asyncio.Lock so concurrent
requests during a cold/expired cache don't all trigger a simultaneous
30MB refetch -- only the first task through the lock refetches, the rest
reuse the result once it's in.
"""
import asyncio
import time
from typing import Any

import httpx

from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus

_BUNDLE_URL = "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json"
_CACHE_TTL_SECONDS = 3600  # refresh at most once per hour

_cache_lock = asyncio.Lock()
_cache_techniques: dict[str, dict[str, Any]] = {}
_cache_fetched_at: float = 0.0


def _index_techniques(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Builds an external_id -> attack-pattern STIX object lookup from a bundle."""
    index: dict[str, dict[str, Any]] = {}
    for obj in bundle.get("objects", []):
        if obj.get("type") != "attack-pattern":
            continue
        for ref in obj.get("external_references", []):
            if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
                index[ref["external_id"].upper()] = obj
    return index


async def _get_technique_index(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    """Returns the cached technique index, refreshing it at most once per hour."""
    global _cache_techniques, _cache_fetched_at

    now = time.monotonic()
    if _cache_techniques and (now - _cache_fetched_at) < _CACHE_TTL_SECONDS:
        return _cache_techniques

    async with _cache_lock:
        # Re-check after acquiring the lock -- another task may have just refreshed it
        # while we were waiting, in which case we should not refetch again.
        now = time.monotonic()
        if _cache_techniques and (now - _cache_fetched_at) < _CACHE_TTL_SECONDS:
            return _cache_techniques

        response = await client.get(_BUNDLE_URL, timeout=60.0)
        response.raise_for_status()
        bundle = response.json()

        _cache_techniques = _index_techniques(bundle)
        _cache_fetched_at = time.monotonic()
        return _cache_techniques


class MitreAttackProvider(BaseProvider):
    provider_id = "mitre_attack"
    provider_name = "MITRE ATT&CK"
    category = ProviderCategory.THREAT_INTEL
    supported_types = {IOCType.MITRE_TECHNIQUE}
    requires_key = False
    configured = True
    base_url = _BUNDLE_URL

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        technique_id = ioc_value.strip().upper()
        index = await _get_technique_index(client)
        obj = index.get(technique_id)

        source_url = f"https://attack.mitre.org/techniques/{technique_id.replace('.', '/')}/"

        if obj is None:
            return ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NO_DATA,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                source_url=source_url,
            )

        tactics = sorted(
            {phase.get("phase_name") for phase in obj.get("kill_chain_phases", []) if phase.get("phase_name")}
        )

        data = {
            "technique_id": technique_id,
            "name": obj.get("name"),
            "description": obj.get("description"),
            "tactics": tactics,
            "mitre_techniques": [technique_id],
            "x_mitre_platforms": obj.get("x_mitre_platforms", []),
            "x_mitre_data_sources": obj.get("x_mitre_data_sources", []),
            "is_subtechnique": obj.get("x_mitre_is_subtechnique", False),
            "revoked": obj.get("revoked", False),
            "deprecated": obj.get("x_mitre_deprecated", False),
        }

        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data=data,
            raw=obj,
            source_url=source_url,
        )


mitre_attack_provider = MitreAttackProvider()
