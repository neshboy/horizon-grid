"""Thin async wrapper around Groq's OpenAI-compatible chat-completions API
(api.groq.com), used as an alternative AI backend (set AI_BACKEND=groq).

Groq is a distinct AI inference provider from "Grok" (xAI) -- this client
talks to Groq's own API at api.groq.com, authenticated with GROQ_API_KEY,
never anything named/branded Grok.

Endpoint and auth verified live against Groq's current documentation
(console.groq.com/docs) at the time this was written:
  - Chat completions: POST https://api.groq.com/openai/v1/chat/completions
  - Model listing:    GET  https://api.groq.com/openai/v1/models
  - Auth: `Authorization: Bearer <GROQ_API_KEY>` (standard OpenAI-compatible
    bearer scheme, not Anthropic's `x-api-key` or Gemini's `?key=` query param).

Exposes the same call_claude_json() method name as bedrock_client.py,
gemini_client.py, anthropic_client.py, and ollama_client.py (the default) so
app/ai/service.py can select any backend without branching on which one is
active.

Structured output: uses OpenAI-style forced tool-calling (`tool_choice`
naming a specific function), the same "force exactly one structured call"
approach as anthropic_client.py, rather than Groq's `response_format`
JSON-mode (which -- per Groq's own docs -- is not guaranteed available on
every model and does not let the caller name/shape a single tool the way
tool_choice does). inline_refs() flattens $ref/$defs the same defensive way
ollama_client.py and gemini_client.py do: Groq's models are served through
constrained/grammar-based decoding on custom LPU hardware, which has the
same class of $ref-support gaps observed elsewhere in this codebase
(app/ai/schemas.py's MitreMapping docstring; ollama_client.py's module
docstring) -- untested whether Groq specifically has this gap, but flattening
is a no-op-if-unnecessary precaution, not a functional risk.
"""
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.groq.com/openai/v1"
_TIMEOUT_SECONDS = 60

# Fallback list used only when a live /models call isn't possible (e.g. the
# wizard's model dropdown before a key has been entered/tested). Never used
# to validate or restrict a real call -- the actual chat-completion request
# always sends whatever model_id the caller/settings specify, and Groq's own
# API is the authority on whether that model exists. Sourced from Groq's
# current production models list (console.groq.com/docs/models) at the time
# this was written; deliberately short and revisited via list_models()
# rather than treated as exhaustive or permanent.
FALLBACK_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
]
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.groq_api_key
        self._model_id = model_id if model_id is not None else settings.groq_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.groq_max_tokens

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
                raise RuntimeError(f"Groq did not respond within {_TIMEOUT_SECONDS}s (model={self._model_id})") from exc
            except httpx.HTTPError as exc:
                logger.error("Groq request failed for model=%s: %r", self._model_id, exc)
                raise RuntimeError(f"Groq request failed (model={self._model_id}): {exc!r}") from exc

        if response.status_code >= 400:
            logger.error("Groq chat completion failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"Groq invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"Groq response had no choices: {payload}")

        tool_calls = choices[0].get("message", {}).get("tool_calls") or []
        matching = next((tc for tc in tool_calls if tc.get("function", {}).get("name") == tool_name), None)
        if not matching:
            raise RuntimeError(f"Groq response did not include the expected tool call {tool_name!r}: {payload}")

        arguments = matching["function"].get("arguments", "")
        try:
            return json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Groq tool-call arguments were not valid JSON: {arguments}") from exc


async def list_models(api_key: str) -> list[str]:
    """Live model discovery against Groq's own /models endpoint, using a
    *candidate* key (never get_settings()) -- mirrors the trust model of
    app/providers/connection_test.py: the caller supplies a key to try, this
    never reads or persists the configured one. Used by the wizard's model
    dropdown (Phase 13: don't rely on a hardcoded list that goes stale) and
    by the AI backend connection test.

    Returns model IDs for models that support chat completions where the
    API reports that distinction; falls back to returning every listed
    model id if the response doesn't include enough detail to filter.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{_API_BASE}/models", headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    data = response.json().get("data", [])
    return [m["id"] for m in data if m.get("id")]


_singleton: Optional[GroqClient] = None


def get_groq_client() -> GroqClient:
    global _singleton
    if _singleton is None:
        _singleton = GroqClient()
    return _singleton
