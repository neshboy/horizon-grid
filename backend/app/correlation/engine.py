"""Data correlation engine.

Takes the full set of ProviderResult objects for one lookup and:
  1. Deduplicates overlapping facts (e.g. three providers all reporting the
     same resolved IP) into a single normalized observation.
  2. Extracts typed relationships between the seed IOC and everything it
     touches (domains, URLs, hashes, certs, ASN, threat actors, campaigns,
     malware families, MITRE techniques, CVEs) as CorrelationEdge objects.
  3. Emits a graph-ready node/edge structure for the frontend's relationship
     graph and for persistence into Neo4j.

This module intentionally contains no I/O -- it is a pure function over
already-fetched ProviderResult data, which keeps it trivially unit-testable
and reusable from both the API layer and Celery tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import logging

from app.core.provenance import category_for_provider_category
from app.ioc.types import IOCType
from app.providers.base import ProviderResult, ProviderStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphNode:
    node_id: str  # f"{type}:{value}", stable so repeated runs dedupe identically
    ioc_type: str
    value: str
    labels: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GraphEdge:
    source: str  # node_id
    target: str  # node_id
    relationship: str
    confidence: float
    provenance: str
    # WHAT KIND of source asserted this edge (app/core/provenance.py),
    # distinct from `provenance` above (WHICH provider). Defaults to
    # "threat_intel" so every pre-existing call site (evidence/loaders.py,
    # this module's own construction, and every test fixture) keeps working
    # unchanged -- only app/security_assessment/ ever passes a different value.
    provenance_category: str = "threat_intel"


@dataclass
class CorrelationResult:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    deduplicated_facts: dict[str, Any]
    provider_agreement: dict[str, list[str]]  # fact -> list of provider_ids asserting it


def _node_id(ioc_type: str, value: str) -> str:
    return f"{ioc_type}:{value.strip().lower()}"


# Maps a dotted-path in provider `data` payload -> (target IOCType, relationship label).
# Every connector normalizes into these common keys precisely so this table can
# stay provider-agnostic; see docs/ARCHITECTURE.md#normalized-fields.
_RELATIONSHIP_EXTRACTORS: list[tuple[str, IOCType, str]] = [
    ("resolved_ips", IOCType.IPV4, "resolves_to"),
    ("resolved_domains", IOCType.DOMAIN, "resolves_to"),
    ("related_urls", IOCType.URL, "hosts"),
    ("related_hashes", IOCType.SHA256, "delivers"),
    ("related_domains", IOCType.DOMAIN, "related_to"),
    ("certificates", IOCType.TLS_CERTIFICATE, "serves_certificate"),
    ("asn", IOCType.ASN, "belongs_to_asn"),
    ("malware_families", IOCType.MALWARE_FAMILY, "associated_with"),
    ("threat_actors", IOCType.THREAT_ACTOR, "attributed_to"),
    ("campaigns", IOCType.CAMPAIGN, "part_of_campaign"),
    ("mitre_techniques", IOCType.MITRE_TECHNIQUE, "uses_technique"),
    ("cves", IOCType.CVE, "exploits"),
]

# Base confidence per source field, reflecting how directly-observed the fact
# is rather than just which vendor category reported it -- a DNS resolution
# is a technical observation, while an OTX pulse's threat_actors/campaigns
# field is a community analyst's tag, not a detection. Falls back to the old
# category-based split (0.7) for any field not listed here.
_FIELD_BASE_CONFIDENCE: dict[str, float] = {
    "resolved_ips": 0.9,
    "resolved_domains": 0.9,
    "asn": 0.9,
    "certificates": 0.85,
    "related_urls": 0.8,
    "related_hashes": 0.8,
    "cves": 0.8,
    "mitre_techniques": 0.75,
    "related_domains": 0.7,
    "malware_families": 0.5,
    "threat_actors": 0.5,
    "campaigns": 0.5,
}

# Per additional distinct provider corroborating the exact same
# (source, target, relationship) edge, beyond the first.
_CORROBORATION_BONUS_PER_PROVIDER = 0.15


def _extract_relationship_value(raw_value: Any, field_name: str, provider_id: str) -> str | None:
    """Real bug found live during overnight QA: correlate()'s extractor loop
    assumed every element of a relationship-extractor field was already a
    scalar and did `str(raw_value)` unconditionally -- crt.sh's own
    "certificates" field (see app/providers/crtsh.py's _map()) is a list of
    dicts ({"issuer_name", "common_name", "name_value", "serial_number",
    "id", ...}), so this produced a garbage TLS_CERTIFICATE node whose value
    was literally Python's dict repr string, polluting the correlation
    graph and never actually correlating with anything. Returns None (skip
    this entry, don't fabricate a node) rather than guessing for a
    dict-shaped value this doesn't specifically know how to identify."""
    if isinstance(raw_value, dict):
        if field_name == "certificates":
            serial = raw_value.get("serial_number")
            if serial:
                return str(serial)
            common_name = raw_value.get("common_name")
            return str(common_name) if common_name else None
        # Generic defensive fallback for any other field that turns out to
        # be dict-shaped (now, or in a future provider) -- try the most
        # common identifying keys before giving up rather than stringifying
        # the whole dict into a meaningless node value.
        for key in ("id", "value", "name"):
            candidate = raw_value.get(key)
            if candidate:
                return str(candidate)
        logger.warning(
            "correlate(): field %r from provider %r produced a dict-shaped value with no recognized "
            "identifying key -- skipping rather than fabricating a garbage node: %r",
            field_name, provider_id, raw_value,
        )
        return None
    return str(raw_value)


def correlate(
    seed_value: str, seed_type: IOCType, results: list[ProviderResult]
) -> CorrelationResult:
    seed_node = GraphNode(node_id=_node_id(seed_type.value, seed_value), ioc_type=seed_type.value, value=seed_value)
    nodes: dict[str, GraphNode] = {seed_node.node_id: seed_node}
    edges: list[GraphEdge] = []
    provider_agreement: dict[str, list[str]] = {}
    deduplicated: dict[str, Any] = {}

    ok_results = [r for r in results if r.status == ProviderStatus.OK]

    for result in ok_results:
        for field_name, target_type, relationship in _RELATIONSHIP_EXTRACTORS:
            values = result.data.get(field_name)
            if not values:
                continue
            if not isinstance(values, (list, tuple, set)):
                # Scalars (e.g. VirusTotal's asn=15169 as an int) are single-valued fields.
                values = [values]
            for raw_value in values:
                if not raw_value:
                    continue
                extracted_value = _extract_relationship_value(raw_value, field_name, result.provider_id)
                if extracted_value is None:
                    continue
                target_node = GraphNode(
                    node_id=_node_id(target_type.value, extracted_value),
                    ioc_type=target_type.value,
                    value=extracted_value,
                )
                nodes.setdefault(target_node.node_id, target_node)
                base_confidence = _FIELD_BASE_CONFIDENCE.get(
                    field_name, 1.0 if result.category.value == "threat_intel" else 0.7
                )
                edges.append(
                    GraphEdge(
                        source=seed_node.node_id,
                        target=target_node.node_id,
                        relationship=relationship,
                        confidence=base_confidence,
                        provenance=result.provider_id,
                        provenance_category=category_for_provider_category(result.category),
                    )
                )

        # Track reputation/verdict-style facts for provider-agreement analysis,
        # which the AI service uses to populate agreeing/disagreeing provider lists.
        verdict = result.data.get("verdict") or result.data.get("reputation")
        if verdict:
            provider_agreement.setdefault(str(verdict).lower(), []).append(result.provider_id)

        for key in ("detection_ratio", "malicious_count", "total_engines", "first_seen", "last_seen"):
            if key in result.data and key not in deduplicated:
                deduplicated[key] = result.data[key]

    # Deduplicate edges that multiple providers asserted identically, merging
    # provenance into a comma-joined field rather than emitting parallel edges.
    # Corroboration itself is a confidence signal -- two independent providers
    # asserting the same fact is stronger evidence than either alone -- so each
    # additional distinct provider boosts confidence rather than just taking
    # the max of the two individual (identical-field-type) base scores.
    merged: dict[tuple[str, str, str], GraphEdge] = {}
    provenance_providers: dict[tuple[str, str, str], set[str]] = {}
    base_confidences: dict[tuple[str, str, str], float] = {}
    for edge in edges:
        dedup_key = (edge.source, edge.target, edge.relationship)
        if dedup_key in merged:
            existing = merged[dedup_key]
            providers = provenance_providers[dedup_key]
            providers.add(edge.provenance)
            base_confidences[dedup_key] = max(base_confidences[dedup_key], edge.confidence)
            boosted = min(1.0, base_confidences[dedup_key] + _CORROBORATION_BONUS_PER_PROVIDER * (len(providers) - 1))
            merged[dedup_key] = GraphEdge(
                source=existing.source,
                target=existing.target,
                relationship=existing.relationship,
                confidence=boosted,
                provenance=f"{existing.provenance},{edge.provenance}",
                # First-seen category wins on a merge -- a security-assessment
                # finding corroborating an existing threat-intel edge (or vice
                # versa) is a real, useful signal, but representing "this one
                # fact has two different kinds of source" isn't modeled here;
                # documented as a deliberate simplification, not hidden.
                provenance_category=existing.provenance_category,
            )
        else:
            provenance_providers[dedup_key] = {edge.provenance}
            base_confidences[dedup_key] = edge.confidence
            merged[dedup_key] = edge

    return CorrelationResult(
        nodes=list(nodes.values()),
        edges=list(merged.values()),
        deduplicated_facts=deduplicated,
        provider_agreement=provider_agreement,
    )


def merge_correlation_results(existing: CorrelationResult, new: CorrelationResult) -> CorrelationResult:
    """Combines an already-persisted correlation (rebuilt via
    app/evidence/loaders.py's correlation_from_records) with a freshly
    computed one (e.g. from a security-assessment run's new provider
    results) for a single generate_final_assessment() call. Does not
    re-run correlate()'s own cross-provider dedup/corroboration-boost logic
    across the two sets -- an edge asserted identically by both an original
    threat-intel provider and a new security-assessment tool will appear
    twice rather than being merged into one boosted-confidence edge. This is
    a deliberate, disclosed simplification (see
    app/core/security_assessment.py), not an oversight: the alternative
    would require re-running the full merge/corroboration pass over
    already-persisted edges on every security-assessment run, which was
    judged unnecessary complexity for what is, in practice, a rare overlap."""
    nodes: dict[str, GraphNode] = {n.node_id: n for n in existing.nodes}
    for n in new.nodes:
        nodes.setdefault(n.node_id, n)

    provider_agreement = {k: list(v) for k, v in existing.provider_agreement.items()}
    for key, providers in new.provider_agreement.items():
        provider_agreement.setdefault(key, [])
        provider_agreement[key] = list(dict.fromkeys(provider_agreement[key] + providers))

    deduplicated_facts = {**existing.deduplicated_facts, **new.deduplicated_facts}

    return CorrelationResult(
        nodes=list(nodes.values()),
        edges=[*existing.edges, *new.edges],
        deduplicated_facts=deduplicated_facts,
        provider_agreement=provider_agreement,
    )
