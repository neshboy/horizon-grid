"""Unit tests for app.core.runtime_context -- the ContextVar-based mechanism
that lets per-investigation provider overrides reach individual connectors
without mutating shared state on the long-lived provider singletons (see the
module's own docstring for why a shared mutable attribute would race across
concurrent investigations). These tests exist specifically to catch a
regression back to that race, which would not show up in any test that only
runs one investigation at a time.
"""
import asyncio

import pytest

from app.core.runtime_context import get_credential, get_provider_override, set_provider_overrides


def test_no_override_set_returns_none():
    async def _run():
        return get_provider_override("virustotal")

    assert asyncio.run(_run()) is None


def test_get_credential_falls_back_when_no_override_set():
    async def _run():
        return get_credential("virustotal", "api_key", "fallback-value")

    assert asyncio.run(_run()) == "fallback-value"


def test_get_credential_returns_override_value_when_set():
    async def _run():
        set_provider_overrides({"virustotal": {"enabled": True, "configured": True, "credentials": {"api_key": "override-value"}}})
        return get_credential("virustotal", "api_key", "fallback-value")

    assert asyncio.run(_run()) == "override-value"


def test_get_credential_falls_back_when_override_field_missing():
    async def _run():
        set_provider_overrides({"virustotal": {"enabled": True, "configured": True, "credentials": {}}})
        return get_credential("virustotal", "api_key", "fallback-value")

    assert asyncio.run(_run()) == "fallback-value"


@pytest.mark.asyncio
async def test_concurrent_tasks_see_isolated_overrides_not_each_others():
    """The exact scenario the whole ContextVar design exists to prevent:
    two "investigations" running concurrently, each setting a DIFFERENT
    override for the same provider_id, must never observe the other's
    value -- this is what a shared instance attribute on the (singleton)
    provider object would get wrong."""

    async def investigation(tag: str, delay: float) -> str:
        set_provider_overrides({"virustotal": {"enabled": True, "configured": True, "credentials": {"api_key": tag}}})
        await asyncio.sleep(delay)  # yield control -- lets the other task run and (if buggy) clobber shared state
        return get_credential("virustotal", "api_key", "unset")

    result_a, result_b = await asyncio.gather(
        investigation("investigation-A-key", 0.05),
        investigation("investigation-B-key", 0.01),
    )
    assert result_a == "investigation-A-key"
    assert result_b == "investigation-B-key"


@pytest.mark.asyncio
async def test_override_set_in_parent_propagates_to_child_task():
    """asyncio.create_task() copies the current context -- this is the
    exact mechanism app/providers/orchestrator.py relies on: it sets the
    override ONCE before spawning per-provider tasks, and every task must
    see it without having to pass it through every function signature."""
    set_provider_overrides({"otx": {"enabled": False, "configured": True, "credentials": {"api_key": "parent-set-value"}}})

    async def child_task() -> str:
        return get_credential("otx", "api_key", "unset")

    result = await asyncio.create_task(child_task())
    assert result == "parent-set-value"
