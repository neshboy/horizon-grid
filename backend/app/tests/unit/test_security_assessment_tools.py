"""Unit tests for the Security Assessment Toolkit's tool adapters --
focused on the safety-critical guarantees: no dangerous flag ever reaches
a real nmap invocation, severity is assigned deterministically (never by
asking the AI), and every tool degrades to a normal ERROR/TIMEOUT result
rather than raising.
"""
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.core.url_safety import resolve_safe_address
from app.ioc.types import IOCType
from app.security_assessment.hash_tool import hash_tool
from app.security_assessment.http_headers_tool import http_headers_tool
from app.security_assessment.nmap_tool import _PROFILE_ARGS, _severity_for_cves, nmap_tool
from app.security_assessment.tls_tool import tls_tool
from app.providers.base import ProviderStatus

# --- Nmap: the profile allowlist itself is the safety boundary ---------------

_FORBIDDEN_FLAGS = ["--script", "-O", "-sS", "-sU", "-D", "-f", "--source-port", "-T0", "-T1"]


def test_every_nmap_profile_excludes_every_forbidden_flag():
    for profile_id, args in _PROFILE_ARGS.items():
        for forbidden in _FORBIDDEN_FLAGS:
            assert forbidden not in args, f"profile {profile_id!r} must never include {forbidden!r}"


def test_nmap_profiles_are_plain_argument_lists_not_strings():
    for profile_id, args in _PROFILE_ARGS.items():
        assert isinstance(args, list), f"profile {profile_id!r} must be a list, never a shell string"
        assert all(isinstance(a, str) for a in args)


@pytest.mark.asyncio
async def test_nmap_unknown_profile_is_rejected_before_any_subprocess():
    result = await nmap_tool.run("127.0.0.1", IOCType.IPV4, "totally-made-up-profile")
    assert result.provider_result.status == ProviderStatus.ERROR
    assert result.findings == []


def _fake_completed_process():
    """A mock asyncio.subprocess.Process reporting a clean, empty scan --
    only argv construction is under test here, not XML parsing."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(b"<nmaprun></nmaprun>", b""))
    proc.returncode = 0
    return proc


@pytest.mark.asyncio
async def test_nmap_adds_the_dash_6_flag_for_an_ipv6_target():
    """Without "-6", nmap treats an IPv6 literal as malformed, prints a
    warning to stderr, and exits 0 having scanned 0 hosts -- confirmed live
    to be silently reported as a normal "completed, 0 findings" result,
    indistinguishable from a genuine clean scan, even though
    NmapTool.supported_types has always claimed IPv6 support.

    is_available() is mocked too (not just create_subprocess_exec): this
    test must not depend on the real environment actually having the nmap
    binary installed -- confirmed live to fail exactly this way in CI's
    bare "unit" job runner (no Docker image, no apt-installed nmap), where
    is_available() genuinely returns False and the code returns before ever
    reaching create_subprocess_exec, leaving the mock uncalled."""
    with patch("app.security_assessment.nmap_tool.NmapTool.is_available", new=AsyncMock(return_value=True)), \
         patch("app.security_assessment.nmap_tool.asyncio.create_subprocess_exec", new=AsyncMock(return_value=_fake_completed_process())) as mock_exec:
        await nmap_tool.run("::1", IOCType.IPV6, "quick")
    argv = mock_exec.call_args.args
    assert "-6" in argv, f"expected -6 in argv for an IPv6 target, got: {argv}"


@pytest.mark.asyncio
async def test_nmap_does_not_add_the_dash_6_flag_for_an_ipv4_target():
    with patch("app.security_assessment.nmap_tool.NmapTool.is_available", new=AsyncMock(return_value=True)), \
         patch("app.security_assessment.nmap_tool.asyncio.create_subprocess_exec", new=AsyncMock(return_value=_fake_completed_process())) as mock_exec:
        await nmap_tool.run("127.0.0.1", IOCType.IPV4, "quick")
    argv = mock_exec.call_args.args
    assert "-6" not in argv, f"-6 should never be added for a non-IPv6 target, got: {argv}"


def test_severity_for_cves_empty_is_low():
    assert _severity_for_cves([]) == "low"


def test_severity_for_cves_critical_score():
    assert _severity_for_cves([{"cvss_score": 9.8, "cvss_severity": "CRITICAL"}]) == "critical"


def test_severity_for_cves_high_score():
    assert _severity_for_cves([{"cvss_score": 7.5, "cvss_severity": "HIGH"}]) == "high"


def test_severity_for_cves_medium_score():
    assert _severity_for_cves([{"cvss_score": 4.0, "cvss_severity": "MEDIUM"}]) == "medium"


def test_severity_for_cves_takes_the_worst_of_several():
    cves = [{"cvss_score": 2.0, "cvss_severity": "LOW"}, {"cvss_score": 9.9, "cvss_severity": "CRITICAL"}]
    assert _severity_for_cves(cves) == "critical"


# --- Hash tool -----------------------------------------------------------


@pytest.mark.asyncio
async def test_hash_tool_identifies_well_formed_sha256():
    value = "a" * 64
    result = await hash_tool.run(value, IOCType.SHA256, "standard")
    assert result.provider_result.status == ProviderStatus.OK
    assert result.findings[0].severity == "info"
    assert result.findings[0].evidence["well_formed_hex"] is True
    assert result.findings[0].evidence["algorithm"] == "SHA-256"


@pytest.mark.asyncio
async def test_hash_tool_flags_non_hex_characters():
    value = "g" * 32  # right length for MD5, but 'g' is not hex
    result = await hash_tool.run(value, IOCType.MD5, "standard")
    assert result.findings[0].evidence["well_formed_hex"] is False


@pytest.mark.asyncio
async def test_hash_tool_never_uploads_or_executes_anything():
    """Structural guarantee: the tool's run() signature takes only the hash
    string, never a file path or file bytes -- there is no way to pass it
    a file to execute even by mistake."""
    import inspect

    sig = inspect.signature(hash_tool.run)
    assert list(sig.parameters) == ["target", "ioc_type", "profile_id"]


# --- HTTP headers tool -----------------------------------------------------
#
# "example.test" is not a real resolvable domain (confirmed live: a real
# socket.getaddrinfo lookup for it raises "Name or service not known"), so
# every test below monkeypatches socket.getaddrinfo to resolve it to a
# fixed, real, globally-routable address (8.8.8.8, the same address the
# existing app.core.url_safety test suite already uses as its own "real,
# stable, globally-routable address" convention) -- required now that
# http_headers_tool.py actually resolves its target once, up front, via
# resolve_safe_address (see the DNS-rebinding-TOCTOU section further below)
# instead of handing httpx a raw hostname it never itself needed to
# resolve. respx's mock is keyed on that same resolved address, since that
# -- not the original hostname -- is what the real outbound request now
# targets.


def _mock_dns_resolves_to(monkeypatch, addr: str) -> None:
    import socket as socket_module

    monkeypatch.setattr(socket_module, "getaddrinfo", lambda host, port: [(None, None, None, None, (addr, 0))])


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_flags_missing_hsts_on_https(monkeypatch):
    _mock_dns_resolves_to(monkeypatch, "8.8.8.8")
    respx.get("https://8.8.8.8/").mock(return_value=httpx.Response(200, headers={}))
    result = await http_headers_tool.run("example.test", IOCType.DOMAIN, "standard")
    assert result.provider_result.status == ProviderStatus.OK
    severities = {f.finding_type: f.severity for f in result.findings}
    assert severities.get("missing_hsts") == "low"
    assert severities.get("missing_csp") == "info"


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_all_present_yields_no_missing_findings(monkeypatch):
    _mock_dns_resolves_to(monkeypatch, "8.8.8.8")
    respx.get("https://8.8.8.8/").mock(
        return_value=httpx.Response(
            200,
            headers={
                "Strict-Transport-Security": "max-age=63072000",
                "Content-Security-Policy": "default-src 'self'",
                "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff",
            },
        )
    )
    result = await http_headers_tool.run("example.test", IOCType.DOMAIN, "standard")
    finding_types = {f.finding_type for f in result.findings}
    assert "missing_hsts" not in finding_types
    assert "missing_csp" not in finding_types
    assert "missing_frame_protection" not in finding_types
    assert "headers_ok" in finding_types


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_reports_verbose_server_header(monkeypatch):
    _mock_dns_resolves_to(monkeypatch, "8.8.8.8")
    respx.get("https://8.8.8.8/").mock(
        return_value=httpx.Response(200, headers={"Server": "Apache/2.4.49"})
    )
    result = await http_headers_tool.run("example.test", IOCType.DOMAIN, "standard")
    verbose = [f for f in result.findings if f.finding_type == "verbose_server_header"]
    assert len(verbose) == 1
    assert verbose[0].severity == "info"


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_preserves_original_host_header_and_sni_when_pinned(monkeypatch):
    """The real outbound connection must target the resolved IP address
    (asserted elsewhere), but the HTTP Host header and TLS SNI hostname
    sent on the wire must still be the ORIGINAL hostname -- otherwise a
    virtual-hosted target would silently receive the wrong site's response
    and any real TLS certificate would fail to verify against a bare IP
    literal."""
    _mock_dns_resolves_to(monkeypatch, "8.8.8.8")
    route = respx.get("https://8.8.8.8/").mock(return_value=httpx.Response(200, headers={}))
    await http_headers_tool.run("example.test", IOCType.DOMAIN, "standard")
    sent_request = route.calls.last.request
    assert sent_request.url.host == "8.8.8.8"
    assert sent_request.headers["host"] == "example.test"
    assert sent_request.extensions.get("sni_hostname") == "example.test"


# --- TLS tool: DNS-rebinding TOCTOU (confirmed P1 SSRF) ---------------------
#
# app/core/security_assessment.py's _validate_scope resolves a domain/
# hostname/URL target's hostname exactly ONCE, well before this tool ever
# runs (a separately-scheduled background task) -- but tls_tool.py used to
# independently re-resolve the same hostname itself, completely
# unsynchronized with that earlier check, via a plain
# socket.create_connection((host, port)) call that resolves `host` fresh.
# A target whose DNS the caller controls (any domain-type IOC -- nothing
# stops investigating a domain the analyst themselves registered) can
# return a safe public address for the earlier check and a private/
# internal address for this tool's own later, real connection (a TTL=0/
# rapid DNS rebind). Live-reproduced by monkeypatching socket.getaddrinfo
# to return a real public IP (8.8.8.8) on the first resolution and a
# sibling Docker container's private address (172.19.0.5) on every later
# one: _validate_scope's one-time check passed, and the tool's own,
# separate resolution then drove a real outbound TCP connect attempt
# against the private address. Fixed by app/core/url_safety.py's
# resolve_safe_address, which tls_tool.py's _connect_sync now calls to
# resolve `host` exactly once and pin the real connection to that same,
# just-validated address -- see that function's docstring.


@pytest.mark.asyncio
async def test_tls_tool_refuses_to_connect_to_a_resolved_private_address(monkeypatch):
    """Core regression: if the hostname currently resolves to a private/
    internal address, the tool must refuse before ever attempting the real
    TCP connect. Pre-fix, _connect_sync called socket.create_connection
    unconditionally with the raw hostname and no safety check at all, so
    the fake create_connection below would have been reached."""
    import socket as socket_module

    monkeypatch.setattr(
        socket_module, "getaddrinfo", lambda host, port: [(None, None, None, None, ("172.19.0.5", 0))]
    )

    connect_calls = []

    def _fake_create_connection(address, timeout=None):
        connect_calls.append(address)
        raise OSError("should never be reached for an unsafe resolved address")

    monkeypatch.setattr(socket_module, "create_connection", _fake_create_connection)

    result = await tls_tool.run("rebind-test.example.invalid", IOCType.DOMAIN, "standard")

    assert connect_calls == [], f"tool attempted a real connection despite an unsafe resolved address: {connect_calls}"
    assert result.provider_result.status == ProviderStatus.ERROR
    assert "not a globally-routable" in result.provider_result.error_message
    assert result.findings == []


@pytest.mark.asyncio
async def test_tls_tool_pins_the_connection_to_the_resolved_address_despite_a_later_dns_rebind(monkeypatch):
    """Live-reproduced DNS-rebinding TOCTOU, exactly as confirmed: the same
    hostname resolves to a real public address on the FIRST DNS lookup and
    a private/internal address on every SUBSEQUENT lookup (simulating a
    TTL=0 rebind). The tool must perform exactly one resolution for the
    whole run and connect only to that one validated address -- never a
    later, independent lookup of the same hostname."""
    import socket as socket_module

    resolutions = []

    def _fake_getaddrinfo(host, port):
        addr = "8.8.8.8" if not resolutions else "172.19.0.5"
        resolutions.append(addr)
        return [(None, None, None, None, (addr, 0))]

    connect_targets = []

    def _fake_create_connection(address, timeout=None):
        connect_targets.append(address[0])
        raise OSError("simulated: no real network access in this test")

    monkeypatch.setattr(socket_module, "getaddrinfo", _fake_getaddrinfo)
    monkeypatch.setattr(socket_module, "create_connection", _fake_create_connection)

    result = await tls_tool.run("rebind-test.example.invalid", IOCType.DOMAIN, "standard")

    assert resolutions == ["8.8.8.8"], f"expected exactly one DNS resolution for the whole run, got {resolutions}"
    assert connect_targets == ["8.8.8.8"], (
        f"the real TCP connect must target the address that was actually validated, not a "
        f"later independent (possibly rebound) resolution -- got {connect_targets}"
    )
    assert result.provider_result.status == ProviderStatus.ERROR


# --- Nmap tool: DNS-rebinding TOCTOU (confirmed P2, same class as tls_tool
# above) -----------------------------------------------------------------
#
# app/core/url_safety.py's resolve_safe_address docstring claims this fix
# ("the tool itself resolves once and immediately uses exactly that
# result") applies to tls_tool.py, http_headers_tool.py, AND nmap_tool.py --
# but nmap_tool.py used to build argv=[..., target] with the raw hostname
# and let the real nmap binary perform its own, later, independent DNS
# resolution, never calling resolve_safe_address at all (confirmed via
# `grep -rn resolve_safe_address backend/app/security_assessment/`, which
# matched only tls_tool.py). A target whose DNS the caller controls (any
# domain/hostname-type IOC) could return a safe public address for
# app/core/security_assessment.py's one-time _validate_scope check and a
# private/internal address for nmap's own later resolution -- the exact
# TOCTOU tls_tool.py was fixed for.


@pytest.mark.asyncio
async def test_nmap_resolves_domain_target_once_and_scans_the_resolved_address(monkeypatch):
    """Simulates a TTL=0 rebind: the domain resolves to a real public
    address on the FIRST DNS lookup (this fix's own resolve_safe_address
    call) and a private/internal address on every SUBSEQUENT lookup (what
    the real nmap binary would have performed itself, pre-fix, at actual
    scan time). Only one resolution must ever happen, and nmap's argv must
    receive that exact validated address, never the raw hostname."""
    import socket as socket_module

    resolutions = []

    def _fake_getaddrinfo(host, port):
        addr = "8.8.8.8" if not resolutions else "172.19.0.5"
        resolutions.append(addr)
        return [(None, None, None, None, (addr, 0))]

    monkeypatch.setattr(socket_module, "getaddrinfo", _fake_getaddrinfo)

    with patch("app.security_assessment.nmap_tool.NmapTool.is_available", new=AsyncMock(return_value=True)), \
         patch("app.security_assessment.nmap_tool.asyncio.create_subprocess_exec", new=AsyncMock(return_value=_fake_completed_process())) as mock_exec:
        await nmap_tool.run("rebind-test.example.invalid", IOCType.DOMAIN, "quick")

    assert resolutions == ["8.8.8.8"], f"expected exactly one DNS resolution for the whole run, got {resolutions}"
    argv = mock_exec.call_args.args
    assert argv[-1] == "8.8.8.8", (
        f"nmap must scan the address that was actually validated, never re-resolve the "
        f"hostname itself -- argv: {argv}"
    )
    assert "rebind-test.example.invalid" not in argv


@pytest.mark.asyncio
async def test_nmap_refuses_to_scan_a_domain_currently_resolving_to_a_private_address(monkeypatch):
    """Core regression: if the hostname currently resolves to a private/
    internal address, the tool must refuse before ever spawning the real
    nmap subprocess."""
    import socket as socket_module

    monkeypatch.setattr(
        socket_module, "getaddrinfo", lambda host, port: [(None, None, None, None, ("172.19.0.5", 0))]
    )

    with patch("app.security_assessment.nmap_tool.NmapTool.is_available", new=AsyncMock(return_value=True)), \
         patch("app.security_assessment.nmap_tool.asyncio.create_subprocess_exec", new=AsyncMock(return_value=_fake_completed_process())) as mock_exec:
        result = await nmap_tool.run("rebind-test.example.invalid", IOCType.DOMAIN, "quick")

    assert not mock_exec.called, "nmap must never be spawned once the resolved address fails the safety check"
    assert result.provider_result.status == ProviderStatus.ERROR
    assert "not a globally-routable" in result.provider_result.error_message
    assert result.findings == []


# --- HTTP headers tool: DNS-rebinding TOCTOU (confirmed P2, same class as
# tls_tool above) ----------------------------------------------------------
#
# http_headers_tool.py used to call httpx.AsyncClient().get(url) directly
# with the raw hostname, letting httpx perform its own, later, independent
# DNS resolution -- never calling resolve_safe_address at all, despite
# being named in that function's own docstring as a tool this exact fix
# applies to.


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_pins_the_connection_to_the_resolved_address_despite_a_later_dns_rebind(monkeypatch):
    """Simulates a TTL=0 rebind: the domain resolves to a real public
    address on the FIRST DNS lookup and a private/internal address on
    every SUBSEQUENT lookup (what httpx's own connection-time resolution
    would have used, pre-fix). Only one resolution must ever happen, and
    the real HTTP request must target that exact validated address."""
    import socket as socket_module

    resolutions = []

    def _fake_getaddrinfo(host, port):
        addr = "8.8.8.8" if not resolutions else "172.19.0.5"
        resolutions.append(addr)
        return [(None, None, None, None, (addr, 0))]

    monkeypatch.setattr(socket_module, "getaddrinfo", _fake_getaddrinfo)
    route = respx.get("https://8.8.8.8/").mock(return_value=httpx.Response(200, headers={}))

    result = await http_headers_tool.run("rebind-test.example.invalid", IOCType.DOMAIN, "standard")

    assert resolutions == ["8.8.8.8"], f"expected exactly one DNS resolution for the whole run, got {resolutions}"
    assert route.called
    sent_request = route.calls.last.request
    assert sent_request.url.host == "8.8.8.8", "the real HTTP connection must target the validated address"
    assert result.provider_result.status == ProviderStatus.OK


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_refuses_to_connect_to_a_domain_currently_resolving_to_a_private_address(monkeypatch):
    """Core regression: if the hostname currently resolves to a private/
    internal address, the tool must refuse before ever making the real
    outbound HTTP request."""
    import socket as socket_module

    monkeypatch.setattr(
        socket_module, "getaddrinfo", lambda host, port: [(None, None, None, None, ("172.19.0.5", 0))]
    )
    route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200))

    result = await http_headers_tool.run("rebind-test.example.invalid", IOCType.DOMAIN, "standard")

    assert not route.called, "must never attempt the real HTTP request once the resolved address fails the safety check"
    assert result.provider_result.status == ProviderStatus.ERROR
    assert "not a globally-routable" in result.provider_result.error_message
    assert result.findings == []


# --- Confirmed P1: a caller-declared port must actually be used ------------
#
# app/pentest/orchestrator.py's PentestTarget/AddTargetRequest/TargetResponse
# all expose a `port` field, but neither tool ever consulted anything but
# its own hardcoded default (443 for tls_tool, 443 falling back to 80 for
# http_headers_tool) -- a Pentest Suite target explicitly declared on a
# non-default port (e.g. 172.19.0.4:9200, a real reachable HTTP service
# confirmed live) was silently probed on the wrong port, producing a false
# "completed, 0 findings" negative indistinguishable from a genuinely clean
# scan. Fixed by adding an optional `port` keyword to both tools' run() --
# defaulted to None so every existing caller (including the per-lookup
# Security Assessment Toolkit, which never sets it) is unaffected.


@pytest.mark.asyncio
async def test_tls_tool_connects_to_the_caller_supplied_port_not_the_hardcoded_default():
    import socket as socket_module

    connect_targets = []

    def _fake_create_connection(address, timeout=None):
        connect_targets.append(address)
        raise OSError("simulated: no real network access in this test")

    with patch.object(socket_module, "create_connection", _fake_create_connection):
        result = await tls_tool.run("8.8.8.8", IOCType.IPV4, "standard", port=9200)

    assert connect_targets and connect_targets[0][1] == 9200, (
        f"expected the real TCP connect to target the caller-declared port 9200, got {connect_targets}"
    )
    assert result.provider_result.status == ProviderStatus.ERROR


@pytest.mark.asyncio
async def test_tls_tool_defaults_to_443_when_no_port_is_supplied():
    """No behavior change for the existing (port-less) call shape every
    other caller still uses."""
    import socket as socket_module

    connect_targets = []

    def _fake_create_connection(address, timeout=None):
        connect_targets.append(address)
        raise OSError("simulated: no real network access in this test")

    with patch.object(socket_module, "create_connection", _fake_create_connection):
        await tls_tool.run("8.8.8.8", IOCType.IPV4, "standard")

    assert connect_targets and connect_targets[0][1] == 443, connect_targets


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_tool_connects_to_the_caller_supplied_port_not_the_hardcoded_default():
    route = respx.get("https://8.8.8.8:9200/").mock(return_value=httpx.Response(200, headers={}))

    result = await http_headers_tool.run("8.8.8.8", IOCType.IPV4, "standard", port=9200)

    assert route.called, "the real HTTP request must target the caller-declared port, not the hardcoded default"
    assert result.provider_result.status == ProviderStatus.OK
    assert result.provider_result.data["checked_url"] == "https://8.8.8.8:9200"


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_tool_falls_back_to_http_on_the_same_caller_supplied_port():
    """The existing https-fails-so-retry-plain-http fallback must keep
    retrying on the SAME declared port, never silently swap to the
    unrelated default port 80."""
    respx.get("https://8.8.8.8:9200/").mock(side_effect=httpx.ConnectError("refused"))
    route = respx.get("http://8.8.8.8:9200/").mock(return_value=httpx.Response(200, headers={}))

    result = await http_headers_tool.run("8.8.8.8", IOCType.IPV4, "standard", port=9200)

    assert route.called, "the http fallback must retry on the same declared port (9200), not port 80"
    assert result.provider_result.status == ProviderStatus.OK
    assert result.provider_result.data["checked_url"] == "http://8.8.8.8:9200"


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_tool_defaults_to_443_then_80_when_no_port_is_supplied():
    """No behavior change for the existing (port-less) call shape every
    other caller (the per-lookup Security Assessment Toolkit) still uses."""
    respx.get("https://8.8.8.8/").mock(side_effect=httpx.ConnectError("refused"))
    route = respx.get("http://8.8.8.8/").mock(return_value=httpx.Response(200, headers={}))

    result = await http_headers_tool.run("8.8.8.8", IOCType.IPV4, "standard")

    assert route.called
    assert result.provider_result.status == ProviderStatus.OK
    assert result.provider_result.data["checked_url"] == "http://8.8.8.8"


# --- Confirmed P1: the Pentest Suite's own scope-authorized RFC1918 targets
# were unconditionally rejected --------------------------------------------
#
# resolve_safe_address (app/core/url_safety.py) enforces a strict
# "globally-routable-or-loopback-only" policy designed for the per-lookup
# Security Assessment Toolkit, whose targets are threat-intel IOCs that
# should never resolve anywhere internal. But tls_tool.py/http_headers_
# tool.py/nmap_tool.py call that SAME function unconditionally, and those
# are the exact tool adapters the Pentest Suite (app/pentest/orchestrator.py)
# reuses -- whose whole documented purpose (see that module's own docstring)
# is testing an operator-declared scope that legitimately includes RFC1918
# targets (e.g. the operator's own router). Live-reproduced pre-fix: a
# Pentest assessment scoped to an operator's own 192.168.1.0/24 LAN got
# ProviderStatus.ERROR ("not a globally-routable address ... refusing to
# connect") from tls_tool and http_headers_tool for every single in-scope
# private target, every time, with no way to ever get a real finding.
#
# Fixed by threading an `allow_private` keyword through resolve_safe_address
# and every tool that calls it, defaulted to False everywhere so the
# per-lookup Security Assessment Toolkit's behavior (reject any private
# target outright) is completely unchanged -- only the Pentest Suite
# orchestrator, and only after its own _is_in_scope authorization check,
# ever passes allow_private=True.


def test_resolve_safe_address_default_still_rejects_an_rfc1918_ip():
    """No behavior change for the existing (allow_private-less) call shape
    every other caller (the per-lookup Security Assessment Toolkit) still
    uses."""
    with pytest.raises(ValueError, match="not a globally-routable"):
        resolve_safe_address("192.168.1.1")


def test_resolve_safe_address_allow_private_accepts_an_rfc1918_ip():
    assert resolve_safe_address("192.168.1.1", allow_private=True) == "192.168.1.1"


def test_resolve_safe_address_allow_private_still_rejects_link_local():
    """Link-local (169.254.0.0/16) -- where every major cloud provider's
    instance-metadata service lives -- must stay blocked even for the
    Pentest Suite: it is never a legitimate RFC1918 pentest target, so
    allow_private must not be read as "allow literally anything private"."""
    with pytest.raises(ValueError, match="not a globally-routable"):
        resolve_safe_address("169.254.169.254", allow_private=True)


@pytest.mark.asyncio
async def test_tls_tool_default_refuses_an_rfc1918_ip_target():
    """Exact reproduction of the confirmed finding: a STANDARD/COMPREHENSIVE
    Pentest profile dispatches tls_tool against a raw private IPv4 target."""
    result = await tls_tool.run("192.168.1.1", IOCType.IPV4, "standard")

    assert result.provider_result.status == ProviderStatus.ERROR
    assert "not a globally-routable" in result.provider_result.error_message
    assert result.findings == []


@pytest.mark.asyncio
async def test_tls_tool_allow_private_lets_an_rfc1918_ip_target_reach_the_real_connect():
    """With allow_private=True (what the Pentest Suite orchestrator now
    passes for an already scope-authorized target), the tool must get PAST
    resolve_safe_address and attempt the real TCP connect against the
    private address -- never short-circuit with the globally-routable-only
    ValueError."""
    import socket as socket_module

    connect_targets = []

    def _fake_create_connection(address, timeout=None):
        connect_targets.append(address)
        raise OSError("simulated: no real network access in this test")

    with patch.object(socket_module, "create_connection", _fake_create_connection):
        result = await tls_tool.run("192.168.1.1", IOCType.IPV4, "standard", allow_private=True)

    assert connect_targets == [("192.168.1.1", 443)], connect_targets
    assert result.provider_result.status == ProviderStatus.ERROR
    assert "not a globally-routable" not in (result.provider_result.error_message or "")


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_tool_default_refuses_an_rfc1918_ip_target():
    """Exact reproduction of the confirmed finding: a STANDARD/COMPREHENSIVE
    Pentest profile dispatches http_headers_tool against a raw private IPv4
    target."""
    route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200))

    result = await http_headers_tool.run("192.168.1.1", IOCType.IPV4, "standard")

    assert not route.called, "must never attempt the real HTTP request once resolve_safe_address refuses"
    assert result.provider_result.status == ProviderStatus.ERROR
    assert "not a globally-routable" in result.provider_result.error_message
    assert result.findings == []


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_tool_allow_private_lets_an_rfc1918_ip_target_reach_the_real_request():
    """With allow_private=True (what the Pentest Suite orchestrator now
    passes for an already scope-authorized target), the tool must get PAST
    resolve_safe_address and make the real outbound HTTP request against
    the private address."""
    route = respx.get("https://192.168.1.1/").mock(return_value=httpx.Response(200, headers={}))

    result = await http_headers_tool.run("192.168.1.1", IOCType.IPV4, "standard", allow_private=True)

    assert route.called, "the real HTTP request must be attempted against the private address"
    assert result.provider_result.status == ProviderStatus.OK
    assert result.findings  # real findings were produced, not a scope/safety error


@pytest.mark.asyncio
async def test_nmap_allow_private_lets_a_domain_resolving_privately_reach_the_real_scan():
    """Mirrors test_nmap_refuses_to_scan_a_domain_currently_resolving_to_a_
    private_address above, but with allow_private=True: nmap_tool only
    consults resolve_safe_address for DOMAIN/HOSTNAME targets (an IPV4/IPV6
    literal never calls it at all -- see the confirmed finding's own
    reproduction), so this is the one shape where the Pentest Suite's fix
    actually changes nmap's behavior."""
    import socket as socket_module

    monkeypatch_addr = "192.168.1.1"
    with patch.object(socket_module, "getaddrinfo", lambda host, port: [(None, None, None, None, (monkeypatch_addr, 0))]), \
         patch("app.security_assessment.nmap_tool.NmapTool.is_available", new=AsyncMock(return_value=True)), \
         patch("app.security_assessment.nmap_tool.asyncio.create_subprocess_exec", new=AsyncMock(return_value=_fake_completed_process())) as mock_exec:
        result = await nmap_tool.run("rebind-test.example.invalid", IOCType.DOMAIN, "quick", allow_private=True)

    assert mock_exec.called, "nmap must actually be spawned once allow_private=True permits the resolved private address"
    argv = mock_exec.call_args.args
    assert argv[-1] == monkeypatch_addr
    assert result.provider_result.status != ProviderStatus.ERROR


# --- HTTP headers tool: SSRF-via-redirect (confirmed, distinct from the
# DNS-rebinding-TOCTOU section above) ---------------------------------------
#
# Real gap found live during overnight QA: this tool's httpx client used to
# use follow_redirects=True and re-validate/re-pin nothing on any hop past
# the first, so a target that redirected to an internal/private address (or
# a cloud metadata endpoint) would be fetched for real, completely
# bypassing the globally-routable-target check the caller already ran
# against the ORIGINAL target. Fixed by _get_with_validated_redirects,
# which manually follows redirects and re-runs the exact same
# resolve+validate+pin step (_pin_to_resolved_address) on every hop,
# including the first -- so these tests mock DNS via the same
# _mock_dns_resolves_to helper (and respx routes on the RESOLVED address,
# never the hostname) as the DNS-rebinding-TOCTOU tests above, since the
# real outbound connection for every hop now targets that pinned address.


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_refuses_to_follow_a_redirect_to_a_private_address(monkeypatch):
    """Only the FIRST hop is mocked here on purpose: if a regression makes
    the tool actually follow the malicious redirect, respx has no route
    registered for it and this test fails loudly instead of silently
    succeeding. The redirect target (169.254.169.254) is an IP literal, so
    no second DNS mock is needed for it -- resolve_safe_address rejects it
    directly, and link-local stays blocked even though it is technically
    within Python's broader `is_private` classification (see
    resolve_safe_address's own docstring)."""
    _mock_dns_resolves_to(monkeypatch, "8.8.8.8")
    respx.get("https://8.8.8.8/").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    )
    result = await http_headers_tool.run("example.test", IOCType.DOMAIN, "standard")
    assert result.provider_result.status == ProviderStatus.ERROR
    assert "refusing to follow" in (result.provider_result.error_message or "").lower()


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_follows_a_redirect_to_a_globally_routable_address(monkeypatch):
    """The fix must not break the ordinary, legitimate case -- a redirect to
    a real, globally-routable host is still followed, re-validated, and
    re-pinned exactly like the first hop, and inspected normally. Both hops
    resolve to the same fixed address here (this test is about redirect-
    following correctness, not DNS-rebinding -- see the dedicated TOCTOU
    section above for that); respx routes are therefore registered against
    that resolved address, not the "example.test" hostname, mirroring
    test_http_headers_pins_the_connection_to_the_resolved_address_despite_a_later_dns_rebind
    above."""
    _mock_dns_resolves_to(monkeypatch, "93.184.216.34")
    respx.get("https://93.184.216.34/").mock(
        return_value=httpx.Response(302, headers={"location": "https://example.test/final"})
    )
    respx.get("https://93.184.216.34/final").mock(
        return_value=httpx.Response(200, headers={"Strict-Transport-Security": "max-age=63072000"})
    )
    result = await http_headers_tool.run("example.test", IOCType.DOMAIN, "standard")
    assert result.provider_result.status == ProviderStatus.OK
    assert result.provider_result.data["checked_url"] == "https://example.test/final"
