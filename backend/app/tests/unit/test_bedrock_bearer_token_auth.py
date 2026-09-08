"""Regression coverage for a confirmed P1 bug: Bedrock "API key" (bearer
token) authentication -- the auth method listed FIRST in the AI Providers
wizard and documented in bedrock_client.py as "preferred over access
key/secret" -- was completely non-functional. It failed with a misleading
`NoCredentialsError: Unable to locate credentials` for ANY bearer token,
valid or not, before ever making a network call.

Root cause: bedrock_client.py's __init__ sets AWS_BEARER_TOKEN_BEDROCK in the
process environment and relies on botocore to auto-detect it as a Bedrock
credential (this is the correct, documented mechanism -- see AWS's "Bedrock
API keys" feature). But requirements.txt pinned boto3==1.35.24 (botocore
1.35.99), a version released before AWS/botocore added ANY bearer-token
support for Bedrock (confirmed: zero occurrences of AWS_BEARER_TOKEN_BEDROCK
in that botocore build, and no bearer-token credential provider registered
for the Bedrock signing name). So the env var was simply never consulted,
and boto3 fell straight through to "no credentials at all."

botocore first gained this feature in 1.39.0 (generic env-var-scoped bearer
token support) and fixed a related over-broad-application bug in 1.39.12
(bearer auth was being applied to every service sharing the "bedrock"
signing name, not just ones whose service model declares
`smithy.api#httpBearerAuth`). Fix: bump the pinned boto3 (which pulls in a
compatible botocore) to >=1.39.12 -- no application code change was needed,
since bedrock_client.py's env-var mechanism was always the officially
documented approach; it just needed an SDK version that implements it.

These tests intentionally do NOT mock boto3/botocore -- the whole point is
to exercise the *real* credential-resolution chain shipped in
requirements.txt. To stay hermetic (no real AWS account/network dependency,
deterministic, fast), they redirect the bedrock-runtime endpoint to an
address nothing listens on (botocore's generic `AWS_ENDPOINT_URL_<SERVICE>`
env var override) -- this makes the test assert exactly the property that
matters: did credential resolution succeed (any failure is now a *network*
failure, past the point credentials were needed), not whether a fake token
happens to be accepted by AWS.
"""
import os

import pytest
from botocore.exceptions import EndpointConnectionError, NoCredentialsError

from app.ai.bedrock_client import BedrockClaudeClient


@pytest.fixture
def unroutable_bedrock_endpoint(monkeypatch):
    """Points the real bedrock-runtime client at an address nothing listens
    on, so a real (mocked-nowhere) HTTP attempt fails fast and deterministically
    with a connection error instead of reaching out to actual AWS -- while
    still exercising botocore's real credential-resolution chain."""
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "https://127.0.0.1:1")
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)


def test_bedrock_bearer_token_is_actually_recognized_as_credentials(
    unroutable_bedrock_endpoint, monkeypatch
):
    """The exact confirmed-finding repro, through the real application code
    path (BedrockClaudeClient), not a hand-rolled boto3 call: constructing
    the client with only a bearer token (no access key/secret) must result
    in botocore treating that token as valid credentials. If it doesn't,
    calling converse() raises NoCredentialsError *before* any network
    attempt -- exactly the bug. If it does, the call still fails (nothing is
    listening at the redirected endpoint), but with a network-layer error,
    proving credential resolution succeeded first.
    """
    client = BedrockClaudeClient(
        bedrock_api_key="fake-test-bearer-token-for-regression-check",
        aws_region="us-east-1",
    )
    assert client.is_configured is True

    with pytest.raises(RuntimeError) as exc_info:
        client._call_sync(
            system_prompt="sys",
            user_prompt="hi",
            json_schema={"type": "object", "properties": {}},
            tool_name="emit_result",
            max_tokens=8,
        )

    # _call_sync wraps BotoCoreError/ClientError in RuntimeError -- inspect the
    # original cause to tell "credentials were never even resolved" (the bug)
    # apart from "credentials resolved fine, network call failed" (fixed).
    cause = exc_info.value.__cause__
    assert not isinstance(cause, NoCredentialsError), (
        "botocore failed to recognize AWS_BEARER_TOKEN_BEDROCK as valid credentials -- "
        "this is the P1 regression where Bedrock bearer-token auth was completely "
        "non-functional with the pinned boto3/botocore version, regardless of token validity"
    )
    assert isinstance(cause, EndpointConnectionError), (
        f"expected a network-layer failure past credential resolution, got {type(cause).__name__}: {cause}"
    )


def test_bedrock_access_key_auth_still_works_unaffected(unroutable_bedrock_endpoint):
    """No-regression check: the classic SigV4 access-key/secret path (which
    never depended on the broken bearer-token mechanism) must still behave
    the same after the boto3/botocore version bump."""
    client = BedrockClaudeClient(
        aws_access_key_id="fake-access-key",
        aws_secret_access_key="fake-secret-key",
        aws_region="us-east-1",
    )
    assert client.is_configured is True

    with pytest.raises(RuntimeError) as exc_info:
        client._call_sync(
            system_prompt="sys",
            user_prompt="hi",
            json_schema={"type": "object", "properties": {}},
            tool_name="emit_result",
            max_tokens=8,
        )

    cause = exc_info.value.__cause__
    assert isinstance(cause, EndpointConnectionError), (
        f"expected a network-layer failure past credential resolution, got {type(cause).__name__}: {cause}"
    )


def test_bedrock_bearer_token_credential_alone_is_considered_configured(unroutable_bedrock_endpoint):
    """A bearer token alone (no access key/secret) must be considered
    configured. Superseded coverage note: an earlier version of this test
    asserted AWS_BEARER_TOKEN_BEDROCK was set in os.environ immediately on
    construction -- that was true before a later fix (env-var mutation is
    now scoped to only exist for the duration of a real call, with
    save/restore, so a live connection test and a real call can't clobber
    each other's credentials; see bedrock_client.py's own docstring on
    _call_sync). This test's actual regression coverage (bearer-token-only
    construction resolving as real credentials past the network layer) is
    already fully exercised by test_bedrock_bearer_token_is_actually_recognized_as_credentials
    above."""
    client = BedrockClaudeClient(bedrock_api_key="my-bearer-token", aws_region="us-east-1")

    assert client.is_configured is True
