"""Unit tests for app.ai.connection_test -- the live AI-backend credential
check added to close the gap found during the API-configuration reliability
investigation (no AI backend had ANY connection test before this module
existed). All HTTP is mocked with respx; every credential value here is a
fake/mock string, never a real production key, per this fix's own security
rule (Phase 30 of API_CONFIGURATION_FIX_REPORT.md).
"""
import httpx
import pytest
import respx

from app.ai.connection_test import test_ai_connection as check_ai_connection


@pytest.mark.asyncio
async def test_unknown_backend_returns_ok_false_with_explanation():
    result = await check_ai_connection("grok", {"api_key": "mock-key"})  # "grok" (xAI), not "groq" -- must not be confused
    assert result.ok is False
    assert "Unknown AI backend" in result.message


@pytest.mark.asyncio
async def test_groq_no_key_fails_before_any_request():
    result = await check_ai_connection("groq", {})
    assert result.ok is False
    assert "No API key" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_groq_200_is_success_and_reports_model():
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "llama-3.3-70b-versatile",
                "choices": [{"message": {"content": "pong"}}],
            },
        )
    )
    result = await check_ai_connection("groq", {"api_key": "mock-groq-key"}, model="llama-3.3-70b-versatile")
    assert result.ok is True
    assert result.model == "llama-3.3-70b-versatile"
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_groq_401_is_auth_failure():
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(401))
    result = await check_ai_connection("groq", {"api_key": "mock-invalid-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_groq_404_is_reported_as_model_not_found():
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(404))
    result = await check_ai_connection("groq", {"api_key": "mock-key"}, model="nonexistent-model-xyz")
    assert result.ok is False
    assert "not found" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_groq_429_is_rate_limited():
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(429))
    result = await check_ai_connection("groq", {"api_key": "mock-key"})
    assert result.ok is False
    assert "Rate limited" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_groq_network_timeout_is_reported_cleanly():
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(side_effect=httpx.TimeoutException("timed out"))
    result = await check_ai_connection("groq", {"api_key": "mock-key"})
    assert result.ok is False
    assert "timed out" in result.message.lower()


@pytest.mark.asyncio
async def test_openai_no_key_fails_before_any_request():
    result = await check_ai_connection("openai", {})
    assert result.ok is False
    assert "No API key" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_openai_200_is_success_and_reports_model():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": "pong"}}],
            },
        )
    )
    result = await check_ai_connection("openai", {"api_key": "mock-openai-key"}, model="gpt-4o-mini")
    assert result.ok is True
    assert result.model == "gpt-4o-mini"
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_openai_401_is_auth_failure():
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(401))
    result = await check_ai_connection("openai", {"api_key": "mock-invalid-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_openai_404_is_reported_as_model_not_found():
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(404))
    result = await check_ai_connection("openai", {"api_key": "mock-key"}, model="nonexistent-model-xyz")
    assert result.ok is False
    assert "not found" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_openai_429_is_rate_limited():
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(429))
    result = await check_ai_connection("openai", {"api_key": "mock-key"})
    assert result.ok is False
    assert "Rate limited" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_openai_network_timeout_is_reported_cleanly():
    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=httpx.TimeoutException("timed out"))
    result = await check_ai_connection("openai", {"api_key": "mock-key"})
    assert result.ok is False
    assert "timed out" in result.message.lower()


@pytest.mark.asyncio
async def test_kimi_no_key_fails_before_any_request():
    result = await check_ai_connection("kimi", {})
    assert result.ok is False
    assert "No API key" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_kimi_200_is_success_and_reports_model():
    respx.post("https://api.moonshot.ai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"model": "kimi-k2.5", "choices": [{"message": {"content": "pong"}}]},
        )
    )
    result = await check_ai_connection("kimi", {"api_key": "mock-kimi-key"}, model="kimi-k2.5")
    assert result.ok is True
    assert result.model == "kimi-k2.5"
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_kimi_401_is_auth_failure():
    respx.post("https://api.moonshot.ai/v1/chat/completions").mock(return_value=httpx.Response(401))
    result = await check_ai_connection("kimi", {"api_key": "mock-invalid-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_kimi_404_is_reported_as_model_not_found():
    respx.post("https://api.moonshot.ai/v1/chat/completions").mock(return_value=httpx.Response(404))
    result = await check_ai_connection("kimi", {"api_key": "mock-key"}, model="nonexistent-model-xyz")
    assert result.ok is False
    assert "not found" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_kimi_429_is_rate_limited():
    respx.post("https://api.moonshot.ai/v1/chat/completions").mock(return_value=httpx.Response(429))
    result = await check_ai_connection("kimi", {"api_key": "mock-key"})
    assert result.ok is False
    assert "Rate limited" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_kimi_400_thinking_conflict_is_reported_clearly():
    respx.post("https://api.moonshot.ai/v1/chat/completions").mock(
        return_value=httpx.Response(400, text="tool_choice 'specified' is incompatible with thinking enabled")
    )
    result = await check_ai_connection("kimi", {"api_key": "mock-key"}, model="kimi-k3")
    assert result.ok is False
    assert "thinking" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_kimi_network_timeout_is_reported_cleanly():
    respx.post("https://api.moonshot.ai/v1/chat/completions").mock(side_effect=httpx.TimeoutException("timed out"))
    result = await check_ai_connection("kimi", {"api_key": "mock-key"})
    assert result.ok is False
    assert "timed out" in result.message.lower()


@pytest.mark.asyncio
async def test_deepseek_no_key_fails_before_any_request():
    result = await check_ai_connection("deepseek", {})
    assert result.ok is False
    assert "No API key" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_deepseek_200_is_success_and_reports_model():
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"model": "deepseek-v4-flash", "choices": [{"message": {"content": "pong"}}]},
        )
    )
    result = await check_ai_connection("deepseek", {"api_key": "mock-deepseek-key"}, model="deepseek-v4-flash")
    assert result.ok is True
    assert result.model == "deepseek-v4-flash"
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_deepseek_401_is_auth_failure():
    respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(401))
    result = await check_ai_connection("deepseek", {"api_key": "mock-invalid-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_deepseek_402_is_reported_as_insufficient_balance():
    respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(402))
    result = await check_ai_connection("deepseek", {"api_key": "mock-key"})
    assert result.ok is False
    assert "balance" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_deepseek_429_is_rate_limited():
    respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(429))
    result = await check_ai_connection("deepseek", {"api_key": "mock-key"})
    assert result.ok is False
    assert "Rate limited" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_deepseek_network_timeout_is_reported_cleanly():
    respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=httpx.TimeoutException("timed out"))
    result = await check_ai_connection("deepseek", {"api_key": "mock-key"})
    assert result.ok is False
    assert "timed out" in result.message.lower()


@pytest.mark.asyncio
async def test_xai_no_key_fails_before_any_request():
    result = await check_ai_connection("xai", {})
    assert result.ok is False
    assert "No API key" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_xai_200_is_success_and_reports_model():
    respx.post("https://api.x.ai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"model": "grok-4.6", "choices": [{"message": {"content": "pong"}}]},
        )
    )
    result = await check_ai_connection("xai", {"api_key": "mock-xai-key"}, model="grok-4.6")
    assert result.ok is True
    assert result.model == "grok-4.6"
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_xai_401_is_auth_failure():
    # xAI's real error body is flat ({"code","error"}), not OpenAI's nested
    # shape -- this test only checks the status-code branch, not body parsing.
    respx.post("https://api.x.ai/v1/chat/completions").mock(return_value=httpx.Response(401))
    result = await check_ai_connection("xai", {"api_key": "mock-invalid-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_xai_400_bad_key_is_reported_as_auth_failure():
    # xAI returns 400 (not 401) for a malformed/incorrect key, confirmed live.
    respx.post("https://api.x.ai/v1/chat/completions").mock(return_value=httpx.Response(400))
    result = await check_ai_connection("xai", {"api_key": "mock-bad-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_xai_429_is_rate_limited():
    respx.post("https://api.x.ai/v1/chat/completions").mock(return_value=httpx.Response(429))
    result = await check_ai_connection("xai", {"api_key": "mock-key"})
    assert result.ok is False
    assert "Rate limited" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_xai_network_timeout_is_reported_cleanly():
    respx.post("https://api.x.ai/v1/chat/completions").mock(side_effect=httpx.TimeoutException("timed out"))
    result = await check_ai_connection("xai", {"api_key": "mock-key"})
    assert result.ok is False
    assert "timed out" in result.message.lower()


@pytest.mark.asyncio
async def test_mistral_no_key_fails_before_any_request():
    result = await check_ai_connection("mistral", {})
    assert result.ok is False
    assert "No API key" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_mistral_200_is_success_and_reports_model():
    respx.post("https://api.mistral.ai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"model": "mistral-small-2506", "choices": [{"message": {"content": "pong"}}]},
        )
    )
    result = await check_ai_connection("mistral", {"api_key": "mock-mistral-key"}, model="mistral-small-2506")
    assert result.ok is True
    assert result.model == "mistral-small-2506"
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_mistral_401_is_auth_failure():
    respx.post("https://api.mistral.ai/v1/chat/completions").mock(return_value=httpx.Response(401))
    result = await check_ai_connection("mistral", {"api_key": "mock-invalid-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_mistral_404_is_reported_as_model_not_found():
    respx.post("https://api.mistral.ai/v1/chat/completions").mock(return_value=httpx.Response(404))
    result = await check_ai_connection("mistral", {"api_key": "mock-key"}, model="nonexistent-model-xyz")
    assert result.ok is False
    assert "not found" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_mistral_429_is_rate_limited():
    respx.post("https://api.mistral.ai/v1/chat/completions").mock(return_value=httpx.Response(429))
    result = await check_ai_connection("mistral", {"api_key": "mock-key"})
    assert result.ok is False
    assert "Rate limited" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_mistral_network_timeout_is_reported_cleanly():
    respx.post("https://api.mistral.ai/v1/chat/completions").mock(side_effect=httpx.TimeoutException("timed out"))
    result = await check_ai_connection("mistral", {"api_key": "mock-key"})
    assert result.ok is False
    assert "timed out" in result.message.lower()


@pytest.mark.asyncio
async def test_openrouter_no_key_fails_before_any_request():
    result = await check_ai_connection("openrouter", {})
    assert result.ok is False
    assert "No API key" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_200_is_success_and_reports_model():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"model": "openai/gpt-4o", "choices": [{"message": {"content": "pong"}}]},
        )
    )
    result = await check_ai_connection("openrouter", {"api_key": "mock-openrouter-key"}, model="openai/gpt-4o")
    assert result.ok is True
    assert result.model == "openai/gpt-4o"
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_401_is_auth_failure():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(return_value=httpx.Response(401))
    result = await check_ai_connection("openrouter", {"api_key": "mock-invalid-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_402_is_reported_as_insufficient_credits():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(return_value=httpx.Response(402))
    result = await check_ai_connection("openrouter", {"api_key": "mock-key"})
    assert result.ok is False
    assert "credits" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_429_is_rate_limited():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(return_value=httpx.Response(429))
    result = await check_ai_connection("openrouter", {"api_key": "mock-key"})
    assert result.ok is False
    assert "Rate limited" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_network_timeout_is_reported_cleanly():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(side_effect=httpx.TimeoutException("timed out"))
    result = await check_ai_connection("openrouter", {"api_key": "mock-key"})
    assert result.ok is False
    assert "timed out" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_200_is_success():
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200, json={"model": "claude-sonnet-4-5-20250929", "content": [{"type": "text", "text": "pong"}]}
        )
    )
    result = await check_ai_connection("anthropic", {"api_key": "mock-anthropic-key"})
    assert result.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_401_is_auth_failure():
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(401))
    result = await check_ai_connection("anthropic", {"api_key": "mock-bad-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_gemini_200_is_success():
    respx.post(url__regex=r"https://generativelanguage\.googleapis\.com/.*").mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "pong"}]}}]}
        )
    )
    result = await check_ai_connection("gemini", {"api_key": "mock-gemini-key"})
    assert result.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_gemini_403_is_auth_failure():
    respx.post(url__regex=r"https://generativelanguage\.googleapis\.com/.*").mock(return_value=httpx.Response(403))
    result = await check_ai_connection("gemini", {"api_key": "mock-bad-key"})
    assert result.ok is False
    assert "Authentication failed" in result.message


@pytest.mark.asyncio
async def test_ollama_missing_base_url_fails_before_any_request():
    result = await check_ai_connection("ollama", {"base_url": ""}, model="llama3.2:3b")
    assert result.ok is False
    assert "required" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_ollama_200_is_success():
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "pong"}})
    )
    result = await check_ai_connection("ollama", {"base_url": "http://localhost:11434"}, model="llama3.2:3b")
    assert result.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_ollama_model_not_pulled_is_clear_error():
    respx.post("http://localhost:11434/api/chat").mock(return_value=httpx.Response(404))
    result = await check_ai_connection("ollama", {"base_url": "http://localhost:11434"}, model="nonexistent:1b")
    assert result.ok is False
    assert "ollama pull" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_ollama_literal_null_message_does_not_crash():
    # Real-world finding: some Ollama versions/proxies return a literal
    # `{"message": null}` instead of omitting the key or using `{}`.
    # `.get("message", {})`'s default only applies when the key is absent,
    # so this used to raise an uncaught AttributeError instead of a clean
    # AITestResult.
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(200, json={"message": None})
    )
    result = await check_ai_connection("ollama", {"base_url": "http://localhost:11434"}, model="llama3.2:3b")
    assert result.ok is True
    assert result.message  # doesn't crash; reply is just empty


@pytest.mark.asyncio
async def test_ollama_connect_error_is_reported_cleanly():
    # Deliberately unreachable port -- exercises the real httpx.ConnectError
    # path without needing respx (no mock installed, so the connection
    # genuinely fails at the TCP layer). Must be Ollama's real default port
    # (11434), not an arbitrary one like ":1" -- url_safety.
    # assert_safe_outbound_url() now rejects any OTHER port on a
    # private/loopback address (see test_url_safety_ollama_port_scan.py),
    # specifically to stop this same base_url field being used to port-scan
    # this app's own internal services, so an arbitrary "obviously
    # unreachable" port would now be refused by that check before ever
    # reaching the network layer -- 11434 is still genuinely unreachable in
    # the test environment (nothing listens on it inside the backend
    # container) while staying a realistic, allowed Ollama address.
    result = await check_ai_connection("ollama", {"base_url": "http://localhost:11434"}, model="llama3.2:3b")
    assert result.ok is False
    assert "reach ollama" in result.message.lower()


@pytest.mark.asyncio
async def test_bedrock_no_credentials_fails_before_any_request():
    result = await check_ai_connection("bedrock", {}, model="anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert result.ok is False
    assert "Bedrock API key" in result.message or "AWS access key" in result.message


@pytest.mark.asyncio
async def test_bedrock_connection_test_closes_the_client_it_builds():
    """Real gap found live during overnight QA: the boto3 client (and its
    underlying connection pool) built for a live connection test was never
    closed -- every test run leaked one for the life of the process."""
    import os
    from unittest.mock import MagicMock, patch

    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "pong"}]}}
    }
    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
    with patch("boto3.client", return_value=fake_client):
        result = await check_ai_connection(
            "bedrock", {"bedrock_api_key": "candidate-token", "aws_region": "us-east-1"},
            model="anthropic.claude-sonnet-4-5-20250929-v1:0",
        )
    assert result.ok is True
    fake_client.close.assert_called_once()
    assert "AWS_BEARER_TOKEN_BEDROCK" not in os.environ


@pytest.mark.asyncio
async def test_bedrock_connection_test_does_not_clobber_a_concurrently_configured_real_token():
    """Real gap found live during overnight QA: this and the real
    BedrockClaudeClient both mutate the same process-global env var with no
    coordination -- a connection test's restore-to-None could stomp on a
    real, concurrently-active token. Simulates "a real token is already
    live" by pre-setting the env var to something else and confirming the
    connection test restores exactly that value afterward, not None."""
    import os
    from unittest.mock import MagicMock, patch

    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = "the-real-live-token"
    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "pong"}]}}
    }
    try:
        with patch("boto3.client", return_value=fake_client):
            result = await check_ai_connection(
                "bedrock", {"bedrock_api_key": "candidate-token", "aws_region": "us-east-1"},
                model="anthropic.claude-sonnet-4-5-20250929-v1:0",
            )
        assert result.ok is True
        assert os.environ.get("AWS_BEARER_TOKEN_BEDROCK") == "the-real-live-token"
    finally:
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
