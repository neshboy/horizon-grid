"""Per-investigation runtime overrides for provider enabled/configured state
and credentials.

Every IOC provider is a long-lived module-level singleton (app/providers/
registry.py), so mutating a shared instance attribute right before calling
it would race across concurrent investigations -- investigation A could set
provider.foo, then before A's fetch() actually runs, investigation B
overwrites the same attribute on the same shared object. A ContextVar avoids
this: asyncio.create_task() copies the current context into the new task, so
every concurrent provider task spawned from one investigation's orchestrator
call sees the SAME immutable snapshot dict, while a different investigation
running at the same time (a different context) sees its own -- exactly the
"snapshot of provider configuration for each investigation" isolation the
runtime-provider architecture needs.
"""
import contextvars
from typing import Optional

_provider_overrides: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "provider_overrides", default=None
)


def set_provider_overrides(overrides: dict) -> None:
    """overrides: {provider_id: {"enabled": bool, "configured": bool, "credentials": dict}}.
    Call once, at the top of an investigation, before spawning any provider
    tasks -- see app/providers/orchestrator.py's run_all_providers()."""
    _provider_overrides.set(overrides)


def get_provider_override(provider_id: str) -> Optional[dict]:
    overrides = _provider_overrides.get()
    if overrides is None:
        return None
    return overrides.get(provider_id)


def get_credential(provider_id: str, field: str, fallback: Optional[str]) -> Optional[str]:
    """The call every provider's fetch() should use instead of
    get_settings().<field> for its own credential. Returns the active
    investigation's runtime override if one is set, else `fallback`
    (normally still get_settings().<field>, preserving legacy .env-driven
    behavior for as long as no runtime config has been seeded/configured)."""
    override = get_provider_override(provider_id)
    if override is not None and "credentials" in override:
        return override["credentials"].get(field) or fallback
    return fallback
