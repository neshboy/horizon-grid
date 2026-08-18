"""Analyst-facing explanation endpoints over an already-completed lookup:
evidence ledger retrieval ("Show Receipts"), WHY malicious, WHAT IS THIS,
provider disagreement, false-positive check, self-challenge, next actions,
intelligence gaps, and score explanation. Every AI-generated explanation here
is grounded against the real EvidenceItem ledger for that lookup -- see
app/ai/analysis_service.py's _strip_invalid_evidence_ids.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.analysis_schemas import (
    ChallengeVerdict,
    DisagreementSummary,
    FalsePositiveAssessment,
    IntelligenceGaps,
    ScoreExplanation,
    SmartNextActions,
    WhatIsThisIOC,
    WhyMaliciousExplanation,
)
from app.ai.analysis_service import (
    answer_copilot_question,
    assess_false_positive,
    challenge_verdict,
    explain_disagreement,
    explain_score,
    explain_what_is_this,
    explain_why_malicious,
    identify_intelligence_gaps,
    suggest_next_actions,
)
from app.ai.analysis_schemas import CopilotAnswer
from app.auth.rbac import CurrentUser, require_permission
from app.core.db import get_db
from app.evidence.loaders import correlation_from_records
from app.models.evidence import EvidenceItem
from app.models.lookup import CorrelationEdgeRecord, IOCLookup

router = APIRouter(prefix="/lookup/{lookup_id}/analysis", tags=["analysis"])


async def _load_lookup(lookup_id: uuid.UUID, db: AsyncSession) -> IOCLookup:
    lookup = (await db.execute(select(IOCLookup).where(IOCLookup.id == lookup_id))).scalar_one_or_none()
    if not lookup:
        raise HTTPException(status_code=404, detail="Lookup not found")
    if lookup.status.value != "completed":
        raise HTTPException(status_code=409, detail=f"Lookup is not completed yet (status={lookup.status.value})")
    return lookup


async def _load_evidence(lookup_id: uuid.UUID, db: AsyncSession) -> list[EvidenceItem]:
    result = await db.execute(select(EvidenceItem).where(EvidenceItem.lookup_id == lookup_id))
    return list(result.scalars().all())


async def _load_correlation_edges(lookup_id: uuid.UUID, db: AsyncSession) -> list[CorrelationEdgeRecord]:
    result = await db.execute(select(CorrelationEdgeRecord).where(CorrelationEdgeRecord.lookup_id == lookup_id))
    return list(result.scalars().all())


def _verdict_label(lookup: IOCLookup) -> str:
    verdict = lookup.final_verdict.value if lookup.final_verdict else "unknown"
    score = lookup.risk_score if lookup.risk_score is not None else 0
    return f"{verdict.upper()} -- {score:.0f}/100"


@router.get("/evidence")
async def get_evidence(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("evidence:read")),
):
    """The raw evidence ledger -- powers 'Show Receipts' and the Evidence tab
    of the investigation workspace. No AI involved in this endpoint."""
    await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    return [
        {
            "id": str(item.id),
            "evidence_type": item.evidence_type.value,
            "source_label": item.source_label,
            "provider_id": item.provider_id,
            "claim": item.claim,
            "interpretation": item.interpretation,
            "confidence": item.confidence,
            "related_ioc_type": item.related_ioc_type,
            "related_ioc_value": item.related_ioc_value,
            "source_url": item.source_url,
            "observed_at": item.observed_at,
            "created_at": item.created_at.isoformat(),
        }
        for item in evidence
    ]


@router.post("/why", response_model=WhyMaliciousExplanation)
async def why_malicious(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("analysis:generate")),
):
    lookup = await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    return await explain_why_malicious(lookup.ioc_value, _verdict_label(lookup), evidence)


@router.post("/what-is-this", response_model=WhatIsThisIOC)
async def what_is_this(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("analysis:generate")),
):
    lookup = await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    return await explain_what_is_this(lookup.ioc_value, lookup.ioc_type, _verdict_label(lookup), evidence)


@router.post("/disagreement", response_model=DisagreementSummary)
async def disagreement(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("analysis:generate")),
):
    lookup = await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    return await explain_disagreement(lookup.ioc_value, evidence)


@router.post("/false-positive", response_model=FalsePositiveAssessment)
async def false_positive(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("analysis:generate")),
):
    lookup = await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    return await assess_false_positive(lookup.ioc_value, lookup.ioc_type, evidence)


@router.post("/challenge", response_model=ChallengeVerdict)
async def challenge(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("analysis:generate")),
):
    lookup = await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    return await challenge_verdict(lookup.ioc_value, _verdict_label(lookup), evidence)


@router.post("/next-actions", response_model=SmartNextActions)
async def next_actions(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("analysis:generate")),
):
    lookup = await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    edge_records = await _load_correlation_edges(lookup_id, db)
    correlation = correlation_from_records(lookup, edge_records)
    return await suggest_next_actions(lookup.ioc_value, evidence, correlation)


@router.post("/gaps", response_model=IntelligenceGaps)
async def intelligence_gaps(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("analysis:generate")),
):
    from app.models.lookup import ProviderResultRecord

    lookup = await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    provider_rows = (
        await db.execute(select(ProviderResultRecord).where(ProviderResultRecord.lookup_id == lookup_id))
    ).scalars().all()
    with_data = [p.provider_name for p in provider_rows if p.status == "ok"]
    without_data = [p.provider_name for p in provider_rows if p.status != "ok"]
    return await identify_intelligence_gaps(lookup.ioc_value, evidence, with_data, without_data)


@router.post("/score-explanation", response_model=ScoreExplanation)
async def score_explanation(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("analysis:generate")),
):
    lookup = await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    return await explain_score(lookup.ioc_value, _verdict_label(lookup), evidence)


@router.post("/copilot", response_model=CopilotAnswer)
async def copilot(
    lookup_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("copilot:query")),
):
    """payload: {"question": str, "notes": list[str] (optional, analyst notes for context)}"""
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is required")
    lookup = await _load_lookup(lookup_id, db)
    evidence = await _load_evidence(lookup_id, db)
    edge_records = await _load_correlation_edges(lookup_id, db)
    correlation = correlation_from_records(lookup, edge_records)
    notes = payload.get("notes") or []
    return await answer_copilot_question(lookup.ioc_value, question, evidence, correlation, notes)
