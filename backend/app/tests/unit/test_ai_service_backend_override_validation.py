"""Regression coverage for a real P2 security/audit-integrity bug found live:

_get_ai_client() (app/ai/service.py) never validated `backend_override`
against the known AI_BACKENDS list (app/core/runtime_config.py) before using
it. An unrecognized backend name -- a typo, or a caller/attacker-chosen
string, reachable by ANY authenticated user holding only "lookup:create"
(POST /lookup/stream, POST /lookup/{id}/reanalyze) -- doesn't match any
ProviderRuntimeConfig row, so get_ai_config()/get_active_ai_config() return
None, which fell into the `config is None` / Settings-based branch and called
_build_client(backend_override, None, None). _build_client's own final
`else` (no matching `if backend == "..."` branch) unconditionally constructed
a real OllamaClient regardless of what was actually asked for -- and since
`backend` itself stayed the ORIGINAL bogus string, the caller ended up
silently running real analysis on Ollama while the bogus string got persisted
verbatim into assessment.ai_backend / FinalAssessmentRecord.ai_backend, the
exact field this platform relies on to answer "which AI produced this
conclusion."

Reproduced directly against the running service layer before the fix:

    _get_ai_client(backend_override="totally_bogus_backend")
    -> (<OllamaClient>, "totally_bogus_backend", None), is_configured=True

Fix: _get_ai_client() now validates backend_override against AI_BACKENDS --
the same list set_active_ai_backend() already validates against -- and
raises ValueError immediately, before ever reaching get_ai_config()/
_build_client(), so an unrecognized backend name can never silently
substitute Ollama or reach a persisted ai_backend field.
"""
import pytest

from app.core.runtime_config import AI_BACKENDS


@pytest.mark.asyncio
async def test_get_ai_client_rejects_unrecognized_backend_override(monkeypatch):
    """The exact live reproduction: a backend name that isn't in AI_BACKENDS
    at all must be rejected outright, not silently resolved to Ollama."""
    from app.ai.service import _get_ai_client

    assert "totally_bogus_backend" not in AI_BACKENDS

    with pytest.raises(ValueError, match="totally_bogus_backend"):
        await _get_ai_client(backend_override="totally_bogus_backend")


@pytest.mark.asyncio
async def test_get_ai_client_never_builds_a_client_for_an_unrecognized_backend_override(monkeypatch):
    """Stronger version of the test above: asserts the Ollama-substitution
    path itself (_build_client) is never even reached for a bogus
    backend_override -- pinning the exact mechanism of the bug (not just its
    externally-visible symptom), so a future regression that re-introduces
    the fallback via a different code path would still be caught."""
    from app.ai import service as service_module

    async def _fail_if_called(backend, credentials, model_id):
        raise AssertionError(
            f"_build_client must never be called for an unrecognized backend_override "
            f"(got backend={backend!r}) -- this is exactly the silent Ollama-substitution bug"
        )

    monkeypatch.setattr(service_module, "_build_client", _fail_if_called)

    with pytest.raises(ValueError):
        await service_module._get_ai_client(backend_override="totally_bogus_backend")


@pytest.mark.asyncio
async def test_get_ai_client_accepts_a_real_backend_override(monkeypatch):
    """Sanity/no-regression check: a real, known backend name in
    backend_override must still resolve normally -- the fix must reject only
    names absent from AI_BACKENDS, never a legitimate one."""
    from app.ai import service as service_module

    class _StubClient:
        is_configured = True

    async def _fake_get_ai_config(backend):
        assert backend == "groq"
        return {"backend": "groq", "credentials": {"api_key": "k"}, "model_id": "stub-model"}

    async def _fake_build_client(backend, credentials, model_id):
        return _StubClient()

    monkeypatch.setattr("app.core.runtime_config.get_ai_config", _fake_get_ai_config)
    monkeypatch.setattr(service_module, "_build_client", _fake_build_client)

    client, backend, model_id = await service_module._get_ai_client(backend_override="groq")

    assert backend == "groq"
    assert model_id == "stub-model"
    assert client.is_configured is True


@pytest.mark.asyncio
async def test_summarize_provider_with_bogus_backend_override_does_not_fabricate_a_summary(monkeypatch):
    """End-to-end (through the public summarize_provider() entry point, not
    the private _get_ai_client() helper) version of the same bug: before the
    fix, a bogus backend_override still produced a real AI-generated
    ProviderSummary (via the silently-substituted Ollama client) -- attacker/
    caller-controlled input having zero effect on the request's success is
    itself part of the bug. After the fix, _get_ai_client's ValueError is
    caught by summarize_provider's existing generic error handler and
    correctly downgrades to the "AI summarization unavailable" fallback,
    exactly like any other AI backend failure -- it must never reach a
    real (Ollama-produced) summary for a backend name that was never valid."""
    from app.ai.service import summarize_provider
    from app.ioc.types import IOCType
    from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus

    result = ProviderResult(
        provider_id="virustotal",
        provider_name="VirusTotal",
        category=ProviderCategory.THREAT_INTEL,
        status=ProviderStatus.OK,
        ioc_value="1.2.3.4",
        ioc_type=IOCType.IPV4,
        data={"detections": 42},
    )

    summary = await summarize_provider(
        "1.2.3.4", "ipv4", result, backend_override="totally_bogus_backend"
    )

    assert summary.confidence == "low"
    assert summary.detection_status == "unknown"
    assert "unavailable" in summary.what_it_knows.lower()
