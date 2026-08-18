"""Thin async wrapper around DeepSeek's OpenAI-compatible chat-completions API
(api.deepseek.com), used as an alternative AI backend (set AI_BACKEND=deepseek).

Endpoint and auth verified live against DeepSeek's own current documentation
(api-docs.deepseek.com) at the time this was written:
  - Base URL: https://api.deepseek.com -- note: NO "/v1" segment in the path,
    unlike most other OpenAI-compatible backends in this module (e.g.
    groq_client.py's https://api.groq.com/openai/v1 or openai_client.py's
    https://api.openai.com/v1). Confirmed verbatim from live docs.
  - Chat completions: POST https://api.deepseek.com/chat/completions
  - Model listing:    GET  https://api.deepseek.com/models
  - Auth: `Authorization: Bearer <DEEPSEEK_API_KEY>` (standard OpenAI-compatible
    bearer scheme).

Exposes the same call_claude_json() method name as bedrock_client.py,
gemini_client.py, anthropic_client.py, groq_client.py, openai_client.py, and
ollama_client.py (the default) so app/ai/service.py can select any backend
without branching on which one is active. Mirrors openai_client.py's and
groq_client.py's shape almost exactly, since DeepSeek's own API is itself
OpenAI-compatible.

Structured output: uses OpenAI-style forced tool-calling (`tool_choice`
naming a specific function) -- the same forced single-tool-call approach
every other client in this module uses -- rather than any bare "return JSON"
instruction, for the same precision reason groq_client.py and openai_client.py
give. inline_refs() flattens $ref/$defs the same defensive way every other
client in this module does.

Error handling note: DeepSeek's API returns a provider-specific HTTP 402
("Insufficient Balance") in addition to the standard 400/401/429/500/503
codes seen elsewhere -- that per-status handling lives in
app/ai/connection_test.py, not in this file.
"""
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.deepseek.com"
_TIMEOUT_SECONDS = 60

# Fallback list used only when a live /models call isn't possible (e.g. the
# wizard's model dropdown before a key has been entered/tested). Never used
# to validate or restrict a real call -- the actual chat-completion request
# always sends whatever model_id the caller/settings specify, and DeepSeek's
# own API is the authority on whether that model exists. Sourced from
# DeepSeek's current live documentation at the time this was written;
# deliberately short and revisited via list_models() rather than treated as
# exhaustive or permanent -- these are the only two model ids confirmed to
# currently exist.
FALLBACK_MODELS = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
]
DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.deepseek_api_key
        self._model_id = model_id if model_id is not None else settings.deepseek_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.deepseek_max_tokens

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
                raise RuntimeError(f"DeepSeek did not respond within {_TIMEOUT_SECONDS}s (model={self._model_id})") from exc
            except httpx.HTTPError as exc:
                logger.error("DeepSeek request failed for model=%s: %r", self._model_id, exc)
                raise RuntimeError(f"DeepSeek request failed (model={self._model_id}): {exc!r}") from exc

        if response.status_code >= 400:
            logger.error("DeepSeek chat completion failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"DeepSeek invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"DeepSeek response had no choices: {payload}")

        tool_calls = choices[0].get("message", {}).get("tool_calls") or []
        matching = next((tc for tc in tool_calls if tc.get("function", {}).get("name") == tool_name), None)
        if not matching:
            raise RuntimeError(f"DeepSeek response did not include the expected tool call {tool_name!r}: {payload}")

        arguments = matching["function"].get("arguments", "")
        try:
            return json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DeepSeek tool-call arguments were not valid JSON: {arguments}") from exc


async def list_models(api_key: str) -> list[str]:
    """Live model discovery against DeepSeek's own /models endpoint, using a
    *candidate* key (never get_settings()) -- mirrors groq_client.list_models
    and openai_client.list_models, and the trust model of
    app/ai/connection_test.py: the caller supplies a key to try, this never
    reads or persists the configured one. Used by the wizard's model dropdown
    and by the AI backend connection test.

    DeepSeek's /models response shape is
    {"object":"list","data":[{"id","object":"model","owned_by":"deepseek"}]} --
    every listed model is chat-capable, so unlike openai_client.list_models
    there's no need to filter out embedding/moderation/image entries.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{_API_BASE}/models", headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    data = response.json().get("data", [])
    return [m["id"] for m in data if m.get("id")]


_singleton: Optional[DeepSeekClient] = None


def get_deepseek_client() -> DeepSeekClient:
    global _singleton
    if _singleton is None:
        _singleton = DeepSeekClient()
    return _singleton
