"""Security Assessment Toolkit API -- active checks against a target
(Nmap/DNS/TLS/HTTP-header/vuln-intel/hash tools), gated by an explicit,
mandatory authorization/scope confirmation on every run. See
app/core/security_assessment.py for the service layer and
app/security_assessment/ for the tool adapters. Deliberately its own
router, not folded into lookup.py, mirroring app/api/routes/admin.py's
precedent for a self-contained new subsystem.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.rbac import CurrentUser, require_permission
from app.core import security_assessment as svc
from app.core.db import get_db
from app.models.security_assessment import SecurityAssessmentRun
from app.schemas.security_assessment import (
    RunAssessmentRequest,
    RunResponse,
    ToolHealthResponse,
    ToolProfileResponse,
)

router = APIRouter(prefix="/security-assessment", tags=["security-assessment"])


def _serialize_run(run: SecurityAssessmentRun) -> dict:
    return {
        "id": str(run.id),
        "lookup_id": str(run.lookup_id),
        "target": run.target,
        "tool_ids": run.tool_ids,
        "profile": run.profile,
        "status": run.status.value,
        "requested_by": str(run.requested_by) if run.requested_by else None,
        "authorization_confirmed_at": run.authorization_confirmed_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_message": run.error_message,
        "findings": [
            {
                "id": str(f.id),
                "tool_id": f.tool_id,
                "finding_type": f.finding_type,
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "target_detail": f.target_detail,
                "cve_ids": f.cve_ids,
                "evidence": f.evidence,
                "created_at": f.created_at.isoformat(),
            }
            for f in run.findings
        ],
    }


@router.get("/profiles", response_model=list[ToolProfileResponse])
async def list_profiles(user: CurrentUser = Depends(require_permission("security_assessment:read"))):
    return svc.list_profiles()


@router.get("/tool-health", response_model=list[ToolHealthResponse])
async def tool_health(user: CurrentUser = Depends(require_permission("security_assessment:read"))):
    return await svc.get_tool_health()


@router.post("/{lookup_id}/run", response_model=dict)
async def run_assessment(
    lookup_id: uuid.UUID,
    payload: RunAssessmentRequest,
    user: CurrentUser = Depends(require_permission("security_assessment:create")),
):
    try:
        return await svc.start_run(
            lookup_id,
            payload.tool_ids,
            payload.profile,
            payload.target_confirmation,
            payload.authorization_confirmed,
            user.id,
            user.email,
        )
    except svc.LookupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        svc.TargetMismatchError,
        svc.AuthorizationNotConfirmedError,
        svc.UnscannableIOCTypeError,
        svc.CIDRTooLargeError,
        svc.UnknownToolError,
        svc.UnsupportedToolForTargetError,
        svc.UnknownProfileError,
        svc.InvalidTargetError,
        svc.UnsafeTargetError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel", response_model=dict)
async def cancel_run(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("security_assessment:create")),
):
    """Cancels a pending/running scan. Gated on security_assessment:create
    (the same permission required to start one) rather than a per-resource
    ownership check -- this app treats investigations and their security
    assessment runs as a shared operational picture (any analyst/admin can
    already read any other user's runs via GET /runs), so any analyst/admin
    can cancel any in-flight scan, not only their own."""
    try:
        return await svc.cancel_run(run_id, user.id, user.email)
    except svc.LookupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except svc.RunNotCancellableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{lookup_id}/runs", response_model=list[RunResponse])
async def list_runs(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("security_assessment:read")),
):
    runs = (
        await db.execute(
            select(SecurityAssessmentRun)
            .where(SecurityAssessmentRun.lookup_id == lookup_id)
            .options(selectinload(SecurityAssessmentRun.findings))
            .order_by(SecurityAssessmentRun.created_at.desc())
        )
    ).scalars().all()
    return [_serialize_run(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("security_assessment:read")),
):
    run = (
        await db.execute(
            select(SecurityAssessmentRun)
            .where(SecurityAssessmentRun.id == run_id)
            .options(selectinload(SecurityAssessmentRun.findings))
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_run(run)
