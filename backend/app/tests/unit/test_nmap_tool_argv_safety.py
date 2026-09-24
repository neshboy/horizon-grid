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

    async def _pretend_nmap_is_installed(self):
        return True

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fail_if_called)
    # Force is_available() to report the binary as present. This test host
    # (like most CI runners, and this one -- `which nmap` finds nothing
    # here) has no real nmap installed, so without this the is_available()
    # check that runs right after the leading-'-' rejection in nmap_tool.py
    # would ALSO short-circuit run() before any subprocess call. That would
    # make this test pass vacuously even if the leading-'-' check itself
    # were deleted or reordered after is_available() -- nothing would ever
    # reach asyncio.create_subprocess_exec either way, so the assertion
    # below wouldn't actually be exercising the behavior this test claims
    # to cover.
    monkeypatch.setattr(NmapTool, "is_available", _pretend_nmap_is_installed)
    tool = NmapTool()
    # IPV4 (not DOMAIN): this target string isn't a real hostname, and a
    # DOMAIN/HOSTNAME ioc_type would additionally route through
    # resolve_safe_address's real DNS lookup below the (hypothetically
    # missing) leading-'-' check, which would itself raise and mask a
    # regression here just as surely as is_available() would.
    await tool.run("-oX", IOCType.IPV4, "quick")
    assert called["spawned"] is False
