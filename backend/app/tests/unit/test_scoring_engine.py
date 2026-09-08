"""Unit tests for app.scoring.engine.score_investigation -- the deterministic
(non-AI) threat-scoring engine. Pure function over already-fetched data, so
these are plain synchronous tests with no mocking, matching
test_correlation_engine.py's own style for the module it most directly
depends on.
"""
from app.correlation.engine import CorrelationResult, GraphEdge, GraphNode
from app.ioc.types import IOCType
from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus
from app.scoring.engine import ScoringResult, score_investigation

SEED_VALUE = "1.2.3.4"
SEED_TYPE = IOCType.IPV4


def make_result(provider_id: str, data: dict, status: ProviderStatus = ProviderStatus.OK) -> ProviderResult:
    return ProviderResult(
        provider_id=provider_id,
        provider_name=provider_id.upper(),
        category=ProviderCategory.THREAT_INTEL,
        status=status,
        ioc_value=SEED_VALUE,
        ioc_type=SEED_TYPE,
        data=data,
    )


def empty_correlation() -> CorrelationResult:
    return CorrelationResult(nodes=[], edges=[], deduplicated_facts={}, provider_agreement={})


# --- Zero evidence -----------------------------------------------------------


def test_zero_evidence_of_every_kind_is_all_zero_not_an_error():
    result = score_investigation([], empty_correlation())
    assert result.overall_risk_score == 0
    assert result.confidence_score == 0
    assert result.malicious_probability == 0
    assert result.severity == "none"


def test_only_non_ok_provider_results_is_treated_as_zero_evidence():
    """A provider that errored/wasn't configured/found nothing must not
    contribute a vote just by existing in the list -- correlate() ignores
    non-OK results the same way (see app/correlation/engine.py)."""
    results = [
        make_result("virustotal", {"verdict": "malicious"}, status=ProviderStatus.ERROR),
        make_result("otx", {"verdict": "malicious"}, status=ProviderStatus.NOT_CONFIGURED),
    ]
    result = score_investigation(results, empty_correlation())
    assert result.overall_risk_score == 0
    assert result.malicious_probability == 0
    assert result.severity == "none"


def test_unknown_verdict_casts_no_vote_rather_than_being_treated_as_clean():
    """A provider that ran fine but had no opinion ("unknown"/missing) must
    not be silently coerced into "clean" -- that would manufacture
    confidence the provider never actually offered. With only a genuinely
    silent provider, this must be indistinguishable from zero evidence."""
    results = [make_result("otx", {"verdict": "unknown"})]
    result = score_investigation(results, empty_correlation())
    assert result.overall_risk_score == 0
    assert result.confidence_score == 0
    assert result.breakdown["voting_provider_count"] == 0


# --- Corroboration: single flag vs. multiple agreeing providers -------------


def test_single_unconfirmed_malicious_flag_scores_meaningfully_lower_than_full_strength():
    """A single provider's "malicious" flag, with nothing else corroborating
    it, must land well under what full provider-verdict-consensus strength
    would be -- this is the direct implementation of the platform
    requirement that a lone flag score meaningfully lower than agreement."""
    result = score_investigation([make_result("virustotal", {"verdict": "malicious"})], empty_correlation())
    assert result.breakdown["voting_provider_count"] == 1
    # 65 is _PROVIDER_VERDICT_WEIGHT (the max this component alone could reach).
    assert 0 < result.overall_risk_score < 65 * 0.5, "a lone flag must be well under full component strength"
    assert result.severity in ("low", "medium")


def test_five_corroborating_malicious_providers_score_much_higher_than_one():
    single = score_investigation([make_result("p0", {"verdict": "malicious"})], empty_correlation())
    five = score_investigation(
        [make_result(f"p{i}", {"verdict": "malicious"}) for i in range(5)], empty_correlation()
    )
    assert five.overall_risk_score > 2 * single.overall_risk_score
    assert five.malicious_probability == 65.0, "5+ agreeing providers should reach full provider-component strength"
    assert five.severity in ("high", "critical")
    assert five.confidence_score > single.confidence_score


def test_corroboration_factor_increases_monotonically_with_agreeing_provider_count():
    scores = [
        score_investigation([make_result(f"p{i}", {"verdict": "malicious"}) for i in range(n)], empty_correlation())
        for n in range(1, 6)
    ]
    for earlier, later in zip(scores, scores[1:]):
        assert later.overall_risk_score >= earlier.overall_risk_score
        assert later.confidence_score >= earlier.confidence_score


# --- Conflicting evidence: uncertainty, not a blind average -----------------


def test_conflicting_verdicts_collapse_confidence_rather_than_averaging_it():
    """The core "don't blindly average conflicting evidence" requirement:
    two providers that AGREE (both "suspicious") and two providers that
    CONFLICT (one "malicious", one "clean") land at a similar risk score
    (both are, honestly, a 0.5-ish mean vote) -- but the conflicting pair's
    confidence must be dramatically lower, not similar. A naive
    average-of-confidences approach would not have this property."""
    agreeing = score_investigation(
        [make_result("vt", {"verdict": "suspicious"}), make_result("otx", {"verdict": "suspicious"})],
        empty_correlation(),
    )
    conflicting = score_investigation(
        [make_result("vt", {"verdict": "malicious"}), make_result("otx", {"verdict": "clean"})],
        empty_correlation(),
    )
    # Similar risk score (both are close to a 0.5 mean vote at n=2) ...
    assert abs(agreeing.overall_risk_score - conflicting.overall_risk_score) < 5
    # ... but NOT similar confidence: conflict must cost real confidence.
    assert conflicting.confidence_score < agreeing.confidence_score / 2
    assert conflicting.confidence_score == 0.0, "a full 1.0-vs-0.0 split must zero out provider-agreement confidence"


def test_perfect_agreement_leaves_confidence_undiminished_by_spread():
    result = score_investigation(
        [make_result("vt", {"verdict": "malicious"}), make_result("otx", {"verdict": "malicious"})],
        empty_correlation(),
    )
    assert result.breakdown["provider_agreement_spread"] == 0.0
    assert result.confidence_score == result.overall_risk_score  # no spread penalty applied at all


# --- Multi-engine detection-ratio precision (VirusTotal-style data) ---------


def test_multi_engine_detection_ratio_used_in_place_of_categorical_verdict():
    """A provider with a real graduated detection ratio (VirusTotal's
    malicious_count/total_engines) should be scored on that ratio, not
    collapsed to a blunt 100%-vote just because verdict=="malicious"."""
    weak_hit = score_investigation(
        [make_result("virustotal", {"verdict": "malicious", "malicious_count": 2, "suspicious_count": 0, "total_engines": 70})],
        empty_correlation(),
    )
    strong_hit = score_investigation(
        [make_result("virustotal", {"verdict": "malicious", "malicious_count": 68, "suspicious_count": 0, "total_engines": 70})],
        empty_correlation(),
    )
    assert weak_hit.overall_risk_score < strong_hit.overall_risk_score
    # A bare categorical "malicious" vote (a provider with no engine-count
    # granularity, e.g. OTX/AbuseIPDB) is taken at face value -- full vote
    # strength (1.0) -- since there is no finer-grained signal to prefer
    # instead. That is deliberately >= even a near-unanimous 68/70 engine
    # ratio (0.971), not "between" the weak and strong engine-ratio cases:
    # this engine has no basis to treat a provider's own plain-word verdict
    # as LESS certain than a provider that happens to expose a fraction.
    categorical = score_investigation([make_result("otx", {"verdict": "malicious"})], empty_correlation())
    assert categorical.overall_risk_score >= strong_hit.overall_risk_score > weak_hit.overall_risk_score


def test_suspicious_count_contributes_half_weight_in_engine_ratio():
    all_malicious = score_investigation(
        [make_result("vt", {"malicious_count": 10, "suspicious_count": 0, "total_engines": 70})], empty_correlation()
    )
    half_suspicious = score_investigation(
        [make_result("vt", {"malicious_count": 5, "suspicious_count": 10, "total_engines": 70})], empty_correlation()
    )
    # 5 + 0.5*10 == 10 -- same effective numerator as all_malicious.
    assert all_malicious.overall_risk_score == half_suspicious.overall_risk_score


# --- Correlation-graph contribution -----------------------------------------


def test_qualifying_correlation_edge_raises_score_with_no_provider_verdict_at_all():
    correlation = CorrelationResult(
        nodes=[GraphNode(node_id=f"ipv4:{SEED_VALUE}", ioc_type="ipv4", value=SEED_VALUE)],
        edges=[
            GraphEdge(
                source=f"ipv4:{SEED_VALUE}",
                target="malware_family:emotet",
                relationship="associated_with",
                confidence=1.0,
                provenance="virustotal,otx",
            )
        ],
        deduplicated_facts={},
        provider_agreement={},
    )
    result = score_investigation([], correlation)
    assert result.overall_risk_score > 0
    assert result.malicious_probability == result.overall_risk_score


def test_single_provider_flooding_distinct_correlation_edges_is_capped_like_a_lone_vote():
    """Regression test for a real, numerically-reproduced red-team finding:
    a single free, unprivileged community account on a provider like OTX/
    ThreatFox/MalwareBazaar can publish one submission listing several
    DISTINCT free-text malware_families/threat_actors/campaigns -- correlate()
    gives each distinct value its own edge (never merged, since they're not
    identical claims), so before this fix a lone source could single-
    handedly saturate _CORRELATION_WEIGHT with zero cross-provider
    corroboration and zero real malicious infrastructure, pushing an
    innocent third-party indicator into the "high" severity band. Reproduces
    the exact scenario: one provider vote (lone, capped at 40% strength) +
    4 distinct same-provider qualifying edges at 0.5 confidence each (sum
    2.0 == full _CORRELATION_SATURATION)."""
    provider_results = [make_result("otx", {"verdict": "malicious"})]
    flooded_correlation = CorrelationResult(
        nodes=[],
        edges=[
            GraphEdge(
                source=f"ipv4:{SEED_VALUE}",
                target=f"malware_family:fake{i}",
                relationship="associated_with",
                confidence=0.5,
                provenance="otx",
            )
            for i in range(4)
        ],
        deduplicated_facts={},
        provider_agreement={},
    )
    flooded = score_investigation(provider_results, flooded_correlation)

    # Before this fix: overall_risk_score/malicious_probability == 61.0,
    # inside the "high" band (>=55). The fix must keep a single-source flood
    # meaningfully below that, without zeroing it out entirely (a lone
    # provider's claim is still SOME evidence, just capped like any other
    # lone vote).
    assert flooded.severity != "high"
    assert flooded.severity != "critical"
    assert flooded.overall_risk_score < 55.0
    assert flooded.overall_risk_score > 0

    # Genuine corroboration must NOT be punished the same way: the same
    # total qualifying confidence (2.0), but asserted by 2 DISTINCT
    # providers instead of 1, should score meaningfully HIGHER than the
    # single-source flood above -- proving the fix discriminates real
    # corroboration from a flood, rather than blindly discounting every
    # correlation edge.
    corroborated_correlation = CorrelationResult(
        nodes=[],
        edges=[
            GraphEdge(
                source=f"ipv4:{SEED_VALUE}",
                target="malware_family:emotet",
                relationship="associated_with",
                confidence=1.0,
                provenance="otx,threatfox",
            ),
            GraphEdge(
                source=f"ipv4:{SEED_VALUE}",
                target="threat_actor:trickbot-crew",
                relationship="attributed_to",
                confidence=1.0,
                provenance="otx,threatfox",
            ),
        ],
        deduplicated_facts={},
        provider_agreement={},
    )
    corroborated = score_investigation(provider_results, corroborated_correlation)
    assert corroborated.overall_risk_score > flooded.overall_risk_score


def test_single_provider_correlation_cap_holds_beyond_the_exact_saturation_point():
    """Regression test for a real defect in the "fix" the previous test
    (test_single_provider_flooding_distinct_correlation_edges_is_capped_like_a_lone_vote)
    was meant to guard: that test only ever exercised EXACTLY 4 edges at 0.5
    confidence each, i.e. sum == 2.0 == _CORRELATION_SATURATION -- the one
    point where the (buggy) `total_confidence * corroboration` formula
    happens to coincide with the intended `min(1, fraction) * corroboration`
    formula. _correlation_fraction() multiplied an UNBOUNDED sum of
    qualifying-edge confidences by the corroboration factor and only clipped
    the *product*, so it did not actually cap the achievable fraction at
    corroboration's value (0.40 for a lone provider) -- it just raised how
    much raw confidence was needed to reach full (100%) saturation, from 2.0
    to 5.0. A single provider asserting 10 distinct qualifying tags (5.0 of
    total confidence at 0.5 each, e.g. 10 OTX malware_families from one
    pulse-heavy indicator) drove correlation_qualifying_fraction to a full
    1.0 pre-fix, saturating the entire 35-point correlation weight with zero
    cross-provider corroboration -- exactly what this module's own docstring
    says must never happen. Sweeping edge count with everything else held
    constant (still ONE provider, still 0.5 confidence/edge) must keep the
    fraction capped at 0.40 the whole way, not just at the single point the
    sibling test happened to check."""
    provider_results = [make_result("otx", {"verdict": "malicious"})]
    for edge_count in (4, 6, 8, 10):
        correlation = CorrelationResult(
            nodes=[],
            edges=[
                GraphEdge(
                    source=f"ipv4:{SEED_VALUE}",
                    target=f"malware_family:fake{i}",
                    relationship="associated_with",
                    confidence=0.5,
                    provenance="otx",
                )
                for i in range(edge_count)
            ],
            deduplicated_facts={},
            provider_agreement={},
        )
        result = score_investigation(provider_results, correlation)
        assert result.breakdown["correlation_qualifying_fraction"] <= 0.4 + 1e-9, (
            f"edge_count={edge_count}: single-provider correlation fraction "
            f"{result.breakdown['correlation_qualifying_fraction']} exceeded the 40% cap"
        )
        assert result.severity not in ("high", "critical"), f"edge_count={edge_count} reached {result.severity}"
        assert result.overall_risk_score < 55.0, f"edge_count={edge_count} reached the 'high' threshold"

    # At 10 edges (5.0 of raw confidence), the pre-fix formula fully
    # saturated the component (fraction == 1.0, correlation_component ==
    # 35.0) and, combined with the lone provider's own vote, reproduced the
    # documented 61.0/"high" outcome. Confirm that specific numeric
    # regression is gone.
    ten_edges = score_investigation(
        provider_results,
        CorrelationResult(
            nodes=[],
            edges=[
                GraphEdge(
                    source=f"ipv4:{SEED_VALUE}",
                    target=f"malware_family:fake{i}",
                    relationship="associated_with",
                    confidence=0.5,
                    provenance="otx",
                )
                for i in range(10)
            ],
            deduplicated_facts={},
            provider_agreement={},
        ),
    )
    assert ten_edges.breakdown["correlation_component"] <= 14.1, "correlation_component must stay ~<=40% of 35"
    assert ten_edges.overall_risk_score != 61.0
    assert ten_edges.severity != "high"


def test_purely_infrastructural_edge_does_not_raise_score():
    """resolves_to/hosts/belongs_to_asn/etc. are not, by themselves,
    evidence of malice -- only malware/threat-actor/campaign/MITRE/CVE
    edges qualify (see _QUALIFYING_RELATIONSHIPS's docstring)."""
    correlation = CorrelationResult(
        nodes=[],
        edges=[
            GraphEdge(source="x", target="ipv4:5.6.7.8", relationship="resolves_to", confidence=1.0, provenance="vt"),
        ],
        deduplicated_facts={},
        provider_agreement={},
    )
    result = score_investigation([], correlation)
    assert result.overall_risk_score == 0


# --- Security Assessment findings: a floor, not an additive term -----------


def test_critical_security_finding_alone_meaningfully_raises_overall_risk():
    result = score_investigation([], empty_correlation(), security_finding_severities=["critical"])
    assert result.overall_risk_score >= 70.0
    assert result.severity in ("high", "critical")
    assert result.confidence_score > 0


def test_security_finding_floor_does_not_inflate_malicious_probability():
    """A critical VULNERABILITY finding ("dangerous to leave exposed") is a
    different claim from "this indicator IS a confirmed malicious actor" --
    malicious_probability must stay a pure reputation/relationship signal so
    FinalAssessment's _verdict_must_agree_with_risk validator continues to
    mean what it always meant."""
    result = score_investigation([], empty_correlation(), security_finding_severities=["critical"])
    assert result.malicious_probability == 0.0
    assert result.overall_risk_score > result.malicious_probability


def test_security_finding_floor_never_lowers_an_already_higher_score():
    high_reputation = score_investigation(
        [make_result(f"p{i}", {"verdict": "malicious"}) for i in range(5)], empty_correlation()
    )
    with_low_finding = score_investigation(
        [make_result(f"p{i}", {"verdict": "malicious"}) for i in range(5)],
        empty_correlation(),
        security_finding_severities=["low"],
    )
    assert with_low_finding.overall_risk_score == high_reputation.overall_risk_score


def test_multiple_findings_at_the_top_severity_nudge_the_floor_higher_than_one():
    one = score_investigation([], empty_correlation(), security_finding_severities=["high"])
    two = score_investigation([], empty_correlation(), security_finding_severities=["high", "high"])
    assert two.overall_risk_score >= one.overall_risk_score


def test_security_finding_severity_accepts_enum_like_objects():
    """Callers pass app/models/security_assessment.py's Severity enum
    members directly (e.g. `finding.severity`), not plain strings -- this
    module must not require the caller to pre-convert them with `.value`."""

    class _FakeSeverity:
        def __init__(self, value):
            self.value = value

    result = score_investigation([], empty_correlation(), security_finding_severities=[_FakeSeverity("critical")])
    assert result.overall_risk_score >= 70.0


def test_unrecognized_severity_string_is_ignored_not_an_error():
    result = score_investigation([], empty_correlation(), security_finding_severities=["not-a-real-severity"])
    assert result.overall_risk_score == 0.0


# --- Duck-typing over ORM rows (reanalyze_lookup()'s call site) ------------


def test_accepts_orm_like_rows_with_plain_string_status():
    """app/api/routes/lookup.py's reanalyze_lookup() passes persisted
    ProviderResultRecord ORM rows (plain str `.status` column, not a
    ProviderStatus enum instance) -- this must score identically to the
    equivalent ProviderResult dataclass instance."""

    class _FakeOrmRow:
        def __init__(self, status: str, data: dict):
            self.status = status
            self.data = data

    orm_style = score_investigation([_FakeOrmRow("ok", {"verdict": "malicious"})], empty_correlation())
    dataclass_style = score_investigation([make_result("vt", {"verdict": "malicious"})], empty_correlation())
    assert orm_style.overall_risk_score == dataclass_style.overall_risk_score


# --- Severity banding ---------------------------------------------------


def test_severity_band_thresholds():
    from app.scoring.engine import _severity_band

    assert _severity_band(0) == "none"
    assert _severity_band(9.9) == "none"
    assert _severity_band(10) == "low"
    assert _severity_band(29.9) == "low"
    assert _severity_band(30) == "medium"
    assert _severity_band(54.9) == "medium"
    assert _severity_band(55) == "high"
    assert _severity_band(79.9) == "high"
    assert _severity_band(80) == "critical"
    assert _severity_band(100) == "critical"


def test_severity_matches_severity_band_of_the_returned_overall_risk_score():
    """Regression test for a real bug: severity was classified from the
    full-precision `overall_risk_score` BEFORE it got rounded to 1 decimal
    for the field actually returned in the same ScoringResult. When the
    unrounded value sits just under a threshold but rounds up onto/over it,
    the two returned fields disagreed with each other under the module's
    own _SEVERITY_THRESHOLDS table.

    Concrete boundary case: 4 "clean" + 1 "suspicious" provider votes (mean
    vote -> provider_component == 6.5) plus one qualifying, single-provider
    correlation edge at confidence 0.4 (correlation_component == 2.8) sums
    to a raw threat_intel_score of 9.950000000000003 -- just under the 10.0
    "low" cutoff, so pre-fix this classified as "none". But
    round(9.950000000000003, 1) == 10.0, which _SEVERITY_THRESHOLDS itself
    maps to "low" -- so the API returned overall_risk_score=10.0 alongside
    severity="none", an internally self-contradictory pair. Post-fix,
    severity must be derived from that same rounded 10.0 and therefore
    agree with _severity_band applied to the exact value returned."""
    from app.scoring.engine import _severity_band

    results = [
        make_result(f"p{i}", {"verdict": v})
        for i, v in enumerate(["clean", "clean", "clean", "clean", "suspicious"])
    ]
    correlation = CorrelationResult(
        nodes=[],
        edges=[
            GraphEdge(
                source=f"ipv4:{SEED_VALUE}",
                target="malware_family:f0",
                relationship="associated_with",
                confidence=0.4,
                provenance="p",
            )
        ],
        deduplicated_facts={},
        provider_agreement={},
    )
    result = score_investigation(results, correlation)

    assert result.overall_risk_score == 10.0
    assert result.severity == _severity_band(result.overall_risk_score), (
        f"severity={result.severity!r} must agree with _severity_band() applied to the "
        f"exact overall_risk_score returned ({result.overall_risk_score}) -> "
        f"{_severity_band(result.overall_risk_score)!r}"
    )
    assert result.severity == "low"


def test_engine_version_is_stamped_on_every_result():
    from app.scoring.engine import SCORING_ENGINE_VERSION

    result = score_investigation([], empty_correlation())
    assert result.engine_version == SCORING_ENGINE_VERSION
