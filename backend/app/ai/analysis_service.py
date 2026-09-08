"""AI-generated explanations over an already-completed lookup's real evidence
ledger (app/models/evidence.py rows, built deterministically by
app/evidence/builder.py). Every function here follows the same shape as
app/ai/service.py: build a grounding-only prompt from real data, call the
configured AI backend for structured output, validate, strip any
evidence_id the model cites that doesn't actually exist, and degrade to a
safe placeholder on any failure rather than raising to the route handler.

The grounding step (_strip_invalid_evidence_ids) is what makes "Show
Receipts" trustworthy: if the model claims evidence_id 'abc123' supports a
reason but 'abc123' isn't in the evidence actually supplied, that citation is
removed rather than rendered as if it were real.
"""
import logging
from typing import Optional, TypeVar

from pydantic import BaseModel

from app.ai.analysis_schemas import (
    ChallengeVerdict,
    CopilotAnswer,
    DetectionRuleDraft,
    DisagreementSummary,
    FalsePositiveAssessment,
    HuntingPackage,
    IntelligenceGaps,
    IOCComparisonNarrative,
    ScoreExplanation,
    SmartNextActions,
    WhatIsThisIOC,
    WhyMaliciousExplanation,
)
from app.ai.service import _get_ai_client
from app.correlation.engine import CorrelationResult
from app.models.evidence import EvidenceItem

logger = logging.getLogger(__name__)

_ModelT = TypeVar("_ModelT", bound=BaseModel)

_EVIDENCE_ID_FIELDS = ("evidence_ids",)


def _evidence_block(evidence: list[EvidenceItem]) -> str:
    lines = []
    for item in evidence:
        related = f" | related: {item.related_ioc_type}:{item.related_ioc_value}" if item.related_ioc_value else ""
        lines.append(
            f"[id={item.id}] ({item.evidence_type.value}, confidence={item.confidence:.0f}) "
            f"{item.source_label}: {item.claim}{related}"
        )
    return "\n".join(lines) if lines else "(no evidence recorded for this lookup)"


def _strip_invalid_evidence_ids(obj: BaseModel, real_ids: set[str]) -> BaseModel:
    """Recursively walks the validated response and removes any evidence_id
    not present in `real_ids` -- the core anti-hallucination guardrail shared
    by every function below. Mutates lists in place field-by-field rather
    than reconstructing the model, since Pydantic models here are not frozen.
    """
    for field_name in type(obj).model_fields:
        value = getattr(obj, field_name)
        if field_name in _EVIDENCE_ID_FIELDS and isinstance(value, list):
            setattr(obj, field_name, [v for v in value if v in real_ids])
        elif isinstance(value, BaseModel):
            _strip_invalid_evidence_ids(value, real_ids)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, BaseModel):
                    _strip_invalid_evidence_ids(item, real_ids)
    return obj


def _backfill_evidence_ids_from_prose(obj: BaseModel, real_ids: set[str]) -> BaseModel:
    """Safety net for models (observed with Ollama's llama3.2:3b, a small local
    model) that narrate a citation in a prose field -- e.g. most_reliable_evidence
    containing literal "[id=<uuid>] ..." copied from the evidence ledger block below
    -- without also listing that id in the structured evidence_ids array next to it,
    even though schema field descriptions now explicitly ask for exactly that (see
    _EVIDENCE_IDS_DESC in app/ai/analysis_schemas.py). A model that "knows" the id
    (it wrote it into prose) but didn't structure it makes the citation exist in text
    but not in the field the frontend actually renders as a clickable receipt link.

    Recurses the same way _strip_invalid_evidence_ids does. For every model in the
    tree that has both an `evidence_ids` field and other string fields, scans those
    string fields for any real evidence id appearing as a substring and appends it if
    missing. Only ever adds ids drawn from `real_ids` -- ids already confirmed present
    in the evidence actually supplied for this call -- so this cannot reintroduce a
    hallucinated id; it only recovers a citation the model already made correctly in
    prose but forgot to structure.
    """
    for field_name in type(obj).model_fields:
        value = getattr(obj, field_name)
        if isinstance(value, BaseModel):
            _backfill_evidence_ids_from_prose(value, real_ids)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, BaseModel):
                    _backfill_evidence_ids_from_prose(item, real_ids)

    if real_ids and "evidence_ids" in type(obj).model_fields:
        evidence_ids: list[str] = getattr(obj, "evidence_ids")
        existing = set(evidence_ids)
        prose = " ".join(
            getattr(obj, name)
            for name in type(obj).model_fields
            if name != "evidence_ids" and isinstance(getattr(obj, name), str)
        )
        for real_id in real_ids:
            if real_id not in existing and real_id in prose:
                evidence_ids.append(real_id)
    return obj


async def _call_and_ground(
    system_prompt: str,
    user_prompt: str,
    schema: type[_ModelT],
    tool_name: str,
    evidence: list[EvidenceItem],
    fallback: _ModelT,
    max_tokens: Optional[int] = None,
) -> _ModelT:
    real_ids = {str(item.id) for item in evidence}
    try:
        client, _backend, _model = await _get_ai_client()
        payload = await client.call_claude_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_schema=schema.model_json_schema(),
            tool_name=tool_name,
            max_tokens=max_tokens,
        )
        result = schema.model_validate(payload)
        result = _backfill_evidence_ids_from_prose(result, real_ids)
        return _strip_invalid_evidence_ids(result, real_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s generation failed: %r", tool_name, exc)
        return fallback


_WHY_MALICIOUS_SYSTEM_PROMPT = """You are a SOC threat analyst explaining WHY an IOC received its verdict, to a fellow analyst.
You are given the final verdict/risk score and a numbered ledger of real evidence records (each with an id).

Rules:
- Every reason you give MUST cite the evidence_ids of the specific evidence records (from the ledger) that support it.
- NEVER invent a reason that isn't backed by at least one evidence record in the ledger.
- NEVER invent an evidence_id that isn't in the ledger.
- If the evidence is thin, say so in the caveat field rather than padding with speculation.
- Keep each reason to one concrete sentence.
"""

_WHAT_IS_THIS_SYSTEM_PROMPT = """You are a SOC threat analyst explaining what an IOC IS, in plain language first, then technically.
You are given the final assessment and a numbered ledger of real evidence records (each with an id).

Rules:
- The plain_language_summary must be understandable by a non-technical manager in one sentence.
- Every claim in technical_explanation must be traceable to the evidence ledger; cite evidence_ids.
- related_infrastructure must list only IOC values that actually appear in the supplied evidence/correlation data.
- Never invent detection counts, actor names, or malware families not present in the evidence.
"""

_DISAGREEMENT_SYSTEM_PROMPT = """You are a SOC threat analyst summarizing where intelligence providers agree and disagree on an IOC.
You are given the per-provider evidence ledger (each record's source_label is the provider, or "Correlation Engine").

Rules:
- agreement: what multiple sources concur on, if anything.
- conflict: name the specific providers that disagree and what each one claims.
- missing_data: call out categories of data no provider addressed (e.g. no sandbox evidence, no historical WHOIS).
- most_reliable_evidence: pick the evidence you'd trust most and explain why (more corroboration, more direct observation vs analyst tag, more recent).
- Cite evidence_ids for every claim. Never invent a provider's position that isn't in the ledger.
"""

_FALSE_POSITIVE_SYSTEM_PROMPT = """You are a SOC threat analyst evaluating whether an IOC's malicious-looking signal could be a false positive
caused by shared/legitimate infrastructure (CDN, cloud provider, shared hosting, NAT, VPN, proxy, security scanner,
search crawler, monitoring system, or otherwise legitimate business infrastructure).

Rules:
- Base your judgment ONLY on the supplied evidence ledger (ASN/org names, hosting indicators, known-scanner tags, etc.).
- If nothing in the evidence suggests shared/benign infrastructure, set likely_false_positive=false and candidate_categories=["none"].
- Cite evidence_ids for every claim. Never invent an ASN/org/provider name not present in the evidence.
"""

_CHALLENGE_SYSTEM_PROMPT = """You are a SOC threat analyst red-teaming your platform's OWN verdict on an IOC, to catch confirmation bias.
You are given the final verdict and the full evidence ledger.

Rules:
- supporting_evidence: the strongest evidence records FOR the current verdict, with evidence_ids.
- contradictory_evidence: any evidence records that cut AGAINST the verdict, with evidence_ids -- if genuinely none exist, return an empty list, do not invent weak ones.
- missing_evidence: what evidence, if it existed, would most change your confidence (do not cite evidence_ids here, these don't exist yet).
- alternative_explanation: the most plausible benign explanation for the observed evidence, even if you still think the verdict is correct.
- final_confidence: your honest confidence in the ORIGINAL verdict after this self-challenge, which may be lower than the original risk score implied.
"""

_NEXT_ACTION_SYSTEM_PROMPT = """You are a SOC threat analyst recommending the single most valuable next investigation step for an IOC,
given its evidence ledger and correlation graph.

Rules:
- Recommend 1-4 concrete actions, each pointing at a SPECIFIC related IOC value that actually appears in the
  supplied correlation edges/evidence -- never a generic "investigate further" with no target.
- priority reflects how much new intelligence this pivot is likely to surface, not how "scary" the target looks.
- rationale must reference why this specific target is promising (e.g. "linked via 3 corroborating providers").
"""

_INTELLIGENCE_GAPS_SYSTEM_PROMPT = """You are a SOC threat analyst identifying what intelligence is MISSING for an IOC investigation.
You are given the evidence ledger and the list of provider categories that returned data vs. did not.

Rules:
- Only list a gap if the supplied data actually shows that category is absent (e.g. no passive DNS provider returned data,
  no sandbox/malware-analysis provider returned data, no historical WHOIS present).
- how_to_close should name the type of data source or action that would fill the gap, not a specific vendor unless one is evident from context.
"""

_SCORE_EXPLANATION_SYSTEM_PROMPT = """You are a SOC threat analyst explaining, component by component, how an IOC's final risk score was reached.
You are given the final risk assessment and the full evidence ledger.

Rules:
- Break the score into components (e.g. malware association, threat actor association, historical abuse, infrastructure
  reputation, provider corroboration, recency) -- only include a component if the evidence ledger actually supports it.
- Cite evidence_ids for every component.
- summary ties the components together into why the final number is what it is, in one paragraph.
"""

_COMPARISON_SYSTEM_PROMPT = """You are a SOC threat analyst comparing multiple IOCs side by side.
You are given a table of deterministic facts about each IOC (verdict, risk score, providers, countries, ASN, etc.).

Rules:
- Base the narrative ONLY on the supplied comparison table -- never invent a fact about any IOC not in the table.
- most_dangerous_ioc_value must be one of the exact ioc_value strings supplied, or null if genuinely too close to call.
- key_differences: short bullet-style strings, the most decision-relevant differences only.
"""


_COPILOT_SYSTEM_PROMPT = """You are the Investigation Copilot: an AI analyst assistant with full context on the CURRENT investigation
(the IOC, its evidence ledger, correlation graph, and any analyst notes supplied below). Answer the analyst's question
directly and concisely.

Rules:
- Answer ONLY from the supplied context. If the context doesn't contain the answer, say so plainly instead of guessing.
- Cite evidence_ids for any factual claim about the IOC.
- suggested_follow_ups are short, clickable next questions relevant to what you just answered (max 4).
"""


def _fallback_reason(exc_note: str = "") -> str:
    return f"AI explanation unavailable (generation error).{(' ' + exc_note) if exc_note else ''}"


async def explain_why_malicious(
    ioc_value: str, verdict_label: str, evidence: list[EvidenceItem]
) -> WhyMaliciousExplanation:
    user_prompt = (
        f"IOC: {ioc_value}\nVerdict: {verdict_label}\n\nEvidence ledger:\n{_evidence_block(evidence)}\n\n"
        "Explain step-by-step why this verdict was reached, citing evidence_ids for every reason."
    )
    fallback = WhyMaliciousExplanation(verdict_restated=verdict_label, reasons=[], caveat=_fallback_reason())
    return await _call_and_ground(
        _WHY_MALICIOUS_SYSTEM_PROMPT, user_prompt, WhyMaliciousExplanation, "emit_why_malicious", evidence, fallback
    )


async def explain_what_is_this(
    ioc_value: str, ioc_type: str, verdict_label: str, evidence: list[EvidenceItem]
) -> WhatIsThisIOC:
    user_prompt = (
        f"IOC: {ioc_value} (type: {ioc_type})\nVerdict: {verdict_label}\n\n"
        f"Evidence ledger:\n{_evidence_block(evidence)}\n\nExplain what this IOC is, plainly then technically."
    )
    fallback = WhatIsThisIOC(
        plain_language_summary="Explanation unavailable (generation error).",
        technical_explanation=_fallback_reason(),
        confidence_narrative="Unknown -- generation error.",
    )
    return await _call_and_ground(
        _WHAT_IS_THIS_SYSTEM_PROMPT, user_prompt, WhatIsThisIOC, "emit_what_is_this", evidence, fallback
    )


async def explain_disagreement(ioc_value: str, evidence: list[EvidenceItem]) -> DisagreementSummary:
    user_prompt = f"IOC: {ioc_value}\n\nEvidence ledger:\n{_evidence_block(evidence)}\n\nSummarize agreement/conflict/gaps."
    fallback = DisagreementSummary(
        agreement="Unavailable (generation error).",
        conflict="Unavailable (generation error).",
        missing_data="Unavailable (generation error).",
        most_reliable_evidence="Unavailable (generation error).",
    )
    return await _call_and_ground(
        _DISAGREEMENT_SYSTEM_PROMPT, user_prompt, DisagreementSummary, "emit_disagreement", evidence, fallback
    )


async def assess_false_positive(ioc_value: str, ioc_type: str, evidence: list[EvidenceItem]) -> FalsePositiveAssessment:
    user_prompt = (
        f"IOC: {ioc_value} (type: {ioc_type})\n\nEvidence ledger:\n{_evidence_block(evidence)}\n\n"
        "Assess whether this could be a false positive due to shared/legitimate infrastructure."
    )
    fallback = FalsePositiveAssessment(
        likely_false_positive=False, candidate_categories=["none"], explanation=_fallback_reason()
    )
    return await _call_and_ground(
        _FALSE_POSITIVE_SYSTEM_PROMPT, user_prompt, FalsePositiveAssessment, "emit_false_positive", evidence, fallback
    )


async def challenge_verdict(ioc_value: str, verdict_label: str, evidence: list[EvidenceItem]) -> ChallengeVerdict:
    user_prompt = (
        f"IOC: {ioc_value}\nCurrent verdict: {verdict_label}\n\nEvidence ledger:\n{_evidence_block(evidence)}\n\n"
        "Red-team this verdict: find supporting evidence, contradictory evidence, missing evidence, and an alternative explanation."
    )
    fallback = ChallengeVerdict(
        alternative_explanation=_fallback_reason(),
        final_confidence="low",
        final_confidence_rationale="Generation error -- confidence cannot be assessed.",
    )
    return await _call_and_ground(
        _CHALLENGE_SYSTEM_PROMPT, user_prompt, ChallengeVerdict, "emit_challenge", evidence, fallback
    )


async def suggest_next_actions(
    ioc_value: str, evidence: list[EvidenceItem], correlation: CorrelationResult
) -> SmartNextActions:
    edges_block = "\n".join(
        f"{e.source} --{e.relationship}--> {e.target} [confidence={e.confidence:.2f}, via {e.provenance}]"
        for e in correlation.edges[:100]
    )
    user_prompt = (
        f"IOC: {ioc_value}\n\nEvidence ledger:\n{_evidence_block(evidence)}\n\n"
        f"Correlation edges:\n{edges_block or '(none discovered)'}\n\n"
        "Recommend the 1-4 most valuable next investigation pivots, each targeting a specific related IOC."
    )
    fallback = SmartNextActions(actions=[])
    return await _call_and_ground(
        _NEXT_ACTION_SYSTEM_PROMPT, user_prompt, SmartNextActions, "emit_next_actions", evidence, fallback
    )


async def identify_intelligence_gaps(
    ioc_value: str, evidence: list[EvidenceItem], providers_with_data: list[str], providers_without_data: list[str]
) -> IntelligenceGaps:
    user_prompt = (
        f"IOC: {ioc_value}\n\nProviders WITH data: {providers_with_data}\nProviders WITHOUT data: {providers_without_data}\n\n"
        f"Evidence ledger:\n{_evidence_block(evidence)}\n\nIdentify missing intelligence categories and how to close each gap."
    )
    fallback = IntelligenceGaps(gaps=[])
    return await _call_and_ground(
        _INTELLIGENCE_GAPS_SYSTEM_PROMPT, user_prompt, IntelligenceGaps, "emit_gaps", evidence, fallback
    )


async def explain_score(ioc_value: str, risk_summary: str, evidence: list[EvidenceItem]) -> ScoreExplanation:
    user_prompt = (
        f"IOC: {ioc_value}\nFinal risk assessment: {risk_summary}\n\n"
        f"Evidence ledger:\n{_evidence_block(evidence)}\n\nBreak the score down into explainable components."
    )
    fallback = ScoreExplanation(components=[], summary=_fallback_reason())
    return await _call_and_ground(
        _SCORE_EXPLANATION_SYSTEM_PROMPT, user_prompt, ScoreExplanation, "emit_score_explanation", evidence, fallback,
        max_tokens=4096,
    )


_MAX_ANALYST_NOTES_KEPT = 40
_MAX_ANALYST_NOTE_LEN = 800


def _prune_analyst_notes_for_prompt(analyst_notes: list[str]) -> str:
    """Caps the analyst-notes/conversation-history blob before it reaches the
    Copilot prompt -- every OTHER input fed into an AI prompt in this module
    and in app/ai/service.py is capped this way (see that module's
    _prune_for_prompt/_prune_ioc_value_for_prompt docstrings, and the
    edges[:100] slicing just above in this function) but analyst_notes was
    the one call path that received no equivalent guard.

    The frontend (InvestigationCopilot.tsx) resends the ENTIRE, ever-growing
    Q&A transcript verbatim as `notes` on every single Copilot call for the
    life of an investigation session, with no cap or eviction on its side --
    so left unbounded, this prompt grows roughly linearly with turn count.
    On a cloud backend with a small token budget (Groq, 12000 TPM per this
    codebase's own documented limit) a long enough session eventually hits
    HTTP 413, the exact failure mode already fixed for NVD's oversized
    fields. On Ollama, _estimate_num_ctx still clamps num_ctx to at most
    8192 tokens regardless of true prompt size, so an oversized notes blob
    just silently pushes real evidence/question content out of context
    instead of crashing -- degraded/wrong answers rather than a crash, but
    the same underlying defect.

    Keeps only the most recent _MAX_ANALYST_NOTES_KEPT notes (older turns
    are the least relevant to the CURRENT question, and are the ones the
    frontend keeps re-sending unchanged turn after turn) and truncates any
    single oversized note, marking both forms of truncation explicitly so
    the model doesn't mistake a cut for the actual end of the record.
    """
    if not analyst_notes:
        return "(no analyst notes yet)"

    total = len(analyst_notes)
    kept = analyst_notes[-_MAX_ANALYST_NOTES_KEPT:]
    lines = []
    if total > len(kept):
        lines.append(f"... [{total - len(kept)} earlier notes truncated] ...")
    for note in kept:
        text = str(note)
        if len(text) > _MAX_ANALYST_NOTE_LEN:
            text = text[:_MAX_ANALYST_NOTE_LEN] + f"... [truncated, {len(text)} chars total]"
        lines.append(f"- {text}")
    return "\n".join(lines)


async def answer_copilot_question(
    ioc_value: str,
    question: str,
    evidence: list[EvidenceItem],
    correlation: CorrelationResult,
    analyst_notes: list[str],
) -> CopilotAnswer:
    edges_block = "\n".join(
        f"{e.source} --{e.relationship}--> {e.target}" for e in correlation.edges[:100]
    )
    notes_block = _prune_analyst_notes_for_prompt(analyst_notes)
    user_prompt = (
        f"Current investigation IOC: {ioc_value}\n\n"
        f"Evidence ledger:\n{_evidence_block(evidence)}\n\n"
        f"Correlation edges:\n{edges_block or '(none discovered)'}\n\n"
        f"Analyst notes so far:\n{notes_block}\n\n"
        f"Analyst question: {question}"
    )
    fallback = CopilotAnswer(answer=_fallback_reason(), suggested_follow_ups=[])
    return await _call_and_ground(
        _COPILOT_SYSTEM_PROMPT, user_prompt, CopilotAnswer, "emit_copilot_answer", evidence, fallback
    )


async def compare_iocs(comparison_rows: list[dict]) -> IOCComparisonNarrative:
    """comparison_rows: one dict per IOC with plain deterministic fields
    (ioc_value, ioc_type, verdict, risk_score, providers, countries, asn, etc.)
    -- built by the caller from persisted lookup data, not evidence rows, so
    this doesn't use _call_and_ground's evidence_id stripping. Grounding here
    is enforced by restricting most_dangerous_ioc_value to the supplied values.
    """
    table = "\n".join(
        f"- {row.get('ioc_value')}: " + ", ".join(f"{k}={v}" for k, v in row.items() if k != "ioc_value")
        for row in comparison_rows
    )
    user_prompt = f"Comparison table:\n{table}\n\nExplain how these IOCs compare and which is most dangerous, if any."
    valid_values = {str(row.get("ioc_value")) for row in comparison_rows}

    try:
        client, _backend, _model = await _get_ai_client()
        payload = await client.call_claude_json(
            system_prompt=_COMPARISON_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            json_schema=IOCComparisonNarrative.model_json_schema(),
            tool_name="emit_comparison",
        )
        result = IOCComparisonNarrative.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("IOC comparison generation failed: %r", exc)
        return IOCComparisonNarrative(narrative=_fallback_reason(), key_differences=[])

    if result.most_dangerous_ioc_value and result.most_dangerous_ioc_value not in valid_values:
        result.most_dangerous_ioc_value = None
    return result
