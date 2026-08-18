"""Unit tests for the WHOIS half of app/providers/whois_rdap.py -- pins down
the fix for socket-level failures (timeout, connection refused) being mapped
to ProviderStatus.NO_DATA identically to a genuine "domain has no WHOIS
record" response, which misleadingly implied the domain might be unregistered.
"""
import socket

import pytest
from whois.exceptions import PywhoisError

from app.ioc.types import IOCType
from app.providers.base import ProviderStatus
from app.providers.whois_rdap import WhoisRdapProvider


@pytest.fixture
def provider():
    return WhoisRdapProvider()


@pytest.mark.asyncio
async def test_socket_timeout_maps_to_timeout_not_no_data(provider, monkeypatch):
    def _raise(*args, **kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr("app.providers.whois_rdap.pywhois.whois", _raise)
    result = await provider._fetch_whois("example.test", IOCType.DOMAIN)
    assert result.status == ProviderStatus.TIMEOUT
    assert "timed out" in result.error_message


@pytest.mark.asyncio
async def test_connection_refused_maps_to_error_not_no_data(provider, monkeypatch):
    def _raise(*args, **kwargs):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr("app.providers.whois_rdap.pywhois.whois", _raise)
    result = await provider._fetch_whois("example.test", IOCType.DOMAIN)
    assert result.status == ProviderStatus.ERROR


@pytest.mark.asyncio
async def test_dns_resolution_failure_maps_to_error(provider, monkeypatch):
    def _raise(*args, **kwargs):
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr("app.providers.whois_rdap.pywhois.whois", _raise)
    result = await provider._fetch_whois("example.test", IOCType.DOMAIN)
    assert result.status == ProviderStatus.ERROR


@pytest.mark.asyncio
async def test_unparseable_tld_response_maps_to_no_data(provider, monkeypatch):
    def _raise(*args, **kwargs):
        raise PywhoisError("could not parse whois output")

    monkeypatch.setattr("app.providers.whois_rdap.pywhois.whois", _raise)
    result = await provider._fetch_whois("example.test", IOCType.DOMAIN)
    assert result.status == ProviderStatus.NO_DATA


@pytest.mark.asyncio
async def test_no_domain_name_in_response_maps_to_no_data(provider, monkeypatch):
    monkeypatch.setattr("app.providers.whois_rdap.pywhois.whois", lambda *a, **k: {})
    result = await provider._fetch_whois("example.test", IOCType.DOMAIN)
    assert result.status == ProviderStatus.NO_DATA


@pytest.mark.asyncio
async def test_successful_lookup_maps_to_ok(provider, monkeypatch):
    monkeypatch.setattr(
        "app.providers.whois_rdap.pywhois.whois",
        lambda *a, **k: {"domain_name": "EXAMPLE.TEST", "registrar": "Example Registrar"},
    )
    result = await provider._fetch_whois("example.test", IOCType.DOMAIN)
    assert result.status == ProviderStatus.OK
    assert result.data["registrar"] == "Example Registrar"
