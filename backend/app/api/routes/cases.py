"""Lightweight case management: group IOCs/lookups/notes/reports under one
investigation with a status workflow. Visibility mirrors lookups (shared
across the whole SOC team for anyone with case:read) since cases exist
precisely so a team can hand off/collaborate on an investigation -- not a
private-per-analyst construct like the basket.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.rbac import CurrentUser, require_permission
from app.core.db import get_db
from app.models.case import Case, CaseIOC, CaseNote, CaseStatus
from app.schemas.case import CaseCreateRequest, CaseIOCAddRequest, CaseNoteCreateRequest, CaseUpdateRequest

router = APIRouter(prefix="/cases", tags=["cases"])


def _serialize_case(case: Case) -> dict:
    return {
        "id": str(case.id),
        "title": case.title,
        "description": case.description,
        "analyst_id": str(case.analyst_id),
        "severity": case.severity.value,
        "status": case.status.value,
        "tags": case.tags,
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
        "iocs": [
            {
                "id": str(i.id),
                "ioc_value": i.ioc_value,
                "ioc_type": i.ioc_type,
                "lookup_id": str(i.lookup_id) if i.lookup_id else None,
                "added_by": str(i.added_by),
                "created_at": i.created_at.isoformat(),
            }
            for i in case.iocs
        ],
        "notes": [
            {
                "id": str(n.id),
                "author_id": str(n.author_id),
                "body": n.body,
                "anchor_type": n.anchor_type,
                "anchor_ref": n.anchor_ref,
                "created_at": n.created_at.isoformat(),
            }
            for n in case.notes
        ],
        "reports": [
            {
                "id": str(r.id),
                "report_type": r.report_type,
                "title": r.title,
                "generated_by": str(r.generated_by),
                "created_at": r.created_at.isoformat(),
            }
            for r in case.reports
        ],
    }


async def _load_case(case_id: uuid.UUID, db: AsyncSession) -> Case:
    result = await db.execute(
        select(Case)
        .options(selectinload(Case.iocs), selectinload(Case.notes), selectinload(Case.reports))
        .where(Case.id == case_id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("")
async def list_cases(
    status_filter: CaseStatus | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("case:read")),
):
    limit = max(1, min(limit, 200))
    query = select(Case).order_by(Case.created_at.desc()).limit(limit)
    if status_filter:
        query = query.where(Case.status == status_filter)
    cases = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "severity": c.severity.value,
            "status": c.status.value,
            "tags": c.tags,
            "created_at": c.created_at.isoformat(),
        }
        for c in cases
    ]


@router.post("", status_code=201)
async def create_case(
    payload: CaseCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("case:create")),
):
    case = Case(
        title=payload.title,
        description=payload.description,
        analyst_id=user.id,
        severity=payload.severity,
        tags=payload.tags,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return _serialize_case(await _load_case(case.id, db))


@router.get("/{case_id}")
async def get_case(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("case:read")),
):
    return _serialize_case(await _load_case(case_id, db))


@router.patch("/{case_id}")
async def update_case(
    case_id: uuid.UUID,
    payload: CaseUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("case:write")),
):
    case = await _load_case(case_id, db)
    updates = payload.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(case, field_name, value)
    await db.commit()
    return _serialize_case(await _load_case(case_id, db))


@router.post("/{case_id}/close")
async def close_case(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("case:close")),
):
    case = await _load_case(case_id, db)
    case.status = CaseStatus.CLOSED
    await db.commit()
    return _serialize_case(await _load_case(case_id, db))


@router.post("/{case_id}/iocs", status_code=201)
async def add_case_ioc(
    case_id: uuid.UUID,
    payload: CaseIOCAddRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("case:write")),
):
    await _load_case(case_id, db)

    # Mirrors app/api/routes/basket.py's add_to_basket(): a case's IOC list
    # must not silently accumulate exact duplicates from a double-click or a
    # network retry. Case-insensitive on purpose, matching add_to_basket()'s
    # own rationale (same IOC re-entered in different casing is still the
    # same logical entry) -- and matching the uq_case_ioc_case_value unique
    # constraint's own case-sensitive comparison is handled below by
    # catching the IntegrityError this pre-check alone can't fully prevent.
    existing = (
        await db.execute(
            select(CaseIOC).where(
                CaseIOC.case_id == case_id, func.lower(CaseIOC.ioc_value) == payload.ioc_value.lower()
            )
        )
    ).scalar_one_or_none()
    if existing:
        return _serialize_case(await _load_case(case_id, db))

    ioc = CaseIOC(
        case_id=case_id,
        ioc_value=payload.ioc_value,
        ioc_type=payload.ioc_type,
        # payload.lookup_id is Optional[uuid.UUID] (see app/schemas/case.py) --
        # Pydantic already validated/coerced it, so no raw uuid.UUID() call
        # (and no try/except around one) is needed here.
        lookup_id=payload.lookup_id,
        added_by=user.id,
    )
    db.add(ioc)
    try:
        await db.commit()
    except IntegrityError:
        # Check-then-insert race, same class of bug as add_to_basket()'s own
        # uq_basket_owner_ioc handling: two concurrent adds of the same
        # (case_id, ioc_value) can both pass the 'existing' SELECT above
        # (both see None), then both attempt the INSERT -- the DB's
        # uq_case_ioc_case_value unique constraint lets exactly one commit
        # through and raises IntegrityError to the loser. Treat that as the
        # idempotent add it really is rather than a 500: roll back this
        # request's now-aborted transaction and return the case as-is, since
        # the winner's row already satisfies the same logical add.
        await db.rollback()
        existing = (
            await db.execute(
                select(CaseIOC).where(CaseIOC.case_id == case_id, CaseIOC.ioc_value == payload.ioc_value)
            )
        ).scalar_one_or_none()
        if existing is None:
            # Constraint violation implies a matching row exists; if it
            # somehow doesn't (e.g. a different constraint fired), don't
            # mask the original error.
            raise
    return _serialize_case(await _load_case(case_id, db))


@router.delete("/{case_id}/iocs/{ioc_id}", status_code=204)
async def remove_case_ioc(
    case_id: uuid.UUID,
    ioc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("case:write")),
):
    ioc = (
        await db.execute(select(CaseIOC).where(CaseIOC.id == ioc_id, CaseIOC.case_id == case_id))
    ).scalar_one_or_none()
    if not ioc:
        raise HTTPException(status_code=404, detail="Case IOC not found")
    await db.delete(ioc)
    await db.commit()


@router.post("/{case_id}/notes", status_code=201)
async def add_case_note(
    case_id: uuid.UUID,
    payload: CaseNoteCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("case:write")),
):
    await _load_case(case_id, db)
    note = CaseNote(
        case_id=case_id,
        author_id=user.id,
        body=payload.body,
        anchor_type=payload.anchor_type,
        anchor_ref=payload.anchor_ref,
    )
    db.add(note)
    await db.commit()
    return _serialize_case(await _load_case(case_id, db))
