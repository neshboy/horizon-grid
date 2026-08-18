"""Thin async wrapper around a locally-hosted Ollama server, used as the
primary AI backend when no cloud AI vendor has a working key/quota (Bedrock
needs IAM + model access, Gemini/OpenAI need billing). Ollama runs entirely
on the user's own machine -- no API key, no quota, no per-token cost.

Uses Ollama's /api/chat structured-output mode (`format: <json schema>`,
supported since Ollama 0.5+): the server grammar-constrains decoding so the
response text is valid JSON matching the schema, without needing the model
to have been trained on tool-calling. This works with any local model,
including ones like Gemma that have no native tool-use format.

Networking note: this backend process runs inside Docker (see
docker-compose.yml), while Ollama runs directly on the host -- so
"localhost" from inside the container is the container itself, not the
host's Ollama server. OLLAMA_BASE_URL defaults to
http://host.docker.internal:11434, which Docker Desktop (Windows/Mac)
resolves to the host automatically.

Schema note: same as Gemini (app/ai/gemini_client.py) -- llama.cpp's
grammar-based structured output (which Ollama's `format` parameter compiles
to) has inconsistent support for JSON Schema `$ref`/`$defs` depending on
model/version, so inline_refs() flattens them defensively before sending.
"""
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 120


class OllamaClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        # Optional overrides let app/core/runtime_config.py construct a
        # client from the currently-active runtime configuration instead of
        # the frozen .env-derived Settings singleton -- defaults preserve
        # the original settings-only behavior for any other caller.
        settings = get_settings()
        self._base_url = (base_url if base_url is not None else settings.ollama_base_url).rstrip("/")
        self._model = model if model is not None else settings.ollama_model
        self._max_tokens = max_tokens if max_tokens is not None else settings.ollama_max_tokens

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._model)

    async def call_claude_json(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        tool_name: str = "emit_result",
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Named call_claude_json to match the Bedrock/Gemini/Anthropic
        clients' method name -- app/ai/service.py calls whichever backend is
        configured through this identical signature.
        """
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": inline_refs(json_schema),
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": max_tokens or self._max_tokens,
            },
        }

        # A model sized to fit fully in VRAM (~4GB card) responds in
        # seconds; _TIMEOUT_SECONDS leaves headroom for first-load latency
        # without masking a genuinely hung request. Raise this if a larger
        # model that spills to CPU/mmap is ever configured -- that was
        # observed to take several minutes per response.
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(f"{self._base_url}/api/chat", json=body)
            except httpx.ConnectError as exc:
                raise RuntimeError(
                    f"Could not reach Ollama at {self._base_url} -- is it running? ({exc})"
                ) from exc
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"Ollama did not respond within {_TIMEOUT_SECONDS}s (model={self._model}) -- "
                    "likely too slow for available hardware"
                ) from exc
            except httpx.HTTPError as exc:
                # Anything else httpx can raise once a connection is
                # established (reset mid-response, protocol error, etc).
                logger.error("Ollama request failed for model=%s: %r", self._model, exc)
                raise RuntimeError(f"Ollama request failed (model={self._model}): {exc!r}") from exc

        if response.status_code >= 400:
            logger.error("Ollama chat call failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"Ollama invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        content = payload.get("message", {}).get("content", "")
        if not content:
            logger.error("Ollama response had no message content (model=%s): %r", self._model, payload)
            raise RuntimeError(f"Ollama response had no message content: {payload}")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("Ollama response was not valid JSON (model=%s): %r", self._model, content)
            raise RuntimeError(f"Ollama response was not valid JSON: {content}") from exc

        if not isinstance(parsed, dict):
            logger.error("Ollama response JSON was not an object (model=%s): %r", self._model, parsed)
            raise RuntimeError(f"Ollama response was valid JSON but not an object: {parsed!r}")
        return parsed


_singleton: Optional[OllamaClient] = None


def get_ollama_client() -> OllamaClient:
    global _singleton
    if _singleton is None:
        _singleton = OllamaClient()
    return _singleton
