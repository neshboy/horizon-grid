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
    except Exception:  # noqa: BLE001 -- real gap found live during overnight QA: a Redis outage on
        # the READ side used to propagate straight out of this function uncaught, which
        # run_all_providers only ever logs and otherwise drops -- so a Redis blip took down
        # this provider's result ENTIRELY for this investigation instead of degrading to a
        # normal cache miss (still make the real call, just don't serve/save a cached one).
        logger.exception("Cache read failed for provider %s (ioc=%r) -- proceeding without cache", provider.provider_id, ioc_value)
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
            provider.run(ioc_value, ioc_type, client),
            # Real gap found live during overnight QA: this used the exact
            # same duration as the httpx client's own per-request timeout
            # below, so on a genuinely slow (not hung) request, this
            # asyncio-level cancellation and httpx's own internal timeout
            # raced to fire first. asyncio.TimeoutError winning that race
            # is caught OUTSIDE the retry loop (see below) -- it never goes
            # through AsyncRetrying at all, unlike httpx.ReadTimeout/
            # ConnectTimeout, which do. A small buffer here means httpx's
            # own (retryable) timeout reliably gets first refusal, so the
            # configured retry policy actually runs instead of being
            # starved by a coin-flip against this outer safety net.
            timeout=settings.provider_timeout_seconds + 1,
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
        except Exception:  # noqa: BLE001 -- a Redis outage on the WRITE side must not discard an already-real, already-successful result
            logger.exception("Cache write failed for provider %s (ioc=%r) -- result still returned", provider.provider_id, ioc_value)
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
        # Real gap found live during overnight QA: asyncio.as_completed()'s
        # own iterator yields internal wrapper coroutines, not the original
        # Task objects, so the previous `for finished in
        # asyncio.as_completed(tasks): ... tasks[finished]`-shaped code
        # could never actually look its own provider back up from this
        # dict -- the `tasks` values existed but were unreachable, and a
        # failure log had no way to say which provider/IOC it was about.
        # asyncio.wait()'s done/pending sets ARE the real Task objects, so
        # `tasks[task]` here genuinely resolves.
        pending = set(tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    provider = tasks[task]
                    try:
                        yield task.result()
                    except Exception as exc:  # noqa: BLE001 -- last-resort guard, providers already normalize errors
                        logger.exception(
                            "Unhandled provider failure: provider=%s ioc=%r: %s", provider.provider_id, ioc_value, exc
                        )
        finally:
            # Real gap found live during overnight QA: if this generator is
            # abandoned early (the caller stops iterating -- e.g. a client
            # disconnects mid-SSE-stream), the still-running provider tasks
            # were never cancelled. Each one kept making a real outbound
            # request (burning API quota/sockets/CPU) for a result nobody
            # would ever consume. A GeneratorExit thrown into this
            # generator on early abandonment lands here via this finally,
            # same as a normal or exceptional exit.
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)


async def run_all_providers_collected(
    ioc_value: str, ioc_type: IOCType, providers: list[BaseProvider] | None = None
) -> list[ProviderResult]:
    """Non-streaming convenience wrapper for callers that need the full batch
    (e.g. the correlation engine and AI service, which run only after every
    provider has reported back)."""
    return [r async for r in run_all_providers(ioc_value, ioc_type, providers)]
