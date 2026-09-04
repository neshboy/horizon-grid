"""Live "does this AI backend actually work" check -- the AI-backend analog
of app/providers/connection_test.py.

Investigation finding: none of the original five AI backends (Ollama,
Anthropic, Bedrock, Gemini, and Groq) had ANY live connection test before
this file existed -- the wizard's AI Configuration page collected keys with
no way to verify them before saving. This closes that gap for all of them
(now six, with OpenAI added) in one consistent mechanism, the same way
connection_test.py did for the intelligence providers.

Mirrors that same trust model exactly: every check below uses the
*candidate* credentials passed in the request, never app.core.config's
get_settings() singleton, and never persists anything. Each check makes one
minimal, real request to the backend's own API and reports what actually
happened -- never a fabricated/simulated latency, model name, or result.
"""
import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.ai.bedrock_client import BEARER_TOKEN_ENV_LOCK
from app.core.url_safety import assert_safe_outbound_url

_MINIMAL_SYSTEM = "You are a connection test. Reply with exactly one word: pong"
_MINIMAL_USER = "ping"


@dataclass
class AITestResult:
    ok: bool
    message: str
    model: Optional[str] = None
    latency_ms: Optional[int] = None


async def _timed(coro_factory) -> tuple[AITestResult, int]:
    start = time.monotonic()
    try:
        result = await coro_factory()
    except httpx.TimeoutException:
        return AITestResult(ok=False, message="Request timed out."), int((time.monotonic() - start) * 1000)
    except httpx.HTTPError as exc:
        return AITestResult(ok=False, message=f"Network error: {exc}"), int((time.monotonic() - start) * 1000)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the UI as a message, never a raw traceback
        return AITestResult(ok=False, message=f"{exc}"), int((time.monotonic() - start) * 1000)
    return result, int((time.monotonic() - start) * 1000)


async def _check_groq(api_key: str, model: str) -> AITestResult:
    if not api_key:
        return AITestResult(ok=False, message="No API key provided.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _MINIMAL_SYSTEM},
                    {"role": "user", "content": _MINIMAL_USER},
                ],
                "max_completion_tokens": 8,
                "temperature": 0,
            },
        )
    if r.status_code == 200:
        payload = r.json()
        reply = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=payload.get("model", model))
    if r.status_code == 401:
        return AITestResult(ok=False, message="Authentication failed -- check your Groq API key.")
    if r.status_code == 404:
        return AITestResult(ok=False, message=f"Model {model!r} was not found or is not available on this account.")
    if r.status_code == 429:
        return AITestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_openai(api_key: str, model: str) -> AITestResult:
    if not api_key:
        return AITestResult(ok=False, message="No API key provided.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _MINIMAL_SYSTEM},
                    {"role": "user", "content": _MINIMAL_USER},
                ],
                "max_completion_tokens": 8,
                "temperature": 0,
            },
        )
    if r.status_code == 200:
        payload = r.json()
        reply = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=payload.get("model", model))
    if r.status_code == 401:
        return AITestResult(ok=False, message="Authentication failed -- check your OpenAI API key.")
    if r.status_code == 404:
        return AITestResult(ok=False, message=f"Model {model!r} was not found or is not available on this account.")
    if r.status_code == 429:
        return AITestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_kimi(api_key: str, model: str) -> AITestResult:
    if not api_key:
        return AITestResult(ok=False, message="No API key provided.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.moonshot.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _MINIMAL_SYSTEM},
                    {"role": "user", "content": _MINIMAL_USER},
                ],
                "max_tokens": 8,
                "temperature": 0,
            },
        )
    if r.status_code == 200:
        payload = r.json()
        reply = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=payload.get("model", model))
    if r.status_code == 401:
        return AITestResult(ok=False, message="Authentication failed -- check your Kimi (Moonshot) API key.")
    if r.status_code == 404:
        return AITestResult(ok=False, message=f"Model {model!r} was not found or is not available on this account.")
    if r.status_code == 429:
        return AITestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    if r.status_code == 400 and "thinking" in r.text.lower():
        return AITestResult(
            ok=False,
            message=f"Model {model!r} requires disabling 'thinking' mode to use a forced tool call -- pick a non-reasoning model (e.g. kimi-k2.5) or a model where thinking can be disabled.",
        )
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_deepseek(api_key: str, model: str) -> AITestResult:
    if not api_key:
        return AITestResult(ok=False, message="No API key provided.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _MINIMAL_SYSTEM},
                    {"role": "user", "content": _MINIMAL_USER},
                ],
                "max_tokens": 8,
                "temperature": 0,
            },
        )
    if r.status_code == 200:
        payload = r.json()
        reply = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=payload.get("model", model))
    if r.status_code == 401:
        return AITestResult(ok=False, message="Authentication failed -- check your DeepSeek API key.")
    if r.status_code == 402:
        return AITestResult(ok=False, message="DeepSeek account balance is insufficient to make this request.")
    if r.status_code == 404:
        return AITestResult(ok=False, message=f"Model {model!r} was not found or is not available on this account.")
    if r.status_code == 429:
        return AITestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_xai(api_key: str, model: str) -> AITestResult:
    """xAI's error body is FLAT ({"code","error"}), not OpenAI's nested
    {"error":{"message"}} shape -- confirmed live against api.x.ai. The
    generic fallback below already just surfaces r.text, so this only needs
    special handling for the specific statuses worth a friendlier message."""
    if not api_key:
        return AITestResult(ok=False, message="No API key provided.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _MINIMAL_SYSTEM},
                    {"role": "user", "content": _MINIMAL_USER},
                ],
                "max_completion_tokens": 8,
                "temperature": 0,
            },
        )
    if r.status_code == 200:
        payload = r.json()
        reply = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=payload.get("model", model))
    if r.status_code in (400, 401):
        return AITestResult(ok=False, message="Authentication failed -- check your xAI (Grok) API key.")
    if r.status_code == 404:
        return AITestResult(ok=False, message=f"Model {model!r} was not found or is not available on this account.")
    if r.status_code == 429:
        return AITestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_mistral(api_key: str, model: str) -> AITestResult:
    if not api_key:
        return AITestResult(ok=False, message="No API key provided.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _MINIMAL_SYSTEM},
                    {"role": "user", "content": _MINIMAL_USER},
                ],
                "max_tokens": 8,
                "temperature": 0,
            },
        )
    if r.status_code == 200:
        payload = r.json()
        reply = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=payload.get("model", model))
    if r.status_code == 401:
        return AITestResult(ok=False, message="Authentication failed -- check your Mistral API key.")
    if r.status_code == 404:
        return AITestResult(ok=False, message=f"Model {model!r} was not found or is not available on this account.")
    if r.status_code == 429:
        return AITestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_openrouter(api_key: str, model: str) -> AITestResult:
    if not api_key:
        return AITestResult(ok=False, message="No API key provided.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _MINIMAL_SYSTEM},
                    {"role": "user", "content": _MINIMAL_USER},
                ],
                "max_tokens": 8,
                "temperature": 0,
            },
        )
    if r.status_code == 200:
        payload = r.json()
        reply = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=payload.get("model", model))
    if r.status_code == 401:
        return AITestResult(ok=False, message="Authentication failed -- check your OpenRouter API key.")
    if r.status_code == 402:
        return AITestResult(ok=False, message="OpenRouter account has insufficient credits for this request.")
    if r.status_code == 404:
        return AITestResult(ok=False, message=f"Model {model!r} was not found or is not available.")
    if r.status_code == 429:
        return AITestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_anthropic(api_key: str, model: str) -> AITestResult:
    if not api_key:
        return AITestResult(ok=False, message="No API key provided.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": model,
                "max_tokens": 8,
                "system": _MINIMAL_SYSTEM,
                "messages": [{"role": "user", "content": _MINIMAL_USER}],
            },
        )
    if r.status_code == 200:
        payload = r.json()
        reply = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=payload.get("model", model))
    if r.status_code == 401:
        return AITestResult(ok=False, message="Authentication failed -- check your Anthropic API key.")
    if r.status_code == 404:
        return AITestResult(ok=False, message=f"Model {model!r} was not found or is not available on this account.")
    if r.status_code == 429:
        return AITestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_gemini(api_key: str, model: str) -> AITestResult:
    if not api_key:
        return AITestResult(ok=False, message="No API key provided.")
    async with httpx.AsyncClient(timeout=20) as client:
        # Key goes in the x-goog-api-key header, not the ?key= query string --
        # httpx logs the full request URL at INFO level, which would
        # otherwise put the candidate key in plain text in the logs on every
        # Test Connection click.
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": _MINIMAL_USER}]}],
                "systemInstruction": {"parts": [{"text": _MINIMAL_SYSTEM}]},
                "generationConfig": {"maxOutputTokens": 8, "temperature": 0},
            },
        )
    if r.status_code == 200:
        payload = r.json()
        candidates = payload.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts") if candidates else []
        reply = "".join(p.get("text", "") for p in (parts or []))
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=model)
    if r.status_code in (400, 403):
        return AITestResult(ok=False, message="Authentication failed -- check your Gemini API key.")
    if r.status_code == 404:
        return AITestResult(ok=False, message=f"Model {model!r} was not found or is not available on this account.")
    if r.status_code == 429:
        return AITestResult(ok=False, message="Rate limited -- key may be valid, but too many requests right now.")
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_ollama(base_url: str, model: str) -> AITestResult:
    base_url = (base_url or "").rstrip("/")
    if not base_url or not model:
        return AITestResult(ok=False, message="Ollama base URL and model are both required.")
    try:
        assert_safe_outbound_url(base_url)
    except ValueError as exc:
        return AITestResult(ok=False, message=f"Refusing to connect to {base_url}: {exc}")
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _MINIMAL_SYSTEM},
                        {"role": "user", "content": _MINIMAL_USER},
                    ],
                    "stream": False,
                    "options": {"num_predict": 8, "temperature": 0},
                },
            )
        except httpx.ConnectError as exc:
            return AITestResult(ok=False, message=f"Could not reach Ollama at {base_url} -- is it running? ({exc})")
    if r.status_code == 200:
        payload = r.json()
        # Same null-vs-missing-key trap as ai_config.py's model listing:
        # `.get("message", {})`'s default only applies when the key is
        # absent. If Ollama (or a proxy in front of it) returns a literal
        # `{"message": null}`, `.get` returns None as-is, and chaining
        # `.get("content", "")` onto that raises an uncaught AttributeError.
        reply = (payload.get("message") or {}).get("content", "")
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=model)
    if r.status_code == 404:
        return AITestResult(
            ok=False,
            message=f"Model {model!r} is not pulled on this Ollama instance -- run `ollama pull {model}` first.",
        )
    return AITestResult(ok=False, message=f"Unexpected response (HTTP {r.status_code}): {r.text[:300]}")


async def _check_bedrock(credentials: dict[str, str], model: str) -> AITestResult:
    """Builds a throwaway boto3 client from the *candidate* credentials only
    -- never app.core.config's global Settings -- so testing a key the user
    just typed can never be confused with, or mutate, the backend's actual
    configured Bedrock session."""
    bearer_token = credentials.get("bedrock_api_key", "")
    access_key = credentials.get("aws_access_key_id", "")
    secret_key = credentials.get("aws_secret_access_key", "")
    region = credentials.get("aws_region") or "us-east-1"

    if not bearer_token and not (access_key and secret_key):
        return AITestResult(ok=False, message="Provide either a Bedrock API key (bearer token) or an AWS access key + secret.")

    # Real gap found live during overnight QA: this used boto3's SYNCHRONOUS
    # client.converse() directly inside an async function with no await --
    # every real network round-trip to AWS blocked the ENTIRE event loop
    # (every other concurrent request this worker was handling) for its
    # full duration, not just this connection test's own caller.
    return await asyncio.to_thread(_check_bedrock_sync, bearer_token, access_key, secret_key, region, model)


def _check_bedrock_sync(bearer_token: str, access_key: str, secret_key: str, region: str, model: str) -> AITestResult:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import BotoCoreError, ClientError

    session_kwargs: dict[str, str] = {"region_name": region}
    restore_env = None
    lock = BEARER_TOKEN_ENV_LOCK if bearer_token else None
    if lock:
        lock.acquire()
        restore_env = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bearer_token
    else:
        session_kwargs["aws_access_key_id"] = access_key
        session_kwargs["aws_secret_access_key"] = secret_key

    client = None
    try:
        client = boto3.client("bedrock-runtime", config=BotoConfig(retries={"max_attempts": 1}), **session_kwargs)
        response = client.converse(
            modelId=model,
            system=[{"text": _MINIMAL_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": _MINIMAL_USER}]}],
            inferenceConfig={"maxTokens": 8, "temperature": 0},
        )
        reply = "".join(b.get("text", "") for b in response["output"]["message"]["content"] if "text" in b)
        return AITestResult(ok=True, message=f"Connected. Model replied: {reply.strip()!r}", model=model)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("UnrecognizedClientException", "AccessDeniedException"):
            return AITestResult(ok=False, message="Authentication failed -- check your Bedrock credentials and IAM permissions.")
        if error_code == "ResourceNotFoundException":
            return AITestResult(ok=False, message=f"Model {model!r} was not found or is not enabled in this AWS account/region.")
        if error_code == "ThrottlingException":
            return AITestResult(ok=False, message="Rate limited -- credentials may be valid, but too many requests right now.")
        return AITestResult(ok=False, message=f"Bedrock error ({error_code}): {exc}")
    except BotoCoreError as exc:
        return AITestResult(ok=False, message=f"AWS SDK error: {exc}")
    finally:
        # Real gap found live during overnight QA: the boto3 client built
        # here (and its underlying connection pool) was never closed --
        # every connection test leaked one, however small, that never got
        # cleaned up for the life of the process.
        if client is not None:
            client.close()
        if lock:
            try:
                if restore_env is None:
                    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
                else:
                    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = restore_env
            finally:
                lock.release()


async def test_ai_connection(backend: str, credentials: dict[str, str], model: Optional[str] = None) -> AITestResult:
    """credentials keys vary by backend:
    - groq / openai / anthropic / gemini: {"api_key": "..."}
    - ollama: {"base_url": "..."}  (model passed separately)
    - bedrock: {"bedrock_api_key": "..."} OR {"aws_access_key_id": "...", "aws_secret_access_key": "...", "aws_region": "..."}
    """
    from app.ai import deepseek_client as _deepseek_defaults
    from app.ai import groq_client as _groq_defaults
    from app.ai import kimi_client as _kimi_defaults
    from app.ai import mistral_client as _mistral_defaults
    from app.ai import openai_client as _openai_defaults
    from app.ai import openrouter_client as _openrouter_defaults
    from app.ai import xai_client as _xai_defaults

    handlers = {
        "groq": lambda: _check_groq(credentials.get("api_key", ""), model or _groq_defaults.DEFAULT_MODEL),
        "openai": lambda: _check_openai(credentials.get("api_key", ""), model or _openai_defaults.DEFAULT_MODEL),
        "kimi": lambda: _check_kimi(credentials.get("api_key", ""), model or _kimi_defaults.DEFAULT_MODEL),
        "deepseek": lambda: _check_deepseek(credentials.get("api_key", ""), model or _deepseek_defaults.DEFAULT_MODEL),
        "xai": lambda: _check_xai(credentials.get("api_key", ""), model or _xai_defaults.DEFAULT_MODEL),
        "mistral": lambda: _check_mistral(credentials.get("api_key", ""), model or _mistral_defaults.DEFAULT_MODEL),
        "openrouter": lambda: _check_openrouter(credentials.get("api_key", ""), model or _openrouter_defaults.DEFAULT_MODEL),
        "anthropic": lambda: _check_anthropic(credentials.get("api_key", ""), model or "claude-sonnet-4-5-20250929"),
        "gemini": lambda: _check_gemini(credentials.get("api_key", ""), model or "gemini-2.0-flash"),
        "ollama": lambda: _check_ollama(credentials.get("base_url", ""), model or "llama3.2:3b"),
        "bedrock": lambda: _check_bedrock(credentials, model or "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    }
    handler = handlers.get(backend)
    if handler is None:
        return AITestResult(ok=False, message=f"Unknown AI backend {backend!r}.")

    result, elapsed_ms = await _timed(handler)
    result.latency_ms = elapsed_ms
    return result
