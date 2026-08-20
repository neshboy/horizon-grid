"""Regression coverage for a real SSRF gap found during a mission-critical-
readiness review: app/core/url_safety.py's assert_safe_outbound_url() (blocks
link-local addresses, including cloud instance-metadata services at
169.254.169.254) was previously only called from the Test-Connection/
model-discovery convenience paths (app/api/routes/ai_config.py,
app/ai/connection_test.py) -- NOT from any real production call path.

Two distinct real call paths needed fixing, not one:

1. app/ai/service.py's _build_client() (via _get_ai_client) -- used whenever
   an operator has saved Ollama config through the runtime-config DB store
   (the "AI Providers" web panel).
2. app/ai/ollama_client.py's get_ollama_client() singleton -- used instead
   of (1) whenever NO runtime-config DB row has ever been saved for
   "ollama", reading ONLY the frozen .env-derived OLLAMA_BASE_URL. Checking
   every real caller confirmed this is the COMMON case for a wizard-driven,
   "install once and never touch the web UI again" deployment (exactly this
   mission's own target scenario), not a rare edge case -- so this path
   mattered just as much as (1).

Both are fixed by a single check inside OllamaClient.__init__ itself (the
one real choke point both paths construct through), rather than duplicating
the check at each call site.
"""
import pytest

from app.ai.ollama_client import OllamaClient
from app.ai.service import _build_client


def test_link_local_base_url_is_rejected_via_the_runtime_config_override_path():
    with pytest.raises(ValueError, match="link-local"):
        _build_client("ollama", {"base_url": "http://169.254.169.254:11434"}, None)


def test_link_local_base_url_is_rejected_via_the_settings_only_singleton_path(monkeypatch):
    """The gap this session actually found: get_ollama_client()'s singleton
    path (no runtime-config DB row saved) previously skipped validation
    entirely, since app/ai/service.py's _build_client() only ever checked
    the credentials-override branch. Fixed by moving the check into
    OllamaClient.__init__ itself so it also covers this settings-only
    construction, not just the override path."""
    import app.ai.ollama_client as ollama_client_module

    class _FakeSettings:
        ollama_base_url = "http://169.254.169.254:11434"
        ollama_model = "llama3.2:3b"
        ollama_max_tokens = 8192

    monkeypatch.setattr(ollama_client_module, "get_settings", lambda: _FakeSettings())
    with pytest.raises(ValueError, match="link-local"):
        OllamaClient()


def test_loopback_base_url_is_still_allowed():
    """Not blocked by design -- Ollama's real use case is a local/LAN
    instance, so loopback/RFC1918 must keep working (see url_safety.py's own
    module docstring for the rationale)."""
    client = _build_client("ollama", {"base_url": "http://127.0.0.1:11434"}, None)
    assert client._base_url == "http://127.0.0.1:11434"


def test_no_credentials_override_uses_the_settings_default_and_it_passes_validation():
    # credentials=None means "use the frozen .env-derived Settings client" --
    # this environment's real default (OLLAMA_BASE_URL, resolved via
    # host.docker.internal) is expected to be a genuinely safe address, so
    # this must construct without raising.
    client = _build_client("ollama", None, None)
    assert client is not None


def test_missing_base_url_in_credentials_does_not_raise():
    # An empty/partial credentials dict (e.g. a save that only changes
    # model_id) must not crash just because base_url wasn't supplied --
    # falls back to the settings default, which passes validation same as
    # the test above.
    client = _build_client("ollama", {}, "llama3.2:3b")
    assert client is not None
