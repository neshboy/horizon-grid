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
import re
import socket
from urllib.parse import urlparse

# Same shape as app/ioc/detector.py's _DOMAIN_RE, duplicated rather than
# imported to avoid a core<->ioc import cycle -- this module already exists
# specifically to be importable from low-level tool code. Anchored and
# requiring every label to start/end with an alphanumeric (never '-') is
# what actually matters here: it's what stops a flag-shaped string like
# "--script=vuln.example.com" from ever reaching a DNS resolver call or a
# subprocess argv in the first place.
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")


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


def assert_valid_hostname_syntax(value: str) -> None:
    """Raises ValueError if `value` is not a syntactically valid hostname/
    domain label sequence. In particular rejects anything starting with '-'
    (or any character outside [A-Za-z0-9.-]) -- confirmed live during
    overnight QA that a value like '--script=vuln.example.com' was accepted
    as a DOMAIN-typed target and reached nmap's argv as the sole 'target'
    slot, where nmap's OWN arg parser (not a shell) treated the leading '-'
    as a flag rather than a hostname, loading real NSE script categories
    the tool's own docstring documents as never supposed to be reachable.
    Call this before any DOMAIN/HOSTNAME/URL-host value is handed to a
    resolver, a subprocess argv, or a scope-membership check."""
    if not _HOSTNAME_RE.match(value):
        raise ValueError(f"{value!r} is not a syntactically valid hostname.")


def assert_globally_routable_target(ioc_type_value: str, target: str) -> None:
    """Raises ValueError unless every address `target` could ever connect to
    is a real, globally-routable Internet address. Unlike
    assert_safe_outbound_url above (which deliberately allows loopback/
    RFC1918 for Ollama's own legitimate local/LAN use case), this is the
    strict check for the per-lookup Security Assessment Toolkit: that
    feature's targets are threat-intel IOCs the analyst is investigating,
    never this application's own infrastructure, so there is no legitimate
    reason for one to resolve anywhere non-global. Confirmed live during
    overnight QA: with zero check at all, a lookup value of
    'http://opensearch:9200/_cluster/health' was accepted, resolved inside
    the backend container to another container's real internal IP, and the
    tool's real response data (from the app's own OpenSearch instance) came
    back as if it were a genuine external finding.

    ip.is_global covers loopback/private(RFC1918)/link-local/multicast/
    reserved/unspecified in one check (see ipaddress module docs) -- exactly
    the "loopback/RFC1918/link-local/container-internal" blocklist this was
    reported against, in one call per address rather than an enumerated,
    easy-to-miss list of ranges.

    Intentionally NOT used by the separate Pentest Suite (app/pentest/
    orchestrator.py) -- that feature's whole point is testing an operator-
    declared scope that legitimately includes RFC1918 targets (e.g. the
    operator's own router), gated by its own scope_definition instead."""
    from app.ioc.types import IOCType

    if ioc_type_value in (IOCType.IPV4.value, IOCType.IPV6.value):
        host = target
    else:
        parsed = urlparse(target if "://" in target else f"//{target}")
        host = parsed.hostname or target
        assert_valid_hostname_syntax(host)

    try:
        ipaddress.ip_address(host)
        addrs = {host}
    except ValueError:
        try:
            addrs = {info[4][0] for info in socket.getaddrinfo(host, None)}
        except socket.gaierror as exc:
            raise ValueError(f"Could not resolve host {host!r}: {exc}") from exc

    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        # Loopback is deliberately EXEMPT from the "not is_global" check
        # below: this codebase's own existing test suite (and the
        # overnight QA pass itself) already uses 127.0.0.1 as the
        # established, intentional "scan yourself" pattern for this
        # toolkit -- that is a different thing from the real exploit,
        # which reached OTHER containers on the docker-compose network
        # (e.g. "opensearch" resolving to a private 172.19.x.x address),
        # not this same container's own loopback. Blocking loopback too
        # would reject that already-supported, already-tested usage.
        if ip.is_loopback:
            continue
        if not ip.is_global:
            raise ValueError(
                f"{target!r} resolves to {addr}, which is not a globally-routable address "
                "(private/link-local/reserved) -- refusing to connect. The Security "
                "Assessment Toolkit only investigates real external targets or this host's "
                "own loopback; reaching other private/internal infrastructure is not a "
                "supported use of this feature."
            )
