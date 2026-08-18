"""Unit tests for InternetIntelligenceCollector.fetch -- pins down the fix
for rate-limited crawler sources being indistinguishable from "found nothing"
(both used to collapse to ProviderStatus.NO_DATA). See app/crawler/collector.py
and app/crawler/sources/errors.py.
"""
import httpx
import pytest

from app.crawler import collector as collector_module
from app.crawler.sources.errors import SourceRateLimitedError
from app.ioc.types import IOCType
from app.providers.base import ProviderStatus


@pytest.fixture
def client():
    return httpx.AsyncClient()


async def _empty(*args, **kwargs):
    return []


async def _rate_limited(*args, **kwargs):
    raise SourceRateLimitedError("github", 403)


@pytest.mark.asyncio
async def test_all_sources_empty_is_no_data(client, monkeypatch):
    for module in collector_module._SOURCE_MODULES:
        monkeypatch.setattr(module, "search", _empty)

    result = await collector_module.internet_intelligence_provider.fetch("example.com", IOCType.DOMAIN, client)
    assert result.status == ProviderStatus.NO_DATA
    assert result.data["rate_limited_sources"] == []


@pytest.mark.asyncio
async def test_all_sources_rate_limited_is_rate_limited_not_no_data(client, monkeypatch):
    for module in collector_module._SOURCE_MODULES:
        monkeypatch.setattr(module, "search", _rate_limited)

    result = await collector_module.internet_intelligence_provider.fetch("example.com", IOCType.DOMAIN, client)
    assert result.status == ProviderStatus.RATE_LIMITED
    assert len(result.data["rate_limited_sources"]) == len(collector_module._SOURCE_MODULES)
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_partial_rate_limit_with_other_findings_still_reports_ok(client, monkeypatch):
    modules = list(collector_module._SOURCE_MODULES)
    monkeypatch.setattr(modules[0], "search", _rate_limited)

    async def _one_finding(*args, **kwargs):
        return [{"title": "t", "url": "https://example.test/1", "snippet": "", "published_at": None, "source": "x"}]

    for module in modules[1:]:
        monkeypatch.setattr(module, "search", _one_finding)

    result = await collector_module.internet_intelligence_provider.fetch("example.com", IOCType.DOMAIN, client)
    assert result.status == ProviderStatus.OK
    assert len(result.data["rate_limited_sources"]) == 1
