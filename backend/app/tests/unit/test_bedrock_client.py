"""Unit tests for app.ai.bedrock_client -- specifically the bearer-token
("Bedrock API key") environment-variable handling. Real bugs found live
during overnight QA: this client used to set AWS_BEARER_TOKEN_BEDROCK once,
permanently, in __init__, with no save/restore -- unlike the sibling
connection-test code path (app/ai/connection_test.py's _check_bedrock),
which already did this correctly. Every real network call is mocked (via
a fake boto3 client substituted in for boto3.client) -- no real AWS calls
are ever made here.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from app.ai.bedrock_client import BedrockClaudeClient


def _fake_response(text: str = "ok") -> dict:
    return {
        "output": {
            "message": {
                "content": [{"toolUse": {"name": "emit_result", "input": {"text": text}}}]
            }
        }
    }


@pytest.mark.asyncio
async def test_bearer_token_is_not_set_into_the_environment_at_construction_time():
    """Real bug found live during overnight QA: constructing this client
    used to immediately, permanently mutate os.environ, whether or not a
    real call was ever made."""
    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
    with patch("app.ai.bedrock_client.boto3.client") as mock_boto_client:
        BedrockClaudeClient(bedrock_api_key="candidate-token", aws_region="us-east-1")
        assert "AWS_BEARER_TOKEN_BEDROCK" not in os.environ
        mock_boto_client.assert_not_called()  # bearer-token path builds its client lazily, per call


@pytest.mark.asyncio
async def test_bearer_token_is_set_only_for_the_duration_of_a_real_call_then_restored():
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = "pre-existing-value"
    seen_token_during_call = {}

    def fake_boto_client(*args, **kwargs):
        seen_token_during_call["value"] = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        client = MagicMock()
        client.converse.return_value = _fake_response()
        return client

    try:
        with patch("app.ai.bedrock_client.boto3.client", side_effect=fake_boto_client):
            client = BedrockClaudeClient(bedrock_api_key="candidate-token", aws_region="us-east-1")
            result = await client.call_claude_json("system", "user", {"type": "object"})
        assert result == {"text": "ok"}
        assert seen_token_during_call["value"] == "candidate-token"
        # Real bug found live during overnight QA: this must be restored to
        # whatever it was before the call, not left at the candidate value.
        assert os.environ.get("AWS_BEARER_TOKEN_BEDROCK") == "pre-existing-value"
    finally:
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)


@pytest.mark.asyncio
async def test_bearer_token_env_var_is_restored_even_if_the_call_raises():
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = "pre-existing-value"

    def fake_boto_client(*args, **kwargs):
        client = MagicMock()
        client.converse.side_effect = RuntimeError("boom")
        return client

    try:
        with patch("app.ai.bedrock_client.boto3.client", side_effect=fake_boto_client):
            client = BedrockClaudeClient(bedrock_api_key="candidate-token", aws_region="us-east-1")
            with pytest.raises(Exception):
                await client.call_claude_json("system", "user", {"type": "object"})
        assert os.environ.get("AWS_BEARER_TOKEN_BEDROCK") == "pre-existing-value"
    finally:
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)


@pytest.mark.asyncio
async def test_access_key_auth_path_never_touches_the_environment():
    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
    with patch("app.ai.bedrock_client.boto3.client") as mock_boto_client:
        fake_client = MagicMock()
        fake_client.converse.return_value = _fake_response()
        mock_boto_client.return_value = fake_client

        client = BedrockClaudeClient(
            aws_access_key_id="AKIA...", aws_secret_access_key="secret", aws_region="us-east-1"
        )
        # Built eagerly (no ambiguity about env-var timing for this path).
        mock_boto_client.assert_called_once()
        result = await client.call_claude_json("system", "user", {"type": "object"})
        assert result == {"text": "ok"}
        assert "AWS_BEARER_TOKEN_BEDROCK" not in os.environ
