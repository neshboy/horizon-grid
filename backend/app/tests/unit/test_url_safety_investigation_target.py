"""Regression tests for app.core.url_safety.assert_globally_routable_target
and assert_valid_hostname_syntax -- added after overnight QA live-proved an
SSRF (a Security Assessment Toolkit target of
"http://opensearch:9200/_cluster/health" reached another Docker container's
real internal service) and an nmap argument-injection bug (a target of
"--script=vuln.example.com" was accepted and reached nmap's argv).
"""
import pytest

from app.core.url_safety import assert_globally_routable_target, assert_valid_hostname_syntax


def test_valid_hostname_syntax_accepts_real_domains():
    assert_valid_hostname_syntax("example.com")
    assert_valid_hostname_syntax("sub.example.com")
    assert_valid_hostname_syntax("a-b.example.co.uk")


@pytest.mark.parametrize(
    "value",
    ["--script=vuln.example.com", "-oX", "", "has space.com", "trailing-dot-missing-label..com"],
)
def test_valid_hostname_syntax_rejects_flag_shaped_and_malformed_values(value):
    with pytest.raises(ValueError):
        assert_valid_hostname_syntax(value)


def test_globally_routable_accepts_loopback_ip():
    """Loopback is deliberately exempt -- this codebase's own existing test
    suite already uses 127.0.0.1 as the established "scan yourself"
    pattern for this toolkit. The real exploit reached OTHER containers on
    the docker network (RFC1918 addresses), not this container's own
    loopback -- see the RFC1918/link-local rejection tests below."""
    assert_globally_routable_target("ipv4", "127.0.0.1")


def test_globally_routable_rejects_rfc1918_ip():
    with pytest.raises(ValueError, match="not a globally-routable"):
        assert_globally_routable_target("ipv4", "10.0.0.5")
    with pytest.raises(ValueError, match="not a globally-routable"):
        assert_globally_routable_target("ipv4", "192.168.1.1")


def test_globally_routable_rejects_link_local():
    with pytest.raises(ValueError, match="not a globally-routable"):
        assert_globally_routable_target("ipv4", "169.254.169.254")


def test_globally_routable_accepts_real_public_ip():
    assert_globally_routable_target("ipv4", "8.8.8.8")  # a real, stable, globally-routable address


def test_globally_routable_rejects_domain_resolving_to_a_private_internal_service(monkeypatch):
    """This is the exact shape of the live-reproduced SSRF: a domain/service
    name that resolves to another container's private (RFC1918) address on
    the docker-compose network, e.g. "opensearch" -> 172.19.0.5."""
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port: [(None, None, None, None, ("172.19.0.5", 0))]
    )
    with pytest.raises(ValueError, match="not a globally-routable"):
        assert_globally_routable_target("domain", "internal-service.local")


def test_globally_routable_accepts_domain_resolving_to_loopback(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port: [(None, None, None, None, ("127.0.0.1", 0))]
    )
    assert_globally_routable_target("domain", "self-test.local")


def test_globally_routable_rejects_flag_shaped_domain_value():
    with pytest.raises(ValueError):
        assert_globally_routable_target("domain", "--script=vuln.example.com")
