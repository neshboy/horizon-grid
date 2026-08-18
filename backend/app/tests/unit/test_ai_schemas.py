"""Unit tests for app.ai.schemas -- pins down the MitreMapping schema
constraints (real tactic enum instead of free text; technique_id is a plain
str with no `pattern=` regex, since Ollama's grammar compiler can't compile
that constraint -- see app/ai/schemas.py's comment on MitreMapping.technique_id)
and the FinalAssessment grounding validator that rejects hallucinated
provider-agreement / MITRE claims not backed by the actual correlation data.
"""
import pytest
from pydantic import ValidationError

from app.ai.schemas import FinalAssessment, MitreMapping, RiskAssessment
from app.correlation.engine import CorrelationResult, GraphEdge, GraphNode


def _risk(**overrides) -> RiskAssessment:
    defaults = dict(
        overall_risk_score=10, confidence_score=80, severity="low",
        reputation="clean", malicious_probability=10, analyst_confidence="high",
    )
    defaults.update(overrides)
    return RiskAssessment(**defaults)


def test_mitre_mapping_rejects_free_text_tactic():
    with pytest.raises(ValidationError):
        MitreMapping(
            technique_id="T1071", technique_name="App Layer Protocol",
            tactic="Command And Control", rationale="r",
        )


def test_mitre_mapping_accepts_real_attck_tactic_slug():
    mapping = MitreMapping(
        technique_id="T1071", technique_name="App Layer Protocol",
        tactic="command-and-control", rationale="r",
    )
    assert mapping.tactic == "command-and-control"


def test_mitre_mapping_accepts_malformed_technique_id():
    # technique_id intentionally has no format/pattern validation (see
    # app/ai/schemas.py) -- a malformed ID is handled downstream by
    # _ground_final_assessment()'s membership check (grounded=False on
    # mismatch), not rejected here.
    mapping = MitreMapping(
        technique_id="not-a-technique-id", technique_name="x",
        tactic="discovery", rationale="r",
    )
    assert mapping.technique_id == "not-a-technique-id"


def test_mitre_mapping_accepts_subtechnique_id():
    mapping = MitreMapping(
        technique_id="T1071.001", technique_name="Web Protocols",
        tactic="command-and-control", rationale="r",
    )
    assert mapping.technique_id == "T1071.001"


def test_mitre_mapping_grounded_defaults_true():
    mapping = MitreMapping(
        technique_id="T1071", technique_name="x", tactic="discovery", rationale="r",
    )
    assert mapping.grounded is True


def _final_assessment(**overrides) -> dict:
    defaults = dict(
        ioc_value="example.com", ioc_type="domain",
        executive_summary="s", technical_summary="s",
        threat_assessment="s", relationships_summary="s",
        risk=_risk(), final_verdict="unknown", verdict_rationale="r",
    )
    defaults.update(overrides)
    return defaults


def test_final_assessment_validates_without_grounding_context():
    # Pydantic-level validation alone (no correlation cross-check) must still
    # accept a well-formed payload -- grounding is enforced separately in
    # app/ai/service.py via _ground_final_assessment, not in this model.
    assessment = FinalAssessment.model_validate(_final_assessment())
    assert assessment.final_verdict.value == "unknown"


def _correlation_with_technique(technique_id: str, provenance: str = "mitre_attack") -> CorrelationResult:
    return CorrelationResult(
        nodes=[GraphNode(node_id="domain:x", ioc_type="domain", value="x")],
        edges=[
            GraphEdge(
                source="domain:x",
                target=f"mitre_technique:{technique_id.lower()}",
                relationship="uses_technique",
                confidence=0.75,
                provenance=provenance,
            )
        ],
        deduplicated_facts={},
        provider_agreement={"malicious": ["virustotal"]},
    )


class TestGroundFinalAssessment:
    def test_technique_present_in_correlation_is_marked_grounded(self):
        from app.ai.service import _ground_final_assessment

        assessment = FinalAssessment.model_validate(
            _final_assessment(
                mitre_mappings=[
                    {"technique_id": "T1071", "technique_name": "x", "tactic": "command-and-control", "rationale": "r"}
                ]
            )
        )
        grounded = _ground_final_assessment(assessment, _correlation_with_technique("T1071"))
        assert grounded.mitre_mappings[0].grounded is True

    def test_technique_absent_from_correlation_is_marked_ungrounded(self):
        from app.ai.service import _ground_final_assessment

        assessment = FinalAssessment.model_validate(
            _final_assessment(
                mitre_mappings=[
                    {"technique_id": "T1071", "technique_name": "x", "tactic": "command-and-control", "rationale": "r"}
                ]
            )
        )
        # correlation only surfaced T1059, not T1071 -- the model invented T1071.
        grounded = _ground_final_assessment(assessment, _correlation_with_technique("T1059"))
        assert grounded.mitre_mappings[0].grounded is False

    def test_agreeing_providers_not_in_correlation_are_stripped(self):
        from app.ai.service import _ground_final_assessment

        assessment = FinalAssessment.model_validate(
            _final_assessment(agreeing_providers=["virustotal", "made_up_provider"])
        )
        grounded = _ground_final_assessment(assessment, _correlation_with_technique("T1059"))
        assert grounded.agreeing_providers == ["virustotal"]

    def test_provider_named_only_in_edge_provenance_is_kept(self):
        from app.ai.service import _ground_final_assessment

        assessment = FinalAssessment.model_validate(_final_assessment(agreeing_providers=["mitre_attack"]))
        grounded = _ground_final_assessment(assessment, _correlation_with_technique("T1059", provenance="mitre_attack"))
        assert grounded.agreeing_providers == ["mitre_attack"]

    def test_merged_comma_joined_provenance_is_split_into_individual_providers(self):
        from app.ai.service import _ground_final_assessment

        correlation = CorrelationResult(
            nodes=[],
            edges=[
                GraphEdge(
                    source="domain:x", target="ipv4:1.2.3.4", relationship="resolves_to",
                    confidence=1.0, provenance="virustotal,otx",
                )
            ],
            deduplicated_facts={},
            provider_agreement={},
        )
        assessment = FinalAssessment.model_validate(_final_assessment(agreeing_providers=["otx", "fake"]))
        grounded = _ground_final_assessment(assessment, correlation)
        assert grounded.agreeing_providers == ["otx"]

    def test_provider_with_no_edges_or_verdict_is_kept_via_known_provider_ids(self):
        # Regression test for a real bug: the OSINT crawler provider
        # (provider_id="internet_intelligence", app/crawler/collector.py) only
        # returns osint_findings/source_count/total_findings -- none of which are
        # a correlation-edge-producing field (_RELATIONSHIP_EXTRACTORS) or a
        # verdict/reputation fact, so it can never appear in correlation.edges'
        # provenance or correlation.provider_agreement. Before known_provider_ids
        # was threaded through, a correct "internet_intelligence" citation in
        # agreeing_providers/disagreeing_providers was indistinguishable from a
        # hallucinated one and got silently stripped here -- reproducing the
        # reported bug where threat_assessment named "Internet Intelligence" in
        # prose while disagreeing_providers rendered empty.
        from app.ai.service import _ground_final_assessment

        assessment = FinalAssessment.model_validate(
            _final_assessment(disagreeing_providers=["internet_intelligence"])
        )
        correlation = CorrelationResult(
            nodes=[], edges=[], deduplicated_facts={}, provider_agreement={},
        )
        grounded = _ground_final_assessment(
            assessment, correlation, known_provider_ids={"internet_intelligence", "spamhaus"}
        )
        assert grounded.disagreeing_providers == ["internet_intelligence"]

    def test_provider_not_in_known_provider_ids_or_correlation_is_still_stripped(self):
        # known_provider_ids widens the accepted set, it must not disable the
        # hallucination guardrail entirely.
        from app.ai.service import _ground_final_assessment

        assessment = FinalAssessment.model_validate(
            _final_assessment(agreeing_providers=["spamhaus", "made_up_provider"])
        )
        correlation = CorrelationResult(
            nodes=[], edges=[], deduplicated_facts={}, provider_agreement={},
        )
        grounded = _ground_final_assessment(assessment, correlation, known_provider_ids={"spamhaus"})
        assert grounded.agreeing_providers == ["spamhaus"]
