"""Thin async wrapper around Google's Gemini API (generateContent) with
structured JSON output, used as a drop-in replacement for bedrock_client.py's
BedrockClaudeClient -- both expose an async `call_claude_json`-shaped method
so app/ai/service.py doesn't need to know which backend it's calling.

Uses plain httpx REST calls (matching every other connector in this
codebase) rather than the google-generativeai SDK, to avoid a new dependency
and keep this fully async-native.

Schema note: Gemini's `responseSchema` is an OpenAPI-3.0-style schema and
does not resolve JSON Schema `$ref`/`$defs` the way Pydantic's
model_json_schema() emits them for nested models (e.g. FinalAssessment's
list[MitreMapping]). inline_refs() (app/ai/schema_utils.py) flattens those
out before sending, since sending raw `$ref` pointers silently produces
malformed/empty fields.
"""
import asyncio
import json
import logging
from typing import Any, Optional

import httpx

from app.ai.schema_utils import inline_refs
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        self._model_id = model_id if model_id is not None else settings.gemini_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.gemini_max_tokens

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
        """Named call_claude_json (not call_gemini_json) so app/ai/service.py
        can call either backend through the identical method name -- swapping
        get_bedrock_client() for get_gemini_client() is the only change needed.
        """
        flat_schema = inline_refs(json_schema)
        body = {
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": flat_schema,
                "maxOutputTokens": max_tokens or self._max_tokens,
                "temperature": 0.1,
            },
        }

        # The API key is sent via the `x-goog-api-key` header rather than the
        # `?key=` query-string convention Google's docs also support --
        # httpx logs the full request URL (including query string) at INFO
        # level by default, which would otherwise put the real key in plain
        # text in every application log line for every Gemini call.
        url = f"{_API_BASE}/models/{self._model_id}:generateContent"

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=body, headers={"x-goog-api-key": self._api_key or ""})

        if response.status_code >= 400:
            logger.error("Gemini generateContent call failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"Gemini invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini response had no candidates: {payload}")

        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text:
            raise RuntimeError(f"Gemini response had no text content: {payload}")

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Gemini response was not valid JSON: {text}") from exc


_singleton: Optional[GeminiClient] = None


def get_gemini_client() -> GeminiClient:
    global _singleton
    if _singleton is None:
        _singleton = GeminiClient()
    return _singleton
