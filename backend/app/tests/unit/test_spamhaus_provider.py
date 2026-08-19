"""Unit tests for the Spamhaus DBL/ZEN connector's query-error handling.

Real, confirmed bug: a query-error DNS response (Spamhaus rejecting the
QUERY itself -- e.g. "public/open resolver not permitted", a common
condition for any container/cloud deployment using default DNS) was
previously classified identically to a real listing, reporting
verdict="malicious" for domains that were never actually checked. Confirmed
live against a real Docker container: example.org (IANA's reserved,
universally-benign example domain) came back "malicious" purely because the
container's DNS resolver got rejected by Spamhaus as a public resolver.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.ioc.types import IOCType
from app.providers.base import ProviderStatus
from app.providers.stubs.spamhaus import spamhaus_provider


def _mock_getaddrinfo(addresses: list[str]):
    return AsyncMock(return_value=[(None, None, None, None, (addr, 0)) for addr in addresses])


@pytest.mark.asyncio
async def test_no_dns_answer_is_reported_clean():
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock(side_effect=__import__("socket").gaierror())
        result = await spamhaus_provider.fetch("example.org", IOCType.DOMAIN, client=None)
    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "clean"
    assert result.data["listed"] is False


@pytest.mark.asyncio
async def test_a_real_listing_code_is_reported_malicious():
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo(["127.0.1.5"])  # real "malware domain" code
        result = await spamhaus_provider.fetch("evil.example", IOCType.DOMAIN, client=None)
    assert result.status == ProviderStatus.OK
    assert result.data["verdict"] == "malicious"
    assert result.data["listed"] is True
    assert "127.0.1.5" in result.data["return_codes"]


@pytest.mark.asyncio
async def test_query_error_code_is_never_reported_as_malicious():
    """The exact bug: previously this returned verdict='malicious' for a
    domain that was never actually checked -- Spamhaus only rejected the
    query itself (public/open resolver), a condition reproduced live via a
    real Docker container's default DNS."""
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo(["127.255.255.254"])
        result = await spamhaus_provider.fetch("example.org", IOCType.DOMAIN, client=None)
    assert result.data["verdict"] != "malicious"
    assert result.data["verdict"] == "unknown"
    assert result.data["listed"] is False
    assert result.status == ProviderStatus.ERROR
    assert "reject" in result.error_message.lower() or "query" in result.error_message.lower()


@pytest.mark.asyncio
async def test_query_error_code_for_ip_zen_lookup_is_also_never_malicious():
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo(["127.255.255.255"])
        result = await spamhaus_provider.fetch("8.8.8.8", IOCType.IPV4, client=None)
    assert result.data["verdict"] == "unknown"
    assert result.data["listed"] is False


@pytest.mark.asyncio
async def test_a_real_listing_mixed_with_a_query_error_code_still_reports_the_real_listing():
    """If Spamhaus somehow returns both a real listing code and an error
    code in the same answer set, the real listing must win -- it's genuine
    evidence and shouldn't be discarded just because an unrelated error
    code was also present."""
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = _mock_getaddrinfo(["127.0.1.5", "127.255.255.254"])
        result = await spamhaus_provider.fetch("evil.example", IOCType.DOMAIN, client=None)
    assert result.data["verdict"] == "malicious"
    assert result.data["return_codes"] == ["127.0.1.5"]
