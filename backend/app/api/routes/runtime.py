"""Runtime provider/AI configuration -- the API surface behind the "no
restart required" architecture. See app/core/runtime_config.py for the
service layer and app/models/runtime_config.py for the schema.

Distinct from app/api/routes/ai_config.py and app/api/routes/providers.py,
which already provide live candidate-credential testing (never touching
stored config) -- this router is what actually PERSISTS a validated
credential into the runtime-mutable store, switches the active AI backend,
and enables/disables IOC providers, all without a process restart.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.auth.rbac import CurrentUser, require_permission
from app.core import runtime_config as svc
from app.providers.registry import get_all_providers

router = APIRouter(prefix="/runtime", tags=["runtime"])


# --- AI providers -----------------------------------------------------------


@router.get("/ai-providers")
async def list_ai_providers(user: CurrentUser = Depends(require_permission("lookup:read"))):
    """Read-only listing (provider_id/configured/masked_credentials/etc. --
    see app/core/runtime_config.py's _row_to_public_dict, which never
    returns a raw credential) -- deliberately gated on "lookup:read", NOT
    "provider:manage", the same lower-privilege choice already made for the
    sibling GET /ai-active below. ANALYST (and VIEWER) hold "lookup:read"
    but not "provider:manage"; ANALYST specifically needs this to populate
    AiComparisonPanel's backend-picker dropdown (the "Analyze with a
    different AI" feature it already has "lookup:create"/reanalyze access
    to -- see POST /{lookup_id}/reanalyze in app/api/routes/lookup.py).
    Every route that actually WRITES provider config below still requires
    "provider:manage"; only this read was ever over-gated."""
    return await svc.list_ai_providers()


class ConfigureAIProviderRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    credentials: dict[str, str] = {}
    model_id: Optional[str] = None


@router.post("/ai-providers/{backend}")
async def configure_ai_provider(
    backend: str,
    payload: ConfigureAIProviderRequest,
    user: CurrentUser = Depends(require_permission("provider:manage")),
):
    if backend not in svc.AI_BACKENDS:
        raise HTTPException(status_code=400, detail=f"Unknown AI backend {backend!r}")
    try:
        return await svc.upsert_ai_provider(
            backend, payload.credentials, payload.model_id, actor_user_id=user.id, actor_email=user.email
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ActivateAIRequest(BaseModel):
    backend: str


@router.post("/ai-active")
async def set_active_ai(
    payload: ActivateAIRequest,
    user: CurrentUser = Depends(require_permission("provider:manage")),
):
    """Changes which AI backend the NEXT investigation (and every AI call
    platform-wide) uses -- takes effect immediately, no restart."""
    try:
        await svc.set_active_ai_backend(payload.backend, actor_user_id=user.id, actor_email=user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"active_backend": payload.backend}


@router.get("/ai-active")
async def get_active_ai(user: CurrentUser = Depends(require_permission("lookup:read"))):
    config = await svc.get_active_ai_config()
    if config is None:
        return {"backend": None, "model_id": None}
    return {"backend": config["backend"], "model_id": config["model_id"]}


class TestResultRequest(BaseModel):
    ok: bool
    message: str = ""


@router.post("/ai-providers/{backend}/record-test")
async def record_ai_test(
    backend: str,
    payload: TestResultRequest,
    user: CurrentUser = Depends(require_permission("provider:manage")),
):
    """Records the result of a /api/v1/ai/test call against this backend's
    now-saved credential, so the Manage Providers panel can show
    "last tested: ok, 3 minutes ago" without re-testing on every page load."""
    if backend not in svc.AI_BACKENDS:
        raise HTTPException(status_code=400, detail=f"Unknown AI backend {backend!r}")
    await svc.record_ai_test_result(backend, payload.ok, payload.message)
    return {"recorded": True}


# --- IOC providers -----------------------------------------------------------


@router.get("/ioc-providers")
async def list_ioc_providers(user: CurrentUser = Depends(require_permission("provider:manage"))):
    known = {p.provider_id: p for p in get_all_providers()}
    configured = {row["provider_id"]: row for row in await svc.list_ioc_providers()}
    out = []
    for provider_id, provider in known.items():
        row = configured.get(provider_id)
        out.append(
            row
            or {
                "provider_id": provider_id,
                "provider_name": provider.provider_name,
                "kind": "ioc",
                "enabled": True,
                "is_active": False,
                "configured": provider.configured,
                "model_id": None,
                "extra_config": {},
                "masked_credentials": {},
                "last_test_at": None,
                "last_test_ok": None,
                "last_test_message": None,
                "updated_at": None,
            }
        )
        out[-1]["requires_key"] = provider.requires_key
        out[-1]["credential_fields"] = svc.IOC_PROVIDER_CREDENTIAL_FIELDS.get(provider_id, [])
        out[-1]["category"] = provider.category.value
        out[-1]["supported_types"] = sorted(t.value for t in provider.supported_types)
    return out


class ConfigureIOCProviderRequest(BaseModel):
    credentials: dict[str, str] = {}
    extra_config: Optional[dict] = None


@router.post("/ioc-providers/{provider_id}")
async def configure_ioc_provider(
    provider_id: str,
    payload: ConfigureIOCProviderRequest,
    user: CurrentUser = Depends(require_permission("provider:manage")),
):
    known = {p.provider_id: p for p in get_all_providers()}
    provider = known.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Unknown IOC provider {provider_id!r}")
    try:
        return await svc.upsert_ioc_provider(
            provider_id,
            provider.provider_name,
            payload.credentials,
            payload.extra_config,
            actor_user_id=user.id,
            actor_email=user.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class EnableRequest(BaseModel):
    enabled: bool


@router.post("/ioc-providers/{provider_id}/enabled")
async def set_ioc_provider_enabled(
    provider_id: str,
    payload: EnableRequest,
    user: CurrentUser = Depends(require_permission("provider:manage")),
):
    """Takes effect on the NEXT investigation started after this call --
    no restart, no reinstall. Historical investigation data for this
    provider is never touched."""
    if provider_id not in {p.provider_id for p in get_all_providers()}:
        raise HTTPException(status_code=404, detail=f"Unknown IOC provider {provider_id!r}")
    await svc.set_ioc_provider_enabled(provider_id, payload.enabled, actor_user_id=user.id, actor_email=user.email)
    return {"provider_id": provider_id, "enabled": payload.enabled}


@router.post("/ioc-providers/{provider_id}/record-test")
async def record_ioc_test(
    provider_id: str,
    payload: TestResultRequest,
    user: CurrentUser = Depends(require_permission("provider:manage")),
):
    if provider_id not in {p.provider_id for p in get_all_providers()}:
        raise HTTPException(status_code=404, detail=f"Unknown IOC provider {provider_id!r}")
    await svc.record_ioc_test_result(provider_id, payload.ok, payload.message)
    return {"recorded": True}


# --- Audit log ---------------------------------------------------------------


@router.get("/audit-log")
async def audit_log(
    limit: int = Query(200, ge=0, le=200),
    user: CurrentUser = Depends(require_permission("audit:read")),
):
    return await svc.list_audit_log(limit)
