"""Thin async wrapper around OpenRouter's OpenAI-compatible chat-completions
API (openrouter.ai), used as an alternative AI backend (set AI_BACKEND=openrouter).

OpenRouter is a meta-router, not a model provider of its own -- it gives
access to hundreds of underlying models from many companies (OpenAI,
Anthropic, Google, Meta, DeepSeek, and others) through one OpenAI-compatible
API surface. Endpoint and auth verified live (curl) against OpenRouter's own
OpenAPI spec at the time this was written, not just docs paraphrase:
  - Base URL:         https://openrouter.ai/api/v1
  - Chat completions: POST https://openrouter.ai/api/v1/chat/completions
  - Model listing:    GET  https://openrouter.ai/api/v1/models
  - Auth: `Authorization: Bearer <OPENROUTER_API_KEY>` (standard OpenAI-
    compatible bearer scheme, same as groq_client.py/openai_client.py).

Exposes the same call_claude_json() method name as bedrock_client.py,
gemini_client.py, anthropic_client.py, groq_client.py, and openai_client.py
so app/ai/service.py can select any backend without branching on which one
is active. Mirrors openai_client.py's shape almost exactly, since OpenRouter's
own API is itself OpenAI-compatible -- OpenAI is the origin of the
request/response shape this client uses, not a coincidence.

Structured output: uses OpenAI-style forced tool-calling (`tool_choice`
naming a specific function, `{"type": "function", "function": {"name": ...}}`)
-- confirmed directly in OpenRouter's own OpenAPI spec (schema
ChatNamedToolChoice) -- rather than a bare "return JSON" instruction, for the
same reason openai_client.py and groq_client.py give. inline_refs() flattens
$ref/$defs the same defensive way every other client in this module does.

Model listing / FALLBACK_MODELS: because OpenRouter fans out to hundreds of
underlying models, many of which do NOT support forced tool-calling at all,
list_models() below filters the live /models response down to ids whose
"supported_parameters" array contains "tool_choice" (confirmed live: 342 of
413 models declared tool_choice support at the time this was written) --
picking a model without it would 400 against this client's forced-tool-
calling call_claude_json(). FALLBACK_MODELS mirrors that same constraint with
a short list of current, stable, tool-calling-capable ids spanning several
underlying providers (confirmed via a live, unsummarized API call at the
time this was written); deliberately short and revisited via list_models()
rather than treated as exhaustive or permanent.

Error shape note (informational only -- actual per-status handling lives in
app/providers/connection_test.py, not here): OpenRouter's error body is
`{"error": {"code": <int>, "message": <string>, "metadata"?: {...}}}` --
similar in shape to OpenAI's nested error object but WITHOUT an `error.type`
or `error.param` field. call_claude_json()'s non-2xx handling below just
surfaces response.text either way (same as every other client in this
module), so this doesn't require any logic change here.
"""
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://openrouter.ai/api/v1"
_TIMEOUT_SECONDS = 60

# Fallback list used only when a live /models call isn't possible (e.g. the
# wizard's model dropdown before a key has been entered/tested). Never used
# to validate or restrict a real call -- the actual chat-completion request
# always sends whatever model_id the caller/settings specify, and
# OpenRouter's own API is the authority on whether that model exists (and
# whether the underlying model actually supports tool_choice). Each id below
# is a current, stable, tool-calling-capable model spanning a different
# underlying provider routed through OpenRouter, confirmed via a live
# unsummarized API call at the time this was written; deliberately short and
# revisited via list_models() rather than treated as exhaustive or permanent.
FALLBACK_MODELS = [
    "openai/gpt-4o",
    "anthropic/claude-sonnet-4.5",
    "google/gemini-2.5-pro",
    "deepseek/deepseek-chat",
    "meta-llama/llama-3.3-70b-instruct",
]
DEFAULT_MODEL = "openai/gpt-4o"


class OpenRouterClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.openrouter_api_key
        self._model_id = model_id if model_id is not None else settings.openrouter_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.openrouter_max_tokens

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def call_claude_json(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        tool_name: str = "emit_result",
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        flat_schema = inline_refs(json_schema)
        body = {
            "model": self._model_id,
            "temperature": 0.1,
            "max_completion_tokens": max_tokens or self._max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": "Emit the structured result for this analysis.",
                        "parameters": flat_schema,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": tool_name}},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(f"{_API_BASE}/chat/completions", headers=headers, json=body)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"OpenRouter did not respond within {_TIMEOUT_SECONDS}s (model={self._model_id})") from exc
            except httpx.HTTPError as exc:
                logger.error("OpenRouter request failed for model=%s: %r", self._model_id, exc)
                raise RuntimeError(f"OpenRouter request failed (model={self._model_id}): {exc!r}") from exc

        if response.status_code >= 400:
            # OpenRouter's error body is {"error": {"code", "message", "metadata"?}}
            # -- no error.type/error.param like OpenAI's -- but we just surface the
            # raw text either way, so no special-casing needed here.
            logger.error("OpenRouter chat completion failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"OpenRouter invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenRouter response had no choices: {payload}")

        tool_calls = choices[0].get("message", {}).get("tool_calls") or []
        matching = next((tc for tc in tool_calls if tc.get("function", {}).get("name") == tool_name), None)
        if not matching:
            raise RuntimeError(f"OpenRouter response did not include the expected tool call {tool_name!r}: {payload}")

        arguments = matching["function"].get("arguments", "")
        try:
            return json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenRouter tool-call arguments were not valid JSON: {arguments}") from exc


async def list_models(api_key: str) -> list[str]:
    """Live model discovery against OpenRouter's own /models endpoint, using a
    *candidate* key (never get_settings()) -- mirrors openai_client.list_models
    and the trust model of app/providers/connection_test.py: the caller
    supplies a key to try, this never reads or persists the configured one.
    Used by the wizard's model dropdown and by the AI backend connection test.

    OpenRouter's /models endpoint lists every model routed through it --
    hundreds of them, from dozens of underlying providers -- most of which
    don't support forced tool-calling at all. Filtered here to ids whose
    "supported_parameters" array contains "tool_choice", so the dropdown
    isn't cluttered with entries that would 400 against this client's
    forced-tool-calling call_claude_json(). Falls back to returning every
    listed model id if the response doesn't include "supported_parameters"
    for any model (i.e. there's nothing to filter on).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{_API_BASE}/models", headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    data = response.json().get("data", [])
    ids = [m["id"] for m in data if m.get("id")]
    tool_choice_ids = [
        m["id"] for m in data
        if m.get("id") and "tool_choice" in (m.get("supported_parameters") or [])
    ]
    return tool_choice_ids or ids


_singleton: Optional[OpenRouterClient] = None


def get_openrouter_client() -> OpenRouterClient:
    global _singleton
    if _singleton is None:
        _singleton = OpenRouterClient()
    return _singleton
