"""Plugin interface every intelligence provider connector implements.

New providers are added by subclassing BaseProvider, implementing `fetch`, and
registering an instance in providers/registry.py. The orchestrator never knows
about concrete providers -- it only calls this interface, which is what makes
the system extensible without touching core application code.
"""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx

from app.ioc.types import IOCType


class ProviderCategory(str, Enum):
    THREAT_INTEL = "threat_intel"
    SANDBOX = "sandbox"
    PASSIVE_DNS = "passive_dns"
    CERTIFICATE_INTEL = "certificate_intel"
    WHOIS = "whois"
    VULNERABILITY = "vulnerability"
    OSINT = "osint"
    # Active checks against the target itself (Nmap/DNS/TLS/HTTP-header
    # tools under app/security_assessment/) -- distinct from every category
    # above, which only ever queries a third party's already-collected data
    # about the target. Never registered in providers/registry.py and never
    # run by the automatic orchestrator fan-out; see app/security_assessment/.
    SECURITY_ASSESSMENT = "security_assessment"


class ProviderStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    NOT_CONFIGURED = "not_configured"
    UNSUPPORTED_IOC = "unsupported_ioc"
    NO_DATA = "no_data"
    # An administrator turned this provider off at runtime -- distinct from
    # NOT_CONFIGURED (has no key) since a provider can have a perfectly
    # valid key and still be intentionally disabled.
    DISABLED = "disabled"


@dataclass
class ProviderResult:
    """Normalized envelope returned by every provider, regardless of source shape."""

    provider_id: str
    provider_name: str
    category: ProviderCategory
    status: ProviderStatus
    ioc_value: str
    ioc_type: IOCType
    data: dict[str, Any] = field(default_factory=dict)
    raw: Any = None
    source_url: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None
    fetched_at: float = field(default_factory=time.time)
    from_cache: bool = False

    def __post_init__(self) -> None:
        # provider_results.source_url / evidence_items.source_url are both
        # VARCHAR(2048); several providers build this URL by interpolating
        # ioc_value with no length cap, and an oversized IOC value (e.g. a
        # very long URL submitted as the lookup target) previously caused an
        # uncaught StringDataRightTruncationError at insert time, which left
        # the lookup permanently stuck in RUNNING (a second commit on the
        # already-rolled-back session masked the failure instead of
        # persisting it). Truncating here protects every provider and every
        # persistence call site by construction, not just the one that broke.
        if self.source_url is not None and len(self.source_url) > 2048:
            self.source_url = self.source_url[:2048]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "category": self.category.value,
            "status": self.status.value,
            "ioc_value": self.ioc_value,
            "ioc_type": self.ioc_type.value,
            "data": self.data,
            "source_url": self.source_url,
            "error_message": self.error_message,
            "latency_ms": self.latency_ms,
            "fetched_at": self.fetched_at,
            "from_cache": self.from_cache,
        }


class BaseProvider(abc.ABC):
    """Base class for every intelligence provider connector (plugin)."""

    provider_id: str
    provider_name: str
    category: ProviderCategory
    supported_types: set[IOCType]
    requires_key: bool = True
    configured: bool = False
    base_url: str = ""

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._client = http_client

    def supports(self, ioc_type: IOCType) -> bool:
        return ioc_type in self.supported_types

    async def run(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        """Wraps fetch() with timing, unsupported/not-configured short-circuits.

        Retries/timeouts are enforced by the orchestrator (app/providers/orchestrator.py),
        which wraps this call in asyncio.wait_for + tenacity retry. Individual
        providers should not implement their own retry loops.
        """
        from app.core.runtime_context import get_provider_override

        start = time.monotonic()
        override = get_provider_override(self.provider_id)
        effective_enabled = override.get("enabled", True) if override else True
        effective_configured = (
            override.get("configured", self.configured) if override else self.configured
        )
        if not effective_enabled:
            result = ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.DISABLED,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                error_message=f"{self.provider_name} is disabled.",
            )
            result.latency_ms = int((time.monotonic() - start) * 1000)
            return result
        if not self.supports(ioc_type):
            result = ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.UNSUPPORTED_IOC,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
            )
            result.latency_ms = int((time.monotonic() - start) * 1000)
            return result
        if self.requires_key and not effective_configured:
            result = ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.NOT_CONFIGURED,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                error_message=f"{self.provider_name} is not configured (missing API key/credentials).",
            )
            result.latency_ms = int((time.monotonic() - start) * 1000)
            return result
        try:
            result = await self.fetch(ioc_value, ioc_type, client)
        except httpx.HTTPStatusError as exc:
            status = (
                ProviderStatus.RATE_LIMITED
                # 509 is PhishTank's documented over-limit response code.
                if exc.response.status_code in (429, 403, 509)
                else ProviderStatus.ERROR
            )
            result = ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=status,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                error_message=f"HTTP {exc.response.status_code}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 -- normalize any connector failure
            result = ProviderResult(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                category=self.category,
                status=ProviderStatus.ERROR,
                ioc_value=ioc_value,
                ioc_type=ioc_type,
                error_message=str(exc),
            )
        result.latency_ms = int((time.monotonic() - start) * 1000)
        return result

    @abc.abstractmethod
    async def fetch(
        self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient
    ) -> ProviderResult:
        """Perform the actual API call and return a normalized ProviderResult."""
        raise NotImplementedError
