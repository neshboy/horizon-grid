"""Threat hunting query and detection rule generation for a completed lookup.
Supports both an exact-match hunting package (query the seed IOC across
requested formats) and hunting expansion (queries for related indicators
actually present in the correlation graph -- see app/ai/hunting_service.py).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.analysis_schemas import DetectionRuleDraft, HuntingPackage
from app.ai.hunting_service import generate_detection_rule, generate_hunting_package
from app.auth.rbac import CurrentUser, require_permission
from app.core.db import get_db
from app.evidence.loaders import correlation_from_records
from app.models.lookup import CorrelationEdgeRecord, IOCLookup

router = APIRouter(prefix="/lookup/{lookup_id}", tags=["hunting"])

_DEFAULT_HUNTING_FORMATS = [
    "sigma", "splunk_spl", "sentinel_kql", "elastic", "qradar_aql", "chronicle_yara_l", "suricata", "snort", "zeek",
]


async def _load_lookup(lookup_id: uuid.UUID, db: AsyncSession) -> IOCLookup:
    lookup = (await db.execute(select(IOCLookup).where(IOCLookup.id == lookup_id))).scalar_one_or_none()
    if not lookup:
        raise HTTPException(status_code=404, detail="Lookup not found")
    return lookup


@router.post("/hunt", response_model=HuntingPackage)
async def hunt_this_ioc(
    lookup_id: uuid.UUID,
    formats: list[str] = Query(default=_DEFAULT_HUNTING_FORMATS),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("hunting:generate")),
):
    lookup = await _load_lookup(lookup_id, db)
    edge_records = (
        await db.execute(select(CorrelationEdgeRecord).where(CorrelationEdgeRecord.lookup_id == lookup_id))
    ).scalars().all()
    correlation = correlation_from_records(lookup, list(edge_records))
    return await generate_hunting_package(lookup.ioc_value, lookup.ioc_type, formats, correlation)


@router.post("/detection", response_model=DetectionRuleDraft)
async def create_detection(
    lookup_id: uuid.UUID,
    format: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("hunting:generate")),
):
    lookup = await _load_lookup(lookup_id, db)
    verdict = lookup.final_verdict.value if lookup.final_verdict else "unknown"
    return await generate_detection_rule(
        lookup.ioc_value, lookup.ioc_type, format, verdict, lookup.risk_score or 0
    )
