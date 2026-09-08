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

Both are fixed by a single check awaited from a single choke point --
OllamaClient.create() (an async classmethod) -- rather than duplicating the
check at each call site. It is async, not a plain function/an __init__,
because of a separate, later-found bug: see
test_ollama_ssrf_check_does_not_block_the_event_loop.py for the regression
coverage of THAT one (the DNS resolution itself blocking every other
concurrent request while it runs), which is what forced the check out of
__init__ (which cannot await) into this classmethod in the first place.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.ai.ollama_client import OllamaClient
from app.ai.service import _build_client


def _mock_getaddrinfo(ip_address: str):
    """Build a fake async event-loop getaddrinfo() that always resolves to a
    single fixed, non-link-local address, regardless of hostname.

    url_safety.assert_safe_outbound_url() awaits asyncio.get_event_loop().
    getaddrinfo(host, None) (the same event-loop-native-resolver pattern
    app/providers/stubs/spamhaus.py already uses, and this file's own
    sibling test mocks the same way -- see test_spamhaus_provider.py).
    Mocking only this DNS-resolution step -- not assert_safe_outbound_url()
    itself -- means the real link-local check still runs for real; we're
    just making "does this hostname resolve, and to what" deterministic and
    environment-independent, instead of depending on whether
    'host.docker.internal' happens to resolve on whatever machine runs the
    test (it does inside a real Docker Desktop network, as in the
    integration-docker CI job, but not on a bare GitHub Actions runner or a
    plain dev laptop, which is exactly what broke this unit job).

    ip_address is expected to be a real, safe, non-link-local address (e.g.
    an RFC 5737 TEST-NET-3 documentation address) so the mocked resolution
    is guaranteed to pass the link-local check on its own merits.
    """
    return AsyncMock(return_value=[(None, None, None, "", (ip_address, 0))])


@pytest.mark.asyncio
async def test_link_local_base_url_is_rejected_via_the_runtime_config_override_path():
    with pytest.raises(ValueError, match="link-local"):
        await _build_client("ollama", {"base_url": "http://169.254.169.254:11434"}, None)


@pytest.mark.asyncio
async def test_link_local_base_url_is_rejected_via_the_settings_only_singleton_path(monkeypatch):
    """The gap this session actually found: get_ollama_client()'s singleton
    path (no runtime-config DB row saved) previously skipped validation
    entirely, since app/ai/service.py's _build_client() only ever checked
    the credentials-override branch. Fixed by moving the check into
    OllamaClient.create() (awaited by both get_ollama_client() and
    _build_client()'s override branch) so it also covers this settings-only
    construction, not just the override path."""
    import app.ai.ollama_client as ollama_client_module

    class _FakeSettings:
        ollama_base_url = "http://169.254.169.254:11434"
        ollama_model = "llama3.2:3b"
        ollama_max_tokens = 8192
        ollama_timeout_seconds = 300

    monkeypatch.setattr(ollama_client_module, "get_settings", lambda: _FakeSettings())
    with pytest.raises(ValueError, match="link-local"):
        await OllamaClient.create()


@pytest.mark.asyncio
async def test_loopback_base_url_is_still_allowed():
    """Not blocked by design -- Ollama's real use case is a local/LAN
    instance, so loopback/RFC1918 must keep working (see url_safety.py's own
    module docstring for the rationale)."""
    client = await _build_client("ollama", {"base_url": "http://127.0.0.1:11434"}, None)
    assert client._base_url == "http://127.0.0.1:11434"


@pytest.mark.asyncio
async def test_no_credentials_override_uses_the_settings_default_and_it_passes_validation(monkeypatch):
    # credentials=None means "use the frozen .env-derived Settings client" --
    # this environment's real default (OLLAMA_BASE_URL, resolved via
    # host.docker.internal) is expected to be a genuinely safe address, so
    # this must construct without raising. host.docker.internal itself only
    # resolves inside a real Docker Desktop network (see this file's
    # integration-docker vs. bare-runner split); DNS resolution is mocked
    # here to a fixed, non-link-local TEST-NET-3 address (RFC 5737) so this
    # test verifies "the real assert_safe_outbound_url() logic doesn't
    # reject a resolvable, non-link-local host" deterministically, without
    # depending on -- or weakening the real check against -- whatever
    # host.docker.internal happens to resolve to on the machine running it.
    import app.ai.ollama_client as ollama_client_module

    # This falls back to the settings-only singleton path (get_ollama_client()).
    # Force a fresh construction so this test actually re-invokes
    # OllamaClient.create() (and therefore the mocked DNS resolution + real
    # link-local check below), rather than potentially passing vacuously on
    # a singleton some earlier-run test in this process already cached.
    monkeypatch.setattr(ollama_client_module, "_singleton", None)

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo("203.0.113.5")
        client = await _build_client("ollama", None, None)
    assert client is not None


@pytest.mark.asyncio
async def test_missing_base_url_in_credentials_does_not_raise(monkeypatch):
    # An empty/partial credentials dict (e.g. a save that only changes
    # model_id) must not crash just because base_url wasn't supplied --
    # falls back to the settings default, which passes validation same as
    # the test above. Same DNS mock, same reason: host.docker.internal
    # isn't resolvable outside a real Docker Desktop network, so pin
    # resolution to a fixed, safe address rather than depending on the
    # environment running the test.
    #
    # Unlike the test above, credentials={} (not None) here, so _build_client
    # takes the direct-construction branch (a fresh OllamaClient every call),
    # never the get_ollama_client() singleton -- no singleton reset needed.
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo("203.0.113.5")
        client = await _build_client("ollama", {}, "llama3.2:3b")
    assert client is not None
