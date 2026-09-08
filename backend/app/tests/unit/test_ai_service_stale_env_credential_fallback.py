"""Regression coverage for a real P1 bug: app/ai/service.py's _build_client()
passed `credentials.get(field)` straight into each cloud client's
constructor. Every client's __init__ resolves its argument with the pattern
`x if x is not None else settings.X` -- so a field simply ABSENT from an
explicit (non-None) runtime-config credentials dict (never entered via the
AI Providers UI, or cleared) came through as a bare `None`, indistinguishable
from "no override was given at all," and silently re-triggered the client's
OWN Settings/.env fallback.

Reproduced live: (1) a ProviderRuntimeConfig row for 'groq' exists (e.g. via
set_active_ai_backend('groq'), which the runtime AI-provider-activate API
calls with no requirement that credentials were ever entered) but its
decrypted credentials dict is `{}` -- get_active_ai_config() correctly
reports `configured: false` for this backend, matching what the AI Providers
panel shows; (2) GROQ_API_KEY is set in the process environment (a leftover
.env value from before this app moved to DB-backed runtime config, or simply
never-cleared); (3) _build_client("groq", {}, ...) still produced a client
with is_configured=True, silently authenticating with the stale
process-environment key -- a real divergence between what the admin UI
reports as configured and what credential live calls actually used.

Fix: app/ai/service.py's new _explicit_cred() helper normalizes a missing
credential field to "" (never None) before it reaches the client
constructor, on the explicit-credentials path. "" is not None, so the
client's `x if x is not None else settings.X` check uses "" as-is instead of
falling back to Settings -- and "" is falsy, so `is_configured` (every
client checks `bool(self._api_key)`) still correctly reports "not
configured," matching the runtime-config/UI layer's own view of this row.
"""
import pytest

from app.ai.service import _build_client, _get_ai_client


class _FakeSettingsWithStaleGroqKey:
    """Stands in for app.core.config.Settings, simulating a leftover/legacy
    GROQ_API_KEY in the process environment that was never entered through
    the runtime-configured AI Providers UI."""

    groq_api_key = "stale-env-key-never-entered-via-ui"
    groq_model_id = "llama-3.3-70b-versatile"
    groq_max_tokens = 4096


class _FakeSettingsWithStaleAnthropicKey:
    anthropic_api_key = "stale-anthropic-env-key"
    anthropic_model_id = "claude-3-5-sonnet-latest"
    anthropic_max_tokens = 4096


@pytest.mark.asyncio
async def test_groq_client_with_no_configured_credential_does_not_fall_back_to_stale_env_key(monkeypatch):
    """The exact reproduction: an explicit (non-None) credentials dict --
    e.g. {} from get_active_ai_config() for a backend that was activated but
    never had credentials entered -- must NOT let the client fall back to
    whatever is sitting in the process environment/.env."""
    import app.ai.groq_client as groq_client_module

    monkeypatch.setattr(groq_client_module, "get_settings", lambda: _FakeSettingsWithStaleGroqKey())

    client = await _build_client("groq", {}, None)

    assert client._api_key == "", "must not silently adopt the stale environment-variable key"
    assert client.is_configured is False, (
        "a backend with no credential entered via the runtime-config/UI layer must report "
        "not-configured, exactly like the AI Providers panel does for this row"
    )


@pytest.mark.asyncio
async def test_groq_client_with_real_configured_credential_still_uses_it(monkeypatch):
    """Sanity/no-regression check: an actually-configured credential (the
    normal, working case) must still be used as-is, not clobbered by this
    fix."""
    import app.ai.groq_client as groq_client_module

    monkeypatch.setattr(groq_client_module, "get_settings", lambda: _FakeSettingsWithStaleGroqKey())

    client = await _build_client("groq", {"api_key": "real-db-configured-key"}, None)

    assert client._api_key == "real-db-configured-key"
    assert client.is_configured is True


@pytest.mark.asyncio
async def test_anthropic_client_with_no_configured_credential_does_not_fall_back_to_stale_env_key(monkeypatch):
    """Same bug, different backend -- confirms the fix isn't groq-specific."""
    import app.ai.anthropic_client as anthropic_client_module

    monkeypatch.setattr(anthropic_client_module, "get_settings", lambda: _FakeSettingsWithStaleAnthropicKey())

    client = await _build_client("anthropic", {}, None)

    assert client._api_key == ""
    assert client.is_configured is False


@pytest.mark.asyncio
async def test_bedrock_client_with_no_configured_credentials_does_not_fall_back_to_stale_env_keys(monkeypatch):
    """Bedrock has three credential-shaped fields (bedrock_api_key,
    aws_access_key_id, aws_secret_access_key) -- all three must be covered,
    not just a single api_key field like the other backends."""
    import app.ai.bedrock_client as bedrock_client_module

    class _FakeBedrockSettings:
        bedrock_api_key = "stale-bedrock-bearer-token"
        aws_access_key_id = "stale-aws-access-key"
        aws_secret_access_key = "stale-aws-secret-key"
        aws_region = "us-east-1"
        bedrock_model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        bedrock_max_tokens = 4096

    monkeypatch.setattr(bedrock_client_module, "get_settings", lambda: _FakeBedrockSettings())
    monkeypatch.setattr(bedrock_client_module.boto3, "client", lambda *a, **kw: object())

    client = await _build_client("bedrock", {}, None)

    assert client.is_configured is False, (
        "must not report configured=True from stale env AWS credentials never entered via the UI"
    )


@pytest.mark.asyncio
async def test_get_ai_client_raises_not_configured_instead_of_using_stale_env_key(monkeypatch):
    """End-to-end version of the live repro in the confirmed finding:
    set_active_ai_backend('groq') with no credentials ever entered means
    get_active_ai_config() returns {'backend': 'groq', 'credentials': {},
    'model_id': None} -- _get_ai_client() must raise "not configured"
    (matching what the AI Providers panel shows), never silently succeed
    using a leftover environment-variable key."""
    import app.ai.groq_client as groq_client_module

    monkeypatch.setattr(groq_client_module, "get_settings", lambda: _FakeSettingsWithStaleGroqKey())

    async def _fake_get_active_ai_config():
        return {"backend": "groq", "credentials": {}, "model_id": None}

    monkeypatch.setattr("app.core.runtime_config.get_active_ai_config", _fake_get_active_ai_config)

    with pytest.raises(RuntimeError, match="not configured"):
        await _get_ai_client()
