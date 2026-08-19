"""Service layer for the Security Assessment Toolkit: validates the
mandatory scope/authorization gate, runs the selected tools, persists
findings, and feeds each tool's ProviderResult through the EXISTING
evidence/correlation/AI pipeline (summarize_provider/correlate/
generate_final_assessment) exactly as app/api/routes/lookup.py's live
investigation stream does -- never a duplicate implementation of that
logic. See app/security_assessment/ for the tool adapters themselves.
"""
import asyncio
import ipaddress
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.ai.service import generate_final_assessment, summarize_provider
from app.ai.schemas import ProviderSummary
from app.core.audit import record_audit
from app.core.db import new_session
from app.correlation.engine import correlate, merge_correlation_results
from app.evidence.builder import build_evidence
from app.evidence.loaders import correlation_from_records
from app.ioc.types import IOCType
from app.models.evidence import EvidenceItem, EvidenceType
from app.models.lookup import AISummaryRecord, CorrelationEdgeRecord, FinalAssessmentRecord, IOCLookup, ProviderResultRecord
from app.models.security_assessment import SecurityAssessmentFinding, SecurityAssessmentRun, SecurityAssessmentRunStatus
from app.providers.base import ProviderStatus
from app.scoring.engine import score_investigation
from app.security_assessment.registry import get_all_tools, get_tool

logger = logging.getLogger(__name__)

# IOC types with a network-addressable target worth scanning. Deliberately
# excludes CVE/malware-family/threat-actor/etc. -- there is nothing to send
# traffic to for those.
SCANNABLE_TYPES = {
    IOCType.IPV4.value, IOCType.IPV6.value, IOCType.DOMAIN.value, IOCType.HOSTNAME.value,
    IOCType.URL.value, IOCType.CIDR.value,
    IOCType.MD5.value, IOCType.SHA1.value, IOCType.SHA256.value, IOCType.SHA512.value,
}

_MAX_CIDR_ADDRESSES = 16  # /28 or smaller

# asyncio.create_task()'s own docs warn that a task with no other strong
# reference can be garbage-collected mid-execution -- this set (plus the
# done-callback that discards from it) is the standard workaround, keeping
# every in-flight run's task alive for as long as it's actually running.
_background_tasks: set[asyncio.Task] = set()

# Separate, run-id-keyed index onto the same tasks, so a cancel request can
# find and cancel the specific in-flight task for one run without touching
# any other concurrently-running scan. Populated/cleared alongside
# _background_tasks; a run_id present here is exactly a run that is still
# genuinely in flight in THIS process (a run "pending"/"running" in the
# database after a backend restart has no entry here at all -- see
# cancel_run()'s handling of that case).
_run_tasks: dict[uuid.UUID, asyncio.Task] = {}


def _spawn_background(coro, run_id: uuid.UUID) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    _run_tasks[run_id] = task

    def _discard(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if _run_tasks.get(run_id) is t:
            del _run_tasks[run_id]

    task.add_done_callback(_discard)
    return task


async def cancel_run(run_id: uuid.UUID, actor_user_id: Optional[uuid.UUID], actor_email: str) -> dict:
    """Cancels an in-flight run. Team-shared, like every other security-
    assessment read/write in this module (GET /runs already lets any holder
    of security_assessment:read see any other user's results) -- any caller
    with security_assessment:create can cancel any pending/running scan, not
    only their own, matching this app's existing "investigations are a
    shared operational picture" model rather than introducing a new
    per-resource ownership check found nowhere else in this codebase.

    Cancelling the asyncio.Task alone would only stop the *Python* side --
    the real nmap subprocess it's awaiting on would be silently orphaned,
    still running, until it exits on its own. Each tool that spawns a real
    subprocess is responsible for catching asyncio.CancelledError and
    actually killing that process before letting the cancellation propagate
    (see app/security_assessment/nmap_tool.py's run()) -- this function only
    triggers that, it doesn't itself know how to clean up a specific tool's
    resources.
    """
    async with new_session() as db:
        run = await db.get(SecurityAssessmentRun, run_id)
        if run is None:
            raise LookupNotFoundError(f"No such security assessment run: {run_id}")
        if run.status not in (SecurityAssessmentRunStatus.PENDING, SecurityAssessmentRunStatus.RUNNING):
            raise RunNotCancellableError(
                f"Run is already {run.status.value} -- only a pending or running scan can be cancelled."
            )
        target = run.target

    task = _run_tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()
        # Deliberately not awaited here -- the task's own cancellation
        # handling (in _execute_run's except branch below) does the actual
        # DB status update and subprocess cleanup asynchronously. Awaiting it
        # here would block this HTTP response on that cleanup completing,
        # which defeats the point of cancel being an immediate action.
    else:
        # The task isn't tracked in THIS process -- most likely the backend
        # restarted after the run was spawned (see Phase 15 of the port-
        # scanning investigation: a restart must not leave a permanently
        # "running"-forever row with no way to ever resolve it). Mark it
        # cancelled directly rather than leaving it stuck; there is no live
        # process to kill since this process never spawned one for this run.
        async with new_session() as db:
            await db.execute(
                update(SecurityAssessmentRun)
                .where(SecurityAssessmentRun.id == run_id)
                .where(SecurityAssessmentRun.status.in_([SecurityAssessmentRunStatus.PENDING, SecurityAssessmentRunStatus.RUNNING]))
                .values(status=SecurityAssessmentRunStatus.CANCELLED, completed_at=datetime.now(timezone.utc))
            )
            await db.commit()

    logger.info("Security assessment run %s cancellation requested by %r (target=%r)", run_id, actor_email, target)
    await record_audit(
        "security_assessment.run_cancelled",
        f"Cancelled a security assessment run against '{target}'.",
        actor_user_id,
        actor_email,
    )
    return {"run_id": str(run_id), "status": "cancelling"}


async def wait_for_background_runs() -> None:
    """Test-only determinism hook: awaits every currently in-flight run
    (including its post-completion _refresh_lookup_assessment step) rather
    than polling SecurityAssessmentRun.status, which flips to COMPLETED
    BEFORE that refresh step runs -- polling on status alone lets a test
    return (and its own DB-engine fixture tear down) while the background
    task is still mid-flight, corrupting whichever test runs next."""
    pending = list(_background_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


class SecurityAssessmentError(Exception):
    """Base for user-facing 4xx conditions raised by this service."""


class TargetMismatchError(SecurityAssessmentError):
    pass


class AuthorizationNotConfirmedError(SecurityAssessmentError):
    pass


class UnscannableIOCTypeError(SecurityAssessmentError):
    pass


class CIDRTooLargeError(SecurityAssessmentError):
    pass


class UnknownToolError(SecurityAssessmentError):
    pass


class UnsupportedToolForTargetError(SecurityAssessmentError):
    pass


class LookupNotFoundError(SecurityAssessmentError):
    pass


class RunNotCancellableError(SecurityAssessmentError):
    pass


def list_profiles() -> list[dict]:
    return [
        {
            "tool_id": tool.tool_id,
            "tool_name": tool.tool_name,
            "profile_id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "supported_types": sorted(t.value for t in tool.supported_types),
        }
        for tool in get_all_tools()
        for profile in tool.profiles.values()
    ]


async def get_tool_health() -> list[dict]:
    return [
        {"tool_id": tool.tool_id, "tool_name": tool.tool_name, "available": await tool.is_available()}
        for tool in get_all_tools()
    ]


def _validate_scope(lookup: IOCLookup, target_confirmation: str, authorization_confirmed: bool) -> IOCType:
    if not authorization_confirmed:
        raise AuthorizationNotConfirmedError("You must confirm you are authorized to test this target.")
    if target_confirmation != lookup.ioc_value:
        raise TargetMismatchError("target_confirmation must exactly match this investigation's target.")
    if lookup.ioc_type not in SCANNABLE_TYPES:
        raise UnscannableIOCTypeError(
            f"IOC type '{lookup.ioc_type}' has no network-addressable target to assess."
        )
    ioc_type = IOCType(lookup.ioc_type)
    if ioc_type == IOCType.CIDR:
        network = ipaddress.ip_network(lookup.ioc_value, strict=False)
        if network.num_addresses > _MAX_CIDR_ADDRESSES:
            raise CIDRTooLargeError(
                f"Active scanning is limited to {_MAX_CIDR_ADDRESSES} addresses (/28) or smaller "
                f"-- this range has {network.num_addresses}."
            )
    return ioc_type


async def start_run(
    lookup_id: uuid.UUID,
    tool_ids: list[str],
    profile_id: str,
    target_confirmation: str,
    authorization_confirmed: bool,
    actor_user_id: Optional[uuid.UUID],
    actor_email: str,
) -> dict:
    async with new_session() as db:
        lookup = await db.get(IOCLookup, lookup_id)
        if lookup is None:
            raise LookupNotFoundError(f"No such lookup: {lookup_id}")
        ioc_type = _validate_scope(lookup, target_confirmation, authorization_confirmed)

        for tool_id in tool_ids:
            tool = get_tool(tool_id)
            if tool is None:
                raise UnknownToolError(f"Unknown tool id: {tool_id!r}")
            if not tool.supports(ioc_type):
                raise UnsupportedToolForTargetError(
                    f"Tool '{tool_id}' does not support IOC type '{ioc_type.value}'."
                )

        run = SecurityAssessmentRun(
            lookup_id=lookup_id,
            requested_by=actor_user_id,
            target=target_confirmation,
            tool_ids=tool_ids,
            profile=profile_id,
            status=SecurityAssessmentRunStatus.PENDING,
            authorization_confirmed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    logger.info(
        "Security assessment run %s requested by %r: tools=%s profile=%r target=%r",
        run_id, actor_email, tool_ids, profile_id, target_confirmation,
    )
    await record_audit(
        "security_assessment.run_requested",
        f"Requested a security assessment ({', '.join(tool_ids)}, profile={profile_id!r}) against '{target_confirmation}'.",
        actor_user_id,
        actor_email,
    )

    _spawn_background(
        _execute_run(run_id, lookup_id, tool_ids, profile_id, target_confirmation, ioc_type, actor_user_id, actor_email),
        run_id,
    )
    return {"run_id": str(run_id), "status": SecurityAssessmentRunStatus.PENDING.value}


async def _execute_run(
    run_id: uuid.UUID,
    lookup_id: uuid.UUID,
    tool_ids: list[str],
    profile_id: str,
    target: str,
    ioc_type: IOCType,
    actor_user_id: Optional[uuid.UUID],
    actor_email: str,
) -> None:
    async with new_session() as db:
        await db.execute(
            update(SecurityAssessmentRun)
            .where(SecurityAssessmentRun.id == run_id)
            .values(status=SecurityAssessmentRunStatus.RUNNING, started_at=datetime.now(timezone.utc))
        )
        await db.commit()

    try:
        tool_results = []
        for tool_id in tool_ids:
            tool = get_tool(tool_id)
            tool_results.append(await tool.run(target, ioc_type, profile_id))
    except asyncio.CancelledError:
        # asyncio.CancelledError has inherited from BaseException (not
        # Exception) since Python 3.8, specifically so a generic `except
        # Exception` below would NOT catch it -- without this dedicated
        # branch, cancel_run()'s task.cancel() would propagate straight
        # through _execute_run uncaught, and this run's row would stay
        # "running" in the database forever with no way to ever resolve it,
        # even though the asyncio Task itself correctly shows as cancelled.
        # Each tool that spawns a real subprocess (nmap_tool.py) is
        # responsible for actually killing it on this same exception before
        # it propagates here -- this branch only persists the outcome.
        logger.info("Security assessment run %s was cancelled", run_id)
        async with new_session() as db:
            await db.execute(
                update(SecurityAssessmentRun)
                .where(SecurityAssessmentRun.id == run_id)
                .values(status=SecurityAssessmentRunStatus.CANCELLED, completed_at=datetime.now(timezone.utc))
            )
            await db.commit()
        await record_audit(
            "security_assessment.run_cancelled",
            f"Security assessment run against '{target}' was cancelled while in progress.",
            actor_user_id,
            actor_email,
        )
        raise  # re-raise so this Task's own .cancelled() is still accurate to asyncio
    except Exception as exc:  # noqa: BLE001 -- a tool bug must fail the run cleanly, not crash the background task
        logger.exception("Security assessment run %s failed", run_id)
        async with new_session() as db:
            await db.execute(
                update(SecurityAssessmentRun)
                .where(SecurityAssessmentRun.id == run_id)
                .values(
                    status=SecurityAssessmentRunStatus.FAILED,
                    error_message=str(exc)[:2000],
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
        await record_audit(
            "security_assessment.run_failed",
            f"Security assessment run against '{target}' failed: {exc}",
            actor_user_id,
            actor_email,
        )
        return

    async with new_session() as db:
        for result in tool_results:
            for finding in result.findings:
                db.add(
                    SecurityAssessmentFinding(
                        run_id=run_id,
                        tool_id=finding.tool_id,
                        finding_type=finding.finding_type,
                        severity=finding.severity,
                        title=finding.title,
                        description=finding.description,
                        target_detail=finding.target_detail,
                        cve_ids=finding.cve_ids,
                        evidence=finding.evidence,
                    )
                )
            db.add(
                ProviderResultRecord(
                    lookup_id=lookup_id,
                    provider_id=result.provider_result.provider_id,
                    provider_name=result.provider_result.provider_name,
                    category=result.provider_result.category.value,
                    status=result.provider_result.status.value,
                    data=result.provider_result.data,
                    source_url=result.provider_result.source_url,
                    error_message=result.provider_result.error_message,
                    latency_ms=result.provider_result.latency_ms,
                )
            )
        await db.execute(
            update(SecurityAssessmentRun)
            .where(SecurityAssessmentRun.id == run_id)
            .values(status=SecurityAssessmentRunStatus.COMPLETED, completed_at=datetime.now(timezone.utc))
        )
        await db.commit()

    finding_count = sum(len(r.findings) for r in tool_results)
    # Previously the ONLY trace of a successful run (including a real nmap
    # scan) was this audit row in Postgres -- `docker logs` showed the
    # initial POST /run request and then nothing, with no way to tell from
    # the log stream alone whether the run ever finished, succeeded, or what
    # it found.
    logger.info(
        "Security assessment run %s completed: %d finding(s) across %d tool(s) against %r",
        run_id, finding_count, len(tool_ids), target,
    )
    await record_audit(
        "security_assessment.run_completed",
        f"Security assessment run against '{target}' completed: {finding_count} finding(s) across {len(tool_ids)} tool(s).",
        actor_user_id,
        actor_email,
    )

    try:
        await _refresh_lookup_assessment(lookup_id, target, [r.provider_result for r in tool_results], actor_user_id)
    except Exception:  # noqa: BLE001 -- findings are already durable; a refresh failure must not look like the scan itself failed
        logger.exception("Failed to refresh lookup %s's final assessment after security assessment run %s", lookup_id, run_id)


async def _refresh_lookup_assessment(
    lookup_id: uuid.UUID, ioc_value: str, new_results: list, actor_user_id: Optional[uuid.UUID]
) -> None:
    """Feeds the new tool ProviderResults through the same
    summarize_provider() -> correlate() -> generate_final_assessment()
    pipeline the original investigation used, merges the result with what
    was already persisted (never discarding existing evidence), and
    promotes the refreshed assessment to primary -- new active-scan
    findings are new evidence about the investigation, not merely an
    alternate AI opinion the way reanalyze_lookup()'s backend-comparison
    re-runs are.

    Also this call site's whole reason for existing: folds every
    SecurityAssessmentFinding ever recorded for this lookup (across every
    run, not just the one that just completed -- a lookup accumulates
    findings over multiple scans) into the deterministic score
    (app/scoring/engine.py), so a critical/high finding actually moves
    risk_score/confidence_score the way the Security Assessment Toolkit's
    own purpose requires. Provider votes/correlation-edge evidence are read
    from EVERY ProviderResultRecord persisted for this lookup (original
    threat-intel providers AND every prior security-assessment tool run --
    `_execute_run` above already committed this run's own results as
    ProviderResultRecord rows before calling this function, so querying all
    of them here picks those up too without needing `new_results` passed in
    separately for scoring)."""
    async with new_session() as db:
        lookup = await db.get(IOCLookup, lookup_id)
        if lookup is None:
            return
        ioc_type_str = lookup.ioc_type

        existing_summary_rows = (
            await db.execute(
                select(AISummaryRecord).where(
                    AISummaryRecord.lookup_id == lookup_id, AISummaryRecord.provider_id.is_not(None)
                )
            )
        ).scalars().all()
        existing_summaries = []
        for row in existing_summary_rows:
            try:
                existing_summaries.append(ProviderSummary.model_validate(row.summary))
            except Exception:  # noqa: BLE001
                continue

        existing_edges = (
            await db.execute(select(CorrelationEdgeRecord).where(CorrelationEdgeRecord.lookup_id == lookup_id))
        ).scalars().all()
        existing_correlation = correlation_from_records(lookup, existing_edges)

        # Every provider result ever persisted for this lookup -- see docstring above for why this
        # (rather than just `new_results`) is what the scoring engine needs.
        all_provider_results = (
            await db.execute(select(ProviderResultRecord).where(ProviderResultRecord.lookup_id == lookup_id))
        ).scalars().all()

        security_runs = (
            await db.execute(
                select(SecurityAssessmentRun)
                .where(SecurityAssessmentRun.lookup_id == lookup_id)
                .options(selectinload(SecurityAssessmentRun.findings))
            )
        ).scalars().all()
        security_finding_severities = [
            finding.severity.value for run in security_runs for finding in run.findings
        ]

    new_summaries = []
    for result in new_results:
        if result.status != ProviderStatus.OK:
            continue
        summary = await summarize_provider(ioc_value, ioc_type_str, result)
        new_summaries.append(summary)
        async with new_session() as db:
            db.add(AISummaryRecord(lookup_id=lookup_id, provider_id=result.provider_id, summary=summary.model_dump()))
            await db.commit()

    new_correlation = correlate(ioc_value, IOCType(ioc_type_str), new_results)
    merged_correlation = merge_correlation_results(existing_correlation, new_correlation)
    scoring = score_investigation(all_provider_results, merged_correlation, security_finding_severities)

    async with new_session() as db:
        for edge in new_correlation.edges:
            db.add(
                CorrelationEdgeRecord(
                    lookup_id=lookup_id,
                    source_type=edge.source.split(":", 1)[0],
                    source_value=edge.source.split(":", 1)[1],
                    target_type=edge.target.split(":", 1)[0],
                    target_value=edge.target.split(":", 1)[1],
                    relationship_type=edge.relationship,
                    confidence=edge.confidence,
                    provenance=edge.provenance,
                    provenance_category=edge.provenance_category,
                )
            )
        await db.commit()

        for record in build_evidence(new_results, new_summaries, new_correlation):
            db.add(
                EvidenceItem(
                    lookup_id=lookup_id,
                    evidence_type=EvidenceType(record.evidence_type),
                    source_label=record.source_label,
                    provider_id=record.provider_id,
                    claim=record.claim,
                    interpretation=record.interpretation,
                    confidence=record.confidence,
                    related_ioc_type=record.related_ioc_type,
                    related_ioc_value=record.related_ioc_value,
                    source_url=record.source_url,
                    observed_at=record.observed_at,
                    raw_data=record.raw_data,
                    provenance_category=record.provenance_category,
                )
            )
        await db.commit()

    all_summaries = existing_summaries + new_summaries
    _UNAVAILABLE_REASONS = {
        ProviderStatus.ERROR.value: "error contacting the provider",
        ProviderStatus.TIMEOUT.value: "timed out",
        ProviderStatus.RATE_LIMITED.value: "rate limited",
        ProviderStatus.NOT_CONFIGURED.value: "not configured (no API key)",
        ProviderStatus.DISABLED.value: "disabled by the administrator",
    }
    unavailable = [
        {"provider_id": r.provider_id, "reason": _UNAVAILABLE_REASONS[r.status.value]}
        for r in new_results
        if r.status.value in _UNAVAILABLE_REASONS
    ]

    final = await generate_final_assessment(
        ioc_value, ioc_type_str, all_summaries, merged_correlation, scoring, unavailable_providers=unavailable
    )

    async with new_session() as db:
        await db.execute(
            update(FinalAssessmentRecord)
            .where(FinalAssessmentRecord.lookup_id == lookup_id, FinalAssessmentRecord.is_primary.is_(True))
            .values(is_primary=False)
        )
        db.add(
            FinalAssessmentRecord(
                lookup_id=lookup_id,
                ai_backend=final.ai_backend or "unknown",
                ai_model=final.ai_model,
                ai_outcome=final.ai_outcome or "unknown",
                is_primary=True,
                assessment=final.model_dump(),
                requested_by=actor_user_id,
            )
        )
        lookup = await db.get(IOCLookup, lookup_id)
        lookup.final_verdict = final.final_verdict
        lookup.risk_score = final.risk.overall_risk_score
        lookup.confidence_score = final.risk.confidence_score
        lookup.final_assessment = final.model_dump()
        await db.commit()
