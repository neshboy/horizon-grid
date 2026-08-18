"""Thin async wrapper around OpenAI's chat-completions API (api.openai.com),
used as an alternative AI backend (set AI_BACKEND=openai).

Endpoint and auth verified against OpenAI's own current documentation
(platform.openai.com/docs) at the time this was written:
  - Chat completions: POST https://api.openai.com/v1/chat/completions
  - Model listing:    GET  https://api.openai.com/v1/models
  - Auth: `Authorization: Bearer <OPENAI_API_KEY>`.

Exposes the same call_claude_json() method name as bedrock_client.py,
gemini_client.py, anthropic_client.py, groq_client.py, and ollama_client.py
(the default) so app/ai/service.py can select any backend without branching
on which one is active. Mirrors groq_client.py's shape almost exactly, since
Groq's own API is itself modeled on OpenAI's -- OpenAI is the origin of the
request/response shape both clients use, not a coincidence.

Structured output: uses OpenAI's forced tool-calling (`tool_choice` naming a
specific function) -- the API this project's other OpenAI-compatible client
(groq_client.py) already copies -- rather than `response_format` JSON mode,
for the same reason groq_client.py gives: naming/shaping a single tool call
is more precise than a bare "return JSON" instruction. inline_refs() flattens
$ref/$defs the same defensive way every other client in this module does.
"""
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.openai.com/v1"
_TIMEOUT_SECONDS = 60

# Fallback list used only when a live /models call isn't possible (e.g. the
# wizard's model dropdown before a key has been entered/tested). Never used
# to validate or restrict a real call -- the actual chat-completion request
# always sends whatever model_id the caller/settings specify, and OpenAI's
# own API is the authority on whether that model exists. Deliberately short
# and revisited via list_models() rather than treated as exhaustive or
# permanent -- OpenAI's own /models listing is what the wizard actually uses
# once a key is present.
FALLBACK_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.1-mini",
    "o3-mini",
]
DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.openai_api_key
        self._model_id = model_id if model_id is not None else settings.openai_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.openai_max_tokens

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
                raise RuntimeError(f"OpenAI did not respond within {_TIMEOUT_SECONDS}s (model={self._model_id})") from exc
            except httpx.HTTPError as exc:
                logger.error("OpenAI request failed for model=%s: %r", self._model_id, exc)
                raise RuntimeError(f"OpenAI request failed (model={self._model_id}): {exc!r}") from exc

        if response.status_code >= 400:
            logger.error("OpenAI chat completion failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"OpenAI invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenAI response had no choices: {payload}")

        tool_calls = choices[0].get("message", {}).get("tool_calls") or []
        matching = next((tc for tc in tool_calls if tc.get("function", {}).get("name") == tool_name), None)
        if not matching:
            raise RuntimeError(f"OpenAI response did not include the expected tool call {tool_name!r}: {payload}")

        arguments = matching["function"].get("arguments", "")
        try:
            return json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI tool-call arguments were not valid JSON: {arguments}") from exc


async def list_models(api_key: str) -> list[str]:
    """Live model discovery against OpenAI's own /models endpoint, using a
    *candidate* key (never get_settings()) -- mirrors groq_client.list_models
    and the trust model of app/providers/connection_test.py: the caller
    supplies a key to try, this never reads or persists the configured one.
    Used by the wizard's model dropdown and by the AI backend connection test.

    OpenAI's /models endpoint lists every model visible to the account,
    including embedding/moderation/image/audio models that don't support
    chat completions at all -- filtered here to ids that look like actual
    chat-capable GPT/O-series models, so the dropdown isn't cluttered with
    entries that would fail immediately if selected.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{_API_BASE}/models", headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    data = response.json().get("data", [])
    ids = [m["id"] for m in data if m.get("id")]
    chat_ids = [
        i for i in ids
        if (i.startswith("gpt-") or i.startswith("o1") or i.startswith("o3") or i.startswith("o4") or i.startswith("chatgpt-"))
        and "audio" not in i and "realtime" not in i and "transcribe" not in i and "tts" not in i and "embedding" not in i
    ]
    return chat_ids or ids


_singleton: Optional[OpenAIClient] = None


def get_openai_client() -> OpenAIClient:
    global _singleton
    if _singleton is None:
        _singleton = OpenAIClient()
    return _singleton
