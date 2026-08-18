"""Pydantic schemas for the analyst-facing explanation features (WHY malicious,
Challenge, Provider Disagreement, Next Action, Score Explanation, Copilot,
Hunting query generation). Kept separate from app/ai/schemas.py (which
governs the per-provider/final-assessment pipeline) since these are all
"explain/query the evidence that already exists" calls, not part of the core
lookup pipeline -- same anti-hallucination rules apply, enforced the same way
(real Literal/enum types, grounding checks against real evidence_ids in
app/ai/analysis_service.py rather than trusting the model's citations).
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

_DetectionRuleFormat = Literal[
    "sigma", "yara", "splunk_spl", "sentinel_kql", "elastic", "qradar_aql",
    "chronicle_yara_l", "suricata", "snort", "zeek",
]

# Shared wording for every `evidence_ids` field below (mirrors ReasonWithEvidence's, the
# original/most explicit one) so a model can't treat this array as decorative just because a
# particular field's description was terser. Spelling out "MUST" + "every claim you make in the
# prose fields above must be reflected here" is deliberate: these fields validate fine as an empty
# list (default_factory=list, no min_length), so nothing but the prompt/description stops a model
# from writing a citation like "[id=...]" into a prose field while leaving this array empty --
# see app/ai/analysis_service.py's _strip_invalid_evidence_ids, which only trims bad IDs, it does
# not backfill missing ones from prose.
_EVIDENCE_IDS_DESC = (
    "IDs of the EvidenceItem records (from the supplied evidence ledger) that support the claims "
    "made in this response's prose fields. MUST reference only IDs actually present in the supplied "
    "evidence -- never invent an ID. If a prose field cites an evidence id (e.g. '[id=...]') or "
    "clearly describes a specific evidence record, that record's id MUST also appear in this list --  "
    "do not leave this empty while making specific claims in prose."
)


class ReasonWithEvidence(BaseModel):
    reason: str = Field(min_length=1, description="One short, concrete reason supporting the verdict")
    evidence_ids: list[str] = Field(default_factory=list, description=_EVIDENCE_IDS_DESC)


class WhyMaliciousExplanation(BaseModel):
    verdict_restated: str = Field(min_length=1, description="e.g. 'MALICIOUS -- 91/100'")
    reasons: list[ReasonWithEvidence] = Field(default_factory=list)
    caveat: Optional[str] = Field(default=None, description="Any honest caveat about evidence strength/gaps")


class WhatIsThisIOC(BaseModel):
    plain_language_summary: str = Field(min_length=1, description="One sentence a non-technical manager could understand")
    technical_explanation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list, description=_EVIDENCE_IDS_DESC)
    confidence_narrative: str = Field(min_length=1, description="How certain we are and why, in prose")
    related_infrastructure: list[str] = Field(default_factory=list, description="Related IOC values worth noting")


class DisagreementSummary(BaseModel):
    agreement: str = Field(min_length=1, description="What providers agree on")
    conflict: str = Field(min_length=1, description="Where providers disagree, named explicitly")
    missing_data: str = Field(min_length=1, description="What no provider addressed")
    most_reliable_evidence: str = Field(min_length=1, description="Which evidence to trust most and why")
    evidence_ids: list[str] = Field(default_factory=list, description=_EVIDENCE_IDS_DESC)


class FalsePositiveAssessment(BaseModel):
    likely_false_positive: bool
    candidate_categories: list[
        Literal[
            "cdn", "cloud_provider", "shared_hosting", "nat", "vpn", "proxy",
            "security_scanner", "search_crawler", "monitoring_system",
            "legitimate_business_infrastructure", "none",
        ]
    ] = Field(default_factory=list)
    explanation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list, description=_EVIDENCE_IDS_DESC)


class ChallengeVerdict(BaseModel):
    supporting_evidence: list[ReasonWithEvidence] = Field(default_factory=list)
    contradictory_evidence: list[ReasonWithEvidence] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list, description="What evidence, if it existed, would change the verdict")
    alternative_explanation: str = Field(min_length=1, description="The most plausible benign explanation, even if unlikely")
    final_confidence: Literal["low", "medium", "high"]
    final_confidence_rationale: str = Field(min_length=1)


class NextAction(BaseModel):
    action: str = Field(min_length=1, description="Concrete next investigation step")
    target_ioc_value: Optional[str] = Field(default=None, description="The specific related IOC to pivot to, if applicable")
    target_ioc_type: Optional[str] = None
    rationale: str = Field(min_length=1)
    priority: Literal["low", "medium", "high"]


class SmartNextActions(BaseModel):
    actions: list[NextAction] = Field(default_factory=list)


class IntelligenceGap(BaseModel):
    gap: str = Field(min_length=1, description="What is missing, e.g. 'No passive DNS history'")
    how_to_close: str = Field(min_length=1)


class IntelligenceGaps(BaseModel):
    gaps: list[IntelligenceGap] = Field(default_factory=list)


class ScoreComponent(BaseModel):
    component: str = Field(min_length=1, description="e.g. 'Malware association', 'Historical abuse'")
    contribution: str = Field(min_length=1, description="Plain-language description of how this component affected the score")
    evidence_ids: list[str] = Field(default_factory=list, description=_EVIDENCE_IDS_DESC)


class ScoreExplanation(BaseModel):
    components: list[ScoreComponent] = Field(default_factory=list)
    summary: str = Field(min_length=1, description="One paragraph tying the components together into the final score")


class HuntingQuery(BaseModel):
    format: _DetectionRuleFormat
    query: str = Field(min_length=1)
    detects: str = Field(min_length=1, description="Plain-language: what this query detects")


class HuntingExpansionTarget(BaseModel):
    related_ioc_value: str
    related_ioc_type: str
    rationale: str = Field(min_length=1)


class HuntingPackage(BaseModel):
    exact_match_queries: list[HuntingQuery] = Field(default_factory=list)
    expansion_targets: list[HuntingExpansionTarget] = Field(
        default_factory=list,
        description="Related indicators (domains, certs, JA3/JA4, hashes, user agents) worth hunting for too, "
        "drawn ONLY from the supplied correlation edges -- never invented.",
    )
    broader_queries: list[HuntingQuery] = Field(
        default_factory=list, description="Queries hunting for the expansion targets, not just the exact IOC"
    )


class DetectionRuleDraft(BaseModel):
    format: _DetectionRuleFormat
    title: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    detection_objective: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    logic_explanation: str = Field(min_length=1)
    false_positive_considerations: str = Field(min_length=1)
    severity: Literal["none", "low", "medium", "high", "critical"]
    mitre_technique_ids: list[str] = Field(default_factory=list)


class CopilotAnswer(BaseModel):
    answer: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list, description=_EVIDENCE_IDS_DESC)
    suggested_follow_ups: list[str] = Field(default_factory=list, max_length=4)


class IOCComparisonNarrative(BaseModel):
    most_dangerous_ioc_value: Optional[str] = Field(
        default=None, description="The ioc_value judged most dangerous among those compared, or null if genuinely tied/unclear"
    )
    narrative: str = Field(min_length=1, description="e.g. 'IOC A appears more dangerous than IOC B because...'")
    key_differences: list[str] = Field(default_factory=list)

