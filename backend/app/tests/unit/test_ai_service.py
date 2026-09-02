"""Unit tests for app.ai.service.generate_final_assessment -- specifically
the no-real-evidence guard.

Regression test for a severe bug found via live E2E testing: looking up
44d88612fea8a8f36de82e1278abb02f (the EICAR test file's real MD5) against
four not_configured providers (zero real data of any kind: empty
provider_summaries, zero correlation edges) still returned
final_verdict="highly_malicious" with malicious_probability=92 and prose
claiming "association with ransomware and trojans" -- entirely fabricated,
since llama3.2:3b answered from its own pretrained knowledge of a famous
test hash rather than admitting it had no evidence, directly violating its
own system prompt's "never fabricate" instruction.

Fix: generate_final_assessment now short-circuits BEFORE calling the AI at
all when there are no provider summaries and no correlation edges, since an
empty-evidence case has exactly one correct answer (verdict=unknown,
malicious_probability=0) regardless of which AI backend is configured --
no prompt wording can reliably fix a model that already had the "don't
fabricate" instruction and ignored it.
"""
import pytest
from pydantic import ValidationError

from app.ai.schemas import FinalAssessment
from app.ai.service import _prune_for_prompt, generate_final_assessment
from app.correlation.engine import CorrelationResult
from app.models.lookup import Verdict
from app.scoring.engine import ScoringResult

_VALID_ASSESSMENT_PAYLOAD = {
    "executive_summary": "Test.",
    "technical_summary": "Test.",
    "threat_assessment": "Test.",
    "relationships_summary": "Test.",
    "risk": {
        "overall_risk_score": 90,
        "confidence_score": 80,
        "severity": "critical",
        "reputation": "malicious",
        "malicious_probability": 95,
        "analyst_confidence": "high",
    },
    "final_verdict": "malicious",
    "verdict_rationale": "Test.",
}

_SELF_CONTRADICTORY_ASSESSMENT_PAYLOAD = {
    **_VALID_ASSESSMENT_PAYLOAD,
    "risk": {**_VALID_ASSESSMENT_PAYLOAD["risk"], "malicious_probability": 10},
}


def _empty_correlation() -> CorrelationResult:
    return CorrelationResult(nodes=[], edges=[], deduplicated_facts={}, provider_agreement={})


def _zero_scoring() -> ScoringResult:
    """A deterministic score matching "no evidence of any kind" -- the
    scoring engine's own actual output for empty input (see
    test_scoring_engine.py), used wherever a test's evidence is empty/
    irrelevant to what it's actually checking."""
    return ScoringResult(overall_risk_score=0, confidence_score=0, malicious_probability=0, severity="none")


def _scoring_matching(payload: dict) -> ScoringResult:
    """Builds a ScoringResult whose numbers match a given AI payload's risk
    block -- used where a test wants the (stubbed) AI response and the
    deterministic score to agree, so generate_final_assessment's own
    swap-and-revalidate step (app/ai/service.py) is a no-op rather than the
    thing under test."""
    risk = payload["risk"]
    return ScoringResult(
        overall_risk_score=risk["overall_risk_score"],
        confidence_score=risk["confidence_score"],
        malicious_probability=risk["malicious_probability"],
        severity=risk["severity"],
    )


@pytest.mark.asyncio
async def test_no_provider_data_and_no_edges_returns_unknown_without_calling_ai(monkeypatch):
    async def _fail_if_called(backend_override=None):
        raise AssertionError("AI client must not be called when there is no real evidence to assess")

    monkeypatch.setattr("app.ai.service._get_ai_client", _fail_if_called)

    result = await generate_final_assessment(
        ioc_value="44d88612fea8a8f36de82e1278abb02f",
        ioc_type="md5",
        provider_summaries=[],
        correlation=_empty_correlation(),
        scoring=_zero_scoring(),
    )

    assert result.final_verdict == Verdict.UNKNOWN
    assert result.risk.malicious_probability == 0
    assert result.risk.overall_risk_score == 0
    assert result.risk.severity == "none"
    # The exact bug: must never claim malware/ransomware/trojan association
    # (or anything else specific) when there's no evidence behind it.
    assert "ransomware" not in result.executive_summary.lower()
    assert "trojan" not in result.executive_summary.lower()
    assert "ransomware" not in result.technical_summary.lower()
    # This is a CORRECT decision, not a failure -- must be tagged distinctly
    # from the genuine-failure fallback (see test_total_failure_sets_ai_outcome_failed
    # below), so a later "AI success rate" KPI never counts this as a failure.
    assert result.ai_outcome == "skipped_no_evidence"
    assert result.ai_backend is None
    assert result.ai_model is None


@pytest.mark.asyncio
async def test_correlation_edges_alone_are_enough_to_call_the_ai(monkeypatch):
    """The guard is specifically "no summaries AND no edges" -- if the
    correlation engine found real relationships (e.g. via a provider that
    returned OK but produced no per-provider summary path), there IS real
    evidence, so the AI must still be consulted rather than short-circuited.
    """
    called = {"value": False}

    class _StubAIClient:
        is_configured = True

        async def call_claude_json(self, system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None):
            called["value"] = True
            return {
                "executive_summary": "Test.",
                "technical_summary": "Test.",
                "threat_assessment": "Test.",
                "relationships_summary": "Test.",
                "risk": {
                    "overall_risk_score": 10,
                    "confidence_score": 50,
                    "severity": "low",
                    "reputation": "unknown",
                    "malicious_probability": 10,
                    "analyst_confidence": "low",
                },
                "final_verdict": "unknown",
                "verdict_rationale": "Test.",
            }

    async def _stub_get_ai_client(backend_override=None):
        return _StubAIClient(), "ollama", "stub-model"

    monkeypatch.setattr("app.ai.service._get_ai_client", _stub_get_ai_client)

    from app.correlation.engine import GraphEdge, GraphNode

    correlation = CorrelationResult(
        nodes=[GraphNode(node_id="md5:x", ioc_type="md5", value="x")],
        edges=[GraphEdge(source="md5:x", target="domain:y", relationship="resolves_to", confidence=0.8, provenance="some_provider")],
        deduplicated_facts={},
        provider_agreement={},
    )

    await generate_final_assessment(
        ioc_value="x",
        ioc_type="md5",
        provider_summaries=[],
        correlation=correlation,
        scoring=ScoringResult(overall_risk_score=10, confidence_score=50, malicious_probability=10, severity="low"),
    )

    assert called["value"], "AI must be consulted when correlation edges provide real evidence"


def _some_evidence_correlation() -> CorrelationResult:
    from app.correlation.engine import GraphEdge, GraphNode

    return CorrelationResult(
        nodes=[GraphNode(node_id="md5:x", ioc_type="md5", value="x")],
        edges=[GraphEdge(source="md5:x", target="domain:y", relationship="resolves_to", confidence=0.8, provenance="p")],
        deduplicated_facts={},
        provider_agreement={},
    )


@pytest.mark.asyncio
async def test_self_contradictory_verdict_is_retried_and_recovers(monkeypatch):
    """Regression test for a real bug found via live E2E testing: Ollama
    (llama3.2:3b) emitted final_verdict="malicious" with
    risk.malicious_probability=10-20 -- FinalAssessment's own validator
    correctly rejected it, but with no retry, that single bad sample threw
    away the whole assessment every time. One retry is a cheap, standard
    mitigation for a stochastic model's next sample not being the same
    sample."""
    call_count = {"value": 0}

    class _FlakyAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            call_count["value"] += 1
            if call_count["value"] == 1:
                return dict(_SELF_CONTRADICTORY_ASSESSMENT_PAYLOAD)
            return dict(_VALID_ASSESSMENT_PAYLOAD)

    async def _stub_get_ai_client(backend_override=None):
        return _FlakyAIClient(), "ollama", "stub-model"

    monkeypatch.setattr("app.ai.service._get_ai_client", _stub_get_ai_client)

    # Matches _VALID_ASSESSMENT_PAYLOAD's risk block (the second attempt) so
    # that generate_final_assessment's post-validation swap-in of the
    # deterministic score (app/ai/service.py) is a no-op here -- this test
    # is specifically about the RETRY mechanism recovering from one bad
    # sample, not about the separate swap-and-revalidate safety net (see
    # test_ai_ignoring_given_score_gets_overridden_and_reverified below for
    # that).
    result = await generate_final_assessment(
        ioc_value="x",
        ioc_type="md5",
        provider_summaries=[],
        correlation=_some_evidence_correlation(),
        scoring=_scoring_matching(_VALID_ASSESSMENT_PAYLOAD),
    )

    assert call_count["value"] == 2, "must retry exactly once after a validation failure"
    assert result.final_verdict == Verdict.MALICIOUS
    assert result.ai_backend == "ollama"
    assert result.risk.malicious_probability == 95


_BARE_VERDICT_CONTRADICTION_PAYLOAD = {
    "ioc_value": "8.8.8.8",
    "ioc_type": "ipv4",
    "executive_summary": "Test.",
    "technical_summary": "Test.",
    "threat_assessment": "malicious",
    "relationships_summary": "Test.",
    "risk": {
        "overall_risk_score": 0,
        "confidence_score": 0,
        "severity": "none",
        "reputation": "unknown",
        "malicious_probability": 0,
        "analyst_confidence": "low",
    },
    "final_verdict": "benign",
    "verdict_rationale": "Test.",
}


def test_bare_verdict_in_threat_assessment_contradicting_final_verdict_is_rejected():
    """Regression test for a real bug found via live E2E testing against a
    freshly installed instance: investigating 8.8.8.8 with Ollama
    (llama3.2:3b) returned threat_assessment="malicious" (a bare one-word
    verdict label, not a sentence) alongside a correctly-computed
    final_verdict="benign"/malicious_probability=0 -- two fields in the same
    response directly contradicting each other, reaching the UI uncaught
    since _verdict_must_agree_with_risk only checks final_verdict against
    the risk numbers, never threat_assessment's own content.
    FinalAssessmentPanel.tsx renders these as two separately-labeled tabs
    ("Threat Assessment" / "Risk & Verdict"), so an analyst reading one
    without the other would see a flatly wrong answer."""
    with pytest.raises(ValidationError, match="threat_assessment.*contradicts final_verdict"):
        FinalAssessment(**_BARE_VERDICT_CONTRADICTION_PAYLOAD)


def test_narrative_threat_assessment_mentioning_malicious_is_not_flagged():
    """The bare-verdict check must not fire on ordinary narrative prose that
    happens to contain a verdict-shaped word mid-sentence -- only on
    threat_assessment being a bare, standalone verdict label."""
    payload = {
        **_BARE_VERDICT_CONTRADICTION_PAYLOAD,
        "threat_assessment": "No provider found evidence that this IP address is malicious; all data points to a benign, well-known public DNS resolver.",
        "supporting_evidence": ["whois_rdap confirms Google LLC ownership with a clean reputation."],
    }
    result = FinalAssessment(**payload)
    assert result.final_verdict == Verdict.BENIGN


@pytest.mark.asyncio
async def test_non_validation_failure_is_not_retried(monkeypatch):
    """Regression test: a Groq HTTP 429 rate-limit error, unlike a
    self-contradictory model sample, is not fixed by retrying immediately --
    it just consumes more of the same exhausted per-minute quota. The retry
    added for the validation-inconsistency bug must not also retry generic
    API/network failures, or every rate limit becomes two failed calls
    instead of one."""
    call_count = {"value": 0}

    class _AlwaysFailsAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            call_count["value"] += 1
            raise RuntimeError("HTTP 429: rate limit exceeded")

    async def _stub_get_ai_client(backend_override=None):
        return _AlwaysFailsAIClient(), "groq", "stub-model"

    monkeypatch.setattr("app.ai.service._get_ai_client", _stub_get_ai_client)

    result = await generate_final_assessment(
        ioc_value="x",
        ioc_type="md5",
        provider_summaries=[],
        correlation=_some_evidence_correlation(),
        scoring=_zero_scoring(),
    )

    assert call_count["value"] == 1, "a non-validation failure must not be retried"
    assert result.final_verdict == Verdict.UNKNOWN
    # A GENUINE failure (the AI backend was reachable but every attempt
    # raised) -- must be tagged distinctly from the no-evidence short-circuit
    # (test_no_provider_data_and_no_edges_returns_unknown_without_calling_ai
    # above), which is a correct decision rather than a failure.
    assert result.ai_outcome == "failed"
    assert result.ai_backend is None
    assert result.ai_model is None


@pytest.mark.asyncio
async def test_ai_that_echoes_given_score_persists_it_unchanged(monkeypatch):
    """The common/happy path for the deterministic-scoring design: the AI is
    told overall_risk_score/confidence_score/malicious_probability/severity
    as given facts and echoes them back consistently with its own verdict.
    The persisted risk block must equal the deterministic `scoring` input
    exactly -- this is the platform's actual score now, not the AI's."""

    class _CompliantAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            return {
                "executive_summary": "Test.", "technical_summary": "Test.", "threat_assessment": "Test.",
                "relationships_summary": "Test.",
                "risk": {
                    "overall_risk_score": 65, "confidence_score": 65, "severity": "high",
                    "reputation": "malicious", "malicious_probability": 65, "analyst_confidence": "medium",
                },
                "final_verdict": "malicious", "verdict_rationale": "Consistent with the given numbers.",
            }

    async def _stub_get_ai_client(backend_override=None):
        return _CompliantAIClient(), "anthropic", "claude-x"

    monkeypatch.setattr("app.ai.service._get_ai_client", _stub_get_ai_client)

    scoring = ScoringResult(overall_risk_score=65, confidence_score=65, malicious_probability=65, severity="high")
    result = await generate_final_assessment(
        ioc_value="x", ioc_type="md5", provider_summaries=[], correlation=_some_evidence_correlation(), scoring=scoring
    )

    assert result.risk.overall_risk_score == 65
    assert result.risk.confidence_score == 65
    assert result.risk.malicious_probability == 65
    assert result.risk.severity == "high"
    assert result.final_verdict == Verdict.MALICIOUS
    # The real success path: the AI was actually called and its output
    # validated -- must be tagged distinctly from either non-success path.
    assert result.ai_outcome == "success"
    assert result.ai_backend == "anthropic"
    assert result.ai_model == "claude-x"


@pytest.mark.asyncio
async def test_ai_ignoring_given_score_gets_overridden_and_reverified(monkeypatch):
    """The safety-net path: a model that ignores the "these numbers are
    given, do not invent your own" instruction and emits a
    self-consistent-but-WRONG pair (verdict="highly_malicious" with its own
    invented malicious_probability=92) must NOT get to persist that pair,
    even though it passes FinalAssessment's validator on its own terms (92
    genuinely supports "highly_malicious").

    This is the exact validator-ordering gap the deterministic-scoring
    design has to close: generate_final_assessment() swaps the model's risk
    numbers for the real, deterministically-computed ones (here, a genuinely
    LOW score of 20 -- one weak, uncorroborated signal) and must re-run
    _verdict_must_agree_with_risk against THAT pair, not silently keep
    whatever passed against the model's own fabricated numbers. Since this
    model always repeats the same invented numbers, the retry also fails,
    and the function must fall through to the deterministic-only fallback
    -- which still reports the REAL score (20), never the model's fantasy
    (92), and never a false "malicious" verdict the real score doesn't
    support.
    """
    call_count = {"value": 0}

    class _NoncompliantAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            call_count["value"] += 1
            return {
                "executive_summary": "Test.", "technical_summary": "Test.", "threat_assessment": "Test.",
                "relationships_summary": "Test.",
                "risk": {
                    "overall_risk_score": 92, "confidence_score": 80, "severity": "critical",
                    "reputation": "malicious", "malicious_probability": 92, "analyst_confidence": "high",
                },
                "final_verdict": "highly_malicious", "verdict_rationale": "Invented, ignoring the given numbers.",
            }

    async def _stub_get_ai_client(backend_override=None):
        return _NoncompliantAIClient(), "ollama", "stub-model"

    monkeypatch.setattr("app.ai.service._get_ai_client", _stub_get_ai_client)

    scoring = ScoringResult(overall_risk_score=20, confidence_score=20, malicious_probability=20, severity="low")
    result = await generate_final_assessment(
        ioc_value="x", ioc_type="md5", provider_summaries=[], correlation=_some_evidence_correlation(), scoring=scoring
    )

    assert call_count["value"] == 2, "the mismatch must be caught after the swap and retried once"
    # The real, deterministic numbers -- never the model's invented 92/critical/highly_malicious.
    assert result.risk.malicious_probability == 20
    assert result.risk.overall_risk_score == 20
    assert result.risk.severity == "low"
    assert result.final_verdict == Verdict.UNKNOWN
    # Fell through to the total-failure fallback (both attempts were rejected
    # by _verdict_must_agree_with_risk after the deterministic-score swap) --
    # a GENUINE failure, must be tagged "failed", not "success".
    assert result.ai_outcome == "failed"


@pytest.mark.asyncio
async def test_total_failure_after_unparseable_output_exhausts_retries_sets_ai_outcome_failed(monkeypatch):
    """Dedicated forced-failure test: the AI backend is reachable and returns
    a response on every call, but the response is missing required fields
    (unparseable against FinalAssessment) both on the first attempt AND the
    retry -- exhausting generate_final_assessment's one-retry budget without
    ever producing a valid FinalAssessment. This is the "every retry attempt
    raised" case ai_outcome="failed" exists to flag, distinct from the
    no-evidence short-circuit (which never calls the AI at all)."""
    call_count = {"value": 0}

    class _AlwaysUnparseableAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            call_count["value"] += 1
            # Missing every required field (executive_summary, risk, final_verdict, etc.)
            # -- FinalAssessment.model_validate() raises ValidationError every time.
            return {"garbage": "not a valid FinalAssessment payload"}

    async def _stub_get_ai_client(backend_override=None):
        return _AlwaysUnparseableAIClient(), "ollama", "stub-model"

    monkeypatch.setattr("app.ai.service._get_ai_client", _stub_get_ai_client)

    result = await generate_final_assessment(
        ioc_value="x",
        ioc_type="md5",
        provider_summaries=[],
        correlation=_some_evidence_correlation(),
        scoring=_zero_scoring(),
    )

    assert call_count["value"] == 2, "must retry exactly once, then give up after the retry also fails"
    assert result.ai_outcome == "failed"
    assert result.ai_backend is None
    assert result.ai_model is None
    assert result.final_verdict == Verdict.UNKNOWN


def test_prune_for_prompt_truncates_oversized_fields_only():
    """Regression test for a real bug found via live E2E testing: NVD's
    `configurations` field for CVE-2021-44228 (Log4Shell) runs to hundreds
    of nested CPE match entries -- dozens of times longer than the actual
    signal (verdict/cvss_score/description). Feeding that unbounded blob to
    summarize_provider() buried the CRITICAL severity under noise, and two
    different AI backends (a local 3B model and a hosted 70B model) both
    called a CVSS 10.0 RCE benign/unknown as a result. Short fields must
    pass through untouched; only oversized ones get collapsed."""
    data = {
        "verdict": "malicious",
        "cvss_score": 10.0,
        "cvss_severity": "CRITICAL",
        "configurations": [{"nested": "entry"} for _ in range(500)],
    }

    pruned = _prune_for_prompt(data)

    assert pruned["verdict"] == "malicious"
    assert pruned["cvss_score"] == 10.0
    assert pruned["cvss_severity"] == "CRITICAL"
    assert len(str(pruned["configurations"])) < len(str(data["configurations"]))
    assert "truncated" in pruned["configurations"]


def test_prune_for_prompt_does_not_truncate_realistic_single_field_signal():
    """Regression test for a bug introduced by the FIRST fix for this same
    function: the initial 800-char cap fixed NVD but broke MITRE ATT&CK,
    whose `description` is the ONLY signal-bearing field (no separate short
    verdict/score field the way NVD has). Real technique descriptions run
    600-1800+ chars (measured live: T1055=934, T1059=1588, T1027=1803), so
    800 silently chopped most real lookups mid-sentence. The cap must be
    high enough to leave realistic single-field-signal content like this
    fully intact."""
    realistic_description = (
        "Adversaries may inject malicious code into processes in order to evade "
        "process-based defenses as well as possibly elevate privileges. " * 13
    )  # 1742 chars, matching the real, measured MITRE ATT&CK T1027 description (1803 chars).
    assert len(realistic_description) < 2000

    data = {"technique_id": "T1055", "description": realistic_description}
    pruned = _prune_for_prompt(data)

    assert pruned["description"] == realistic_description, "a realistic single-field signal must not be truncated"


# --- Real P2 bug found live during overnight QA: unlike every field that
# reaches a prompt through _prune_for_prompt above, `ioc_value` itself was
# interpolated verbatim and unbounded -- a realistic ~2000-char URL IOC
# (well under the 2048-char field max) reliably broke structured-JSON
# generation on a small local model, since it must echo ioc_value back
# into its own JSON output and truncated mid-string. ---


def test_prune_ioc_value_leaves_realistic_short_iocs_untouched():
    from app.ai.service import _prune_ioc_value_for_prompt

    for value in ["8.8.8.8", "example.com", "CVE-2021-44228", "a" * 64]:  # ip/domain/cve/hash-length
        assert _prune_ioc_value_for_prompt(value) == value


def test_prune_ioc_value_truncates_a_realistic_long_url():
    from app.ai.service import _prune_ioc_value_for_prompt

    long_url = "http://example.com/" + "a" * 2000
    pruned = _prune_ioc_value_for_prompt(long_url)
    assert len(pruned) < len(long_url)
    assert pruned.startswith("http://example.com/")
    assert "truncated" in pruned
    assert "2019 chars total" in pruned  # len("http://example.com/") == 19, plus 2000 'a's


def test_prune_for_prompt_keeps_large_list_fields_tightly_capped():
    """Regression test for a bug introduced by the SECOND fix for this same
    function: raising the (then-uniform) cap to fix MITRE's description
    pushed a real live Groq call to HTTP 413 ("Request too large... 12402
    tokens" against a 12000 TPM limit), because NVD has TWO oversized
    fields, not one -- `references` (7,851 chars, a bare list of URLs) as
    well as `configurations` (67,721 chars) -- and both got quadrupled in
    size for no analytical benefit (neither carries a verdict). List/dict
    fields must stay tightly capped regardless of the generous cap given
    to genuine prose fields, even when realistically large."""
    data = {
        "verdict": "malicious",
        "references": [f"https://example.com/advisory-{i}" for i in range(200)],  # realistic NVD-scale list
    }
    assert len(str(data["references"])) > 5000

    pruned = _prune_for_prompt(data)

    assert len(pruned["references"]) <= 900, "a large list field must stay near the original tight cap, not the prose cap"
