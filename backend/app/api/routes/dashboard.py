"""Executive KPI endpoint for the ops/exec dashboard. Read-only aggregation
over already-persisted data -- see app/core/dashboard.py::get_kpis() for the
exact definition of every KPI returned here.

GET /dashboard/executive-summary reuses the same "dashboard:read" permission
(no new permission needed) and layers an AI-generated narrative on top of
the exact same get_kpis() numbers -- see app/ai/dashboard_summary.py for why
the AI-calling logic lives there and not in app/core/dashboard.py (which is
deliberately AI-free).
"""
from fastapi import APIRouter, Depends, Query

from app.ai.dashboard_summary import generate_executive_summary
from app.auth.rbac import CurrentUser, require_permission
from app.core.dashboard import get_activity_timeline, get_geo_activity, get_kpis

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/kpis")
async def dashboard_kpis(user: CurrentUser = Depends(require_permission("dashboard:read"))):
    return await get_kpis()


@router.get("/activity-timeline")
async def dashboard_activity_timeline(
    hours: int = Query(24, ge=1, le=168),
    user: CurrentUser = Depends(require_permission("dashboard:read")),
):
    return {"buckets": await get_activity_timeline(hours=hours)}


@router.get("/geo-activity")
async def dashboard_geo_activity(
    hours: int = Query(720, ge=1, le=4320),
    user: CurrentUser = Depends(require_permission("dashboard:read")),
):
    return await get_geo_activity(hours=hours)


@router.get("/executive-summary")
async def dashboard_executive_summary(user: CurrentUser = Depends(require_permission("dashboard:read"))):
    return await generate_executive_summary()
