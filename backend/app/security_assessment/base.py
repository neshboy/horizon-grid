"""Shared contract every security-assessment tool implements.

Deliberately separate from app/providers/base.py's BaseProvider: that
class's run() wrapper is built around the automatic, always-on orchestrator
fan-out (disabled/not-configured short-circuits driven by DB-backed runtime
config, see app/providers/orchestrator.py). Tools here are never auto-run --
only ever invoked through an explicit, authorization-gated call
(app/api/routes/security_assessment.py) -- and are often materially slower
(a real scan, not a single HTTP call), so they get their own thin wrapper
instead of BaseProvider's.

Every tool still PRODUCES a genuine ProviderResult (ToolRunResult.provider_result)
so its data flows through the existing summarize_provider()/correlate()/
generate_final_assessment() pipeline (app/ai/service.py,
app/correlation/engine.py) with zero changes to that pipeline's own code --
confirmed by direct research before this package was written.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional

from app.ioc.types import IOCType
from app.providers.base import ProviderCategory, ProviderResult, ProviderStatus


@dataclass(frozen=True)
class ScanProfile:
    """One named, fixed, server-defined argument set for a tool. Callers
    (the API, the frontend) only ever select a profile by `id` -- there is
    no path from user input to a raw command string or raw flags anywhere
    in this package."""

    id: str
    name: str
    description: str


@dataclass
class Finding:
    """Mirrors app/models/security_assessment.py's SecurityAssessmentFinding
    columns minus run_id (assigned by the caller once the parent
    SecurityAssessmentRun row exists). Severity is assigned by the tool
    itself using fixed, documented, deterministic rules -- never "ask the
    AI" -- see each tool module's own severity-rule docstring."""

    tool_id: str
    finding_type: str
    severity: str  # Severity value (app/models/security_assessment.py)
    title: str
    description: str
    target_detail: Optional[str] = None
    cve_ids: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolRunResult:
    """What every tool adapter's run() returns: the generic envelope that
    flows unchanged through the existing AI/correlation pipeline, plus the
    structured findings for persistence and UI drill-down."""

    provider_result: ProviderResult
    findings: list[Finding]


class SecurityAssessmentTool(abc.ABC):
    """Base class for every active-check tool."""

    tool_id: str
    tool_name: str
    supported_types: set[IOCType]
    category: ProviderCategory = ProviderCategory.SECURITY_ASSESSMENT
    profiles: dict[str, ScanProfile] = {}

    def supports(self, ioc_type: IOCType) -> bool:
        return ioc_type in self.supported_types

    async def is_available(self) -> bool:
        """Overridden by tools with an external binary dependency (Nmap).
        Pure-Python tools (DNS/TLS/HTTP-headers/vuln-intel/hash) are always
        available -- surfaced via GET /api/v1/security-assessment/tool-health."""
        return True

    @abc.abstractmethod
    async def run(self, target: str, ioc_type: IOCType, profile_id: str) -> ToolRunResult:
        """Executes the check and returns a normalized result. Must never
        raise for an ordinary failure (unreachable target, timeout, missing
        binary) -- catch it and return a ProviderResult with an ERROR/TIMEOUT
        status and error_message set instead, exactly like
        BaseProvider.run() does, so one tool's failure never aborts the
        others in the same run."""
        raise NotImplementedError

    def _result(
        self,
        target: str,
        ioc_type: IOCType,
        status: ProviderStatus,
        *,
        data: Optional[dict] = None,
        raw: Any = None,
        error_message: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> ProviderResult:
        return ProviderResult(
            provider_id=self.tool_id,
            provider_name=self.tool_name,
            category=self.category,
            status=status,
            ioc_value=target,
            ioc_type=ioc_type,
            data=data or {},
            raw=raw,
            error_message=error_message,
            source_url=source_url,
        )

    def _error(self, target: str, ioc_type: IOCType, status: ProviderStatus, message: str) -> ToolRunResult:
        return ToolRunResult(provider_result=self._result(target, ioc_type, status, error_message=message), findings=[])
