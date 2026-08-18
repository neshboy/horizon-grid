"""Unit tests for app.evidence.builder -- the deterministic (no-AI) evidence
extraction that every AI explanation feature (WHY, Challenge, Score
Explanation, Copilot) must cite rather than assert claims from scratch.
"""
from app.ai.schemas import ProviderSummary
from app.correlation.engine import CorrelationResult, GraphEdge, GraphNode
from app.evidence.builder import build_evidence, build_evidence_from_correlation, build_evidence_from_providers
from app.ioc.types import IOCType
from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus

SEED_VALUE = "1.2.3.4"


def make_result(provider_id: str, status: ProviderStatus = ProviderStatus.OK, data: dict | None = None) -> ProviderResult:
    return ProviderResult(
        provider_id=provider_id,
        provider_name=provider_id.upper(),
        category=ProviderCategory.THREAT_INTEL,
        status=status,
        ioc_value=SEED_VALUE,
        ioc_type=IOCType.IPV4,
        data=data or {},
        source_url=f"https://example.test/{provider_id}",
    )


def make_summary(provider_id: str, **overrides) -> ProviderSummary:
    defaults = dict(
        provider_id=provider_id,
        what_it_knows="Some findings.",
        reputation="malicious",
        detection_status="10/70",
        threat_level="high",
        confidence="high",
        interesting_findings=["Flagged by 10 engines"],
    )
    defaults.update(overrides)
    return ProviderSummary(**defaults)


def test_no_evidence_for_non_ok_provider():
    result = make_result("virustotal", status=ProviderStatus.NO_DATA)
    summary = make_summary("virustotal")
    records = build_evidence_from_providers([result], [summary])
    assert records == []


def test_ok_provider_with_summary_produces_reputation_evidence():
    result = make_result("virustotal")
    summary = make_summary("virustotal")
    records = build_evidence_from_providers([result], [summary])

    reputation_records = [r for r in records if r.evidence_type == "reputation"]
    assert len(reputation_records) == 1
    assert reputation_records[0].source_label == "VIRUSTOTAL"
    assert reputation_records[0].provider_id == "virustotal"
    assert reputation_records[0].confidence == 90.0  # "high" -> 90
    assert "malicious" in reputation_records[0].claim


def test_unknown_reputation_produces_detection_not_reputation_evidence():
    result = make_result("otx")
    summary = make_summary("otx", reputation="unknown", confidence="low")
    records = build_evidence_from_providers([result], [summary])
    detection_records = [r for r in records if r.evidence_type == "detection"]
    assert len(detection_records) == 1
    assert detection_records[0].confidence == 30.0  # "low" -> 30


def test_interesting_findings_each_produce_their_own_evidence_record():
    result = make_result("virustotal")
    summary = make_summary("virustotal", interesting_findings=["Finding A", "Finding B"])
    records = build_evidence_from_providers([result], [summary])
    other_records = [r for r in records if r.evidence_type == "other"]
    assert {r.claim for r in other_records} == {"Finding A", "Finding B"}


def test_correlation_edge_to_malware_produces_malware_association_evidence():
    correlation = CorrelationResult(
        nodes=[GraphNode(node_id=f"ipv4:{SEED_VALUE}", ioc_type="ipv4", value=SEED_VALUE)],
        edges=[
            GraphEdge(
                source=f"ipv4:{SEED_VALUE}",
                target="malware_family:emotet",
                relationship="associated_with",
                confidence=0.5,
                provenance="virustotal",
            )
        ],
        deduplicated_facts={},
        provider_agreement={},
    )
    records = build_evidence_from_correlation(correlation)
    assert len(records) == 1
    assert records[0].evidence_type == "malware_association"
    assert records[0].related_ioc_type == "malware_family"
    assert records[0].related_ioc_value == "emotet"
    assert records[0].confidence == 50.0
    assert records[0].source_label == "virustotal"


def test_corroborated_correlation_edge_labels_source_as_correlation_engine():
    correlation = CorrelationResult(
        nodes=[],
        edges=[
            GraphEdge(
                source=f"ipv4:{SEED_VALUE}",
                target="ipv4:5.6.7.8",
                relationship="resolves_to",
                confidence=1.0,
                provenance="virustotal,otx",
            )
        ],
        deduplicated_facts={},
        provider_agreement={},
    )
    records = build_evidence_from_correlation(correlation)
    assert records[0].source_label == "Correlation Engine (corroborated)"
    assert records[0].provider_id is None  # multiple providers -- no single provider_id


def test_threat_actor_and_campaign_and_mitre_edge_types():
    correlation = CorrelationResult(
        nodes=[],
        edges=[
            GraphEdge(source="x", target="threat_actor:apt28", relationship="attributed_to", confidence=0.5, provenance="otx"),
            GraphEdge(source="x", target="campaign:op-x", relationship="part_of_campaign", confidence=0.5, provenance="otx"),
            GraphEdge(source="x", target="mitre_technique:t1071", relationship="uses_technique", confidence=0.8, provenance="mitre_attack"),
            GraphEdge(source="x", target="domain:evil.test", relationship="resolves_to", confidence=0.9, provenance="virustotal"),
        ],
        deduplicated_facts={},
        provider_agreement={},
    )
    records = build_evidence_from_correlation(correlation)
    by_type = {r.related_ioc_value: r.evidence_type for r in records}
    assert by_type["apt28"] == "threat_actor_association"
    assert by_type["op-x"] == "campaign_association"
    assert by_type["t1071"] == "mitre_technique"
    assert by_type["evil.test"] == "infrastructure"


def test_build_evidence_combines_both_sources():
    result = make_result("virustotal")
    summary = make_summary("virustotal")
    correlation = CorrelationResult(
        nodes=[],
        edges=[GraphEdge(source="x", target="malware_family:emotet", relationship="associated_with", confidence=0.5, provenance="virustotal")],
        deduplicated_facts={},
        provider_agreement={},
    )
    records = build_evidence([result], [summary], correlation)
    types = {r.evidence_type for r in records}
    assert "reputation" in types
    assert "other" in types  # interesting_findings
    assert "malware_association" in types
