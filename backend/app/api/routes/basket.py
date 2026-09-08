"""IOC Basket: per-analyst scratch space for collecting IOCs across an
investigation, then acting on the set (investigate all, compare, promote to
a case). See app/models/basket.py for the model rationale.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.analysis_service import compare_iocs
from app.auth.rbac import CurrentUser, require_permission
from app.core.db import get_db
from app.ioc.detector import detect_ioc_type, value_matches_ioc_type
from app.ioc.types import IOCType
from app.models.basket import BasketItem
from app.models.lookup import IOCLookup, LookupStatus
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
    # See app/api/routes/lookup.py's stream_lookup() for the full rationale --
    # identical bug, identical fix: Field(min_length=1) only guards the raw,
    # pre-.strip() value, and a caller-supplied ioc_type_hint used to bypass
    # the UNKNOWN-rejection safety net entirely (it only ever checked the
    # auto-detected type).
    if not ioc_value:
        raise HTTPException(status_code=422, detail="IOC value cannot be empty or whitespace-only.")

    if payload.ioc_type_hint is not None:
        ioc_type = payload.ioc_type_hint
        if ioc_type == IOCType.UNKNOWN or not value_matches_ioc_type(ioc_value, ioc_type):
            raise HTTPException(
                status_code=422,
                detail=f"'{ioc_value}' does not look like a valid {ioc_type.value}; "
                "pass a different ioc_type_hint or omit it to auto-detect.",
            )
    else:
        ioc_type = detect_ioc_type(ioc_value)
        if ioc_type == IOCType.UNKNOWN:
            raise HTTPException(status_code=422, detail="Could not determine IOC type; pass ioc_type_hint.")

    # Case-insensitive on purpose: ioc_value is only whitespace-stripped
    # above, not case-normalized, and the same logical IOC is routinely
    # re-entered in different casing (e.g. 'EXAMPLE.COM' vs 'example.com').
    # Without this, that byte-for-byte comparison (and the DB's
    # uq_basket_owner_ioc unique constraint, which is equally
    # case-sensitive) let the two casings create two separate basket rows
    # instead of being recognized as the same entry -- inconsistent with
    # app/correlation/engine.py's own _node_id(), which lowercases values
    # specifically so the same IOC in different casing dedupes to one graph
    # node. Deliberately compares case-insensitively without rewriting the
    # stored value itself, so whichever casing was entered first is kept
    # and handed back on a later re-add in different casing, rather than
    # silently mutating an analyst's existing basket entry.
    existing = (
        await db.execute(
            select(BasketItem).where(
                BasketItem.owner_id == user.id, func.lower(BasketItem.ioc_value) == ioc_value.lower()
            )
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
    try:
        await db.commit()
    except IntegrityError:
        # Check-then-insert race: two concurrent adds of the same
        # (owner_id, ioc_value) can both pass the 'existing' SELECT above
        # (both see None), then both attempt the INSERT -- the DB's
        # uq_basket_owner_ioc unique constraint lets exactly one commit
        # through and raises IntegrityError to the loser. Same class of
        # bug as app/core/users.py's create_user() and
        # app/core/runtime_config.py's upsert_*() docstrings; here the
        # correct behavior is to treat it as the idempotent add it really
        # is and hand back the row that won the race, rather than 500ing
        # on what's typically just an ordinary double-submit. rollback()
        # is required first: the failed commit leaves this request's
        # session's transaction aborted, so it can't run the SELECT below
        # until the transaction is reset.
        await db.rollback()
        existing = (
            await db.execute(
                select(BasketItem).where(BasketItem.owner_id == user.id, BasketItem.ioc_value == ioc_value)
            )
        ).scalar_one_or_none()
        if existing is None:
            # Constraint violation implies a matching row exists; if it
            # somehow doesn't (e.g. a different constraint fired), don't
            # mask the original error.
            raise
        return _serialize(existing)
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
        if lookup.status != LookupStatus.COMPLETED:
            # Matches this endpoint's own docstring ("IOCs must already have
            # a completed lookup") and the analogous check in
            # reanalyze_lookup(): a pending/running/failed lookup has no
            # trustworthy risk_score/confidence_score/final_verdict yet, so
            # silently including it here would misrepresent incomplete data
            # as a real, comparable investigation row. Skipped the same way
            # an unresolvable/nonexistent lookup_id already is above, rather
            # than raising, so one bad id doesn't block comparing the rest.
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
