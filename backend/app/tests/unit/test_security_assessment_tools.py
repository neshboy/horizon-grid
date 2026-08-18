"""Unit tests for the Security Assessment Toolkit's tool adapters --
focused on the safety-critical guarantees: no dangerous flag ever reaches
a real nmap invocation, severity is assigned deterministically (never by
asking the AI), and every tool degrades to a normal ERROR/TIMEOUT result
rather than raising.
"""
import httpx
import pytest
import respx

from app.ioc.types import IOCType
from app.security_assessment.hash_tool import hash_tool
from app.security_assessment.http_headers_tool import http_headers_tool
from app.security_assessment.nmap_tool import _PROFILE_ARGS, _severity_for_cves, nmap_tool
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


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_flags_missing_hsts_on_https():
    respx.get("https://example.test/").mock(return_value=httpx.Response(200, headers={}))
    result = await http_headers_tool.run("example.test", IOCType.DOMAIN, "standard")
    assert result.provider_result.status == ProviderStatus.OK
    severities = {f.finding_type: f.severity for f in result.findings}
    assert severities.get("missing_hsts") == "low"
    assert severities.get("missing_csp") == "info"


@pytest.mark.asyncio
@respx.mock
async def test_http_headers_all_present_yields_no_missing_findings():
    respx.get("https://example.test/").mock(
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
async def test_http_headers_reports_verbose_server_header():
    respx.get("https://example.test/").mock(
        return_value=httpx.Response(200, headers={"Server": "Apache/2.4.49"})
    )
    result = await http_headers_tool.run("example.test", IOCType.DOMAIN, "standard")
    verbose = [f for f in result.findings if f.finding_type == "verbose_server_header"]
    assert len(verbose) == 1
    assert verbose[0].severity == "info"
