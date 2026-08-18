"""Unit tests for app.ai.analysis_service's grounding guardrails:
_strip_invalid_evidence_ids (stops an AI-cited evidence_id from rendering as a
real citation when it isn't actually present in the evidence supplied for that
call) and _backfill_evidence_ids_from_prose (recovers a citation the model
wrote into a prose field, e.g. "[id=...] ...", but forgot to also list in the
structured evidence_ids array next to it -- the exact shape of a real bug
reported against POST /analysis/disagreement, where most_reliable_evidence
named a real evidence id in prose while evidence_ids stayed empty).
Uses schemas that already exist (WhyMaliciousExplanation/ReasonWithEvidence,
DisagreementSummary) so tests exercise real nested-model traversal, not a
fabricated stand-in schema.
"""
from app.ai.analysis_schemas import DisagreementSummary, ReasonWithEvidence, WhyMaliciousExplanation
from app.ai.analysis_service import _backfill_evidence_ids_from_prose, _strip_invalid_evidence_ids


def test_strips_evidence_id_not_in_real_ids():
    explanation = WhyMaliciousExplanation(
        verdict_restated="MALICIOUS -- 90/100",
        reasons=[ReasonWithEvidence(reason="Flagged by many engines", evidence_ids=["real-1", "fake-1"])],
    )
    result = _strip_invalid_evidence_ids(explanation, real_ids={"real-1"})
    assert result.reasons[0].evidence_ids == ["real-1"]


def test_keeps_all_ids_when_all_real():
    explanation = WhyMaliciousExplanation(
        verdict_restated="MALICIOUS -- 90/100",
        reasons=[ReasonWithEvidence(reason="r", evidence_ids=["a", "b"])],
    )
    result = _strip_invalid_evidence_ids(explanation, real_ids={"a", "b", "c"})
    assert result.reasons[0].evidence_ids == ["a", "b"]


def test_strips_all_ids_when_none_real():
    explanation = WhyMaliciousExplanation(
        verdict_restated="MALICIOUS -- 90/100",
        reasons=[
            ReasonWithEvidence(reason="r1", evidence_ids=["x"]),
            ReasonWithEvidence(reason="r2", evidence_ids=["y"]),
        ],
    )
    result = _strip_invalid_evidence_ids(explanation, real_ids=set())
    assert result.reasons[0].evidence_ids == []
    assert result.reasons[1].evidence_ids == []


def test_recurses_into_nested_list_of_models():
    explanation = WhyMaliciousExplanation(
        verdict_restated="v",
        reasons=[
            ReasonWithEvidence(reason="r1", evidence_ids=["real"]),
            ReasonWithEvidence(reason="r2", evidence_ids=["fake"]),
            ReasonWithEvidence(reason="r3", evidence_ids=["real", "fake"]),
        ],
    )
    result = _strip_invalid_evidence_ids(explanation, real_ids={"real"})
    assert [r.evidence_ids for r in result.reasons] == [["real"], [], ["real"]]


class TestBackfillEvidenceIdsFromProse:
    def test_backfills_id_cited_in_prose_but_missing_from_structured_field(self):
        # Regression test for the reported bug: most_reliable_evidence names the
        # evidence id in prose (copied verbatim from the "[id=...]" ledger format
        # built by _evidence_block) but evidence_ids came back empty.
        real_id = "b6f79056-d4ae-420b-a14d-740a45db447f"
        summary = DisagreementSummary(
            agreement="reputation = clean",
            conflict="threat_level",
            missing_data="sandbox evidence, historical WHOIS records",
            most_reliable_evidence=(
                f"[id={real_id}] (reputation, confidence=90) Spamhaus DBL/ZEN: "
                "Spamhaus DBL/ZEN reports reputation=clean, threat_level=low (ok)"
            ),
            evidence_ids=[],
        )
        result = _backfill_evidence_ids_from_prose(summary, real_ids={real_id})
        assert result.evidence_ids == [real_id]

    def test_does_not_add_id_not_mentioned_in_prose(self):
        summary = DisagreementSummary(
            agreement="a", conflict="c", missing_data="m", most_reliable_evidence="no ids mentioned here",
        )
        result = _backfill_evidence_ids_from_prose(summary, real_ids={"real-1", "real-2"})
        assert result.evidence_ids == []

    def test_does_not_duplicate_id_already_present(self):
        summary = DisagreementSummary(
            agreement="a", conflict="c", missing_data="m",
            most_reliable_evidence="see [id=real-1]", evidence_ids=["real-1"],
        )
        result = _backfill_evidence_ids_from_prose(summary, real_ids={"real-1"})
        assert result.evidence_ids == ["real-1"]

    def test_recurses_into_nested_models_and_backfills_each(self):
        explanation = WhyMaliciousExplanation(
            verdict_restated="MALICIOUS -- 90/100",
            reasons=[
                ReasonWithEvidence(reason="Flagged per [id=real-1]", evidence_ids=[]),
                ReasonWithEvidence(reason="No citation here", evidence_ids=[]),
            ],
        )
        result = _backfill_evidence_ids_from_prose(explanation, real_ids={"real-1"})
        assert [r.evidence_ids for r in result.reasons] == [["real-1"], []]

    def test_never_adds_an_id_not_in_real_ids_even_if_it_looks_like_one(self):
        # Only ids already confirmed real are ever added -- this cannot be used
        # to smuggle in a hallucinated id via prose.
        summary = DisagreementSummary(
            agreement="a", conflict="c", missing_data="m",
            most_reliable_evidence="see [id=hallucinated-id]",
        )
        result = _backfill_evidence_ids_from_prose(summary, real_ids={"real-1"})
        assert result.evidence_ids == []
