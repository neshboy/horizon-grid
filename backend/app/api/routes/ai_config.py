"""AI-backend configuration endpoints: live connection testing and model
discovery. The AI-backend analog of app/api/routes/providers.py -- see
app/ai/connection_test.py for why this exists (no AI backend had any live
test before this).
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import deepseek_client, groq_client, kimi_client, mistral_client, openai_client, openrouter_client, xai_client
from app.ai.connection_test import test_ai_connection
from app.auth.rbac import CurrentUser, bearer_scheme, get_current_user, require_permission
from app.core.db import get_db
from app.core.url_safety import assert_safe_outbound_url
from app.models.user import ROLE_PERMISSIONS, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])

# Static fallback lists for backends without a practical live-discovery
# endpoint wired up yet. These are a starting point for the UI's dropdown,
# not an enforced allow-list -- the actual call always sends whatever
# model id the caller configured; the provider's own API is the authority
# on whether that model exists. Groq, OpenAI, Kimi, DeepSeek, xAI, Mistral,
# and OpenRouter all have real dynamic discovery (see the matching branches
# below), per the explicit requirement to not hard-code an assumed model
# list that goes stale. Anthropic/Gemini/Bedrock remain static-list-only.
_STATIC_MODEL_LISTS = {
    "anthropic": ["claude-sonnet-4-5-20250929", "claude-opus-4-1-20250805", "claude-haiku-4-5-20251001"],
    "gemini": ["gemini-2.0-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
    "bedrock": ["global.anthropic.claude-sonnet-4-5-20250929-v1:0", "anthropic.claude-sonnet-4-5-20250929-v1:0"],
}


def parse_ollama_tags_response(payload: dict) -> list[str]:
    """Extracts pulled model names from Ollama's GET /api/tags response.

    Real-world finding: `.get("models", [])`'s default only applies when
    the key is ABSENT. Some Ollama versions/proxies return a literal
    `{"models": null}` when nothing is pulled yet, which `.get` happily
    returns as None (not the default) -- iterating that used to raise an
    uncaught TypeError instead of falling back to the static model list.
    Also tolerant of entries missing a "name" key (some Ollama API
    versions use "model" instead) and of non-dict entries.
    """
    models_field = payload.get("models") or []
    return [
        n for n in (m.get("name") or m.get("model") for m in models_field if isinstance(m, dict))
        if n
    ]


class AITestRequest(BaseModel):
    backend: str
    credentials: dict[str, str] = {}
    model: str | None = None


async def _require_provider_manage_or_bootstrap(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser | None:
    """Same bootstrap window as /auth/register: before the very first admin
    account exists, nobody could possibly hold a valid session, yet the
    wizard's own AI Configuration page needs exactly this endpoint to work at
    that point (a real fresh install cannot "sign in" before Start
    Installation ever creates that first account). Allow through
    unauthenticated ONLY while zero users exist -- this closes permanently
    and automatically the moment the first account is created, matching the
    exact same real-world security boundary /auth/register already commits
    to; unauthenticated forever would be a real SSRF-shaped hole (arbitrary
    outbound requests to a caller-supplied base_url/credentials), which is
    why this is not simply removing auth from the route.
    """
    result = await db.execute(select(User.id))
    if result.first() is None:
        return None
    user = await get_current_user(credentials, db)
    if "provider:manage" not in ROLE_PERMISSIONS.get(user.role, set()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.value}' lacks permission 'provider:manage'",
        )
    return user


@router.post("/test")
async def ai_test_connection(
    payload: AITestRequest,
    user: CurrentUser | None = Depends(_require_provider_manage_or_bootstrap),
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

    if backend == "kimi":
        api_key = payload.credentials.get("api_key", "")
        if not api_key:
            return {"backend": backend, "models": kimi_client.FALLBACK_MODELS, "source": "fallback", "default": kimi_client.DEFAULT_MODEL}
        try:
            models = await kimi_client.list_models(api_key)
            if models:
                return {"backend": backend, "models": sorted(models), "source": "live", "default": kimi_client.DEFAULT_MODEL}
        except httpx.HTTPError as exc:
            logger.warning("Kimi live model discovery failed, falling back to static list: %r", exc)
        return {"backend": backend, "models": kimi_client.FALLBACK_MODELS, "source": "fallback", "default": kimi_client.DEFAULT_MODEL}

    if backend == "deepseek":
        api_key = payload.credentials.get("api_key", "")
        if not api_key:
            return {"backend": backend, "models": deepseek_client.FALLBACK_MODELS, "source": "fallback", "default": deepseek_client.DEFAULT_MODEL}
        try:
            models = await deepseek_client.list_models(api_key)
            if models:
                return {"backend": backend, "models": sorted(models), "source": "live", "default": deepseek_client.DEFAULT_MODEL}
        except httpx.HTTPError as exc:
            logger.warning("DeepSeek live model discovery failed, falling back to static list: %r", exc)
        return {"backend": backend, "models": deepseek_client.FALLBACK_MODELS, "source": "fallback", "default": deepseek_client.DEFAULT_MODEL}

    if backend == "xai":
        api_key = payload.credentials.get("api_key", "")
        if not api_key:
            return {"backend": backend, "models": xai_client.FALLBACK_MODELS, "source": "fallback", "default": xai_client.DEFAULT_MODEL}
        try:
            models = await xai_client.list_models(api_key)
            if models:
                return {"backend": backend, "models": sorted(models), "source": "live", "default": xai_client.DEFAULT_MODEL}
        except httpx.HTTPError as exc:
            logger.warning("xAI live model discovery failed, falling back to static list: %r", exc)
        return {"backend": backend, "models": xai_client.FALLBACK_MODELS, "source": "fallback", "default": xai_client.DEFAULT_MODEL}

    if backend == "mistral":
        api_key = payload.credentials.get("api_key", "")
        if not api_key:
            return {"backend": backend, "models": mistral_client.FALLBACK_MODELS, "source": "fallback", "default": mistral_client.DEFAULT_MODEL}
        try:
            models = await mistral_client.list_models(api_key)
            if models:
                return {"backend": backend, "models": sorted(models), "source": "live", "default": mistral_client.DEFAULT_MODEL}
        except httpx.HTTPError as exc:
            logger.warning("Mistral live model discovery failed, falling back to static list: %r", exc)
        return {"backend": backend, "models": mistral_client.FALLBACK_MODELS, "source": "fallback", "default": mistral_client.DEFAULT_MODEL}

    if backend == "openrouter":
        api_key = payload.credentials.get("api_key", "")
        if not api_key:
            return {"backend": backend, "models": openrouter_client.FALLBACK_MODELS, "source": "fallback", "default": openrouter_client.DEFAULT_MODEL}
        try:
            models = await openrouter_client.list_models(api_key)
            if models:
                return {"backend": backend, "models": sorted(models), "source": "live", "default": openrouter_client.DEFAULT_MODEL}
        except httpx.HTTPError as exc:
            logger.warning("OpenRouter live model discovery failed, falling back to static list: %r", exc)
        return {"backend": backend, "models": openrouter_client.FALLBACK_MODELS, "source": "fallback", "default": openrouter_client.DEFAULT_MODEL}

    if backend == "ollama":
        base_url = payload.credentials.get("base_url", "").rstrip("/")
        if base_url:
            try:
                assert_safe_outbound_url(base_url)
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(f"{base_url}/api/tags")
                if r.status_code == 200:
                    names = parse_ollama_tags_response(r.json())
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
