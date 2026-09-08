"""Parallel intelligence engine.

Fans a single IOC out to every registered provider concurrently, applies a
per-provider timeout + retry policy, checks/populates the Redis cache, and
yields ProviderResult objects as an async generator so the API layer can
stream results to the UI the moment each provider finishes -- callers must
not wait for the slowest provider before showing anything.
"""
import asyncio
import logging
from collections.abc import AsyncIterator

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.cache import get_cached_result, set_cached_result
from app.core.config import get_settings
from app.core.runtime_config import get_ioc_provider_snapshot
from app.core.runtime_context import set_provider_overrides
from app.ioc.types import IOCType
from app.providers.base import RETRYABLE_EXCEPTIONS, BaseProvider, ProviderCategory, ProviderResult, ProviderStatus
from app.providers.registry import get_all_providers

logger = logging.getLogger(__name__)

# Imported from base.py, not redefined here -- base.py's BaseProvider.run()
# must re-raise exactly this set (not catch it in its own generic
# except Exception) for the retry loop below to ever actually fire. See
# base.py's own comment on RETRYABLE_EXCEPTIONS for the real bug this fixes.
_RETRYABLE_EXC = RETRYABLE_EXCEPTIONS


async def _run_with_policy(
    provider: BaseProvider, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient
) -> ProviderResult:
    settings = get_settings()

    try:
        cached = await get_cached_result(provider.provider_id, ioc_type.value, ioc_value)
    except Exception as exc:  # noqa: BLE001 -- cache is best-effort; a Redis blip must not drop this provider
        logger.warning(
            "Cache read failed for %s (%s): %s -- falling back to a live fetch",
            provider.provider_id,
            ioc_value,
            exc,
        )
        cached = None
    if cached is not None:
        result = ProviderResult(
            **{
                **cached,
                "ioc_type": IOCType(cached["ioc_type"]),
                "category": ProviderCategory(cached["category"]),
                "status": ProviderStatus(cached["status"]),
            }
        )
        result.from_cache = True
        return result

    async def _attempt() -> ProviderResult:
        return await asyncio.wait_for(
            provider.run(ioc_value, ioc_type, client), timeout=settings.provider_timeout_seconds
        )

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(settings.provider_max_retries + 1),
            wait=wait_exponential(multiplier=0.5, max=4),
            retry=retry_if_exception_type(_RETRYABLE_EXC),
            reraise=True,
        ):
            with attempt:
                result = await _attempt()
    except asyncio.TimeoutError:
        result = ProviderResult(
            provider_id=provider.provider_id,
            provider_name=provider.provider_name,
            category=provider.category,
            status=ProviderStatus.TIMEOUT,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            error_message=f"Timed out after {settings.provider_timeout_seconds}s",
        )
    except _RETRYABLE_EXC as exc:
        result = ProviderResult(
            provider_id=provider.provider_id,
            provider_name=provider.provider_name,
            category=provider.category,
            status=ProviderStatus.ERROR,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            error_message=f"Connection error after retries: {exc}",
        )

    if result.status == ProviderStatus.OK:
        try:
            await set_cached_result(
                provider.provider_id, ioc_type.value, ioc_value, result.to_dict(), settings.provider_cache_ttl_seconds
            )
        except Exception as exc:  # noqa: BLE001 -- cache is best-effort; must not discard an already-fetched result
            logger.warning(
                "Cache write failed for %s (%s): %s -- returning the fetched result uncached",
                provider.provider_id,
                ioc_value,
                exc,
            )
    return result


async def run_all_providers(
    ioc_value: str, ioc_type: IOCType, providers: list[BaseProvider] | None = None
) -> AsyncIterator[ProviderResult]:
    """Yields each provider's ProviderResult as soon as it completes.

    Providers unsupported for this ioc_type are filtered out before dispatch
    rather than dispatched and short-circuited, so the UI's total-provider
    count reflects only providers that could plausibly contribute.
    """
    settings = get_settings()
    candidates = providers if providers is not None else get_all_providers()
    applicable = [p for p in candidates if p.supports(ioc_type)]

    if not applicable:
        return

    # One snapshot read per investigation, set into a ContextVar so every
    # concurrent provider task below (asyncio.create_task copies the
    # current context) sees the SAME consistent enabled/configured/
    # credentials state -- even if an administrator changes a provider's
    # config in the runtime store while this investigation is still running.
    # See app/core/runtime_context.py for why this can't just be a mutated
    # instance attribute on the (shared, singleton) provider objects.
    snapshot = await get_ioc_provider_snapshot()
    set_provider_overrides(snapshot)

    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
    async with httpx.AsyncClient(
        timeout=settings.provider_timeout_seconds, limits=limits, follow_redirects=True
    ) as client:
        tasks = {
            asyncio.create_task(_run_with_policy(p, ioc_value, ioc_type, client)): p
            for p in applicable
        }
        for finished in asyncio.as_completed(tasks):
            try:
                yield await finished
            except Exception as exc:  # noqa: BLE001 -- last-resort guard, providers already normalize errors
                logger.exception("Unhandled provider failure: %s", exc)


async def run_all_providers_collected(
    ioc_value: str, ioc_type: IOCType, providers: list[BaseProvider] | None = None
) -> list[ProviderResult]:
    """Non-streaming convenience wrapper for callers that need the full batch
    (e.g. the correlation engine and AI service, which run only after every
    provider has reported back)."""
    return [r async for r in run_all_providers(ioc_value, ioc_type, providers)]
