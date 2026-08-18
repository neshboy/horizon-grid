"""Guard against SSRF via operator-supplied outbound URLs (currently: the
Ollama `base_url` field, the one place this codebase makes a server-side
HTTP call to a fully caller-chosen host).

Deliberately does NOT block loopback/private (RFC1918) ranges -- Ollama's
whole legitimate use case is a local or LAN instance (this deployment's own
OLLAMA_BASE_URL points at host.docker.internal), so blocking those would
break real functionality, not just theoretical attacks. What this DOES
block is link-local space (169.254.0.0/16, fe80::/10), which has no
legitimate Ollama use and is where every major cloud provider's instance
metadata service lives (169.254.169.254) -- the single highest-value SSRF
target this endpoint could otherwise be used to reach.
"""
import ipaddress
import socket
from urllib.parse import urlparse


def assert_safe_outbound_url(url: str) -> None:
    """Raises ValueError if `url` is not safe to fetch server-side."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme {parsed.scheme!r} -- only http/https are allowed.")
    if not parsed.hostname:
        raise ValueError("URL has no host.")

    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {parsed.hostname!r}: {exc}") from exc

    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        if ip.is_link_local:
            raise ValueError(
                f"Host {parsed.hostname!r} resolves to a link-local address ({addr}), "
                "which includes cloud instance-metadata services -- refusing to connect."
            )
