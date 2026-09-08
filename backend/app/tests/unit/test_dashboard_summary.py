"""Unit tests for app.ai.dashboard_summary.generate_executive_summary --
specifically the deterministic-fallback discipline this module exists to
guarantee: get_kpis() is the ONLY source of truth for every number, on BOTH
the AI-success path and the template_fallback path, and "source" always
honestly reflects which path actually produced the text (never let a
fallback silently look like a real success -- see app/ai/schemas.py's
FinalAssessment.ai_outcome docstring for the rationale this test suite
extends to the dashboard).

Mirrors app/tests/unit/test_ai_service.py's monkeypatch-the-module-level-name
pattern (there is no shared conftest.py in this repo).
"""
import asyncio
import time

import pytest
from pydantic import ValidationError

from app.ai.dashboard_summary import _template_fallback_narrative, generate_executive_summary

_SAMPLE_KPIS = {
    "active_investigations": 3,
    "critical_high_risk_iocs": 28,
    "open_cases": 11,
    "open_critical_cases": 4,
    "avg_threat_score": 62.5,
    "provider_health_percentage": 87.34,
    "ai_success_rate": 91.0,
}

_SAMPLE_KPIS_NO_AI_DATA = {**_SAMPLE_KPIS, "ai_success_rate": None}


async def _stub_get_kpis(kpis: dict = _SAMPLE_KPIS):
    return dict(kpis)


# --- _template_fallback_narrative (pure, DB-free) ---------------------------


def test_template_fallback_narrative_is_number_accurate():
    narrative = _template_fallback_narrative(_SAMPLE_KPIS)
    for value in _SAMPLE_KPIS.values():
        assert str(value) in narrative, f"expected the real KPI value {value!r} to appear verbatim in the fallback narrative"


def test_template_fallback_narrative_never_prints_literal_none_for_missing_ai_rate():
    narrative = _template_fallback_narrative(_SAMPLE_KPIS_NO_AI_DATA)
    assert "None" not in narrative
    assert "no ai analyses" in narrative.lower()


def test_template_fallback_narrative_is_non_empty():
    assert len(_template_fallback_narrative(_SAMPLE_KPIS).strip()) > 0


# --- generate_executive_summary: fallback path ------------------------------


@pytest.mark.asyncio
async def test_ai_unreachable_falls_back_to_template_with_real_numbers(monkeypatch):
    async def _raise_unreachable(backend_override=None):
        raise RuntimeError("AI backend 'ollama' is not configured")

    monkeypatch.setattr("app.ai.dashboard_summary.get_kpis", _stub_get_kpis)
    monkeypatch.setattr("app.ai.dashboard_summary._get_ai_client", _raise_unreachable)

    result = await generate_executive_summary()

    assert result["source"] == "template_fallback"
    assert result["kpis"] == _SAMPLE_KPIS
    assert isinstance(result["summary"], str) and len(result["summary"]) > 0
    assert str(_SAMPLE_KPIS["critical_high_risk_iocs"]) in result["summary"]
    assert str(_SAMPLE_KPIS["open_critical_cases"]) in result["summary"]


@pytest.mark.asyncio
async def test_generic_ai_failure_is_not_retried_before_falling_back(monkeypatch):
    """A non-validation failure (e.g. a rate limit or network error) must not
    be retried -- mirrors generate_final_assessment()'s own convention
    (app/ai/service.py): an immediate retry can't fix a real outage/rate
    limit, it would just double the cost of one."""
    call_count = {"value": 0}

    class _AlwaysFailsAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            call_count["value"] += 1
            raise RuntimeError("HTTP 429: rate limit exceeded")

    async def _stub_get_ai_client(backend_override=None):
        return _AlwaysFailsAIClient(), "groq", "stub-model"

    monkeypatch.setattr("app.ai.dashboard_summary.get_kpis", _stub_get_kpis)
    monkeypatch.setattr("app.ai.dashboard_summary._get_ai_client", _stub_get_ai_client)

    result = await generate_executive_summary()

    assert call_count["value"] == 1, "a non-validation failure must not be retried"
    assert result["source"] == "template_fallback"
    assert result["kpis"] == _SAMPLE_KPIS


@pytest.mark.asyncio
async def test_validation_failure_is_retried_once_then_falls_back(monkeypatch):
    """A validation failure (malformed/missing 'narrative' field) IS retried
    once (a stochastic model's next sample is not the same sample), but if
    the retry also fails validation, this must fall back to the template --
    never raise, never return an empty/error response."""
    call_count = {"value": 0}

    class _AlwaysMalformedAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            call_count["value"] += 1
            return {"not_narrative": "missing the required field"}

    async def _stub_get_ai_client(backend_override=None):
        return _AlwaysMalformedAIClient(), "ollama", "stub-model"

    monkeypatch.setattr("app.ai.dashboard_summary.get_kpis", _stub_get_kpis)
    monkeypatch.setattr("app.ai.dashboard_summary._get_ai_client", _stub_get_ai_client)

    result = await generate_executive_summary()

    assert call_count["value"] == 2, "must retry exactly once after a validation failure, then give up"
    assert result["source"] == "template_fallback"
    assert result["kpis"] == _SAMPLE_KPIS
    assert str(_SAMPLE_KPIS["avg_threat_score"]) in result["summary"]


@pytest.mark.asyncio
async def test_validation_failure_recovers_on_retry(monkeypatch):
    """The flip side of the retry: if attempt 1 fails validation but attempt
    2 succeeds, the AI-authored narrative must be used, not the fallback."""
    call_count = {"value": 0}

    class _FlakyAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            call_count["value"] += 1
            if call_count["value"] == 1:
                return {"not_narrative": "malformed"}
            return {"narrative": "SOC leadership narrative grounded in the given KPIs."}

    async def _stub_get_ai_client(backend_override=None):
        return _FlakyAIClient(), "ollama", "stub-model"

    monkeypatch.setattr("app.ai.dashboard_summary.get_kpis", _stub_get_kpis)
    monkeypatch.setattr("app.ai.dashboard_summary._get_ai_client", _stub_get_ai_client)

    result = await generate_executive_summary()

    assert call_count["value"] == 2
    assert result["source"] == "ai"
    assert result["summary"] == "SOC leadership narrative grounded in the given KPIs."
    assert result["kpis"] == _SAMPLE_KPIS


@pytest.mark.asyncio
async def test_slow_ai_backend_times_out_and_falls_back_to_template_instead_of_hanging(monkeypatch):
    """Real P3 bug found via live testing: generate_executive_summary() had
    no request-scoped timeout of its own, so a slow/busy shared AI backend
    (e.g. Ollama under concurrent load, or paying a cold model-reload cost --
    see app/ai/ollama_client.py's own 300s timeout) could hang this
    at-a-glance dashboard endpoint for as long as the underlying client's
    own timeout, with no response at all -- confirmed live: a single,
    uncontended call with Ollama active did not return within 60s.

    This pins the fix: the AI call is now bounded by
    settings.dashboard_summary_ai_timeout_seconds via asyncio.wait_for, and
    a backend that is merely slow (never actually erroring) must still
    resolve to the fast, deterministic template_fallback well within that
    bound -- not hang, and not be retried (mirrors the existing "a generic
    failure like a rate limit or outage is not retried" convention: an
    immediate retry against a backend that is merely slow/busy can't help,
    it would just double the wait)."""
    call_count = {"value": 0}

    class _HangingAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            call_count["value"] += 1
            # Much longer than the patched timeout below -- asyncio.wait_for
            # must cancel this, not actually wait it out.
            await asyncio.sleep(10)
            return {"narrative": "should never be reached"}

    async def _stub_get_ai_client(backend_override=None):
        return _HangingAIClient(), "ollama", "stub-model"

    class _FastTimeoutSettings:
        dashboard_summary_ai_timeout_seconds = 0.05

    monkeypatch.setattr("app.ai.dashboard_summary.get_kpis", _stub_get_kpis)
    monkeypatch.setattr("app.ai.dashboard_summary._get_ai_client", _stub_get_ai_client)
    monkeypatch.setattr("app.ai.dashboard_summary.get_settings", lambda: _FastTimeoutSettings())

    started = time.monotonic()
    result = await generate_executive_summary()
    elapsed = time.monotonic() - started

    assert elapsed < 5, "a slow/hanging AI backend must not be waited out past the configured timeout"
    assert call_count["value"] == 1, "a timeout must not be retried (same convention as a generic AI failure)"
    assert result["source"] == "template_fallback"
    assert result["kpis"] == _SAMPLE_KPIS
    assert str(_SAMPLE_KPIS["open_cases"]) in result["summary"]


# --- generate_executive_summary: success path -------------------------------


@pytest.mark.asyncio
async def test_ai_success_path_returns_ai_source_and_real_kpis(monkeypatch):
    class _CompliantAIClient:
        is_configured = True

        async def call_claude_json(self, **kwargs):
            return {"narrative": "Three active investigations and four open critical cases need attention."}

    async def _stub_get_ai_client(backend_override=None):
        return _CompliantAIClient(), "anthropic", "claude-x"

    monkeypatch.setattr("app.ai.dashboard_summary.get_kpis", _stub_get_kpis)
    monkeypatch.setattr("app.ai.dashboard_summary._get_ai_client", _stub_get_ai_client)

    result = await generate_executive_summary()

    assert result["source"] == "ai"
    assert result["summary"] == "Three active investigations and four open critical cases need attention."
    assert result["kpis"] == _SAMPLE_KPIS


@pytest.mark.asyncio
async def test_ai_call_is_grounded_only_in_the_given_kpis(monkeypatch):
    """Confirms the exact 7 KPI values are the only numbers handed to the
    prompt -- verbatim -- and that the returned kpis dict is untouched."""
    captured = {}

    class _CapturingAIClient:
        is_configured = True

        async def call_claude_json(self, system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None):
            captured["user_prompt"] = user_prompt
            return {"narrative": "Narrative."}

    async def _stub_get_ai_client(backend_override=None):
        return _CapturingAIClient(), "ollama", "stub-model"

    monkeypatch.setattr("app.ai.dashboard_summary.get_kpis", _stub_get_kpis)
    monkeypatch.setattr("app.ai.dashboard_summary._get_ai_client", _stub_get_ai_client)

    await generate_executive_summary()

    for key, value in _SAMPLE_KPIS.items():
        assert f"{key}: {value}" in captured["user_prompt"]
