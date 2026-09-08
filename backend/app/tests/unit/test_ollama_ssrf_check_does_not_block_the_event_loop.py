"""Regression test for a real P2 bug: app/core/url_safety.py's
assert_safe_outbound_url() (the SSRF/link-local guard on the Ollama
`base_url` field) used to call the SYNCHRONOUS, un-timeboxed
socket.getaddrinfo() directly, on the shared asyncio event loop, from
inside async code.

Real call chain this matters on: app/ai/ollama_client.py's OllamaClient
construction path is awaited from app/ai/service.py's _get_ai_client() (via
_build_client()) -- which every single Ollama-backed summarize_provider/
generate_final_assessment call goes through once runtime-config has been
seeded, which app/core/runtime_config.py's seed_from_env_if_empty() does
unconditionally on every startup (app/main.py). This is one, shared,
process-wide event loop also serving every OTHER concurrent request
(health checks, other investigations, dashboard loads) the backend is
handling at the same moment.

Live reproduction (from the confirmed finding): a background asyncio
"ticker" task incrementing a counter every 50ms recorded ZERO ticks during
the 0.567s a real synchronous getaddrinfo() call for an unresolvable host
took to raise 'Could not resolve host' -- versus the ~11 ticks that would
have fired in that window had the event loop stayed responsive. That
directly proves a slow-to-resolve or unreachable-nameserver Ollama
base_url -- a realistic operational condition, not a contrived one -- froze
the ENTIRE backend process for the full DNS-resolution duration, not just
the one request that triggered it.

Fix: assert_safe_outbound_url() is now itself a coroutine that awaits
asyncio.get_event_loop().getaddrinfo() -- the same event-loop-native-
resolver pattern app/providers/stubs/spamhaus.py already used elsewhere in
this codebase -- instead of calling socket.getaddrinfo() directly. The
actual (still blocking, still potentially slow) getaddrinfo(3) syscall now
runs in a worker thread; this coroutine -- and therefore this process's
event loop -- suspends and yields control back to every OTHER pending task
for as long as that takes, instead of monopolizing the one thread that
runs all of them. Because __init__ cannot await, the check was moved out of
OllamaClient.__init__ into an async OllamaClient.create() classmethod (see
test_ai_service_ollama_ssrf.py for that half of the regression coverage --
the SSRF check itself still firing correctly on every real construction
path); this file covers the concurrency property specifically.

This test proves the actual property the finding cares about -- concurrent
progress during DNS resolution -- rather than just that the function is
now technically a coroutine: it mocks the event loop's getaddrinfo() with a
slow-but-cooperative (asyncio.sleep-based) fake standing in for a slow
resolver, runs it concurrently with a ticker task via a real asyncio
scheduling race (asyncio.create_task + await), and asserts the ticker made
real, repeated progress during the simulated resolution window. Run against
the pre-fix code, `await assert_safe_outbound_url(...)` fails immediately
with a TypeError (the old function was a plain synchronous function
returning None, not a coroutine, so it cannot be awaited at all) -- itself
proof that the old API made this concurrency structurally impossible, not
just slow.
"""
import asyncio
from unittest.mock import patch

import pytest

from app.core.url_safety import assert_safe_outbound_url

_SIMULATED_DNS_DELAY_SECONDS = 0.3
_TICKER_INTERVAL_SECONDS = 0.02
# Theoretical max is _SIMULATED_DNS_DELAY_SECONDS / _TICKER_INTERVAL_SECONDS
# == 15; a much lower bar keeps this robust against normal test-runner
# scheduling jitter while still clearly distinguishing "the loop stayed
# responsive" from the bug's own measured "zero ticks fired at all".
_MIN_EXPECTED_TICKS = 5


async def _slow_but_cooperative_getaddrinfo(host, port, *args, **kwargs):
    """Stands in for a real, slow-to-resolve (or unreachable-nameserver)
    DNS lookup: awaits -- rather than blocks -- for
    _SIMULATED_DNS_DELAY_SECONDS, then resolves to a fixed, safe
    (non-link-local) RFC 5737 TEST-NET-3 address, same as this fix's real
    asyncio.get_event_loop().getaddrinfo() await would for a real slow
    resolver."""
    await asyncio.sleep(_SIMULATED_DNS_DELAY_SECONDS)
    return [(None, None, None, "", ("203.0.113.5", 0))]


@pytest.mark.asyncio
async def test_dns_resolution_does_not_block_other_concurrent_asyncio_tasks():
    ticks = 0

    async def _ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(_TICKER_INTERVAL_SECONDS)
            ticks += 1

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _slow_but_cooperative_getaddrinfo

        ticker_task = asyncio.create_task(_ticker())
        try:
            # The call under test: must not monopolize the event loop for
            # the ~0.3s the (mocked) DNS resolution takes.
            await assert_safe_outbound_url("http://slow-dns-host.example:11434")
        finally:
            ticker_task.cancel()

    # The exact shape of the finding's own live repro: if this coroutine
    # blocked the event loop for the full simulated DNS delay instead of
    # awaiting it cooperatively, the ticker task above would never get a
    # chance to run at all during that window (measured live: 0 ticks in
    # 0.567s of real blocking, vs. ~11 expected).
    assert ticks >= _MIN_EXPECTED_TICKS, (
        f"only {ticks} ticker ticks fired during the simulated DNS resolution delay -- "
        "the event loop appears to have been blocked while assert_safe_outbound_url() "
        "was resolving the host, exactly the bug this test guards against"
    )


@pytest.mark.asyncio
async def test_still_raises_on_a_real_gaierror_after_switching_resolvers(monkeypatch):
    """No-regression check: switching from socket.getaddrinfo() to
    asyncio.get_event_loop().getaddrinfo() must not change the observable
    error-handling behavior for an unresolvable host -- both raise/wrap
    socket.gaierror identically."""
    import socket

    async def _raise_gaierror(host, port, *args, **kwargs):
        raise socket.gaierror("simulated: name or service not known")

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _raise_gaierror
        with pytest.raises(ValueError, match="Could not resolve host"):
            await assert_safe_outbound_url("http://this-host-should-not-resolve.invalid:11434")
