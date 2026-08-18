from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.rbac import CurrentUser, require_permission
from app.core.dashboard import get_provider_health_history
from app.providers.connection_test import test_provider_connection

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/health")
async def provider_health(user: CurrentUser = Depends(require_permission("dashboard:read"))):
    """Real, DB-backed provider health (1h/24h/7d/30d windows) -- see
    app/core/dashboard.py::get_provider_health_history() for the exact
    response shape and status-threshold rules. Previously this route returned
    only static config metadata (configured/requires_key/supported_types)
    from app/providers/registry.py::get_provider_health(), never touching the
    database or reporting any real status/latency/failure information --
    that stub is now dead code, replaced by this real computation.

    Gated on "dashboard:read" rather than the original "lookup:read" --
    semantically this is operational/dashboard visibility, not lookup access
    (every role that previously had "lookup:read" also has "dashboard:read",
    so this doesn't reduce anyone's access).
    """
    return await get_provider_health_history()


class ProviderTestRequest(BaseModel):
    credentials: dict[str, str]


@router.post("/{provider_id}/test")
async def provider_test_connection(
    provider_id: str,
    payload: ProviderTestRequest,
    user: CurrentUser = Depends(require_permission("provider:manage")),
):
    """Live credential check for the setup wizard / provider-settings UI --
    makes one real, safe outbound API call with the candidate credentials
    (never persisted, never read from settings) and reports whether the
    provider accepted them. See app/providers/connection_test.py."""
    result = await test_provider_connection(provider_id, payload.credentials)
    return {
        "provider_id": provider_id,
        "ok": result.ok,
        "message": result.message,
        "latency_ms": result.latency_ms,
    }
