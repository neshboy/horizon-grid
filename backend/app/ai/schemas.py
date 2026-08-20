"""Pydantic schemas that constrain what Claude is allowed to return.

Both the per-provider summary and the final assessment are requested as
structured JSON (via Bedrock's tool-use / forced JSON), validated against
these models. If Claude's output doesn't validate, the AI service retries
once with the validation error appended to the prompt, then falls back to a
minimal degraded summary -- it never lets malformed AI output reach the UI,
and it never lets the model invent fields outside this schema.

Every field the frontend keys off of exact string values (final_verdict,
reputation, threat_level, confidence, severity, detection rule format) uses
a real Literal/enum rather than a prose description. This matters for two
independent reasons: (1) backends that compile the JSON Schema into a
decoding grammar -- e.g. Ollama's structured output -- only enforce actual
`enum` constraints, not hints in a description string, so a prose-only
field lets a local model emit any string it wants; (2) the frontend's badge
color logic (frontend/lib/utils.ts, components/dashboard/ProviderCard.tsx)
is a hardcoded switch on exact lowercase values -- an off-spec value like
"Critical" or "very high" doesn't error, it just silently falls through to
the default/muted style.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.lookup import Verdict

_MALICIOUS_VERDICTS = {Verdict.MALICIOUS, Verdict.HIGHLY_MALICIOUS}
_BENIGN_VERDICTS = {Verdict.BENIGN, Verdict.LIKELY_BENIGN}

_Reputation = Literal["malicious", "suspicious", "clean", "unknown", "no data"]
_ThreatLevel = Literal["none", "low", "medium", "high", "critical"]
_Confidence = Literal["low", "medium", "high"]
# Which of generate_final_assessment()'s three return paths (app/ai/service.py)
# actually produced a given FinalAssessment -- "success" (the AI was called and
# validated), "skipped_no_evidence" (a CORRECT decision never to call the AI at
# all -- no provider data and no correlation edges), or "failed" (every retry
# attempt raised / never validated). Exists so a later KPI ("AI analysis
# success rate") can tell a genuine generation failure apart from a case where
# there was simply nothing to analyze, without inferring it from ai_backend
# being null/"unknown" -- which is true of BOTH non-success paths and can't
# distinguish them.
_AIOutcome = Literal["success", "failed", "skipped_no_evidence"]
_DetectionRuleFormat = Literal[
    "sigma", "yara", "splunk_spl", "sentinel_kql", "elastic", "qradar_aql", "suricata", "snort", "zeek"
]
# Exact ATT&CK phase_name slugs (matches app/providers/mitre_attack.py:98's
# kill_chain_phases[].phase_name values) -- a real enum here, not free text,
# so "Command And Control" and "command-and-control" can't land as two
# different tactics in MitreMatrix.tsx's exact-string-equality grouping.
_MitreTactic = Literal[
    "reconnaissance", "resource-development", "initial-access", "execution", "persistence",
    "privilege-escalation", "defense-evasion", "credential-access", "discovery", "lateral-movement",
    "collection", "command-and-control", "exfiltration", "impact",
]


class ProviderSummary(BaseModel):
    provider_id: str
    what_it_knows: str = Field(min_length=1, description="What this provider's data shows, in 1-3 sentences")
    reputation: _Reputation
    detection_status: str = Field(description="Detection counts / verdicts if the provider gave any")
    threat_level: _ThreatLevel
    confidence: _Confidence = Field(description="How much weight to give this source")
    interesting_findings: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list, description="Related IOCs this provider surfaced")
    unique_observations: list[str] = Field(default_factory=list)
    caveats: Optional[str] = Field(default=None, description="Data gaps, staleness, or ambiguity to flag")


class MitreMapping(BaseModel):
    # No `pattern=` here on purpose: Ollama's grammar compiler (llama.cpp
    # json-schema-to-grammar, observed on server 0.32.6) fails to compile a
    # regex `pattern` constraint into decoding grammar and returns HTTP 400
    # "failed to parse grammar", which breaks every generate_final_assessment()
    # call. A malformed technique_id isn't a real safety issue: it's already
    # handled downstream by app/ai/service.py's _ground_final_assessment(),
    # which only checks technique_id membership against real correlation-graph
    # technique IDs and sets grounded=False on mismatch -- it doesn't care
    # about ID format. The description still guides cloud models (Claude/
    # Gemini/Bedrock), which don't compile schemas into a decoding grammar.
    technique_id: str = Field(description="ATT&CK technique ID, e.g. T1071 or T1071.001")
    technique_name: str
    tactic: _MitreTactic
    kill_chain_stage: Optional[str] = Field(
        default=None,
        description=(
            "Only for a non-ATT&CK Cyber Kill Chain stage (e.g. Lockheed Martin's 7 stages: "
            "reconnaissance, weaponization, delivery, exploitation, installation, command-and-control, "
            "actions-on-objectives). Leave null unless you have a specific reason to add this beyond "
            "the ATT&CK tactic already captured in `tactic` -- do not restate `tactic` here."
        ),
    )
    rationale: str
    grounded: bool = Field(
        default=True,
        description=(
            "Set to false if this technique was NOT explicitly surfaced by a provider's data "
            "(e.g. MITRE ATT&CK provider's mitre_techniques field) and is instead your own inference "
            "from the IOC's behavior. Never claim grounded=true for an inferred mapping."
        ),
    )


class DetectionRule(BaseModel):
    format: _DetectionRuleFormat
    title: str
    rule: str


class RiskAssessment(BaseModel):
    overall_risk_score: float = Field(
        ge=0, le=100, description="Integer-like scale from 0 (no risk) to 100 (maximum risk). NOT a 0-1 probability."
    )
    confidence_score: float = Field(
        ge=0,
        le=100,
        description="How confident you are in this assessment, as a percentage from 0 to 100. NOT a 0-1 probability.",
    )
    severity: _ThreatLevel
    reputation: _Reputation
    malicious_probability: float = Field(
        ge=0,
        le=100,
        description="Probability this IOC is malicious, expressed as a percentage from 0 to 100 (e.g. 50, not 0.5).",
    )
    analyst_confidence: _Confidence
    # Set by the platform from app/scoring/engine.py's ScoringResult after generation -- do not
    # fill in. Persisted (not just computed in-memory) so a stored assessment can always be traced
    # back to which scoring engine version and factor breakdown actually produced its numbers, per
    # that module's own auditability requirement -- without this, engine.py's documented weights
    # would be auditable in source control but not against any specific past assessment.
    scoring_engine_version: Optional[str] = Field(
        default=None, description="Set by the platform after generation -- do not fill in."
    )
    scoring_breakdown: dict[str, float] = Field(
        default_factory=dict, description="Set by the platform after generation -- do not fill in."
    )

    @field_validator("overall_risk_score", "confidence_score", "malicious_probability")
    @classmethod
    def _reject_0_to_1_scale(cls, value: float) -> float:
        """Small local models default to a 0-1 probability convention for
        these fields despite the 0-100 description (observed: llama3.2:3b
        returning 0.5 for "50% confidence"). A fractional value under 1 is
        never a legitimate 0-100 score, so treat it as the model having used
        the wrong scale and rescale rather than silently accepting a score
        that's off by 100x.
        """
        if 0 < value < 1:
            return value * 100
        return value


class FinalAssessment(BaseModel):
    ioc_value: str
    ioc_type: str

    executive_summary: str = Field(min_length=1)
    technical_summary: str = Field(min_length=1)

    threat_assessment: str = Field(min_length=1)
    supporting_evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete evidence excerpts (quote or closely paraphrase specific facts from the "
            "per-provider summaries above) that back threat_assessment. If threat_assessment cites "
            "specific findings, this list must NOT be left empty -- prose alone does not satisfy this "
            "platform's evidence-traceability requirement; the UI renders this list, not the prose, as "
            "the assessment's supporting citations."
        ),
    )
    agreeing_providers: list[str] = Field(
        default_factory=list,
        description=(
            "The provider_id of every provider (as given in the per-provider summaries above, e.g. "
            "'virustotal', 'internet_intelligence' -- NOT its display name) that you describe in "
            "threat_assessment as agreeing with the verdict/reputation. Every provider named as "
            "agreeing in the prose MUST also be listed here: this array, not the prose, is what the UI "
            "renders as clickable provider citations."
        ),
    )
    disagreeing_providers: list[str] = Field(
        default_factory=list,
        description=(
            "The provider_id of every provider (as given in the per-provider summaries above -- NOT its "
            "display name) that you describe in threat_assessment as disagreeing or conflicting with the "
            "majority verdict or with another provider. Every provider named as disagreeing in the prose "
            "MUST also be listed here, for the same reason as agreeing_providers."
        ),
    )

    relationships_summary: str = Field(min_length=1)

    mitre_mappings: list[MitreMapping] = Field(default_factory=list)

    risk: RiskAssessment

    detection_rules: list[DetectionRule] = Field(default_factory=list)

    recommended_actions: list[str] = Field(default_factory=list)
    investigation_priorities: list[str] = Field(default_factory=list)
    incident_response_recommendations: list[str] = Field(default_factory=list)

    final_verdict: Verdict
    verdict_rationale: str

    # Traceability (Phase 20): which AI actually produced this conclusion.
    # Never filled in by the model itself -- app/ai/service.py overwrites
    # both fields with the real, code-derived backend/model right after
    # validation succeeds, specifically so a model can't cause these to lie
    # about their own identity. Optional/nullable so the no-evidence
    # short-circuit path (service.py's generate_final_assessment, which
    # never calls an AI backend at all) can leave both null rather than
    # falsely attributing a deterministic fallback to whichever backend
    # happens to be configured.
    ai_backend: Optional[str] = Field(default=None, description="Set by the platform after generation -- do not fill in.")
    ai_model: Optional[str] = Field(default=None, description="Set by the platform after generation -- do not fill in.")
    # Explicit outcome signal (see _AIOutcome above) -- set at all three of
    # generate_final_assessment's return sites, the same mechanical pattern as
    # ai_backend/ai_model just above. Optional/nullable for the same reason
    # those two fields are: a model that somehow echoed a value back here must
    # not be trusted, and the field has no meaningful value until the platform
    # sets it after generation actually finishes one way or another.
    ai_outcome: Optional[_AIOutcome] = Field(default=None, description="Set by the platform after generation -- do not fill in.")

    @model_validator(mode="after")
    def _verdict_must_agree_with_risk(self) -> "FinalAssessment":
        """Small local models have been observed emitting a verdict that
        flatly contradicts their own risk numbers in the same response --
        e.g. final_verdict="malicious" alongside malicious_probability=0 and
        severity="low" (the fields validate individually, the model just
        didn't reconcile them). Only rejects the egregious/clearly-wrong
        combinations, not borderline judgment calls, so this doesn't degrade
        every "suspicious"-ish assessment to the fallback path.
        """
        prob = self.risk.malicious_probability
        if self.final_verdict in _MALICIOUS_VERDICTS and prob < 30:
            raise ValueError(
                f"final_verdict={self.final_verdict.value!r} contradicts risk.malicious_probability="
                f"{prob} (expected a high probability for a malicious verdict)"
            )
        if self.final_verdict in _BENIGN_VERDICTS and prob > 50:
            raise ValueError(
                f"final_verdict={self.final_verdict.value!r} contradicts risk.malicious_probability="
                f"{prob} (expected a low probability for a benign verdict)"
            )
        return self

    @model_validator(mode="after")
    def _substantive_threat_assessment_must_cite_supporting_evidence(self) -> "FinalAssessment":
        """supporting_evidence's own field description already tells the
        model 'if threat_assessment cites specific findings, this list must
        NOT be left empty' -- but nothing previously enforced that. Confirmed
        live (Ollama): a real assessment's threat_assessment cited specific
        findings ('the high malicious probability and severity scores...
        support this conclusion') while supporting_evidence was an empty
        list, the exact violation the prompt calls out, surfaced to the UI
        uncorrected. supporting_evidence is free-text paraphrased excerpts,
        not structured evidence_ids, so there's no safe backfill (unlike
        app/ai/analysis_service.py's evidence_ids backfill for a different,
        ID-based field) -- fabricating a plausible-looking quote here would
        itself be the kind of fabrication this platform's evidence-
        traceability model exists to prevent. Instead this reuses the
        existing retry-on-ValidationError mechanism (service.py's
        generate_final_assessment already retries once on any validator
        failure, then falls back to a genuine ai_outcome="failed" rather
        than persisting an incomplete assessment) -- giving the model a
        second, real chance to either supply the citations it implied, or
        write a shorter threat_assessment that doesn't imply them.
        Deliberately length-gated rather than checking every non-empty
        threat_assessment: a short, formulaic disclaimer (e.g. "Insufficient
        data to assess.") makes no specific claim to back up in the first
        place.
        """
        if len(self.threat_assessment.strip()) > 80 and not self.supporting_evidence:
            raise ValueError(
                "threat_assessment makes a substantive claim but supporting_evidence is empty -- "
                "either cite concrete excerpts or shorten threat_assessment to not imply specific findings"
            )
        return self

    @model_validator(mode="after")
    def _threat_assessment_bare_verdict_must_agree_with_final_verdict(self) -> "FinalAssessment":
        """A third variant of the same small-local-model self-contradiction
        class _verdict_must_agree_with_risk already guards against, caught
        live against a real Ollama/llama3.2:3b investigation of 8.8.8.8:
        threat_assessment (free narrative text, per this schema) degenerated
        to a single bare word -- "malicious" -- while final_verdict/risk in
        the SAME response correctly said "benign"/malicious_probability=0.0.
        _verdict_must_agree_with_risk only checks final_verdict against the
        risk numbers; it never looks at threat_assessment's own content, so
        this exact contradiction validated cleanly and reached the UI, where
        FinalAssessmentPanel.tsx renders threat_assessment and final_verdict
        as two separately-labeled tabs ("Threat Assessment" / "Risk &
        Verdict") an analyst could read one of without the other.

        Deliberately narrow: only fires when threat_assessment, stripped and
        lowercased, is an EXACT match for one of Verdict's own string values
        (i.e. the model used it as a bare category label instead of writing
        a sentence) AND that value's malicious/benign category contradicts
        final_verdict's. A real narrative -- even one containing the word
        "malicious" mid-sentence -- never matches this, so ordinary
        assessments are unaffected.
        """
        bare = self.threat_assessment.strip().lower()
        try:
            bare_verdict = Verdict(bare)
        except ValueError:
            return self
        if bare_verdict in _MALICIOUS_VERDICTS and self.final_verdict in _BENIGN_VERDICTS:
            raise ValueError(
                f"threat_assessment={self.threat_assessment!r} is a bare verdict label that contradicts "
                f"final_verdict={self.final_verdict.value!r} -- write a real sentence, or make the two agree"
            )
        if bare_verdict in _BENIGN_VERDICTS and self.final_verdict in _MALICIOUS_VERDICTS:
            raise ValueError(
                f"threat_assessment={self.threat_assessment!r} is a bare verdict label that contradicts "
                f"final_verdict={self.final_verdict.value!r} -- write a real sentence, or make the two agree"
            )
        return self
