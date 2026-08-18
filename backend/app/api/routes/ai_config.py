"""AI-backend configuration endpoints: live connection testing and model
discovery. The AI-backend analog of app/api/routes/providers.py -- see
app/ai/connection_test.py for why this exists (no AI backend had any live
test before this).
"""
import logging

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai import groq_client, openai_client
from app.ai.connection_test import test_ai_connection
from app.auth.rbac import CurrentUser, require_permission
from app.core.url_safety import assert_safe_outbound_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])

# Static fallback lists for backends without a practical live-discovery
# endpoint wired up yet. These are a starting point for the UI's dropdown,
# not an enforced allow-list -- the actual call always sends whatever
# model id the caller configured; the provider's own API is the authority
# on whether that model exists. Groq and OpenAI are the two backends with
# real dynamic discovery (see /ai/groq/models and /ai/openai/models below),
# per the explicit requirement to not hard-code an assumed model list that
# goes stale.
_STATIC_MODEL_LISTS = {
    "anthropic": ["claude-sonnet-4-5-20250929", "claude-opus-4-1-20250805", "claude-haiku-4-5-20251001"],
    "gemini": ["gemini-2.0-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
    "bedrock": ["global.anthropic.claude-sonnet-4-5-20250929-v1:0", "anthropic.claude-sonnet-4-5-20250929-v1:0"],
}


class AITestRequest(BaseModel):
    backend: str
    credentials: dict[str, str] = {}
    model: str | None = None


@router.post("/test")
async def ai_test_connection(
    payload: AITestRequest,
    user: CurrentUser = Depends(require_permission("provider:manage")),
):
    """Live credential check for any AI backend (Ollama/Anthropic/Bedrock/
    Gemini/Groq/OpenAI) -- makes one real, minimal chat request with the candidate
    credentials (never persisted, never read from settings) and reports
    whether the backend accepted them, what model responded, and the
    actually-measured latency."""
    result = await test_ai_connection(payload.backend, payload.credentials, payload.model)
    return {
        "backend": payload.backend,
        "ok": result.ok,
        "message": result.message,
        "model": result.model,
        "latency_ms": result.latency_ms,
    }


class ModelListRequest(BaseModel):
    credentials: dict[str, str] = {}


@router.post("/{backend}/models")
async def ai_list_models(
    backend: str,
    payload: ModelListRequest,
    user: CurrentUser = Depends(require_permission("provider:manage")),
):
    """Model list for the wizard's dropdown. Groq supports real dynamic
    discovery against its own /models endpoint using the candidate key the
    operator just typed; other backends return a curated static list (see
    _STATIC_MODEL_LISTS) since they don't have an equivalently simple
    discovery call wired up here. Ollama lists whatever is actually pulled
    locally, which IS live/real (GET {base_url}/api/tags), not a guess."""
    if backend == "groq":
        api_key = payload.credentials.get("api_key", "")
        if not api_key:
            return {"backend": backend, "models": groq_client.FALLBACK_MODELS, "source": "fallback", "default": groq_client.DEFAULT_MODEL}
        try:
            models = await groq_client.list_models(api_key)
            if models:
                return {"backend": backend, "models": sorted(models), "source": "live", "default": groq_client.DEFAULT_MODEL}
        except httpx.HTTPError as exc:
            logger.warning("Groq live model discovery failed, falling back to static list: %r", exc)
        return {"backend": backend, "models": groq_client.FALLBACK_MODELS, "source": "fallback", "default": groq_client.DEFAULT_MODEL}

    if backend == "openai":
        api_key = payload.credentials.get("api_key", "")
        if not api_key:
            return {"backend": backend, "models": openai_client.FALLBACK_MODELS, "source": "fallback", "default": openai_client.DEFAULT_MODEL}
        try:
            models = await openai_client.list_models(api_key)
            if models:
                return {"backend": backend, "models": sorted(models), "source": "live", "default": openai_client.DEFAULT_MODEL}
        except httpx.HTTPError as exc:
            logger.warning("OpenAI live model discovery failed, falling back to static list: %r", exc)
        return {"backend": backend, "models": openai_client.FALLBACK_MODELS, "source": "fallback", "default": openai_client.DEFAULT_MODEL}

    if backend == "ollama":
        base_url = payload.credentials.get("base_url", "").rstrip("/")
        if base_url:
            try:
                assert_safe_outbound_url(base_url)
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(f"{base_url}/api/tags")
                if r.status_code == 200:
                    names = [m["name"] for m in r.json().get("models", [])]
                    if names:
                        return {"backend": backend, "models": sorted(names), "source": "live", "default": "llama3.2:3b"}
            except ValueError as exc:
                logger.warning("Ollama live model discovery refused an unsafe base_url: %r", exc)
            except httpx.HTTPError as exc:
                logger.warning("Ollama live model discovery failed, falling back to static list: %r", exc)
        return {"backend": backend, "models": ["llama3.2:3b", "llama3.1:8b"], "source": "fallback", "default": "llama3.2:3b"}

    static_list = _STATIC_MODEL_LISTS.get(backend)
    if static_list is None:
        return {"backend": backend, "models": [], "source": "unknown", "default": None}
    return {"backend": backend, "models": static_list, "source": "static", "default": static_list[0]}
