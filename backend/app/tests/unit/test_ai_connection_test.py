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
async def test_ollama_connect_error_is_reported_cleanly():
    # Deliberately unreachable port -- exercises the real httpx.ConnectError
    # path without needing respx (no mock installed, so the connection
    # genuinely fails at the TCP layer).
    result = await check_ai_connection("ollama", {"base_url": "http://localhost:1"}, model="llama3.2:3b")
    assert result.ok is False
    assert "reach ollama" in result.message.lower()


@pytest.mark.asyncio
async def test_bedrock_no_credentials_fails_before_any_request():
    result = await check_ai_connection("bedrock", {}, model="anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert result.ok is False
    assert "Bedrock API key" in result.message or "AWS access key" in result.message
