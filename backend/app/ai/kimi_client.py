"""Thin async wrapper around Kimi's (Moonshot AI) OpenAI-compatible
chat-completions API (api.moonshot.ai), used as an alternative AI backend
(set AI_BACKEND=kimi).

Endpoint and auth verified live against Moonshot's current documentation
(platform.moonshot.ai / api.moonshot.ai) at the time this was written:
  - Base URL:          https://api.moonshot.ai/v1
  - Chat completions: POST https://api.moonshot.ai/v1/chat/completions
  - Model listing:    GET  https://api.moonshot.ai/v1/models -> {"object":
    "list", "data": [{"id": ...}, ...]}
  - Auth: `Authorization: Bearer <KIMI_API_KEY>` (standard OpenAI-compatible
    bearer scheme).
  - Error bodies look like {"error": {"type": "...", "message": "..."}}
    (handled by app/providers/connection_test.py, not here).

Exposes the same call_claude_json() method name as bedrock_client.py,
gemini_client.py, anthropic_client.py, groq_client.py, openai_client.py, and
ollama_client.py (the default) so app/ai/service.py can select any backend
without branching on which one is active.

Structured output: uses OpenAI-style forced tool-calling (`tool_choice`
naming a specific function), the same approach openai_client.py and
groq_client.py use, rather than a bare "return JSON" instruction.
inline_refs() flattens $ref/$defs the same defensive way every other client
in this module does.

IMPORTANT model caveat (why DEFAULT_MODEL isn't Moonshot's newest model):
forcing a specific tool_choice is documented as INCOMPATIBLE with Moonshot's
"thinking" mode on several current models -- kimi-k3 and kimi-k2.7-code
always have thinking on with no way to disable it, so a forced tool_choice
call will 400 on those. kimi-k2.5 and the moonshot-v1-* family have no
thinking parameter at all and work with forced tool_choice with zero special
handling, so DEFAULT_MODEL is pinned to "kimi-k2.5" here. kimi-k2.6 can go
either way depending on how it's deployed; if forced tool_choice starts
400ing on kimi-k2.6 (or any future thinking-capable model added to
FALLBACK_MODELS), the fix is to add "thinking": {"type": "disabled"} to the
request body for that model -- deliberately not done here to keep this
client as simple/uniform as openai_client.py's template.
"""
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.moonshot.ai/v1"
_TIMEOUT_SECONDS = 60

# Fallback list used only when a live /models call isn't possible (e.g. the
# wizard's model dropdown before a key has been entered/tested). Never used
# to validate or restrict a real call -- the actual chat-completion request
# always sends whatever model_id the caller/settings specify, and Moonshot's
# own API is the authority on whether that model exists. kimi-k2.5 and the
# moonshot-v1-* family have no "thinking" parameter and work with forced
# tool_choice with no special handling; kimi-k2.6 is included last as a
# newer option that may need the thinking-disable workaround noted above.
# Deliberately short and revisited via list_models() rather than treated as
# exhaustive or permanent.
FALLBACK_MODELS = [
    "kimi-k2.5",
    "moonshot-v1-128k",
    "moonshot-v1-32k",
    "moonshot-v1-8k",
    "kimi-k2.6",
]
DEFAULT_MODEL = "kimi-k2.5"


class KimiClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.kimi_api_key
        self._model_id = model_id if model_id is not None else settings.kimi_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.kimi_max_tokens

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
                raise RuntimeError(f"Kimi did not respond within {_TIMEOUT_SECONDS}s (model={self._model_id})") from exc
            except httpx.HTTPError as exc:
                logger.error("Kimi request failed for model=%s: %r", self._model_id, exc)
                raise RuntimeError(f"Kimi request failed (model={self._model_id}): {exc!r}") from exc

        if response.status_code >= 400:
            logger.error("Kimi chat completion failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"Kimi invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"Kimi response had no choices: {payload}")

        tool_calls = choices[0].get("message", {}).get("tool_calls") or []
        matching = next((tc for tc in tool_calls if tc.get("function", {}).get("name") == tool_name), None)
        if not matching:
            raise RuntimeError(f"Kimi response did not include the expected tool call {tool_name!r}: {payload}")

        arguments = matching["function"].get("arguments", "")
        try:
            return json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Kimi tool-call arguments were not valid JSON: {arguments}") from exc


async def list_models(api_key: str) -> list[str]:
    """Live model discovery against Moonshot's own /models endpoint, using a
    *candidate* key (never get_settings()) -- mirrors the trust model of
    app/providers/connection_test.py: the caller supplies a key to try, this
    never reads or persists the configured one. Used by the wizard's model
    dropdown and by the AI backend connection test.

    Returns every model id Moonshot's own API reports for the account --
    Moonshot's /models response doesn't distinguish chat-capable models from
    other kinds the way OpenAI's does, so there's nothing to filter here.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{_API_BASE}/models", headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    data = response.json().get("data", [])
    return [m["id"] for m in data if m.get("id")]


_singleton: Optional[KimiClient] = None


def get_kimi_client() -> KimiClient:
    global _singleton
    if _singleton is None:
        _singleton = KimiClient()
    return _singleton
