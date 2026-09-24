"""Regression test for a real P1 bug found live during overnight QA:
app.ai.ollama_client's call_claude_json() never set num_ctx, so Ollama
0.33.0's default behavior sized the KV-cache to the MODEL's own trained
maximum context (131072 tokens for Llama 3.2) rather than the prompt --
confirmed live via `ollama ps` that one ordinary investigation turned a
2GB model into an 18GB resident allocation, with host free RAM dropping
into the 600MB-1.8GB range on a 16GB host. _estimate_num_ctx caps this to
something sane for a summarization-sized prompt.
"""
import pytest

import app.ai.ollama_client as ollama_client_module
from app.ai.ollama_client import _MAX_NUM_CTX, _MIN_NUM_CTX, OllamaClient, _estimate_num_ctx


class _FakeChatResponse:
    status_code = 200

    def json(self):
        return {"message": {"content": '{"ok": true}'}}


class _OptionsRecordingAsyncClient:
    """Stand-in for httpx.AsyncClient that records the real request body
    call_claude_json() sends, then answers with a canned valid response --
    so the real call_claude_json() code path (including building
    `options["num_ctx"]` via _estimate_num_ctx, which is exactly what the
    original P1 bug this file regression-tests omitted entirely) actually
    runs, without any real network I/O.
    """

    last_body = None

    def __init__(self, timeout=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        _OptionsRecordingAsyncClient.last_body = json
        return _FakeChatResponse()


@pytest.mark.asyncio
async def test_call_claude_json_actually_wires_num_ctx_into_the_real_request(monkeypatch):
    """The three tests below confirm _estimate_num_ctx computes sane values
    in isolation, but the real bug was that call_claude_json() never put
    num_ctx into the request at all -- a pure-function test of the helper
    can never catch that wiring being dropped again. This drives the actual
    call_claude_json() call path (like test_ollama_timeout.py does for the
    timeout fix) and asserts on the literal request body that would be sent
    to Ollama.
    """
    monkeypatch.setattr(ollama_client_module.httpx, "AsyncClient", _OptionsRecordingAsyncClient)

    client = await OllamaClient.create(base_url="http://127.0.0.1:11434", model="llama3.2:3b")
    await client.call_claude_json(
        system_prompt="short system prompt",
        user_prompt="IOC: 8.8.8.8",
        json_schema={"type": "object"},
        max_tokens=512,
    )

    sent_options = _OptionsRecordingAsyncClient.last_body["options"]
    assert "num_ctx" in sent_options
    assert sent_options["num_ctx"] == _estimate_num_ctx(
        "short system prompt", "IOC: 8.8.8.8", response_budget=512
    )
    assert sent_options["num_ctx"] < 131072  # nowhere near the model's full trained context


def test_short_prompt_uses_the_minimum_not_the_models_full_context():
    result = _estimate_num_ctx("short system prompt", "IOC: 8.8.8.8", response_budget=512)
    assert result == _MIN_NUM_CTX
    assert result < 131072  # nowhere near a real model's trained max context


def test_long_prompt_scales_up_but_stays_bounded():
    huge_prompt = "x" * 100_000
    result = _estimate_num_ctx("system", huge_prompt, response_budget=512)
    assert result == _MAX_NUM_CTX  # capped, never unbounded


def test_medium_prompt_scales_between_the_bounds():
    medium_prompt = "x" * 9000  # ~3000 estimated tokens
    result = _estimate_num_ctx("system", medium_prompt, response_budget=1000)
    assert _MIN_NUM_CTX < result < _MAX_NUM_CTX
