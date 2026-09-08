"""Guard against SSRF via operator-supplied outbound URLs (currently: the
Ollama `base_url` field, the one place this codebase makes a server-side
HTTP call to a fully caller-chosen host).

Deliberately does NOT block loopback/private (RFC1918) ranges outright --
Ollama's whole legitimate use case is a local or LAN instance (this
deployment's own OLLAMA_BASE_URL points at host.docker.internal), so
blocking those would break real functionality, not just theoretical
attacks. What this unconditionally blocks is link-local space
(169.254.0.0/16, fe80::/10), which has no legitimate Ollama use and is
where every major cloud provider's instance metadata service lives
(169.254.169.254).

Confirmed live (provider:manage-holding ADMIN account) that allowing ALL of
RFC1918/loopback on ANY port turned this into a semi-blind internal port
scanner: pointing `base_url` at this deployment's own sibling containers --
http://opensearch:9200, http://neo4j:7474, http://redis:6379, even
http://localhost:8000 (the backend's own API port, reachable because
"localhost" from inside the backend container IS the backend) -- each
produced a real, distinguishable response/error (in one case OpenSearch's
own JSON error body, verbatim) echoed back through the `message` field,
confirming reachability and service identity for arbitrary internal
targets. None of those are anything a real Ollama server would ever be
listening on, so assert_safe_outbound_url now additionally requires that
any private/loopback destination be on Ollama's own default port (11434,
what OLLAMA_HOST binds to out of the box and what every one of this app's
own docs/wizards assumes) -- closing the fingerprinting vector while still
allowing the one legitimate shape (a local/LAN Ollama instance) this check
exists to permit. Public/global addresses are NOT port-restricted --
link-local is still the only thing blocked there.
"""
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse

# Ollama's own real, essentially-fixed default port (what `ollama serve` /
# OLLAMA_HOST binds to unless explicitly overridden) -- see this module's
# docstring for why private/loopback destinations are restricted to it.
_OLLAMA_DEFAULT_PORT = 11434

# Same shape as app/ioc/detector.py's _DOMAIN_RE, duplicated rather than
# imported to avoid a core<->ioc import cycle -- this module already exists
# specifically to be importable from low-level tool code. Anchored and
# requiring every label to start/end with an alphanumeric (never '-') is
# what actually matters here: it's what stops a flag-shaped string like
# "--script=vuln.example.com" from ever reaching a DNS resolver call or a
# subprocess argv in the first place.
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")


async def assert_safe_outbound_url(url: str) -> None:
    """Raises ValueError if `url` is not safe to fetch server-side.

    async (not a plain function) specifically so the DNS-resolution step
    below runs via the event loop's own resolver (asyncio.AbstractEventLoop.
    getaddrinfo(), which hands the blocking getaddrinfo(3) call to a worker
    thread and awaits it) instead of calling socket.getaddrinfo() directly
    on the event loop thread. Confirmed live: every real caller of this
    function (app/ai/ollama_client.py's OllamaClient construction path,
    app/api/routes/ai_config.py's connection test, app/core/runtime_config.
    py's save path) runs inside an async request/call, sharing ONE process-
    wide event loop with every other concurrent request the backend is
    serving. socket.getaddrinfo() has no timeout parameter and, with
    multiple configured nameservers each retried in sequence on a slow/
    unreachable resolver, can take tens of seconds -- and being a plain
    blocking call invoked directly on the event loop thread with no
    run_in_executor/to_thread wrapper, it froze the ENTIRE process for that
    whole duration, not just the one request that happened to trigger it.
    Measured directly: a background asyncio ticker task incrementing every
    50ms recorded ZERO ticks during a 0.567s synchronous getaddrinfo() call
    for an unresolvable host, versus the ~11 ticks expected if the loop had
    stayed responsive. Switching to the event-loop-native resolver fixes
    that by construction: the blocking syscall still happens in a worker
    thread, but this coroutine (and therefore this process's event loop)
    suspends and yields control back to every OTHER pending task for the
    whole duration, instead of monopolizing the thread that runs all of
    them.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme {parsed.scheme!r} -- only http/https are allowed.")
    if not parsed.hostname:
        raise ValueError("URL has no host.")

    try:
        # asyncio.get_event_loop() (not get_running_loop()) to match the
        # same event-loop-native-resolver pattern this codebase already
        # uses for DNS lookups from async code (see
        # app/providers/stubs/spamhaus.py's fetch()) -- also what this
        # module's own test suite mocks via patch("asyncio.get_event_loop").
        loop = asyncio.get_event_loop()
        infos = await loop.getaddrinfo(parsed.hostname, None)
        addrs = {info[4][0] for info in infos}
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {parsed.hostname!r}: {exc}") from exc

    is_private_or_loopback = False
    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        if ip.is_link_local:
            raise ValueError(
                f"Host {parsed.hostname!r} resolves to a link-local address ({addr}), "
                "which includes cloud instance-metadata services -- refusing to connect."
            )
        if not ip.is_global:
            is_private_or_loopback = True

    if is_private_or_loopback:
        # Implied-default-port URLs (e.g. "http://opensearch", no explicit
        # port) must be checked against the SAME default a real browser/
        # httpx client would actually connect to -- not treated as "no
        # port restriction" just because the caller omitted one.
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if port != _OLLAMA_DEFAULT_PORT:
            raise ValueError(
                f"Host {parsed.hostname!r} resolves to a private/loopback address, and port "
                f"{port} is not Ollama's default port ({_OLLAMA_DEFAULT_PORT}) -- refusing to "
                "connect. Local/LAN Ollama instances are only permitted on their default port; "
                "this restriction exists to stop this feature being used to probe/fingerprint "
                "other internal services."
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


def _is_permitted_address(ip: "ipaddress.IPv4Address | ipaddress.IPv6Address", *, allow_private: bool) -> bool:
    """Shared predicate for resolve_safe_address's two call sites (the
    IP-literal branch and the per-resolved-address loop) -- kept as one
    function so both branches apply IDENTICAL rules rather than risking the
    allow_private carve-out being added to one and forgotten on the other.
    Loopback is handled by each call site itself (its handling differs
    between the two: the IP-literal branch returns immediately, the
    resolved-address loop `continue`s), not here."""
    if ip.is_global or ip.is_loopback:
        return True
    # Link-local (169.254.0.0/16, fe80::/10) stays blocked even with
    # allow_private=True -- see resolve_safe_address's own docstring: this
    # is where cloud instance-metadata services live, never a legitimate
    # RFC1918 pentest target.
    return allow_private and ip.is_private and not ip.is_link_local


def resolve_safe_address(host: str, *, allow_private: bool = False) -> str:
    """Resolves `host` (a bare hostname or IP literal, e.g. already stripped
    of scheme/port by a caller) to exactly ONE IP address that has just been
    verified globally-routable (or loopback -- see the "scan yourself"
    rationale on assert_globally_routable_target below), and returns THAT
    literal address for the caller to actually connect to.

    `allow_private=True` additionally permits RFC1918 private addresses
    (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, and their IPv6 unique-local
    equivalent) -- but NOT link-local (169.254.0.0/16, fe80::/10), which
    stays blocked unconditionally regardless of this flag, since that's
    where cloud instance-metadata services live and no caller of this
    function has a legitimate reason to reach one.

    This exists for the Pentest Suite (app/pentest/orchestrator.py), whose
    whole documented purpose is testing an operator-declared scope that
    legitimately includes RFC1918 targets (e.g. the operator's own router --
    see assert_globally_routable_target's own docstring below, which
    documents this exact carve-out for that feature). That carve-out was
    originally only applied to assert_globally_routable_target, one layer
    up -- but tls_tool.py/http_headers_tool.py/nmap_tool.py (reused by BOTH
    the Pentest Suite and the stricter per-lookup Security Assessment
    Toolkit) call THIS function unconditionally, so every Pentest Suite
    TLS/HTTP-headers/nmap-domain check against an authorized private target
    was silently failing with "not a globally-routable address" even though
    it was fully in-scope. The Pentest Suite orchestrator passes
    allow_private=True here -- only after its own _is_in_scope check has
    already authorized the target -- while the per-lookup toolkit (which
    never investigates a private target) leaves this at its default of
    False, preserving the original strict behavior for that caller.

    This exists to close a confirmed DNS-rebinding TOCTOU: assert_globally_
    routable_target below is called once, up front, by _validate_scope
    (app/core/security_assessment.py) -- but every Security Assessment
    Toolkit tool (tls_tool.py, http_headers_tool.py, nmap_tool.py) was only
    ever given the hostname *string*, and each independently re-resolved it
    at actual-connection time (a fresh, separate socket.getaddrinfo/DNS
    lookup). For a target whose DNS the caller/attacker controls (i.e. any
    domain-type IOC -- nothing stops investigating a domain the analyst
    themselves registered), a TTL=0/rapid-rebind DNS setup can legitimately
    return a safe public address for the first lookup and an internal
    address for the second, completely defeating the check. Confirmed live:
    monkeypatched socket.getaddrinfo to return 8.8.8.8 on the first
    resolution and a sibling Docker container's private address on every
    later one -- _validate_scope's one-time check passed, and tls_tool's own
    later, independent resolution then drove a real outbound TCP connect
    attempt against the private address.

    The fix is for the tool itself to resolve once and immediately use
    exactly that result, rather than trusting a separate, earlier check and
    then re-resolving blind: callers must connect to the exact address this
    function returns (passing the original `host` only for TLS SNI/
    Host-header purposes where relevant), never re-resolve `host`
    themselves for the real connection.
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not _is_permitted_address(ip, allow_private=allow_private):
            raise ValueError(
                f"{host!r} is not a globally-routable address (private/link-local/reserved) "
                "-- refusing to connect."
            )
        return host

    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {host!r}: {exc}") from exc

    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        if ip.is_loopback:
            continue
        if not _is_permitted_address(ip, allow_private=allow_private):
            raise ValueError(
                f"{host!r} resolves to {addr}, which is not a globally-routable address "
                "(private/link-local/reserved) -- refusing to connect."
            )
    # Every candidate address just resolved passed the check above --
    # deterministically pick one (sorted, not set/getaddrinfo iteration
    # order) to actually connect to, so the address that was validated is
    # the exact same address that gets used, atomically, with no second
    # resolution in between.
    return sorted(addrs)[0]


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
    operator's own router), gated by its own scope_definition instead.

    A CIDR-typed target is validated by calling this once per address in
    the (size-capped) network rather than once for the target string
    itself -- see security_assessment.py's CIDR branch of _validate_scope."""
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
