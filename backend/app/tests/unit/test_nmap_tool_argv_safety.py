"""Regression test for app.security_assessment.nmap_tool's leading-'-'
rejection -- added after overnight QA live-proved a target of
"--script=vuln.example.com" was accepted and reached nmap's real argv,
where nmap's own argument parser (not a shell) treated the leading '-' as
a flag rather than a hostname and successfully loaded a real NSE script
category, contradicting this module's own documented "no code path to
--script" safety invariant.
"""
import pytest

from app.ioc.types import IOCType
from app.providers.base import ProviderStatus
from app.security_assessment.nmap_tool import NmapTool


@pytest.mark.asyncio
async def test_target_starting_with_dash_is_rejected_before_building_argv():
    tool = NmapTool()
    result = await tool.run("--script=vuln.example.com", IOCType.DOMAIN, "quick")
    assert result.provider_result.status == ProviderStatus.ERROR
    assert result.findings == []
    assert "refus" in (result.provider_result.error_message or "").lower()


@pytest.mark.asyncio
async def test_target_starting_with_dash_never_spawns_a_subprocess(monkeypatch):
    import asyncio

    called = {"spawned": False}

    async def _fail_if_called(*args, **kwargs):
        called["spawned"] = True
        raise AssertionError("nmap subprocess must never be spawned for a '-'-prefixed target")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fail_if_called)
    tool = NmapTool()
    await tool.run("-oX", IOCType.DOMAIN, "quick")
    assert called["spawned"] is False
