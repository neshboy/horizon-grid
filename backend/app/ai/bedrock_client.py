"""Thin async wrapper around AWS Bedrock's Converse API for Claude models.

Kept separate from ai/service.py (which owns prompting/schema logic) so the
AWS auth and boto3 specifics are isolated in one place. If Anthropic's
direct API is ever added as an alternative, only this file needs a sibling
implementation behind the same call_claude_json() signature.

Supports two auth schemes:
  - Bedrock API key (bearer token): set AWS_BEARER_TOKEN_BEDROCK in the
    environment (via bedrock_api_key setting below) and omit
    aws_access_key_id/secret -- botocore's token provider chain picks this
    up automatically with no explicit wiring needed here. This is the
    scheme AWS's "Generate API key" button in IAM produces.
  - Classic SigV4 (IAM access key + secret) -- kept as a fallback for
    accounts that grant bedrock:InvokeModel via a normal IAM user/role
    instead of a bearer token.
"""
import asyncio
import json
import logging
import os
import threading
from typing import Any, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# botocore only ever reads a Bedrock bearer token from this process-global
# environment variable (there is no per-Session/per-client way to inject
# one -- see AWS's own documented usage, which sets this same env var).
# Real bug found live during overnight QA: this class used to set it once,
# permanently, in __init__ with no save/restore -- unlike the sibling
# connection-test code path (app/ai/connection_test.py's _check_bedrock),
# which correctly saves/restores it around a single throwaway call. A
# stale value from whatever candidate key was last tested (or the reverse:
# a real call clobbering a concurrent connection-test's throwaway value)
# could silently authenticate as the wrong identity. This lock (shared with
# connection_test.py) serializes every place in this codebase that touches
# AWS_BEARER_TOKEN_BEDROCK, and the token is only ever set for the
# duration of one real call, then restored, exactly like the test path.
BEARER_TOKEN_ENV_LOCK = threading.Lock()


class BedrockClaudeClient:
    def __init__(
        self,
        bedrock_api_key: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_region: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._model_id = model_id if model_id is not None else settings.bedrock_model_id
        self._max_tokens = max_tokens if max_tokens is not None else settings.bedrock_max_tokens
        bearer_token = bedrock_api_key if bedrock_api_key is not None else settings.bedrock_api_key
        access_key = aws_access_key_id if aws_access_key_id is not None else settings.aws_access_key_id
        secret_key = aws_secret_access_key if aws_secret_access_key is not None else settings.aws_secret_access_key
        region = aws_region if aws_region is not None else settings.aws_region
        self._configured = bool(bearer_token or (access_key and secret_key))
        self._bearer_token = bearer_token or None

        self._region = region
        if self._bearer_token:
            # Deliberately NOT constructed here. Whether botocore's bearer-
            # token credential provider resolves the env var at client-
            # construction time or lazily per-request is genuinely
            # ambiguous from the outside -- constructing a fresh client
            # inside _converse, while the lock holds the env var set,
            # covers both possibilities correctly rather than gambling on
            # one. The boto3.client() call itself is cheap.
            self._client: Optional[Any] = None
        else:
            session_kwargs: dict[str, Any] = {"region_name": region}
            if access_key and secret_key:
                session_kwargs["aws_access_key_id"] = access_key
                session_kwargs["aws_secret_access_key"] = secret_key
            self._client = boto3.client(
                "bedrock-runtime",
                config=BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"}),
                **session_kwargs,
            )

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def call_claude_json(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        tool_name: str = "emit_result",
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Forces Claude to respond via a single tool call matching json_schema,
        which is the most reliable way to get schema-conformant JSON out of a
        model without post-hoc regex extraction of a JSON blob from prose.
        """
        return await asyncio.to_thread(
            self._call_sync, system_prompt, user_prompt, json_schema, tool_name, max_tokens
        )

    def _call_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        tool_name: str,
        max_tokens: Optional[int],
    ) -> dict[str, Any]:
        tool_config = {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool_name,
                        "description": "Emit the structured result for this analysis.",
                        "inputSchema": {"json": json_schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": tool_name}},
        }
        # Bedrock API keys are short-lived, refreshable tokens by design (AWS's
        # own token-generator docs describe fetching a fresh one "before each
        # request") -- resolving/injecting it right before this specific call,
        # under a process-wide lock shared with the connection-test path, then
        # restoring immediately after, means neither a stale token nor a
        # concurrent connection-test's throwaway value can leak into or get
        # clobbered by a real call.
        if self._bearer_token:
            with BEARER_TOKEN_ENV_LOCK:
                restore_env = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
                os.environ["AWS_BEARER_TOKEN_BEDROCK"] = self._bearer_token
                try:
                    client = boto3.client(
                        "bedrock-runtime",
                        region_name=self._region,
                        config=BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"}),
                    )
                    response = self._converse(client, system_prompt, user_prompt, tool_config, max_tokens)
                finally:
                    if restore_env is None:
                        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
                    else:
                        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = restore_env
        else:
            response = self._converse(self._client, system_prompt, user_prompt, tool_config, max_tokens)

        for block in response["output"]["message"]["content"]:
            if "toolUse" in block and block["toolUse"]["name"] == tool_name:
                return block["toolUse"]["input"]

        raise RuntimeError("Bedrock response did not include the expected tool_use block")

    def _converse(self, client, system_prompt: str, user_prompt: str, tool_config: dict, max_tokens: Optional[int]) -> dict:
        try:
            return client.converse(
                modelId=self._model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={"maxTokens": max_tokens or self._max_tokens, "temperature": 0.1},
                toolConfig=tool_config,
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error("Bedrock Converse call failed: %s", exc)
            raise RuntimeError(f"Bedrock invocation failed: {exc}") from exc


_singleton: Optional[BedrockClaudeClient] = None


def get_bedrock_client() -> BedrockClaudeClient:
    global _singleton
    if _singleton is None:
        _singleton = BedrockClaudeClient()
    return _singleton
