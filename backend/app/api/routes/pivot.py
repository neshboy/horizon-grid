"""Deterministic pivot ranking: given a completed lookup's correlation graph,
rank every directly-related IOC by confidence and corroboration so the
analyst can jump straight to the most valuable next investigation with one
click. Deliberately NOT AI-generated -- this is a pure sort over real edges,
so it can never hallucinate a pivot target. (The AI-generated "next actions"
in app/api/routes/analysis.py is the complementary explain-WHY-to-pivot
layer; this endpoint is the ranked list itself.)
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import CurrentUser, require_permission
from app.core.db import get_db
from app.evidence.pivot import EdgeLike, rank_pivots
from app.models.lookup import CorrelationEdgeRecord, IOCLookup

router = APIRouter(prefix="/lookup/{lookup_id}/pivots", tags=["pivot"])


@router.get("")
async def get_pivots(
    lookup_id: uuid.UUID,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("lookup:read")),
):
    lookup = (await db.execute(select(IOCLookup).where(IOCLookup.id == lookup_id))).scalar_one_or_none()
    if not lookup:
        raise HTTPException(status_code=404, detail="Lookup not found")

    edges = (
        await db.execute(select(CorrelationEdgeRecord).where(CorrelationEdgeRecord.lookup_id == lookup_id))
    ).scalars().all()

    edge_likes = [
        EdgeLike(
            source_value=e.source_value,
            source_type=e.source_type,
            target_value=e.target_value,
            target_type=e.target_type,
            relationship_type=e.relationship_type,
            confidence=e.confidence,
            provenance=e.provenance,
        )
        for e in edges
    ]
    return rank_pivots(lookup.ioc_value, edge_likes, limit)
