"""IOC Basket: per-analyst scratch space for collecting IOCs across an
investigation, then acting on the set (investigate all, compare, promote to
a case). See app/models/basket.py for the model rationale.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.analysis_service import compare_iocs
from app.auth.rbac import CurrentUser, require_permission
from app.core.db import get_db
from app.ioc.detector import detect_ioc_type
from app.ioc.types import IOCType
from app.models.basket import BasketItem
from app.models.lookup import IOCLookup
from app.schemas.basket import BasketAddRequest

router = APIRouter(prefix="/basket", tags=["basket"])


def _serialize(item: BasketItem) -> dict:
    return {
        "id": str(item.id),
        "ioc_value": item.ioc_value,
        "ioc_type": item.ioc_type,
        "note": item.note,
        "latest_lookup_id": str(item.latest_lookup_id) if item.latest_lookup_id else None,
        "created_at": item.created_at.isoformat(),
    }


@router.get("")
async def list_basket(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("basket:manage")),
):
    items = (
        await db.execute(select(BasketItem).where(BasketItem.owner_id == user.id).order_by(BasketItem.created_at.desc()))
    ).scalars().all()
    return [_serialize(i) for i in items]


@router.post("", status_code=201)
async def add_to_basket(
    payload: BasketAddRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("basket:manage")),
):
    ioc_value = payload.ioc_value.strip()
    ioc_type = payload.ioc_type_hint or detect_ioc_type(ioc_value)
    if ioc_type == IOCType.UNKNOWN:
        raise HTTPException(status_code=422, detail="Could not determine IOC type; pass ioc_type_hint.")

    existing = (
        await db.execute(
            select(BasketItem).where(BasketItem.owner_id == user.id, BasketItem.ioc_value == ioc_value)
        )
    ).scalar_one_or_none()
    if existing:
        return _serialize(existing)

    # Best-effort: attach the most recent completed lookup for this exact IOC
    # value, if one exists, so basket actions have something to work from
    # immediately without forcing a re-investigation.
    latest_lookup = (
        await db.execute(
            select(IOCLookup)
            .where(IOCLookup.ioc_value == ioc_value, IOCLookup.status == "completed")
            .order_by(IOCLookup.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    item = BasketItem(
        owner_id=user.id,
        ioc_value=ioc_value,
        ioc_type=ioc_type.value,
        note=payload.note,
        latest_lookup_id=latest_lookup.id if latest_lookup else None,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _serialize(item)


@router.delete("/{item_id}", status_code=204)
async def remove_from_basket(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("basket:manage")),
):
    item = (
        await db.execute(select(BasketItem).where(BasketItem.id == item_id, BasketItem.owner_id == user.id))
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Basket item not found")
    await db.delete(item)
    await db.commit()


@router.delete("", status_code=204)
async def clear_basket(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("basket:manage")),
):
    items = (await db.execute(select(BasketItem).where(BasketItem.owner_id == user.id))).scalars().all()
    for item in items:
        await db.delete(item)
    await db.commit()


@router.post("/compare")
async def compare_basket_iocs(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("basket:manage")),
):
    """payload: {"lookup_ids": list[str]} -- IOCs must already have a
    completed lookup (from the basket's latest_lookup_id or any other).
    Builds a deterministic comparison table, then asks the AI for a narrative."""
    from app.models.lookup import CorrelationEdgeRecord

    lookup_ids = payload.get("lookup_ids") or []
    if len(lookup_ids) < 2:
        raise HTTPException(status_code=422, detail="Provide at least 2 lookup_ids to compare")
    if len(lookup_ids) > 10:
        raise HTTPException(status_code=422, detail="Cannot compare more than 10 IOCs at once")

    rows = []
    for raw_id in lookup_ids:
        try:
            parsed_id = uuid.UUID(raw_id)
        except (ValueError, AttributeError, TypeError):
            # Real bug found live during overnight QA: this raw uuid.UUID()
            # call had no try/except, so any non-UUID string in
            # lookup_ids crashed the whole request with an unhandled 500
            # (this endpoint takes a raw `payload: dict`, bypassing
            # FastAPI/Pydantic's normal automatic UUID coercion+422 that
            # every path-param UUID already gets). Skipping an unparseable
            # id rather than 500ing matches this loop's own existing
            # "if not lookup: continue" behavior for a well-formed but
            # nonexistent id.
            continue
        lookup = (await db.execute(select(IOCLookup).where(IOCLookup.id == parsed_id))).scalar_one_or_none()
        if not lookup:
            continue
        edges = (
            await db.execute(select(CorrelationEdgeRecord).where(CorrelationEdgeRecord.lookup_id == lookup.id))
        ).scalars().all()
        asns = sorted({e.target_value for e in edges if e.target_type == "asn"})
        malware = sorted({e.target_value for e in edges if e.target_type == "malware_family"})
        actors = sorted({e.target_value for e in edges if e.target_type == "threat_actor"})
        domains = sorted({e.target_value for e in edges if e.target_type == "domain"})

        rows.append(
            {
                "ioc_value": lookup.ioc_value,
                "ioc_type": lookup.ioc_type,
                "verdict": lookup.final_verdict.value if lookup.final_verdict else "unknown",
                "risk_score": lookup.risk_score,
                "confidence_score": lookup.confidence_score,
                "asn": asns,
                "malware_families": malware,
                "threat_actors": actors,
                "related_domains": domains,
                "first_seen": lookup.created_at.isoformat(),
            }
        )

    if len(rows) < 2:
        raise HTTPException(status_code=422, detail="Fewer than 2 of the given lookup_ids resolved to completed lookups")

    narrative = await compare_iocs(rows)
    return {"rows": rows, "narrative": narrative.model_dump()}
