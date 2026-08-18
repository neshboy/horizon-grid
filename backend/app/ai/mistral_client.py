"""Thin async wrapper around Mistral AI's chat-completions API
(api.mistral.ai), used as an alternative AI backend (set AI_BACKEND=mistral).

Endpoint and auth verified live against Mistral's own current documentation
(docs.mistral.ai) at the time this was written:
  - Base URL:         https://api.mistral.ai
  - Chat completions: POST https://api.mistral.ai/v1/chat/completions
  - Model listing:    GET  https://api.mistral.ai/v1/models
  - Auth: `Authorization: Bearer <MISTRAL_API_KEY>` (standard OpenAI-compatible
    bearer scheme, not Anthropic's `x-api-key` or Gemini's `?key=` query param).

Exposes the same call_claude_json() method name as bedrock_client.py,
gemini_client.py, anthropic_client.py, groq_client.py, openai_client.py, and
ollama_client.py (the default) so app/ai/service.py can select any backend
without branching on which one is active.

Structured output: uses Mistral's forced tool-calling (`tool_choice` given as
the exact OpenAI-shaped forced-function object
`{"type": "function", "function": {"name": ...}}`, per Mistral's own live API
reference) -- the same "force exactly one structured call" approach
openai_client.py and groq_client.py use, rather than any bare "return JSON"
instruction, for the same precision reason those two give. inline_refs()
flattens $ref/$defs the same defensive way every other client in this module
does.

Error handling note: Mistral's error-response body shape is UNCONFIRMED --
no dedicated error-schema page was found during research for this client, so
this deliberately does not attempt to deeply parse it. Same as
openai_client.py's own template, which never parses OpenAI's error body
either -- it just surfaces response.text on a non-2xx status. No special
handling is needed here for the same reason.

Model IDs: Mistral versions its models with dated suffixes (e.g.
"mistral-small-2506") rather than a single rolling name, though rolling
aliases (e.g. "mistral-large-latest") also exist. DEFAULT_MODEL below follows
this project's convention of defaulting to the smaller/faster/cheaper model
(see openai_client.py's "gpt-4o-mini", groq_client.py's
"llama-3.3-70b-versatile") rather than the largest.
"""
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.mistral.ai/v1"
_TIMEOUT_SECONDS = 60

# Fallback list used only when a live /models call isn't possible (e.g. the
# wizard's model dropdown before a key has been entered/tested). Never used
# to validate or restrict a real call -- the actual chat-completion request
# always sends whatever model_id the caller/settings specify, and Mistral's
# own API is the authority on whether that model exists. Deliberately short
# and revisited via list_models() rather than treated as exhaustive or
# permanent -- Mistral's own /models listing is what the wizard actually uses
# once a key is present.
FALLBACK_MODELS = [
    "mistral-small-2506",
    "mistral-large-2411",
    "mistral-medium-2508",
    "codestral-2501",
]
DEFAULT_MODEL = "mistral-small-2506"


class MistralClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.mistral_api_key
        self._model_id = model_id if model_id is not None else settings.mistral_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.mistral_max_tokens

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
                raise RuntimeError(f"Mistral did not respond within {_TIMEOUT_SECONDS}s (model={self._model_id})") from exc
            except httpx.HTTPError as exc:
                logger.error("Mistral request failed for model=%s: %r", self._model_id, exc)
                raise RuntimeError(f"Mistral request failed (model={self._model_id}): {exc!r}") from exc

        if response.status_code >= 400:
            logger.error("Mistral chat completion failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"Mistral invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"Mistral response had no choices: {payload}")

        tool_calls = choices[0].get("message", {}).get("tool_calls") or []
        matching = next((tc for tc in tool_calls if tc.get("function", {}).get("name") == tool_name), None)
        if not matching:
            raise RuntimeError(f"Mistral response did not include the expected tool call {tool_name!r}: {payload}")

        arguments = matching["function"].get("arguments", "")
        try:
            return json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Mistral tool-call arguments were not valid JSON: {arguments}") from exc


async def list_models(api_key: str) -> list[str]:
    """Live model discovery against Mistral's own /models endpoint, using a
    *candidate* key (never get_settings()) -- mirrors groq_client.list_models
    and openai_client.list_models, and the trust model of
    app/providers/connection_test.py: the caller supplies a key to try, this
    never reads or persists the configured one. Used by the wizard's model
    dropdown and by the AI backend connection test.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{_API_BASE}/models", headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    data = response.json().get("data", [])
    return [m["id"] for m in data if m.get("id")]


_singleton: Optional[MistralClient] = None


def get_mistral_client() -> MistralClient:
    global _singleton
    if _singleton is None:
        _singleton = MistralClient()
    return _singleton
