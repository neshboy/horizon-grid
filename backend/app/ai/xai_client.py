"""Thin async wrapper around xAI's OpenAI-compatible chat-completions API
(api.x.ai), used as an alternative AI backend (set AI_BACKEND=xai).

Endpoint and auth verified live against xAI's current documentation
(docs.x.ai) at the time this was written:
  - Base URL:         https://api.x.ai/v1
  - Chat completions: POST https://api.x.ai/v1/chat/completions
  - Model listing:    GET  https://api.x.ai/v1/models
  - Auth: `Authorization: Bearer <XAI_API_KEY>` (standard OpenAI-compatible
    bearer scheme).

Model IDs current/live as of this writing (docs.x.ai/docs/models):
"grok-3" is RETIRED as of 2026-05-15 -- do not use it. FALLBACK_MODELS and
DEFAULT_MODEL below are sourced from the confirmed-live replacement lineup,
newest/most-capable first, and -- same as every other client in this
module -- are only a fallback for when a live /models call isn't possible
(e.g. the wizard's model dropdown before a key has been entered/tested).
Never used to validate or restrict a real call -- the actual chat-completion
request always sends whatever model_id the caller/settings specify, and
xAI's own API is the authority on whether that model exists.

Exposes the same call_claude_json() method name as bedrock_client.py,
gemini_client.py, anthropic_client.py, groq_client.py, openai_client.py, and
ollama_client.py (the default) so app/ai/service.py can select any backend
without branching on which one is active. Mirrors openai_client.py's shape
almost exactly, since xAI's own API is itself OpenAI-compatible.

Structured output: uses xAI's forced tool-calling (`tool_choice` naming a
specific function via the standard OpenAI-shaped
`{"type": "function", "function": {"name": ...}}` object), the same
approach openai_client.py and groq_client.py use, rather than any bare
"return JSON" instruction. Note that xAI's own docs state tools[].function
.parameters "should" be followed by the model but is "not enforced at the
moment" -- there's no guaranteed strict JSON schema adherence on xAI's end,
so the JSONDecodeError handling below is left just as defensive as the
template's, not loosened or tightened. inline_refs() flattens $ref/$defs the
same defensive way every other client in this module does.

Caveat (handling lives in app/providers/connection_test.py, not here): xAI's
error response body is FLAT, not nested like OpenAI's -- confirmed live:
`{"code": "invalid-argument", "error": "message text"}`, i.e. a bare
top-level "error" *string* field, not OpenAI's `error.message`. This module
doesn't parse error bodies itself (it surfaces `response.text` verbatim in
its RuntimeErrors), so that shape difference doesn't affect anything here.
"""
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.x.ai/v1"
_TIMEOUT_SECONDS = 60

# Fallback list used only when a live /models call isn't possible (e.g. the
# wizard's model dropdown before a key has been entered/tested). Never used
# to validate or restrict a real call -- the actual chat-completion request
# always sends whatever model_id the caller/settings specify, and xAI's own
# API is the authority on whether that model exists. "grok-3" is retired
# (2026-05-15) and deliberately excluded. Deliberately short and revisited
# via list_models() rather than treated as exhaustive or permanent.
FALLBACK_MODELS = [
    "grok-4.6",
    "grok-4.5",
    "grok-4.3",
    "grok-code-fast-1",
]
DEFAULT_MODEL = "grok-4.6"


class XAIClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.xai_api_key
        self._model_id = model_id if model_id is not None else settings.xai_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.xai_max_tokens

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
                raise RuntimeError(f"xAI did not respond within {_TIMEOUT_SECONDS}s (model={self._model_id})") from exc
            except httpx.HTTPError as exc:
                logger.error("xAI request failed for model=%s: %r", self._model_id, exc)
                raise RuntimeError(f"xAI request failed (model={self._model_id}): {exc!r}") from exc

        if response.status_code >= 400:
            logger.error("xAI chat completion failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"xAI invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"xAI response had no choices: {payload}")

        tool_calls = choices[0].get("message", {}).get("tool_calls") or []
        matching = next((tc for tc in tool_calls if tc.get("function", {}).get("name") == tool_name), None)
        if not matching:
            raise RuntimeError(f"xAI response did not include the expected tool call {tool_name!r}: {payload}")

        arguments = matching["function"].get("arguments", "")
        try:
            return json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"xAI tool-call arguments were not valid JSON: {arguments}") from exc


async def list_models(api_key: str) -> list[str]:
    """Live model discovery against xAI's own /models endpoint, using a
    *candidate* key (never get_settings()) -- mirrors openai_client.list_models
    and groq_client.list_models, and the trust model of
    app/providers/connection_test.py: the caller supplies a key to try, this
    never reads or persists the configured one. Used by the wizard's model
    dropdown and by the AI backend connection test.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{_API_BASE}/models", headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    data = response.json().get("data", [])
    return [m["id"] for m in data if m.get("id")]


_singleton: Optional[XAIClient] = None


def get_xai_client() -> XAIClient:
    global _singleton
    if _singleton is None:
        _singleton = XAIClient()
    return _singleton
