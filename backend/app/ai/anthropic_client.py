"""Thin async wrapper around Anthropic's direct Messages API (api.anthropic.com),
used as an alternative AI backend (set AI_BACKEND=anthropic). A single
`sk-ant-...` API key, no cloud project/IAM/quota provisioning required --
unlike AWS Bedrock (IAM permissions) or the Gemini API (separate Cloud
project + quota grant), this just needs the key to exist and have credit.

Exposes the same call_claude_json() method name as bedrock_client.py,
gemini_client.py, and ollama_client.py (the default) so app/ai/service.py
can select any of the four backends without branching on which one is
active.
"""
import logging
from typing import Any, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class AnthropicClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.anthropic_api_key
        self._model_id = model_id if model_id is not None else settings.anthropic_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.anthropic_max_tokens

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
        """Forces Claude to respond via a single tool call matching json_schema
        (Anthropic's Messages API resolves standard JSON Schema $ref/$defs
        natively, so -- unlike gemini_client.py -- no schema flattening is
        needed here).
        """
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self._model_id,
            "max_tokens": max_tokens or self._max_tokens,
            "temperature": 0.1,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "tools": [
                {
                    "name": tool_name,
                    "description": "Emit the structured result for this analysis.",
                    "input_schema": json_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(_API_BASE, headers=headers, json=body)

        if response.status_code >= 400:
            logger.error("Anthropic Messages call failed: HTTP %s: %s", response.status_code, response.text)
            raise RuntimeError(f"Anthropic invocation failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        for block in payload.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == tool_name:
                return block["input"]

        raise RuntimeError(f"Anthropic response did not include the expected tool_use block: {payload}")


_singleton: Optional[AnthropicClient] = None


def get_anthropic_client() -> AnthropicClient:
    global _singleton
    if _singleton is None:
        _singleton = AnthropicClient()
    return _singleton
