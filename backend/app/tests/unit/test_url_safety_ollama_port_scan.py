"""Regression coverage for a real, live-confirmed P2 SSRF gap:
app/core/url_safety.py's assert_safe_outbound_url() (the guard on the
Ollama `base_url` field, called from app/ai/connection_test.py's
"Test AI Connection" and app/api/routes/ai_config.py's model-listing) used
to allow ANY port on any RFC1918/loopback address, only rejecting
link-local space.

Live-confirmed exploit (provider:manage-holding ADMIN account): pointing
`base_url` at this deployment's own sibling containers --
http://opensearch:9200, http://neo4j:7474, http://redis:6379, and even
http://localhost:8000 (the backend's own API port, reachable because
"localhost" from inside the backend container IS the backend) -- each
produced a real, distinguishable response/error reflected back through the
API's `message` field, confirming reachability and service identity for
arbitrary internal targets. None of those are ports a real Ollama server
would ever listen on.

Fix: private/loopback destinations are now additionally required to be on
Ollama's own default port (11434). Public/global addresses are unaffected
(no port restriction there -- only link-local is blocked for those, same
as before). This closes the internal-port-scanning vector while still
allowing the one legitimate shape (a local/LAN Ollama instance on its
default port) this check exists to permit.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.core.url_safety import assert_safe_outbound_url


def _mock_getaddrinfo(ip_address: str):
    """Same pattern as test_ai_service_ollama_ssrf.py's helper of the same
    name: a fake async event-loop getaddrinfo() that always resolves to one
    fixed address, regardless of hostname, so these tests don't depend on
    whatever "opensearch"/"localhost" happen to resolve to in whatever
    environment runs them."""
    return AsyncMock(return_value=[(None, None, None, "", (ip_address, 0))])


@pytest.mark.asyncio
async def test_private_address_on_a_non_ollama_port_is_rejected():
    """The exact shape of the live exploit: a docker-compose sibling
    hostname resolving to a private (RFC1918) address, on a port a real
    internal service (not Ollama) actually listens on."""
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo("172.19.0.5")
        with pytest.raises(ValueError, match="not Ollama's default port"):
            await assert_safe_outbound_url("http://opensearch:9200")


@pytest.mark.asyncio
async def test_loopback_address_on_a_non_ollama_port_is_rejected():
    """The backend-probing-itself shape of the live exploit: "localhost"
    resolving to loopback, on the backend's own API port rather than
    Ollama's."""
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo("127.0.0.1")
        with pytest.raises(ValueError, match="not Ollama's default port"):
            await assert_safe_outbound_url("http://localhost:8000")


@pytest.mark.asyncio
async def test_private_address_with_no_explicit_port_is_rejected():
    """No explicit port (implied default HTTP port 80) must be checked
    against that SAME implied default, not treated as unrestricted just
    because the caller omitted a port."""
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo("172.19.0.5")
        with pytest.raises(ValueError, match="not Ollama's default port"):
            await assert_safe_outbound_url("http://opensearch")


@pytest.mark.asyncio
async def test_private_address_on_the_real_ollama_default_port_is_allowed():
    """The legitimate use case this check exists to permit must keep
    working: a LAN Ollama instance on a private address, on Ollama's real
    default port."""
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo("192.168.1.50")
        await assert_safe_outbound_url("http://192.168.1.50:11434")  # must not raise


@pytest.mark.asyncio
async def test_loopback_on_the_real_ollama_default_port_is_allowed():
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo("127.0.0.1")
        await assert_safe_outbound_url("http://127.0.0.1:11434")  # must not raise


@pytest.mark.asyncio
async def test_public_address_is_not_port_restricted():
    """The port restriction only exists to stop THIS app's own internal
    infrastructure from being probed -- a genuine public address (not
    link-local) must not be rejected just for being on a non-11434 port."""
    with patch("asyncio.get_event_loop") as mock_loop:
        # 8.8.8.8 (not an RFC 5737 TEST-NET address) -- those are marked
        # is_private=True/is_global=False by Python's ipaddress module
        # (they're documentation-only, non-routable ranges), which would
        # defeat the point of this test. 8.8.8.8 is a real, stable,
        # globally-routable address (same choice this codebase's own
        # test_url_safety_investigation_target.py already makes for the
        # same reason).
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo("8.8.8.8")
        await assert_safe_outbound_url("http://8.8.8.8:443")  # must not raise


@pytest.mark.asyncio
async def test_link_local_is_still_rejected_regardless_of_port():
    """Pre-existing protection must survive this change unweakened -- the
    cloud-metadata address must still be rejected even on Ollama's own
    default port."""
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo("169.254.169.254")
        with pytest.raises(ValueError, match="link-local"):
            await assert_safe_outbound_url("http://169.254.169.254:11434")
