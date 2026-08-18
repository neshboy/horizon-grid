"""Deterministic evidence extraction -- turns already-fetched provider data
and the correlation engine's output into EvidenceItem rows, with NO AI
involved. This is intentional: every AI-generated explanation in the platform
(WHY malicious, Score Explanation, Challenge, Copilot answers) must cite one
of these records rather than assert a claim from scratch, so "the AI made
this up" and "the AI cited real evidence" are mechanically distinguishable.

Confidence here is 0-100, same scale as RiskAssessment (app/ai/schemas.py),
so evidence and risk numbers are directly comparable in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.ai.schemas import ProviderSummary
from app.core.provenance import THREAT_INTEL, category_for_provider_category
from app.correlation.engine import CorrelationResult
from app.ioc.types import NETWORK_TYPES
from app.providers.base import ProviderResult, ProviderStatus

_CONFIDENCE_LEVEL_TO_SCORE = {"low": 30.0, "medium": 60.0, "high": 90.0}

# IOC types (by string value) that make a correlation edge count as a named
# attribution rather than a generic relationship -- drives which EvidenceType
# an edge is recorded as.
_MALWARE_TARGET_TYPES = {"malware_family"}
_THREAT_ACTOR_TARGET_TYPES = {"threat_actor"}
_CAMPAIGN_TARGET_TYPES = {"campaign"}
_MITRE_TARGET_TYPES = {"mitre_technique"}
_INFRASTRUCTURE_TARGET_TYPES = {t.value for t in NETWORK_TYPES} | {"tls_certificate", "asn"}


@dataclass
class EvidenceRecord:
    """Mirrors app/models/evidence.py's EvidenceItem columns, minus lookup_id
    (assigned by the caller once the parent IOCLookup row exists)."""

    evidence_type: str  # EvidenceType value
    source_label: str
    provider_id: Optional[str]
    claim: str
    interpretation: Optional[str]
    confidence: float
    related_ioc_type: Optional[str] = None
    related_ioc_value: Optional[str] = None
    source_url: Optional[str] = None
    observed_at: Optional[str] = None
    raw_data: Optional[dict] = None
    provenance_category: str = THREAT_INTEL


def _relationship_evidence_type(target_type: str) -> str:
    if target_type in _MALWARE_TARGET_TYPES:
        return "malware_association"
    if target_type in _THREAT_ACTOR_TARGET_TYPES:
        return "threat_actor_association"
    if target_type in _CAMPAIGN_TARGET_TYPES:
        return "campaign_association"
    if target_type in _MITRE_TARGET_TYPES:
        return "mitre_technique"
    if target_type in _INFRASTRUCTURE_TARGET_TYPES:
        return "infrastructure"
    return "relationship"


def build_evidence_from_providers(
    provider_results: list[ProviderResult],
    provider_summaries: list[ProviderSummary],
) -> list[EvidenceRecord]:
    """One reputation/detection record per provider that returned OK data,
    plus one lower-level record per interesting_finding it surfaced."""
    summaries_by_id = {s.provider_id: s for s in provider_summaries}
    records: list[EvidenceRecord] = []

    for result in provider_results:
        if result.status != ProviderStatus.OK:
            continue
        summary = summaries_by_id.get(result.provider_id)
        if summary is None:
            continue

        confidence = _CONFIDENCE_LEVEL_TO_SCORE.get(summary.confidence, 50.0)
        evidence_type = "detection" if summary.reputation in ("unknown", "no data") else "reputation"
        category = category_for_provider_category(result.category)
        records.append(
            EvidenceRecord(
                evidence_type=evidence_type,
                source_label=result.provider_name,
                provider_id=result.provider_id,
                claim=(
                    f"{result.provider_name} reports reputation={summary.reputation}, "
                    f"threat_level={summary.threat_level} ({summary.detection_status})"
                ),
                interpretation=summary.what_it_knows,
                confidence=confidence,
                source_url=result.source_url,
                raw_data={"interesting_findings": summary.interesting_findings, "caveats": summary.caveats},
                provenance_category=category,
            )
        )
        for finding in summary.interesting_findings:
            records.append(
                EvidenceRecord(
                    evidence_type="other",
                    source_label=result.provider_name,
                    provider_id=result.provider_id,
                    claim=finding,
                    interpretation=None,
                    confidence=confidence,
                    source_url=result.source_url,
                    provenance_category=category,
                )
            )

    return records


def build_evidence_from_correlation(correlation: CorrelationResult) -> list[EvidenceRecord]:
    """One record per correlation edge -- the relationship IS the claim, the
    provider(s) in `provenance` ARE the source."""
    records: list[EvidenceRecord] = []

    for edge in correlation.edges:
        target_type, _, target_value = edge.target.partition(":")
        source_type, _, source_value = edge.source.partition(":")
        providers = [p for p in edge.provenance.split(",") if p]
        source_label = "Correlation Engine (corroborated)" if len(providers) > 1 else (providers[0] if providers else "Correlation Engine")

        records.append(
            EvidenceRecord(
                evidence_type=_relationship_evidence_type(target_type),
                source_label=source_label,
                provider_id=providers[0] if len(providers) == 1 else None,
                claim=f"{source_value} {edge.relationship.replace('_', ' ')} {target_value}",
                interpretation=None,
                confidence=round(edge.confidence * 100, 1),
                related_ioc_type=target_type,
                related_ioc_value=target_value,
                raw_data={"provenance": edge.provenance, "relationship": edge.relationship},
                provenance_category=edge.provenance_category,
            )
        )

    return records


def build_evidence(
    provider_results: list[ProviderResult],
    provider_summaries: list[ProviderSummary],
    correlation: CorrelationResult,
) -> list[EvidenceRecord]:
    return build_evidence_from_providers(provider_results, provider_summaries) + build_evidence_from_correlation(correlation)
