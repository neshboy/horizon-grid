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
from typing import Any, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


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

        session_kwargs: dict[str, Any] = {"region_name": region}
        if bearer_token:
            # botocore resolves this from the environment for the
            # "bedrock" signing name (AWS_BEARER_TOKEN_BEDROCK) -- setting
            # it here (rather than requiring it pre-set in the container
            # env) keeps all Bedrock config in one place: this app's Settings.
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bearer_token
        elif access_key and secret_key:
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
        try:
            response = self._client.converse(
                modelId=self._model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={"maxTokens": max_tokens or self._max_tokens, "temperature": 0.1},
                toolConfig=tool_config,
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error("Bedrock Converse call failed: %s", exc)
            raise RuntimeError(f"Bedrock invocation failed: {exc}") from exc

        for block in response["output"]["message"]["content"]:
            if "toolUse" in block and block["toolUse"]["name"] == tool_name:
                return block["toolUse"]["input"]

        raise RuntimeError("Bedrock response did not include the expected tool_use block")


_singleton: Optional[BedrockClaudeClient] = None


def get_bedrock_client() -> BedrockClaudeClient:
    global _singleton
    if _singleton is None:
        _singleton = BedrockClaudeClient()
    return _singleton
