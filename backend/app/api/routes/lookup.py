"""The core lookup endpoint: detect IOC type, fan out to every provider in
parallel, stream results to the client via Server-Sent Events as each
provider finishes, then run correlation + AI summarization and stream those
too. This is the single endpoint the frontend's search box drives.
"""
import asyncio
import csv
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal
from xml.sax import saxutils

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.schemas import ProviderSummary
from app.ai.service import generate_final_assessment, summarize_provider
from app.auth.rbac import CurrentUser, require_permission
from app.core.cache import RateLimiter
from app.core.config import get_settings
from app.core.db import get_db, new_session
from app.core import runtime_config as runtime_config_svc
from app.correlation.engine import correlate
from app.evidence.builder import build_evidence
from app.evidence.loaders import correlation_from_records
from app.ioc.detector import detect_ioc_type, value_matches_ioc_type
from app.ioc.types import IOCType
from app.models.evidence import EvidenceItem, EvidenceType
from app.models.lookup import (
    AISummaryRecord,
    CorrelationEdgeRecord,
    FinalAssessmentRecord,
    IOCLookup,
    LookupStatus,
    ProviderResultRecord,
)
from app.models.security_assessment import SecurityAssessmentRun
from app.providers.base import ProviderStatus
from app.providers.orchestrator import run_all_providers
from app.providers.registry import get_all_providers
from app.schemas.lookup import LookupCreateRequest
from app.scoring.engine import score_investigation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/lookup", tags=["lookup"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/stream")
async def stream_lookup(
    payload: LookupCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("lookup:create")),
):
    """Streams the full lookup lifecycle as SSE events:
    `detected` -> N x `provider_result` -> N x `provider_summary` -> `correlation` -> `final_assessment` -> `done`.
    The frontend renders provider cards incrementally as `provider_result`/`provider_summary` events arrive,
    keyed by `provider_id` in each event -- not by arrival order. Every `provider_result` for an OK provider
    kicks off that provider's AI summarization concurrently in the background (see the comment inside
    event_stream() below), so `provider_summary` events arrive in AI-completion order once every provider
    result is in, not necessarily immediately after their matching `provider_result`.
    """
    # Real P2 bug found live: an unrecognized ai_backend (typo, or a
    # caller/attacker-chosen string -- this route only requires
    # "lookup:create") used to sail through entirely unvalidated as
    # backend_override into summarize_provider/generate_final_assessment,
    # which silently ran the analysis on Ollama anyway (app/ai/service.py's
    # _build_client fallback) while persisting the bogus string verbatim
    # into FinalAssessmentRecord.ai_backend -- the field this platform relies
    # on for AI-result traceability. Rejecting it here, before any provider
    # calls/DB writes happen, matches the same AI_BACKENDS check already
    # used for POST /runtime/ai-providers/{backend} (app/api/routes/runtime.py).
    if payload.ai_backend is not None and payload.ai_backend not in runtime_config_svc.AI_BACKENDS:
        raise HTTPException(status_code=400, detail=f"Unknown AI backend {payload.ai_backend!r}")

    settings = get_settings()
    limiter = RateLimiter(
        f"lookup_create:{user.id}",
        max_calls=settings.lookup_rate_limit_max_calls,
        window_seconds=settings.lookup_rate_limit_window_seconds,
    )
    if not await limiter.allow():
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: max {settings.lookup_rate_limit_max_calls} lookups per "
                f"{settings.lookup_rate_limit_window_seconds}s. Each lookup fans out to every provider "
                "plus the crawler and multiple AI calls, so this bounds cost/load per user."
            ),
        )

    ioc_value = payload.value.strip()
    # Field(min_length=1) on payload.value only runs against the RAW value,
    # before this .strip() -- a whitespace-only string (e.g. "   ") passes
    # that check and lands here as "". Must be rejected before ioc_type_hint
    # is even considered, or a caller-supplied hint (checked next) would
    # otherwise never see it as invalid: detect_ioc_type("") does return
    # UNKNOWN, but that path is skipped entirely whenever a hint is present.
    if not ioc_value:
        raise HTTPException(status_code=422, detail="IOC value cannot be empty or whitespace-only.")

    if payload.ioc_type_hint is not None:
        ioc_type = payload.ioc_type_hint
        # A caller-supplied hint used to be trusted with zero validation --
        # detect_ioc_type()'s own UNKNOWN-rejection safety net only ever ran
        # against the auto-detected type, never against ioc_type_hint, so
        # ANY hint (including a garbage value/type pairing like
        # value="totally-not-an-ip", ioc_type_hint="ipv4") bypassed it
        # entirely. value_matches_ioc_type() re-validates the hint against
        # the value's actual shape for every type with a fixed syntax.
        if ioc_type == IOCType.UNKNOWN or not value_matches_ioc_type(ioc_value, ioc_type):
            raise HTTPException(
                status_code=422,
                detail=f"'{ioc_value}' does not look like a valid {ioc_type.value}; "
                "pass a different ioc_type_hint or omit it to auto-detect.",
            )
    else:
        ioc_type = detect_ioc_type(ioc_value)
        if ioc_type == IOCType.UNKNOWN:
            raise HTTPException(status_code=422, detail="Could not determine IOC type; pass ioc_type_hint.")

    lookup = IOCLookup(
        ioc_value=ioc_value, ioc_type=ioc_type.value, status=LookupStatus.RUNNING, requested_by=user.id
    )
    db.add(lookup)
    await db.commit()
    await db.refresh(lookup)
    lookup_id = lookup.id

    async def event_stream():
        yield _sse("detected", {"lookup_id": str(lookup_id), "ioc_value": ioc_value, "ioc_type": ioc_type.value})

        # The request's Depends(get_db) session is torn down as soon as this
        # route function returns the StreamingResponse -- generators are lazy,
        # so that happens BEFORE this generator body ever runs. Using it here
        # would silently drop every later `lookup.status = ...` mutation once
        # the session closes (fresh db.add()s still "work" since they open an
        # implicit new transaction, which is why provider/correlation rows
        # persisted while the lookup's own completion status never did).
        # This generator therefore owns its own session for its whole run.
        async with new_session() as stream_db:
            stream_lookup_row = await stream_db.get(IOCLookup, lookup_id)
            provider_results = []
            candidate_providers = None
            if payload.provider_ids is not None:
                selected = set(payload.provider_ids)
                candidate_providers = [p for p in get_all_providers() if p.provider_id in selected]
            try:
                # Populated below with one asyncio.Task per OK provider result
                # (its AI summarization, dispatched concurrently rather than
                # awaited inline -- see the comment inside the loop).
                summary_tasks: list[asyncio.Task] = []
                async for result in run_all_providers(ioc_value, ioc_type, candidate_providers):
                    provider_results.append(result)
                    stream_db.add(
                        ProviderResultRecord(
                            lookup_id=lookup_id,
                            provider_id=result.provider_id,
                            provider_name=result.provider_name,
                            category=result.category.value,
                            status=result.status.value,
                            data=result.data,
                            source_url=result.source_url,
                            error_message=result.error_message,
                            latency_ms=result.latency_ms,
                            # Preserve whether this result is a replayed Redis
                            # cache hit (app/providers/orchestrator.py's
                            # _run_with_policy sets ProviderResult.from_cache
                            # when it skips the real provider call entirely).
                            # Without this, app/core/dashboard.py's health
                            # queries could not distinguish a genuine,
                            # freshly-verified provider attempt from a stale
                            # cached one replayed with a brand-new
                            # created_at -- see that module's _NON_ATTEMPT_STATUSES
                            # handling, which from_cache rows are now treated
                            # identically to.
                            from_cache=result.from_cache,
                        )
                    )

                    # Commit after every provider (not once at the end of the
                    # loop) -- confirmed live that a client disconnecting
                    # mid-investigation (page refresh/tab close, or the
                    # GeneratorExit path documented below) discarded every
                    # ProviderResultRecord/AISummaryRecord added so far,
                    # because they were still sitting uncommitted in this
                    # transaction. The lookup correctly flipped to FAILED, but
                    # GET /lookup/{id} came back with providers_results: []
                    # even though 7 real provider calls (including a live
                    # Spamhaus hit) had already completed and been yielded
                    # over SSE before the disconnect. Providers are already
                    # rate-limited to a handful per lookup, so a commit per
                    # result is cheap relative to the network calls it
                    # follows.
                    #
                    # Real gap in that same fix found live during overnight
                    # QA: this commit used to happen AFTER the summarize_
                    # provider() AI call below, not right here -- so the
                    # exact disconnect-mid-investigation scenario the comment
                    # above describes could still lose an already-successful
                    # provider result, just from a slightly later disconnect
                    # (during the AI call instead of during the network
                    # fetch). Confirmed live: a real NVD call returned 200 in
                    # ~1s, but the AI summarization queued behind other
                    # concurrent Ollama load and didn't return before the
                    # client gave up -- the lookup ended FAILED with
                    # provider_results: [], discarding the real, already-
                    # fetched NVD/CVSS data. Committing the provider result
                    # immediately, before the AI call even starts, closes
                    # that window: the AI summary can still be lost to a
                    # disconnect (it's best-effort narrative, not primary
                    # evidence), but the real provider result underneath it
                    # no longer can be.
                    await stream_db.commit()
                    yield _sse("provider_result", result.to_dict())

                    if result.status.value == "ok":
                        # Real P2 latency bug found live: summarize_provider()
                        # (an AI call) used to be `await`ed right here, one
                        # provider at a time, inside this same `async for`
                        # loop -- so even though run_all_providers() already
                        # fans every provider's NETWORK fetch out concurrently
                        # via asyncio.create_task, the AI summarization step
                        # was entirely serial: the loop could not even pull
                        # the NEXT provider's already-finished result out of
                        # run_all_providers() until the CURRENT provider's AI
                        # summary finished. Total wall-clock time therefore
                        # scaled with (number of providers that returned OK) x
                        # (AI-call latency) rather than being bounded by the
                        # slowest single call -- confirmed live as wildly
                        # inconsistent total investigation time (seconds to
                        # several minutes) for functionally similar IOCs,
                        # purely as a function of how many providers returned
                        # OK and how loaded the AI backend happened to be.
                        #
                        # Fixed by dispatching summarize_provider() as a
                        # background task the instant this OK result arrives,
                        # instead of awaiting it inline -- it then runs
                        # concurrently with the NEXT provider's fetch (still
                        # in flight in run_all_providers()) and with every
                        # other provider's pending summary. Every task is
                        # drained via asyncio.as_completed() once the provider
                        # loop itself finishes below, so total AI-summarization
                        # time is bounded by the slowest single summary call,
                        # not their sum. Creating the task here (rather than
                        # earlier) still happens AFTER this provider's
                        # ProviderResultRecord add+commit+yield above, so the
                        # disconnect-safety property documented in the long
                        # comment above (a lost AI summary can never take an
                        # already-fetched provider result down with it) is
                        # unchanged.
                        summary_tasks.append(
                            asyncio.create_task(
                                summarize_provider(
                                    ioc_value, ioc_type.value, result, backend_override=payload.ai_backend
                                )
                            )
                        )

                # Drain every in-flight summary task concurrently rather than
                # one at a time -- see the comment above for why these were
                # dispatched as background tasks instead of being awaited
                # inline. summarize_provider() itself never lets an exception
                # escape (it catches everything internally and returns a
                # fallback ProviderSummary), so `await summary_task` here
                # cannot raise because of a single provider's AI failure.
                for summary_task in asyncio.as_completed(summary_tasks):
                    summary = await summary_task
                    stream_db.add(
                        AISummaryRecord(lookup_id=lookup_id, provider_id=summary.provider_id, summary=summary.model_dump())
                    )
                    await stream_db.commit()
                    yield _sse("provider_summary", summary.model_dump())

                correlation = correlate(ioc_value, ioc_type, provider_results)
                for edge in correlation.edges:
                    stream_db.add(
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
                yield _sse(
                    "correlation",
                    {
                        "nodes": [n.__dict__ for n in correlation.nodes],
                        "edges": [e.__dict__ for e in correlation.edges],
                    },
                )

                summary_rows = (
                    await stream_db.execute(select(AISummaryRecord).where(AISummaryRecord.lookup_id == lookup_id))
                ).scalars().all()
                provider_summaries = []
                for row in summary_rows:
                    try:
                        provider_summaries.append(ProviderSummary.model_validate(row.summary))
                    except Exception as exc:  # noqa: BLE001 -- one malformed row shouldn't sink the whole assessment
                        logger.warning(
                            "Skipping unparseable persisted summary for provider %s on lookup %s: %r",
                            row.provider_id, lookup_id, exc,
                        )

                # Distinct from providers that ran fine and found nothing
                # (NO_DATA) or that simply don't apply to this IOC type
                # (UNSUPPORTED_IOC, not a gap worth mentioning) -- these
                # applied here but returned nothing usable, for a specific
                # reason, which the AI must not silently read as "clean."
                _UNAVAILABLE_REASONS = {
                    ProviderStatus.ERROR.value: "error contacting the provider",
                    ProviderStatus.TIMEOUT.value: "timed out",
                    ProviderStatus.RATE_LIMITED.value: "rate limited",
                    ProviderStatus.NOT_CONFIGURED.value: "not configured (no API key)",
                    ProviderStatus.DISABLED.value: "disabled by the administrator",
                }
                unavailable_providers = [
                    {"provider_id": r.provider_id, "reason": _UNAVAILABLE_REASONS[r.status.value]}
                    for r in provider_results
                    if r.status.value in _UNAVAILABLE_REASONS
                ]

                # Deterministic score, computed from the SAME provider_results/correlation
                # gathered above -- BEFORE the AI is asked for anything. A brand-new lookup has no
                # Security Assessment Toolkit findings yet (that's a separate, later, explicit
                # action against an already-completed lookup), so no severities are passed here.
                scoring = score_investigation(provider_results, correlation)

                final = await generate_final_assessment(
                    ioc_value,
                    ioc_type.value,
                    provider_summaries,
                    correlation,
                    scoring,
                    backend_override=payload.ai_backend,
                    unavailable_providers=unavailable_providers,
                )

                stream_lookup_row.status = LookupStatus.COMPLETED
                stream_lookup_row.final_verdict = final.final_verdict
                stream_lookup_row.risk_score = final.risk.overall_risk_score
                stream_lookup_row.confidence_score = final.risk.confidence_score
                stream_lookup_row.final_assessment = final.model_dump()
                stream_db.add(
                    FinalAssessmentRecord(
                        lookup_id=lookup_id,
                        ai_backend=final.ai_backend or "unknown",
                        ai_model=final.ai_model,
                        ai_outcome=final.ai_outcome or "unknown",
                        is_primary=True,
                        assessment=final.model_dump(),
                        requested_by=user.id,
                    )
                )

                # Deterministic evidence ledger -- built from provider_results/
                # provider_summaries/correlation only, never from the AI's own
                # output, so every later AI explanation (WHY, Score Explanation,
                # Challenge, Copilot) has real, independently-checkable records to
                # cite rather than asserting claims from scratch.
                for record in build_evidence(provider_results, provider_summaries, correlation):
                    stream_db.add(
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
                await stream_db.commit()

                yield _sse("final_assessment", final.model_dump())
                yield _sse("done", {"lookup_id": str(lookup_id)})
            except Exception as exc:  # noqa: BLE001
                logger.exception("Lookup %s failed: %s", lookup_id, exc)
                # Do NOT reuse stream_db here: if the exception came from a
                # failed flush/commit on this same session (e.g. a DB
                # constraint violation), the session requires an explicit
                # rollback before it can run anything else -- committing
                # directly raises an unhandled PendingRollbackError that
                # escapes this except block entirely, leaves
                # stream_lookup_row.status mutated to FAILED only in memory
                # (never persisted), and fools the `finally` block's own
                # recovery check below into thinking this already succeeded.
                # A fresh session (same pattern already used in `finally`)
                # sidesteps the broken session instead of trying to repair it.
                try:
                    async with new_session() as failure_db:
                        row = await failure_db.get(IOCLookup, lookup_id)
                        if row is not None:
                            row.status = LookupStatus.FAILED
                            await failure_db.commit()
                    stream_lookup_row.status = LookupStatus.FAILED
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to persist FAILED status for lookup %s after the original failure", lookup_id)
                yield _sse("error", {"message": str(exc)})
            finally:
                # `except Exception` above does NOT catch a client
                # disconnecting mid-stream: FastAPI/Starlette raises
                # GeneratorExit (a BaseException, not an Exception) into this
                # generator when the underlying connection closes, at
                # whichever `yield` happens to be executing. Confirmed live:
                # without this, a lookup a client walked away from (page
                # refresh, tab close, or just a client-side timeout while the
                # ~25-40s pipeline was still genuinely running) stayed
                # "running" in the database forever -- GET /lookup/{id}
                # never transitioned to completed OR failed, and it kept
                # showing up in the team-shared GET /lookup list
                # indefinitely.
                #
                # First attempt at this fix reused `stream_db` (the session
                # from the enclosing `async with new_session()`) inside an
                # asyncio.shield()'d commit. Confirmed live that this is
                # actually WORSE: the `async with` block's own __aexit__
                # rollback races the shielded task, so the shield just
                # detaches the commit into an orphaned task that then hits
                # `sqlalchemy.exc.ResourceClosedError: This transaction is
                # closed` against an already-closing session -- visible in
                # the real logs as "Task exception was never retrieved".
                # Fix: open a BRAND NEW, independent session for the
                # recovery write, scoped to nothing this generator's own
                # `async with` can tear down, and shield the whole
                # operation (session creation included) as one unit.
                if stream_lookup_row.status == LookupStatus.RUNNING:
                    async def _mark_failed():
                        async with new_session() as cleanup_db:
                            row = await cleanup_db.get(IOCLookup, lookup_id)
                            if row is not None and row.status == LookupStatus.RUNNING:
                                row.status = LookupStatus.FAILED
                                await cleanup_db.commit()

                    try:
                        await asyncio.shield(_mark_failed())
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "Failed to mark lookup %s as failed during stream cleanup", lookup_id
                        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class ReanalyzeRequest(BaseModel):
    ai_backend: str


@router.post("/{lookup_id}/reanalyze")
async def reanalyze_lookup(
    lookup_id: uuid.UUID,
    payload: ReanalyzeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("lookup:create")),
):
    """Re-runs ONLY the final-assessment AI step against a lookup's already-
    collected evidence, using an explicit AI backend -- the "Analyze with
    Groq instead" comparison feature. Never re-queries any IOC provider:
    provider_summaries and correlation are both rebuilt purely from already-
    persisted rows, matching exactly what stream_lookup itself does before
    its own call to generate_final_assessment. Every result (the original
    plus every comparison) is durable in final_assessment_records, keyed by
    which backend produced it -- never silently overwrites the original.

    The deterministic score (app/scoring/engine.py) is recomputed here from
    the same persisted provider_results/correlation/Security Assessment
    findings the primary assessment used -- it is NOT re-derived from
    whatever the primary assessment happened to persist, and it does not
    vary with `payload.ai_backend`. This is deliberate: every backend
    compared side-by-side here must show the IDENTICAL score, differing
    only in AI-authored prose/verdict-choice-among-consistent-options -- a
    backend that "computed" a different score would defeat the purpose of
    a same-evidence comparison. Folding in Security Assessment findings
    here too (not just in the toolkit's own refresh path) matters
    specifically because a lookup can accumulate findings AFTER its
    original investigation ran; without this, re-analyzing with a
    different backend would silently show a DIFFERENT score than the
    primary assessment for a reason that has nothing to do with the AI
    backend at all.
    """
    lookup = await db.get(
        IOCLookup,
        lookup_id,
        options=[
            selectinload(IOCLookup.provider_results),
            selectinload(IOCLookup.correlation_edges),
            selectinload(IOCLookup.security_assessment_runs).selectinload(SecurityAssessmentRun.findings),
        ],
    )
    if lookup is None:
        raise HTTPException(status_code=404, detail="Lookup not found")
    if lookup.status != LookupStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Lookup must be completed before it can be re-analyzed.")
    # Same validation as stream_lookup above -- see its comment for the full
    # bug writeup. payload.ai_backend is required (not Optional) here, so
    # every request must name a real backend.
    if payload.ai_backend not in runtime_config_svc.AI_BACKENDS:
        raise HTTPException(status_code=400, detail=f"Unknown AI backend {payload.ai_backend!r}")

    summary_rows = (
        await db.execute(
            select(AISummaryRecord).where(
                AISummaryRecord.lookup_id == lookup_id, AISummaryRecord.provider_id.is_not(None)
            )
        )
    ).scalars().all()
    provider_summaries = []
    for row in summary_rows:
        try:
            provider_summaries.append(ProviderSummary.model_validate(row.summary))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping unparseable persisted summary for lookup %s: %r", lookup_id, exc)

    correlation = correlation_from_records(lookup, lookup.correlation_edges)

    _UNAVAILABLE_REASONS = {
        ProviderStatus.ERROR.value: "error contacting the provider",
        ProviderStatus.TIMEOUT.value: "timed out",
        ProviderStatus.RATE_LIMITED.value: "rate limited",
        ProviderStatus.NOT_CONFIGURED.value: "not configured (no API key)",
        ProviderStatus.DISABLED.value: "disabled by the administrator",
    }
    unavailable_providers = [
        {"provider_id": r.provider_id, "reason": _UNAVAILABLE_REASONS[r.status]}
        for r in lookup.provider_results
        if r.status in _UNAVAILABLE_REASONS
    ]

    security_finding_severities = [
        finding.severity.value for run in lookup.security_assessment_runs for finding in run.findings
    ]
    scoring = score_investigation(lookup.provider_results, correlation, security_finding_severities)

    final = await generate_final_assessment(
        lookup.ioc_value,
        lookup.ioc_type,
        provider_summaries,
        correlation,
        scoring,
        backend_override=payload.ai_backend,
        unavailable_providers=unavailable_providers,
    )

    record = FinalAssessmentRecord(
        lookup_id=lookup_id,
        ai_backend=final.ai_backend or payload.ai_backend,
        ai_model=final.ai_model,
        ai_outcome=final.ai_outcome or "unknown",
        is_primary=False,
        assessment=final.model_dump(),
        requested_by=user.id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": str(record.id), "ai_backend": record.ai_backend, "ai_model": record.ai_model, "assessment": final.model_dump()}


@router.get("/{lookup_id}/assessments")
async def list_assessments(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("lookup:read")),
):
    """Every final assessment ever generated for this lookup (the original
    plus every AI-comparison re-analysis), so the frontend can render a
    side-by-side "Claude said X, Groq said Y" comparison view."""
    rows = (
        await db.execute(
            select(FinalAssessmentRecord)
            .where(FinalAssessmentRecord.lookup_id == lookup_id)
            .order_by(FinalAssessmentRecord.created_at.asc())
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "ai_backend": r.ai_backend,
            "ai_model": r.ai_model,
            "is_primary": r.is_primary,
            "assessment": r.assessment,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def _load_lookup_detail(db: AsyncSession, lookup_id: uuid.UUID) -> IOCLookup:
    result = await db.execute(
        select(IOCLookup)
        .options(
            selectinload(IOCLookup.provider_results),
            selectinload(IOCLookup.ai_summaries),
            selectinload(IOCLookup.correlation_edges),
        )
        .where(IOCLookup.id == lookup_id)
    )
    lookup = result.scalar_one_or_none()
    if not lookup:
        raise HTTPException(status_code=404, detail="Lookup not found")
    return lookup


def _serialize_lookup(lookup: IOCLookup) -> dict:
    return {
        "id": str(lookup.id),
        "ioc_value": lookup.ioc_value,
        "ioc_type": lookup.ioc_type,
        "status": lookup.status.value,
        "final_verdict": lookup.final_verdict.value if lookup.final_verdict else None,
        "risk_score": lookup.risk_score,
        "confidence_score": lookup.confidence_score,
        "final_assessment": lookup.final_assessment,
        "provider_results": [
            {
                "provider_id": p.provider_id,
                "provider_name": p.provider_name,
                "category": p.category,
                "status": p.status,
                "data": p.data,
                "source_url": p.source_url,
                "error_message": p.error_message,
                "latency_ms": p.latency_ms,
            }
            for p in lookup.provider_results
        ],
        "ai_summaries": [s.summary for s in lookup.ai_summaries],
        "created_at": lookup.created_at.isoformat(),
        "correlation": _correlation_payload(lookup),
    }


@router.get("/{lookup_id}")
async def get_lookup(
    lookup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("lookup:read")),
):
    lookup = await _load_lookup_detail(db, lookup_id)
    return _serialize_lookup(lookup)


_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@")


def _csv_safe(value):
    """Neutralizes CSV/formula injection (CWE-1236). A cell whose text starts
    with '=', '+', '-', or '@' is interpreted as a live formula by Excel/
    LibreOffice when the exported CSV is reopened (e.g. a free-text IOC value
    of '=1+1+cmd|calc!A1'). Empirically confirmed that csv.writer's own
    quoting is NOT a defense here: QUOTE_MINIMAL leaves a comma-free formula
    payload completely unquoted and raw, and even QUOTE_ALL only wraps it as
    "=1+1+cmd|calc!A1" -- the spreadsheet app strips the CSV-level quotes
    during parsing and then evaluates the remaining cell content, which still
    starts with '='. The standard mitigation is prefixing a literal leading
    apostrophe, which survives CSV parsing and forces the cell to render as
    text. Only applied to strings -- numeric/enum fields are never
    attacker-controlled free text and a leading apostrophe would corrupt
    them.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def _render_csv(lookup: IOCLookup) -> str:
    """One CSV per investigation: a short key/value metadata block (the
    fields also shown in the JSON/Markdown exports' header line), a blank
    separator row, then one row per provider result -- CSV has no natural
    way to nest the free-text assessment sections the Markdown export has,
    so those aren't included here; a user wanting the executive summary/
    MITRE mappings/etc. in a flat file already has the Markdown option.

    Every field that can ever contain free-text/attacker-influenced content
    (ioc_value, provider_name, source_url, error_message -- see
    _csv_safe()'s docstring) is passed through _csv_safe() before being
    written. Fields drawn from fixed enums/numeric columns (ioc_type,
    final_verdict, risk_score, confidence_score, provider_id, category,
    status, latency_ms, created_at) are never free text and are left as-is.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["field", "value"])
    writer.writerow(["platform", "HORIZON GRID"])
    writer.writerow(["investigation_id", str(lookup.id)])
    writer.writerow(["ioc_value", _csv_safe(lookup.ioc_value)])
    writer.writerow(["ioc_type", lookup.ioc_type])
    writer.writerow(["final_verdict", lookup.final_verdict.value if lookup.final_verdict else ""])
    writer.writerow(["risk_score", lookup.risk_score if lookup.risk_score is not None else ""])
    writer.writerow(["confidence_score", lookup.confidence_score if lookup.confidence_score is not None else ""])
    writer.writerow(["created_at", lookup.created_at.isoformat()])
    writer.writerow([])
    writer.writerow(["provider_id", "provider_name", "category", "status", "source_url", "error_message", "latency_ms"])
    for p in lookup.provider_results:
        writer.writerow(
            [
                p.provider_id,
                _csv_safe(p.provider_name),
                p.category,
                p.status,
                _csv_safe(p.source_url or ""),
                _csv_safe(p.error_message or ""),
                p.latency_ms,
            ]
        )
    return buf.getvalue()


def _pdf_esc(value) -> str:
    """XML-escapes a value before it reaches a ReportLab Paragraph().

    Paragraph() parses its input as a small XML/HTML-like markup dialect, not
    literal text. Two live failure modes if interpolated text isn't escaped
    first: (a) malformed/unclosed markup (e.g. an IOC value containing a
    stray '<tag') makes reportlab.platypus.paraparser raise an uncaught
    ValueError -- a persistent HTTP 500 for that lookup's PDF export forever;
    (b) well-formed markup (e.g. '<font color="red" size="40">FAKE-VERDICT
    </font>') is accepted as real formatting, letting free-text/AI-generated
    content inject spoofed formatting into an otherwise official-looking
    report. xml.sax.saxutils.escape() (amp/lt/gt) makes any '<'/'>'/'&' in
    the source text render as literal characters instead of being parsed as
    markup, which fixes both: malformed tags can no longer reach the parser
    as tags at all, and well-formed-looking tags render as visible text
    rather than being applied as formatting.

    None/missing values become "" rather than the literal string "None".
    """
    if value is None:
        return ""
    return saxutils.escape(str(value))


def _render_pdf(lookup: IOCLookup) -> bytes:
    """Mirrors ExportMenu.tsx's buildMarkdown() section order/content so a
    user gets the same report regardless of which format they picked --
    the only reason this exists server-side rather than also being built
    client-side like the JSON/Markdown formats is that there's no
    reasonable pure-JS PDF layout engine to reuse from this codebase's
    existing frontend dependencies.

    Every piece of interpolated text that originates from the IOC value or
    from AI-generated FinalAssessment content is passed through _pdf_esc()
    before it reaches a Paragraph()/_section()/_bullet_section() call -- see
    _pdf_esc()'s docstring. Literal markup this function itself adds (e.g.
    the <b> tags around a label, '&nbsp;', '&bull;') is written directly, not
    escaped, since it isn't attacker-influenced.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    # topMargin/bottomMargin leave room for the branded header/footer drawn
    # directly on the canvas below -- SimpleDocTemplate's flowable story
    # never overlaps that reserved band on any page.
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=1.0 * inch, bottomMargin=0.85 * inch)

    def _draw_header_footer(canvas, _doc) -> None:
        """HORIZON GRID branding + page numbering on every page -- drawn
        directly on the canvas (not part of the flowable story) so it's
        positioned identically regardless of how many pages the story
        content spans. Nothing here is attacker-influenced (fixed strings,
        page count, generation timestamp), so no _pdf_esc() is needed.
        """
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(0.75 * inch, letter[1] - 0.5 * inch, "HORIZON GRID")
        canvas.setFont("Helvetica", 8)
        canvas.drawString(2.05 * inch, letter[1] - 0.5 * inch, "  --  Every Signal. One Operational Picture.")
        canvas.line(0.75 * inch, letter[1] - 0.58 * inch, letter[0] - 0.75 * inch, letter[1] - 0.58 * inch)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(0.75 * inch, 0.55 * inch, f"Investigation ID: {lookup.id}")
        canvas.drawRightString(letter[0] - 0.75 * inch, 0.55 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    story = [
        Paragraph(f"IOC Assessment: {_pdf_esc(lookup.ioc_value)}", styles["Title"]),
        Paragraph(
            f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} &nbsp;&nbsp; "
            f"Investigation ID: {lookup.id}",
            styles["BodyText"],
        ),
    ]

    fa = lookup.final_assessment
    if not fa:
        story.append(Spacer(1, 12))
        story.append(Paragraph("No final assessment is available for this investigation yet.", styles["BodyText"]))
        doc.build(story, onFirstPage=_draw_header_footer, onLaterPages=_draw_header_footer)
        return buf.getvalue()

    story.append(
        Paragraph(
            f"<b>Type:</b> {_pdf_esc(lookup.ioc_type)} &nbsp;&nbsp; "
            f"<b>Final Verdict:</b> {_pdf_esc(fa.get('final_verdict', 'unknown'))} &nbsp;&nbsp; "
            f"<b>Risk Score:</b> {_pdf_esc(fa.get('risk', {}).get('overall_risk_score', 'n/a'))} "
            f"(confidence {_pdf_esc(fa.get('risk', {}).get('confidence_score', 'n/a'))})",
            styles["BodyText"],
        )
    )

    def _section(title: str, body: str) -> None:
        story.append(Spacer(1, 10))
        # Real bug found live during overnight QA: `title` was never
        # escaped here (unlike every dynamic value in this file, which all
        # go through _pdf_esc) -- the one hardcoded caller with a literal
        # '&' in its title ("MITRE ATT&CK Mappings", in _bullet_section
        # below) rendered as "MITRE ATT&CK; Mappings" because ReportLab's
        # Paragraph() parses its input as mini-XML and a bare '&' isn't a
        # valid entity start. Escaping here too, even though today's only
        # callers pass a plain string literal, so this can never regress
        # if a future title is ever built from anything dynamic.
        story.append(Paragraph(_pdf_esc(title), styles["Heading2"]))
        story.append(Paragraph(_pdf_esc(body), styles["BodyText"]))

    def _bullet_section(title: str, items: list, *, already_escaped: bool = False) -> None:
        if not items:
            return
        story.append(Spacer(1, 10))
        story.append(Paragraph(_pdf_esc(title), styles["Heading2"]))
        for item in items:
            text = item if already_escaped else _pdf_esc(item)
            story.append(Paragraph(f"&bull; {text}", styles["BodyText"]))

    _section("Executive Summary", fa.get("executive_summary", ""))
    _section("Technical Summary", fa.get("technical_summary", ""))
    _section("Threat Assessment", fa.get("threat_assessment", ""))
    _section("Verdict Rationale", fa.get("verdict_rationale", ""))
    _bullet_section("Supporting Evidence", fa.get("supporting_evidence") or [])
    _bullet_section(
        "MITRE ATT&CK Mappings",
        [
            f"<b>{_pdf_esc(m.get('technique_id'))}</b> {_pdf_esc(m.get('technique_name'))} "
            f"({_pdf_esc(m.get('tactic'))}): {_pdf_esc(m.get('rationale'))}"
            for m in (fa.get("mitre_mappings") or [])
        ],
        already_escaped=True,  # each dynamic component above is already escaped; only our own literal <b> tags remain
    )
    _bullet_section("Recommended Actions", fa.get("recommended_actions") or [])
    _bullet_section("Investigation Priorities", fa.get("investigation_priorities") or [])
    _bullet_section("Incident Response Recommendations", fa.get("incident_response_recommendations") or [])

    detection_rules = fa.get("detection_rules") or []
    if detection_rules:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Detection Rules", styles["Heading2"]))
        for rule in detection_rules:
            story.append(Paragraph(f"{_pdf_esc(rule.get('title'))} ({_pdf_esc(rule.get('format'))})", styles["Heading3"]))
            # Preformatted renders its text literally (no XML/markup parsing,
            # unlike Paragraph), so it is not a paraparser injection/crash
            # vector -- confirmed by reading reportlab.platypus.Preformatted's
            # implementation, which never calls the paraparser at all.
            story.append(Preformatted(rule.get("rule", ""), styles["Code"]))

    doc.build(story, onFirstPage=_draw_header_footer, onLaterPages=_draw_header_footer)
    return buf.getvalue()


@router.post("/{lookup_id}/export")
async def export_lookup(
    lookup_id: uuid.UUID,
    format: Literal["pdf", "csv"],
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("lookup:export")),
):
    """Server-rendered export for the two formats ExportMenu.tsx cannot
    build client-side (JSON/Markdown are built directly in the browser from
    data already loaded there -- see that component).

    Gated on the dedicated `lookup:export` permission (ADMIN/ANALYST only,
    per ROLE_PERMISSIONS in app/models/user.py) rather than `lookup:read`.
    VIEWER holds `lookup:read` but not `lookup:export`, and exporting a real
    file to disk is a materially different, more sensitive action than
    viewing JSON in the app -- `lookup:export` already existed in the
    permission matrix for exactly this endpoint but was never referenced by
    any route dependency until now."""
    lookup = await _load_lookup_detail(db, lookup_id)
    filename = f"ioc-assessment-{lookup_id}.{format}"
    if format == "csv":
        return Response(
            content=_render_csv(lookup),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return Response(
        content=_render_pdf(lookup),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _correlation_payload(lookup: IOCLookup) -> dict:
    """Rebuilds the {nodes, edges} graph payload from persisted
    CorrelationEdgeRecord rows, in the same shape the live SSE `correlation`
    event uses (see CorrelationPayload in frontend/lib/types.ts) -- confirmed
    live that GET /lookup/{id} was omitting this entirely, so the relationship
    graph rendered fine during a live investigation but came back empty on
    every later revisit even though correlation_edges are persisted
    specifically so "a lookup's graph can be rebuilt from Postgres alone"
    (see CorrelationEdgeRecord's own docstring). Edge rows don't carry node
    labels, so rebuilt nodes get an empty labels list -- the graph component
    only uses labels for optional annotation, not identity.

    Always includes the seed IOC as a node even with zero edges, matching the
    live event's behavior (confirmed live: a lookup with no discovered
    relationships still streams a single-node, zero-edge `correlation` event,
    not a missing one) -- otherwise "no relationships found" would look
    identical to "graph data unavailable" instead of being distinguishable.
    """
    node_ids: dict[str, dict] = {}

    def _ensure_node(node_type: str, value: str) -> None:
        node_id = f"{node_type}:{value}"
        node_ids.setdefault(node_id, {"node_id": node_id, "ioc_type": node_type, "value": value, "labels": []})

    _ensure_node(lookup.ioc_type, lookup.ioc_value)

    edges = []
    for e in lookup.correlation_edges:
        _ensure_node(e.source_type, e.source_value)
        _ensure_node(e.target_type, e.target_value)
        edges.append(
            {
                "source": f"{e.source_type}:{e.source_value}",
                "target": f"{e.target_type}:{e.target_value}",
                "relationship": e.relationship_type,
                "confidence": e.confidence,
                "provenance": e.provenance,
            }
        )
    return {"nodes": list(node_ids.values()), "edges": edges}


@router.get("")
async def list_lookups(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("lookup:read")),
    limit: int = 50,
):
    # Lookups are intentionally shared across the whole SOC team (any
    # lookup:read role sees everyone's), but the limit itself must still be
    # bounded -- it's a client-supplied query param with no cap otherwise.
    limit = max(1, min(limit, 200))
    result = await db.execute(select(IOCLookup).order_by(IOCLookup.created_at.desc()).limit(limit))
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "ioc_value": r.ioc_value,
            "ioc_type": r.ioc_type,
            "status": r.status.value,
            "final_verdict": r.final_verdict.value if r.final_verdict else None,
            "risk_score": r.risk_score,
            "confidence_score": r.confidence_score,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
