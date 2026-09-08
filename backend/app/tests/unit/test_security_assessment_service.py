"""Unit tests for app.core.security_assessment's scope/authorization gate
(_validate_scope) -- the mandatory safety check every run must pass BEFORE
any tool is ever invoked. Tested directly against SimpleNamespace fakes,
mirroring this session's established pattern for testing a mechanism
directly rather than through incidental side effects."""
from types import SimpleNamespace

import pytest

from app.core.security_assessment import (
    AuthorizationNotConfirmedError,
    CIDRTooLargeError,
    InvalidTargetError,
    TargetMismatchError,
    UnsafeTargetError,
    UnscannableIOCTypeError,
    _validate_scope,
)
from app.ioc.types import IOCType


def _lookup(ioc_value: str, ioc_type: str):
    return SimpleNamespace(ioc_value=ioc_value, ioc_type=ioc_type)


def test_rejects_when_authorization_not_confirmed():
    lookup = _lookup("1.2.3.4", "ipv4")
    with pytest.raises(AuthorizationNotConfirmedError):
        _validate_scope(lookup, "1.2.3.4", False)


def test_rejects_when_target_confirmation_does_not_match():
    lookup = _lookup("1.2.3.4", "ipv4")
    with pytest.raises(TargetMismatchError):
        _validate_scope(lookup, "5.6.7.8", True)


def test_rejects_unscannable_ioc_type():
    lookup = _lookup("CVE-2021-44228", "cve")
    with pytest.raises(UnscannableIOCTypeError):
        _validate_scope(lookup, "CVE-2021-44228", True)


def test_accepts_matching_confirmation_for_a_scannable_type():
    lookup = _lookup("1.2.3.4", "ipv4")
    assert _validate_scope(lookup, "1.2.3.4", True) == IOCType.IPV4


def test_accepts_a_small_cidr_at_exactly_the_cap():
    # 8.8.8.0/28 -- exactly 16 addresses, all within Google's globally-
    # routable 8.8.8.0/24 block (same address family this suite already
    # uses elsewhere, e.g. test_accepts_a_real_globally_routable_ipv4_target,
    # as the established "known-public" test range). Must NOT be an RFC1918
    # range here: a private range would now (correctly) be rejected by the
    # routability check added below -- see
    # test_rejects_a_private_rfc1918_cidr_target for that; this test's own
    # intent is only the SIZE boundary, so it uses a public range to isolate
    # that.
    lookup = _lookup("8.8.8.0/28", "cidr")
    assert _validate_scope(lookup, "8.8.8.0/28", True) == IOCType.CIDR


def test_rejects_a_cidr_larger_than_the_cap():
    lookup = _lookup("8.8.8.0/27", "cidr")  # 32 addresses -- over the /28 cap
    with pytest.raises(CIDRTooLargeError):
        _validate_scope(lookup, "8.8.8.0/27", True)


def test_rejects_a_private_rfc1918_cidr_target():
    """Real gap found live during overnight QA: every OTHER scannable type
    (IPv4/IPv6/domain/hostname/URL) was already checked for global
    routability -- CIDR was not, so a CIDR-typed lookup could target this
    platform's own docker-compose network (e.g. a real "172.19.0.0/28")
    and nmap would genuinely scan other containers on it."""
    lookup = _lookup("10.0.0.0/28", "cidr")  # exactly 16 addresses, but RFC1918
    with pytest.raises(UnsafeTargetError):
        _validate_scope(lookup, "10.0.0.0/28", True)


def test_accepts_a_loopback_cidr_target():
    """Loopback is exempt from the CIDR routability check too, mirroring
    the same exemption already established for single IPv4/IPv6 targets."""
    lookup = _lookup("127.0.0.0/28", "cidr")
    assert _validate_scope(lookup, "127.0.0.0/28", True) == IOCType.CIDR


def test_authorization_is_checked_before_target_mismatch():
    """Order matters for a clear error message: an unconfirmed request
    should say so, not report a target mismatch that may not even be true."""
    lookup = _lookup("1.2.3.4", "ipv4")
    with pytest.raises(AuthorizationNotConfirmedError):
        _validate_scope(lookup, "wrong-target", False)


def test_malformed_cidr_value_raises_a_clean_error_not_a_raw_valueerror():
    """A lookup can only reach ioc_type=cidr with a malformed ioc_value via
    the pre-existing lookup-creation ioc_type_hint override (which doesn't
    itself validate value-matches-hint) -- confirmed live to otherwise raise
    an uncaught ValueError here, surfacing as a raw 500 instead of the clean
    400 every other validation failure in this function produces."""
    lookup = _lookup("not-a-real-network; touch /tmp/pwned", "cidr")
    with pytest.raises(InvalidTargetError):
        _validate_scope(lookup, "not-a-real-network; touch /tmp/pwned", True)


# --- Real bugs found live during overnight QA: SSRF (a "url"-typed target
# of "http://opensearch:9200/_cluster/health" reached another Docker
# container's real internal service with zero destination check) and
# nmap argument injection (a "domain"-typed target of
# "--script=vuln.example.com" reached nmap's real argv). Both root-caused
# to this function only ever format/destination-validating the CIDR IOC
# type -- IPV4/IPV6/DOMAIN/HOSTNAME/URL got none at all. ---


def test_accepts_loopback_ipv4_target():
    """Loopback is deliberately exempt from the SSRF blocklist -- this
    codebase's own existing integration test suite already uses 127.0.0.1
    as the established "scan yourself" pattern for this toolkit (e.g.
    test_security_assessment_api.py's real nmap runs). The real exploit
    reached OTHER containers' private addresses via service-name
    resolution, not this container's own loopback."""
    lookup = _lookup("127.0.0.1", "ipv4")
    assert _validate_scope(lookup, "127.0.0.1", True) == IOCType.IPV4


def test_rejects_private_rfc1918_ipv4_target():
    lookup = _lookup("172.19.0.5", "ipv4")
    with pytest.raises(UnsafeTargetError):
        _validate_scope(lookup, "172.19.0.5", True)


def test_accepts_a_real_globally_routable_ipv4_target():
    lookup = _lookup("8.8.8.8", "ipv4")
    assert _validate_scope(lookup, "8.8.8.8", True) == IOCType.IPV4


def test_rejects_flag_shaped_domain_value_before_any_dns_lookup():
    """This is the exact live-reproduced nmap argument-injection payload --
    must be rejected on syntax alone, before assert_globally_routable_target
    would even attempt to resolve it."""
    lookup = _lookup("--script=vuln.example.com", "domain")
    with pytest.raises(InvalidTargetError):
        _validate_scope(lookup, "--script=vuln.example.com", True)


def test_rejects_url_target_resolving_to_internal_docker_service(monkeypatch):
    """This is the exact live-reproduced SSRF: a url-typed target naming an
    internal Docker Compose service, which resolves inside the backend
    container to another container's real internal address."""
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port: [(None, None, None, None, ("172.19.0.5", 0))]
    )
    lookup = _lookup("http://opensearch:9200/_cluster/health", "url")
    with pytest.raises(UnsafeTargetError):
        _validate_scope(lookup, "http://opensearch:9200/_cluster/health", True)


def test_rejects_a_private_rfc1918_cidr_target():
    """Regression test for the CIDR-typed sibling of the SSRF bug above:
    _validate_scope's CIDR branch size-checked the network but never called
    assert_globally_routable_target the way the IPV4/IPV6/DOMAIN/HOSTNAME/
    URL branch does. Confirmed live: a lookup of ioc_value='172.19.0.0/28'
    (auto-detected as ioc_type=cidr by app/ioc/detector.py for any value
    containing '/' that parses as a network -- no special hint needed) was
    accepted by _validate_scope and went on to a real nmap scan of this
    deployment's own docker-compose subnet, returning genuine open ports
    (Postgres, etc.) on sibling containers as if they were an external
    finding. A CIDR-typed target must be rejected exactly like a directly
    IPV4/IPV6-typed one would be for the same underlying address range."""
    lookup = _lookup("172.19.0.0/28", "cidr")
    with pytest.raises(UnsafeTargetError):
        _validate_scope(lookup, "172.19.0.0/28", True)
