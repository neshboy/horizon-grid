"""Regression test for a real P1 bug found via live testing against the
dev stack's actual Ollama instance (llama3.2:3b, confirmed CPU-only via
`size_vram: 0` in Ollama's own /api/ps): app.ai.ollama_client's
call_claude_json() hardcoded a 120s httpx timeout
(_TIMEOUT_SECONDS/OllamaClient.__init__), justified by a comment claiming
"a model sized to fit fully in VRAM responds in seconds". That assumption
does not hold for this backend's own default deployment target -- CPU-only
inference is the whole point of a "no GPU required" local backend, and
Ollama's default idle-unload behavior means the first call after any idle
period pays a full model reload (measured live at 62.8s and 78.8s on two
separate cold loads) before generation (measured live at ~4.7 tokens/sec)
even starts.

Live reproduction: calling OllamaClient().call_claude_json() with the exact
system/user-prompt shape and max_tokens=8192 that
app/ai/service.py:generate_final_assessment() sends raised
`RuntimeError("Ollama did not respond within 120s ...")` at the 120s
cutoff. Removing the artificial cutoff (raw httpx call, same body/options,
600s timeout) showed the identical request completing successfully with
valid JSON in 187s (`done_reason: "stop"`) -- proving the request was
genuinely working the whole time and only needed ~67 more seconds.
app/ai/service.py's retry loop (lines ~620-718) only retries
pydantic.ValidationError; this RuntimeError instead falls into the generic
`except Exception: break`, so there was no second attempt either -- the
investigation's final AI assessment permanently degraded to "AI-generated
assessment unavailable (generation error)" even though the exact same
request would have produced a real, valid assessment about a minute later.

Fixed by raising the default to 300s (app/core/config.py's
ollama_timeout_seconds, configurable per-deployment) -- enough headroom
above the measured 187s baseline for a cold-loaded CPU-only model -- and by
threading that value through to the real httpx.AsyncClient() call instead
of the module's old hardcoded constant.

This test verifies the WIRING (the actual timeout value handed to
httpx.AsyncClient for a real call_claude_json() call), not real elapsed
time -- asserting the fix by actually waiting out a 120s-vs-300s window
would make this test itself take minutes for no added confidence.
"""
import pytest

import app.ai.ollama_client as ollama_client_module
from app.ai.ollama_client import OllamaClient


class _FakeChatResponse:
    status_code = 200

    def json(self):
        return {"message": {"content": '{"ok": true}'}}


class _TimeoutRecordingAsyncClient:
    """Stand-in for httpx.AsyncClient that records the `timeout=` kwarg it
    was constructed with, then answers the one POST call_claude_json makes
    with a canned, valid response -- so the real call_claude_json() code
    path (including the httpx.AsyncClient(timeout=...) construction being
    regression-tested here) actually runs, without any real network I/O or
    real waiting.
    """

    last_timeout = None

    def __init__(self, timeout=None):
        _TimeoutRecordingAsyncClient.last_timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None):
        return _FakeChatResponse()


@pytest.mark.asyncio
async def test_call_claude_json_uses_the_cpu_and_reload_aware_timeout_not_the_old_120s(monkeypatch):
    monkeypatch.setattr(ollama_client_module.httpx, "AsyncClient", _TimeoutRecordingAsyncClient)

    client = await OllamaClient.create(base_url="http://127.0.0.1:11434", model="llama3.2:3b")
    result = await client.call_claude_json(
        system_prompt="system prompt",
        user_prompt="user prompt",
        json_schema={"type": "object"},
    )

    assert result == {"ok": True}
    # The old bug: this was hardcoded to 120, well under the measured 187s
    # a real cold-loaded CPU-only llama3.2:3b request took to complete.
    assert _TimeoutRecordingAsyncClient.last_timeout != 120
    assert _TimeoutRecordingAsyncClient.last_timeout >= 300


@pytest.mark.asyncio
async def test_timeout_is_configurable_per_deployment_via_settings(monkeypatch):
    """An operator on even slower hardware (a bigger model, a busier host)
    must be able to raise this further without a code change -- confirms
    the value actually flows from Settings.ollama_timeout_seconds through
    to the real httpx call, not just that the new default is bigger."""
    monkeypatch.setattr(ollama_client_module.httpx, "AsyncClient", _TimeoutRecordingAsyncClient)

    client = await OllamaClient.create(base_url="http://127.0.0.1:11434", model="llama3.2:3b", timeout_seconds=900)
    await client.call_claude_json(
        system_prompt="system prompt",
        user_prompt="user prompt",
        json_schema={"type": "object"},
    )

    assert _TimeoutRecordingAsyncClient.last_timeout == 900


def test_settings_default_gives_real_headroom_above_the_measured_187s_cold_load(monkeypatch):
    """Direct check on the configured default itself (app/core/config.py's
    ollama_timeout_seconds) -- decoupled from the httpx wiring tests above
    so this keeps failing even if some future refactor stops threading the
    value through the way it does today."""
    from app.core.config import get_settings

    settings = get_settings()
    assert settings.ollama_timeout_seconds >= 300
    # The live-measured time for the exact request generate_final_assessment
    # sends to complete successfully on a cold-loaded CPU-only llama3.2:3b.
    measured_successful_completion_seconds = 187
    assert settings.ollama_timeout_seconds > measured_successful_completion_seconds
