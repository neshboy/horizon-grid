"""Unit tests for app.correlation.engine.correlate.

Builds fake ProviderResult envelopes (no network I/O -- correlate() is a pure
function over already-fetched provider data) and asserts the produced graph
node/edge structure, edge de-duplication/merge behaviour, and provider
agreement bucketing described in app/correlation/engine.py.
"""
import pytest

from app.correlation.engine import GraphEdge, GraphNode, correlate
from app.ioc.types import IOCType
from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus

SEED_VALUE = "1.2.3.4"
SEED_TYPE = IOCType.IPV4


def make_result(
    provider_id: str,
    category: ProviderCategory,
    data: dict,
    status: ProviderStatus = ProviderStatus.OK,
) -> ProviderResult:
    return ProviderResult(
        provider_id=provider_id,
        provider_name=provider_id.upper(),
        category=category,
        status=status,
        ioc_value=SEED_VALUE,
        ioc_type=SEED_TYPE,
        data=data,
    )


@pytest.fixture
def sample_results() -> list[ProviderResult]:
    return [
        make_result(
            "virustotal",
            ProviderCategory.THREAT_INTEL,
            {
                "resolved_ips": ["5.6.7.8"],
                "malware_families": ["Emotet"],
                "verdict": "malicious",
                "detection_ratio": "10/70",
            },
        ),
        make_result(
            "otx",
            ProviderCategory.OSINT,
            {
                "resolved_ips": ["5.6.7.8"],
                "threat_actors": ["APT28"],
                "reputation": "malicious",
            },
        ),
        make_result(
            "abuseipdb",
            ProviderCategory.THREAT_INTEL,
            {
                "mitre_techniques": ["T1059"],
                "verdict": "clean",
                "detection_ratio": "0/70",
            },
        ),
        # A failed provider's data must be ignored entirely.
        make_result(
            "broken_provider",
            ProviderCategory.THREAT_INTEL,
            {"resolved_ips": ["9.9.9.9"], "verdict": "malicious"},
            status=ProviderStatus.ERROR,
        ),
    ]


def test_seed_node_present(sample_results: list[ProviderResult]) -> None:
    result = correlate(SEED_VALUE, SEED_TYPE, sample_results)
    seed_node_id = f"ipv4:{SEED_VALUE}"
    node_ids = {n.node_id for n in result.nodes}
    assert seed_node_id in node_ids
    seed_node = next(n for n in result.nodes if n.node_id == seed_node_id)
    assert seed_node == GraphNode(
        node_id=seed_node_id, ioc_type="ipv4", value=SEED_VALUE
    )


def test_failed_provider_contributes_no_nodes_or_edges(
    sample_results: list[ProviderResult],
) -> None:
    result = correlate(SEED_VALUE, SEED_TYPE, sample_results)
    node_ids = {n.node_id for n in result.nodes}
    assert "ipv4:9.9.9.9" not in node_ids
    assert not any(e.target == "ipv4:9.9.9.9" for e in result.edges)


def test_expected_edges_with_relationship_labels(
    sample_results: list[ProviderResult],
) -> None:
    result = correlate(SEED_VALUE, SEED_TYPE, sample_results)
    edges_by_target = {e.target: e for e in result.edges}

    resolves_edge = edges_by_target["ipv4:5.6.7.8"]
    assert resolves_edge.source == f"ipv4:{SEED_VALUE}"
    assert resolves_edge.relationship == "resolves_to"

    malware_edge = edges_by_target["malware_family:emotet"]
    assert malware_edge.relationship == "associated_with"
    assert malware_edge.provenance == "virustotal"
    assert malware_edge.confidence == 0.5  # pulse/tag-based attribution, not a technical observation

    actor_edge = edges_by_target["threat_actor:apt28"]
    assert actor_edge.relationship == "attributed_to"
    assert actor_edge.provenance == "otx"
    assert actor_edge.confidence == 0.5  # pulse/tag-based attribution, not a technical observation

    technique_edge = edges_by_target["mitre_technique:t1059"]
    assert technique_edge.relationship == "uses_technique"
    assert technique_edge.provenance == "abuseipdb"


def test_duplicate_edges_from_two_providers_are_merged(
    sample_results: list[ProviderResult],
) -> None:
    result = correlate(SEED_VALUE, SEED_TYPE, sample_results)
    resolves_edges = [
        e
        for e in result.edges
        if e.target == "ipv4:5.6.7.8" and e.relationship == "resolves_to"
    ]
    # virustotal and otx both assert seed -> 5.6.7.8 resolves_to; must collapse to one edge.
    assert len(resolves_edges) == 1
    merged_edge = resolves_edges[0]
    assert merged_edge.provenance == "virustotal,otx"
    # Both providers' resolved_ips field has base confidence 0.9; two distinct
    # providers corroborating the same fact adds one +0.15 corroboration bonus.
    assert merged_edge.confidence == pytest.approx(1.0)


def test_corroboration_from_three_providers_boosts_confidence_further() -> None:
    results = [
        make_result("virustotal", ProviderCategory.THREAT_INTEL, {"malware_families": ["Emotet"]}),
        make_result("otx", ProviderCategory.OSINT, {"malware_families": ["Emotet"]}),
        make_result("abuseipdb", ProviderCategory.THREAT_INTEL, {"malware_families": ["Emotet"]}),
    ]
    result = correlate(SEED_VALUE, SEED_TYPE, results)
    edge = next(e for e in result.edges if e.target == "malware_family:emotet")
    # Base confidence 0.5 (pulse/tag-based field) + 2 corroboration bonuses (3 distinct providers).
    assert edge.confidence == pytest.approx(0.5 + 0.15 * 2)
    assert set(edge.provenance.split(",")) == {"virustotal", "otx", "abuseipdb"}


def test_directly_observed_field_has_higher_base_confidence_than_pulse_tagged_field() -> None:
    results = [
        make_result("passive_dns", ProviderCategory.PASSIVE_DNS, {"resolved_ips": ["5.6.7.8"]}),
        make_result("otx", ProviderCategory.OSINT, {"threat_actors": ["APT28"]}),
    ]
    result = correlate(SEED_VALUE, SEED_TYPE, results)
    dns_edge = next(e for e in result.edges if e.relationship == "resolves_to")
    actor_edge = next(e for e in result.edges if e.relationship == "attributed_to")
    assert dns_edge.confidence > actor_edge.confidence


def test_provider_agreement_buckets_by_verdict(
    sample_results: list[ProviderResult],
) -> None:
    result = correlate(SEED_VALUE, SEED_TYPE, sample_results)
    assert result.provider_agreement["malicious"] == ["virustotal", "otx"]
    assert result.provider_agreement["clean"] == ["abuseipdb"]
    # The failed provider's verdict must not appear anywhere.
    for providers in result.provider_agreement.values():
        assert "broken_provider" not in providers


def test_deduplicated_facts_keeps_first_seen_value_only(
    sample_results: list[ProviderResult],
) -> None:
    result = correlate(SEED_VALUE, SEED_TYPE, sample_results)
    # virustotal is processed first and sets detection_ratio; abuseipdb's later
    # detection_ratio for the same key must not overwrite it.
    assert result.deduplicated_facts["detection_ratio"] == "10/70"


def test_correlate_with_no_results_returns_only_seed_node() -> None:
    result = correlate(SEED_VALUE, SEED_TYPE, [])
    assert len(result.nodes) == 1
    assert result.nodes[0].node_id == f"ipv4:{SEED_VALUE}"
    assert result.edges == []
    assert result.provider_agreement == {}
    assert result.deduplicated_facts == {}


def test_string_value_in_relationship_field_is_treated_as_single_item() -> None:
    # related_urls etc. may be provided as a bare string rather than a list;
    # correlate() must wrap it instead of iterating its characters.
    result_obj = make_result(
        "urlscan",
        ProviderCategory.THREAT_INTEL,
        {"related_urls": "http://evil.example/payload"},
    )
    result = correlate(SEED_VALUE, SEED_TYPE, [result_obj])
    target_ids = {n.node_id for n in result.nodes}
    assert "url:http://evil.example/payload" in target_ids
    hosts_edges = [e for e in result.edges if e.relationship == "hosts"]
    assert len(hosts_edges) == 1


def test_int_value_in_relationship_field_is_treated_as_single_item() -> None:
    # VirusTotal reports asn as a bare int (e.g. 15169); correlate() must wrap
    # it in a list rather than trying to iterate an int (regression test for
    # a live "'int' object is not iterable" crash on the ASN field).
    result_obj = make_result(
        "virustotal",
        ProviderCategory.THREAT_INTEL,
        {"asn": 15169},
    )
    result = correlate(SEED_VALUE, SEED_TYPE, [result_obj])
    target_ids = {n.node_id for n in result.nodes}
    assert "asn:15169" in target_ids
    asn_edges = [e for e in result.edges if e.relationship == "belongs_to_asn"]
    assert len(asn_edges) == 1


def test_crtsh_dict_shaped_certificates_are_identified_by_serial_number_not_stringified() -> None:
    """Real bug found live during overnight QA: app/providers/crtsh.py's
    "certificates" field is a list of dicts ({"issuer_name", "common_name",
    "serial_number", ...}), but correlate() used to assume every
    relationship-extractor list element was already a scalar and did
    str(raw_value) unconditionally -- producing a garbage TLS_CERTIFICATE
    node whose value was Python's dict repr string."""
    result_obj = make_result(
        "crtsh",
        ProviderCategory.THREAT_INTEL,
        {
            "certificates": [
                {"issuer_name": "Let's Encrypt", "common_name": "example.com", "serial_number": "03A1B2C3", "id": 12345},
            ]
        },
    )
    result = correlate(SEED_VALUE, SEED_TYPE, [result_obj])
    target_ids = {n.node_id for n in result.nodes}
    assert "tls_certificate:03a1b2c3" in target_ids
    assert not any("{" in node_id for node_id in target_ids), "no node value should ever be a stringified dict"
    cert_edges = [e for e in result.edges if e.relationship == "serves_certificate"]
    assert len(cert_edges) == 1


def test_crtsh_certificate_dict_with_no_serial_number_falls_back_to_common_name() -> None:
    result_obj = make_result(
        "crtsh",
        ProviderCategory.THREAT_INTEL,
        {"certificates": [{"issuer_name": "Let's Encrypt", "common_name": "example.com", "serial_number": None}]},
    )
    result = correlate(SEED_VALUE, SEED_TYPE, [result_obj])
    target_ids = {n.node_id for n in result.nodes}
    assert "tls_certificate:example.com" in target_ids


def test_dict_shaped_relationship_value_with_no_identifying_key_is_skipped_not_fabricated() -> None:
    """Generic defensive case: an unrecognized dict shape in ANY
    relationship-extractor field must be skipped, never turned into a
    garbage node by stringifying the whole dict."""
    result_obj = make_result(
        "some-future-provider",
        ProviderCategory.THREAT_INTEL,
        {"related_urls": [{"unexpected": "shape", "no_recognizable_key": True}]},
    )
    result = correlate(SEED_VALUE, SEED_TYPE, [result_obj])
    assert not any(e.relationship == "hosts" for e in result.edges)
    assert not any("{" in n.node_id for n in result.nodes)
