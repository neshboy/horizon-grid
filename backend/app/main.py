"""FastAPI application entrypoint."""
import asyncio
import contextvars
import logging
import time
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.routes import (
    admin,
    ai_config,
    analysis,
    auth,
    basket,
    cases,
    dashboard,
    hunting,
    lookup,
    pentest,
    pentest_exploit,
    pivot,
    providers,
    runtime,
    security_assessment,
)
from app.core.cache import RateLimiterUnavailable
from app.core.config import get_settings
from app.core.runtime_config import seed_from_env_if_empty

# Every logger in this process (app.*, uvicorn.access, httpx, etc.) propagates
# to the root logger's handler by default -- attaching the request-id filter
# there, once, covers every log line a single request produces, including
# the ones this app's own code never touches directly (uvicorn's access log,
# httpx's per-outbound-call log). Without this, concurrent requests' log
# lines were confirmed live to be unattributable: nothing tied together the
# several lines one request produces, or distinguished them from a
# concurrent request's lines, beyond an ephemeral source TCP port.
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [request_id=%(request_id)s] %(name)s: %(message)s",
)
logging.getLogger().handlers[0].addFilter(_RequestIdLogFilter())
structlog.configure(processors=[structlog.processors.JSONRenderer()])

settings = get_settings()

_APP_VERSION = "0.3.9"
# Real gap found live during the 0.3.8 QA pass: this constant was never
# bumped alongside windows/installer.iss and linux/debian/control for six
# releases (0.3.1-0.3.8 all shipped still reporting "0.3.0" via /health and
# the OpenAPI schema) -- there is no single canonical version source shared
# across Python/Inno/Debian today, so this needs a manual bump alongside
# those two files until one exists. See test_app_version_matches_release
# for the regression guard that at least catches the next drift.
# Process start time, for /health's uptime field -- confirmed live that no
# version or uptime indicator was visible anywhere an operator would look
# (the FastAPI version= below only ever surfaces via /docs' OpenAPI schema).
_process_started_at = time.monotonic()

# Real gap fixed: /docs, /redoc, and the raw OpenAPI schema were exposed
# unconditionally with no environment gate at all -- a full map of every
# route, request/response shape, and parameter, reachable by anyone who can
# reach the API at all (this app's real authorization boundary is JWT auth,
# not network placement, but handing an attacker the API's own blueprint is
# still real reconnaissance value worth denying by default in production).
# settings.environment defaults to "development" and is never set to
# "production" by any real install path except docker-compose.prod.yml's own
# explicit ENVIRONMENT=production (the override every real installer uses) --
# so this is a no-op for local dev/CI, where the interactive docs are still
# genuinely useful.
_docs_enabled = settings.environment != "production"

app = FastAPI(
    title=settings.app_name,
    version=_APP_VERSION,
    description="Unified threat intelligence workbench: single-search IOC lookup across "
    "dozens of providers, correlated and summarized by a local Ollama model "
    "(or AWS Bedrock/Gemini/Anthropic/Groq/OpenAI/Kimi/DeepSeek/xAI/Mistral/OpenRouter, configurable via AI_BACKEND).",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json" if _docs_enabled else None,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
)

# RFC 1918 private ranges + loopback + the literal "localhost", http only
# (this app terminates no TLS of its own). This relaxes only the browser's
# same-origin policy for these hosts -- the real authorization boundary
# behind it is JWT auth (app/auth/rbac.py), not origin matching. Matching
# any port on a qualifying host (rather than a specific configured port) is
# deliberate: it avoids extra plumbing for no real security gain, since the
# origin check is not the thing standing between a request and the API.
PRIVATE_NETWORK_ORIGIN_REGEX = (
    r"^http://("
    r"localhost"
    r"|127\.0\.0\.1"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=PRIVATE_NETWORK_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    # Trusts an inbound X-Request-Id only as a caller-supplied correlation
    # hint (e.g. a reverse proxy's own trace ID) -- it's never used for any
    # authorization/security decision, only log grouping, so accepting a
    # client-supplied value here carries no privilege-escalation risk.
    #
    # Deliberately NOT reset in a `finally` here: for a StreamingResponse
    # (e.g. /lookup/stream's SSE generator), Starlette's BaseHTTPMiddleware
    # returns from call_next() as soon as headers are ready, well before the
    # body generator actually runs -- a finally-reset here would clear the
    # contextvar before the very provider-fanout log lines this exists to
    # attribute ever execute. Each request already runs in its own asyncio
    # Task, so this value never leaks into a concurrent, unrelated request;
    # letting it live for the rest of this task's lifetime is correct, not a
    # leak. A background task spawned mid-request (e.g. security assessment
    # runs, via asyncio.create_task) inherits a copy of this same context,
    # which usefully ties its later log lines back to the request that
    # started it too.
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    _request_id_var.set(request_id)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


# Real gap fixed: no request-body-size limit existed anywhere -- an
# unauthenticated or authenticated caller could send an arbitrarily large
# request body to any JSON endpoint, forcing the full body to be buffered
# in memory before Pydantic validation (and its own per-field max_length
# checks) ever runs. Checked against the client-supplied Content-Length
# header BEFORE reading the body -- a lightweight, early rejection; a
# caller that lies about Content-Length and streams more than declared is
# still bounded by ASGI/uvicorn's own default body-read behavior, so this
# is a real, cheap first line of defense, not the only one.
_MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MB


@app.middleware("http")
async def request_body_size_limit_middleware(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (max {_MAX_REQUEST_BODY_BYTES} bytes)."},
                )
        except ValueError:
            pass

    # Real gap found live during overnight QA: the Content-Length check
    # above is completely bypassed by chunked Transfer-Encoding, which
    # omits Content-Length entirely -- not a caller "lying" about the
    # header (the only case this code previously acknowledged), just
    # ordinary standard HTTP/1.1 behavior. Confirmed live that a ~11MB
    # chunked-encoded body was fully read, buffered, and Pydantic-validated
    # with this limit never enforced at all. Actually counting bytes as
    # the body streams closes this regardless of how the client shapes the
    # request; `request._body` is populated afterward (Starlette's own
    # caching attribute) so downstream body-parsing dependencies still see
    # the exact same bytes without re-reading the now-exhausted ASGI
    # receive channel.
    total = 0
    chunks = []
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large (max {_MAX_REQUEST_BODY_BYTES} bytes)."},
            )
        chunks.append(chunk)
    request._body = b"".join(chunks)

    return await call_next(request)


@app.exception_handler(DBAPIError)
async def _database_data_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """Real, systemic gap found live during overnight QA: a literal NUL
    byte (\\x00) in ANY free-text field (case title, admin full_name, a
    lookup value, etc.) reaches Postgres, which rejects it with
    asyncpg.exceptions.CharacterNotInRepertoireError -- and since nothing
    caught that anywhere, it fell through as a bare, unhandled 500 on
    whichever endpoint happened to receive it. Pydantic's `str` type has no
    built-in rejection of U+0000, so this was reachable through
    essentially any POST/PATCH endpoint with a text field, not one single
    bug to patch at the call site.

    Scoped narrowly to asyncpg's DataError family (Postgres SQLSTATE class
    22, "data exception") specifically so this stays a translation of
    genuinely bad CLIENT input into a clean 422 -- it does not swallow
    other DBAPIError causes (connection failures, etc.), which still
    surface as a real 500 rather than being silently reclassified.
    """
    from asyncpg.exceptions import DataError as AsyncpgDataError

    if isinstance(exc.orig, AsyncpgDataError):
        logging.getLogger(__name__).warning("Rejected request with invalid data for Postgres: %s", exc.orig)
        return JSONResponse(status_code=422, content={"detail": "Invalid character or value in request body."})
    raise exc


@app.exception_handler(RateLimiterUnavailable)
async def _rate_limiter_unavailable_handler(request: Request, exc: RateLimiterUnavailable) -> JSONResponse:
    """Real P1 found live during a Redis outage (`docker compose stop redis`):
    app/core/cache.py's RateLimiter.allow() -- called unconditionally by
    POST /api/v1/lookup/stream, and on the failed-credential branch of POST
    /api/v1/auth/login and /api/v1/auth/register -- had no timeout and no
    exception handling around its Redis calls. A Redis outage turned
    lookup/stream into a several-second hang followed by a bare, content-free
    Starlette 500, and turned a failed login into a hang with no response at
    all (client timeout, no status code) -- both far worse than this app's
    own /health/detailed docstring, which documents a Redis outage as merely
    DEGRADED. RateLimiter.allow() now bounds every Redis call with a timeout
    and raises RateLimiterUnavailable on any Redis error/timeout instead of
    letting redis.exceptions.ConnectionError (or an unbounded hang) fall
    through; this handler turns that into one clean, fast, actionable 503
    across all three call sites instead of a route-by-route try/except.
    """
    logging.getLogger(__name__).warning("Rate limiting unavailable (Redis unreachable/timed out): %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Rate limiting temporarily unavailable, please retry."},
    )


Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(lookup.router, prefix=settings.api_v1_prefix)
app.include_router(providers.router, prefix=settings.api_v1_prefix)
app.include_router(ai_config.router, prefix=settings.api_v1_prefix)
app.include_router(analysis.router, prefix=settings.api_v1_prefix)
app.include_router(hunting.router, prefix=settings.api_v1_prefix)
app.include_router(pivot.router, prefix=settings.api_v1_prefix)
app.include_router(basket.router, prefix=settings.api_v1_prefix)
app.include_router(cases.router, prefix=settings.api_v1_prefix)
app.include_router(runtime.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router, prefix=settings.api_v1_prefix)
app.include_router(security_assessment.router, prefix=settings.api_v1_prefix)
app.include_router(pentest.router, prefix=settings.api_v1_prefix)
app.include_router(pentest_exploit.router, prefix=settings.api_v1_prefix)
app.include_router(dashboard.router, prefix=settings.api_v1_prefix)


_KNOWN_PLACEHOLDER_JWT_SECRETS = {"change-me-in-production", "replace-with-a-long-random-string"}


@app.on_event("startup")
async def _warn_if_jwt_secret_is_a_placeholder() -> None:
    """.env.example ships a literal placeholder (not the Settings field's own
    Python-level default -- the two strings differ, so a check against only
    one would miss someone who copies .env.example verbatim, which the
    README's quick-start does not explicitly warn against). Every JWT this
    process issues is only as strong as this value, so a fresh install that
    never got past copy-pasting the example file should say so loudly rather
    than silently issue forgeable tokens.

    Real gap found live during the overnight QA pass: a warning alone is not
    enough -- confirmed live that a token forged entirely offline with the
    exact placeholder string was accepted by GET /auth/me and by the
    admin-only POST /admin/users for a real account, with no login and no
    real credentials at all. In production this is a full authentication
    bypass, so it now hard-fails startup there instead of only logging.
    Development keeps the warning-only behavior so a first-run dev install
    still boots without extra setup friction."""
    if settings.jwt_secret_key in _KNOWN_PLACEHOLDER_JWT_SECRETS:
        message = (
            "JWT_SECRET_KEY is still set to the placeholder value from .env.example. "
            "Every access/refresh token this server issues can be forged by anyone who "
            "knows this default. Generate a real random secret and set it in .env before "
            "exposing this instance to anything but localhost."
        )
        if settings.environment == "production":
            raise RuntimeError(message)
        logging.getLogger(__name__).warning(message)


@app.on_event("startup")
async def _warn_if_msf_rpc_password_is_a_placeholder() -> None:
    """Same reasoning as the JWT-secret warning above, for the Metasploit
    RPC password (app/pentest/exploit.py's gated real-exploit-validation
    feature) -- mitigated by msfrpcd being bound to 127.0.0.1 only (nothing
    outside this container can reach it regardless), but a fresh install
    that never overrode MSF_RPC_PASSWORD should still know that."""
    if settings.msf_rpc_password == "horizon-grid-msf-rpc-local":
        logging.getLogger(__name__).warning(
            "MSF_RPC_PASSWORD is still set to its default placeholder value. This only "
            "matters if msfrpcd is ever reachable from outside this container (it isn't, "
            "by default -- bound to 127.0.0.1) -- override it in .env if that ever changes."
        )


@app.on_event("startup")
async def _seed_runtime_config() -> None:
    """Populates provider_runtime_configs from the current .env-derived
    Settings on first boot of the runtime-provider feature, so upgrading
    never silently drops an administrator's already-configured keys. A
    no-op on every subsequent restart once the table has any row at all --
    see app/core/runtime_config.py's seed_from_env_if_empty()."""
    try:
        await seed_from_env_if_empty()
    except Exception:
        logging.getLogger(__name__).exception("Runtime config seed failed -- continuing without it.")


@app.on_event("startup")
async def _load_pentest_kill_switch_state() -> None:
    """Hydrates the in-process global pentest kill switch flag from its
    persisted state (app/models/pentest.py's PentestGlobalKillSwitch
    singleton row) on every backend startup.

    Real P1 found live during overnight QA: without this, the platform-wide
    pentest kill switch (app/pentest/orchestrator.py) was a bare in-memory
    boolean with nothing anywhere reading it back at process start --
    engaging it, then restarting the backend (a routine hot-reload, a
    crash, `docker restart`), silently reverted it to disengaged with no
    audit entry or warning that the safety control an admin had explicitly
    activated was no longer in effect. load_global_kill_switch_state()
    itself fails SAFE (engaged) on a read error rather than raising, so
    this call is not expected to ever throw -- the try/except below is
    defense in depth only, matching every other startup hook in this file."""
    try:
        from app.pentest.orchestrator import load_global_kill_switch_state, start_kill_switch_sync_loop

        await load_global_kill_switch_state()
        # Real P1 found live: this startup-only hydration is exactly correct
        # for docker-compose.yml/the installers (a single backend process),
        # but k8s/base/backend-deployment.yaml runs replicas=2 of this same
        # process behind one Service -- an engage/disengage call handled by
        # one pod never reached the other pod's own in-memory flag, which
        # then kept serving exploit/assessment actions under stale state
        # until it happened to restart on its own. start_kill_switch_sync_loop()
        # starts a background task (app/pentest/orchestrator.py) that
        # re-hydrates this same flag from the DB on a short interval for the
        # rest of this process's lifetime, so every replica converges on
        # whichever state was most recently persisted, not just the one
        # that handled that specific call.
        start_kill_switch_sync_loop()
    except Exception:
        logging.getLogger(__name__).exception(
            "Failed to load persisted pentest kill switch state at startup -- continuing without it."
        )


@app.on_event("shutdown")
async def _stop_pentest_kill_switch_sync() -> None:
    """Cancels the background task _load_pentest_kill_switch_state() above
    started, so it doesn't outlive the event loop it was scheduled on (and
    so repeated app startup/shutdown cycles within one process, e.g. across
    tests that do trigger real lifespan events, don't accumulate orphaned
    tasks)."""
    try:
        from app.pentest.orchestrator import stop_kill_switch_sync_loop

        await stop_kill_switch_sync_loop()
    except Exception:
        logging.getLogger(__name__).exception("Failed to stop pentest kill switch background sync task at shutdown.")


@app.on_event("startup")
async def _recover_orphaned_running_lookups() -> None:
    """A SIGKILL (OOM-kill, `docker kill`, power loss) gives the process zero
    chance to run any Python cleanup -- event_stream()'s own except/finally
    blocks in app/api/routes/lookup.py never execute, since the process is
    gone before any of that code can run. Confirmed live during enterprise
    QA chaos testing: a lookup whose investigation was in flight during a
    hard kill stayed status=RUNNING forever, even after the backend
    restarted cleanly. Since this process just started, ANY row already
    marked RUNNING at this point cannot belong to a request this process is
    handling (no such request could exist yet) -- it's necessarily orphaned
    from a previous, no-longer-running process instance."""
    from sqlalchemy import select, update

    from app.core.db import new_session
    from app.models.lookup import IOCLookup, LookupStatus

    try:
        async with new_session() as db:
            result = await db.execute(
                update(IOCLookup)
                .where(IOCLookup.status == LookupStatus.RUNNING)
                .values(status=LookupStatus.FAILED)
            )
            await db.commit()
        if result.rowcount:
            logging.getLogger(__name__).warning(
                "Recovered %d lookup(s) orphaned in RUNNING status by an unclean shutdown", result.rowcount
            )
    except Exception:
        logging.getLogger(__name__).exception("Orphaned-lookup recovery sweep failed -- continuing without it.")

    # SecurityAssessmentRun uses the exact same detached-background-task
    # pattern as IOCLookup (app/core/security_assessment.py's
    # _spawn_background) -- confirmed live during enterprise QA chaos
    # testing that a hard kill mid-scan leaves a run permanently RUNNING,
    # with nothing else in the codebase (no cron, no cancel endpoint) ever
    # able to recover it. Also sweeps PENDING: a crash in the narrow window
    # between start_run()'s initial commit and _execute_run()'s first
    # RUNNING write would otherwise leave a row stuck PENDING forever too.
    try:
        from app.models.security_assessment import SecurityAssessmentRun, SecurityAssessmentRunStatus

        async with new_session() as db:
            result = await db.execute(
                update(SecurityAssessmentRun)
                .where(SecurityAssessmentRun.status.in_([SecurityAssessmentRunStatus.PENDING, SecurityAssessmentRunStatus.RUNNING]))
                .values(
                    status=SecurityAssessmentRunStatus.FAILED,
                    error_message="Orphaned by an unclean shutdown; recovered at startup.",
                    # Real bug found live during overnight QA: every OTHER
                    # code path that finalizes a run's status (the success
                    # path and both exception paths in core/
                    # security_assessment.py, plus cancel_run's direct
                    # write) pairs the terminal status write with
                    # completed_at in the same .values(...) -- this sweep
                    # was the one that didn't, leaving a permanently
                    # self-contradictory row (status=FAILED,
                    # completed_at=None) that no other write ever
                    # back-fills.
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
        if result.rowcount:
            logging.getLogger(__name__).warning(
                "Recovered %d security assessment run(s) orphaned by an unclean shutdown", result.rowcount
            )
    except Exception:
        logging.getLogger(__name__).exception("Orphaned-security-assessment-run recovery sweep failed -- continuing without it.")

    # The Pentest Suite (app/pentest/orchestrator.py) uses the exact same
    # detached-asyncio.Task background-execution pattern as IOCLookup/
    # SecurityAssessmentRun above (start_assessment/resume_assessment's
    # `_assessment_tasks[assessment_id] = asyncio.create_task(...)`), tracked
    # only in that in-process dict -- which is empty on every fresh process
    # start, identical to `_run_tasks` before the SecurityAssessmentRun sweep
    # was added. A hard kill while an assessment is running therefore leaves
    # it permanently ACTIVE with no live task anywhere ever able to advance
    # or recover it: start_assessment only accepts DRAFT/PAUSED, and
    # resume_assessment only accepts PAUSED, so an orphaned ACTIVE row is a
    # dead end reachable only via a manual cancel. This mirrors that same
    # manual-cancel fallback (orchestrator.py's cancel_assessment, when it
    # finds no live task for the assessment) by writing CANCELLED directly,
    # then additionally cleans up what cancel_assessment itself does not:
    # the assessment's own non-terminal targets and any exploit attempt left
    # RUNNING.
    #
    # PentestTarget's DISCOVERING/ENUMERATING/ASSESSING/PENDING statuses are
    # only ever transient while _run_assessment's own task is actively
    # driving them -- deliberately scoped to targets of an assessment THIS
    # sweep is finding ACTIVE-with-no-task, since PENDING is also the
    # perfectly normal resting state for a target under a DRAFT assessment
    # (never started) or a PAUSED one (pause_assessment/resume_assessment
    # intentionally reset not-yet-completed targets to PENDING while
    # awaiting a future resume) -- neither of those is orphaned.
    #
    # PentestExploitAttempt is different: exploit.py's run_module() drives it
    # synchronously within the request/response cycle, not via
    # _assessment_tasks, and is deliberately allowed regardless of the
    # parent assessment's status (COMPLETED included -- see run_module's own
    # comment). So a RUNNING attempt is swept unconditionally, exactly like
    # IOCLookup above: this process just started, so no in-flight request
    # anywhere could still own it.
    try:
        from app.models.pentest import (
            PentestAssessment,
            PentestAssessmentStatus,
            PentestExploitAttempt,
            PentestExploitStatus,
            PentestTarget,
            PentestTargetStatus,
        )

        async with new_session() as db:
            orphaned_assessment_ids = (
                await db.execute(
                    select(PentestAssessment.id).where(PentestAssessment.status == PentestAssessmentStatus.ACTIVE)
                )
            ).scalars().all()

            targets_recovered = 0
            if orphaned_assessment_ids:
                targets_result = await db.execute(
                    update(PentestTarget)
                    .where(PentestTarget.assessment_id.in_(orphaned_assessment_ids))
                    .where(PentestTarget.status.in_([
                        PentestTargetStatus.PENDING, PentestTargetStatus.DISCOVERING,
                        PentestTargetStatus.ENUMERATING, PentestTargetStatus.ASSESSING,
                    ]))
                    .values(status=PentestTargetStatus.FAILED)
                )
                targets_recovered = targets_result.rowcount

            exploit_result = await db.execute(
                update(PentestExploitAttempt)
                .where(PentestExploitAttempt.status == PentestExploitStatus.RUNNING)
                .values(
                    status=PentestExploitStatus.ERROR,
                    result_transcript=PentestExploitAttempt.result_transcript
                    + "\n[orphaned by an unclean shutdown; recovered at startup]",
                )
            )

            assessments_recovered = 0
            if orphaned_assessment_ids:
                assessments_result = await db.execute(
                    update(PentestAssessment)
                    .where(PentestAssessment.id.in_(orphaned_assessment_ids))
                    .where(PentestAssessment.status == PentestAssessmentStatus.ACTIVE)
                    .values(status=PentestAssessmentStatus.CANCELLED)
                )
                assessments_recovered = assessments_result.rowcount

            await db.commit()
        if assessments_recovered or targets_recovered or exploit_result.rowcount:
            logging.getLogger(__name__).warning(
                "Recovered %d pentest assessment(s), %d target(s), %d exploit attempt(s) orphaned by an unclean shutdown",
                assessments_recovered, targets_recovered, exploit_result.rowcount,
            )
    except Exception:
        logging.getLogger(__name__).exception("Orphaned-pentest-assessment recovery sweep failed -- continuing without it.")


_HEALTH_CHECK_TIMEOUT_SECONDS = 3.0


async def _check_postgres() -> tuple[bool, str]:
    try:
        from app.core.db import new_session

        async def _ping():
            async with new_session() as db:
                await db.execute(text("SELECT 1"))

        await asyncio.wait_for(_ping(), timeout=_HEALTH_CHECK_TIMEOUT_SECONDS)
        return True, "reachable"
    except Exception as exc:  # noqa: BLE001 -- a health check must never itself raise
        return False, f"{type(exc).__name__}: {exc}"[:200]


async def _check_redis() -> tuple[bool, str]:
    try:
        from app.core.cache import get_redis

        await asyncio.wait_for(get_redis().ping(), timeout=_HEALTH_CHECK_TIMEOUT_SECONDS)
        return True, "reachable"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:200]


@app.get("/health")
async def health():
    """Deliberately dependency-free liveness check -- kept that way on
    purpose (see this repo's own backend-tests.yml comment and
    test_api_health.py's docstring, both explicit that this route needs no
    real DB/Redis so it can smoke-test on a bare CI runner). Real
    dependency checking lives at GET /health/detailed instead of here, so
    this endpoint's existing fast, infra-independent contract is preserved
    for anything already relying on it. version/uptime_seconds are new but
    additive -- no dependency involved, and no existing caller asserts an
    exact/closed body shape (confirmed: test_api_health.py only checks
    status=="ok" and "service" in body)."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": _APP_VERSION,
        "uptime_seconds": round(time.monotonic() - _process_started_at, 1),
    }


@app.get("/health/detailed")
async def health_detailed(response: Response):
    """The real dependency-aware health check. Previously there was no such
    thing anywhere in the app -- GET /health (above) unconditionally
    returned {"status": "ok"} regardless of any real dependency, confirmed
    live to still return 200 with Postgres fully stopped, which is exactly
    the signal a watchdog needs to judge whether the backend is actually
    usable, not just alive. Windows/Linux watchdog scripts and the Docker
    Compose healthcheck: block should point here, not at the plain
    /health above.

    Postgres is load-bearing for virtually every endpoint, so its failure
    makes the service genuinely DOWN (503). Redis failure is DEGRADED
    (200): caching, rate limiting, and Celery break, but read-mostly
    endpoints that don't touch Redis still work -- collapsing that into the
    same DOWN/503 state as a real outage would be less accurate, not more.
    """
    postgres_ok, postgres_detail = await _check_postgres()
    redis_ok, redis_detail = await _check_redis()

    if not postgres_ok:
        overall = "down"
    elif not redis_ok:
        overall = "degraded"
    else:
        overall = "healthy"

    response.status_code = 200 if overall != "down" else 503
    return {
        "status": overall,
        "service": settings.app_name,
        "version": _APP_VERSION,
        "uptime_seconds": round(time.monotonic() - _process_started_at, 1),
        "dependencies": {
            "postgres": {"ok": postgres_ok, "detail": postgres_detail},
            "redis": {"ok": redis_ok, "detail": redis_detail},
        },
    }


@app.get("/network-info")
async def network_info():
    """Unauthenticated, same trust model as /health -- a point-in-time
    snapshot from the Windows wizard's last run (Common.ps1's
    Get-LanIpAddress), not a live re-detection; a container can never
    discover the Windows host's real LAN IP itself (verified empirically:
    self-detecting inside this very container returns Docker's own bridge
    address, and host.docker.internal resolves to Docker Desktop's internal
    VM gateway -- neither is the host's real interface)."""
    return {
        "detected_lan_ip": settings.detected_lan_ip,
        "frontend_port": settings.host_port_frontend,
        "backend_port": settings.host_port_backend,
    }
