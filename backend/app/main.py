"""FastAPI application entrypoint."""
import contextvars
import logging
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

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
    pivot,
    providers,
    runtime,
    security_assessment,
)
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

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Unified threat intelligence workbench: single-search IOC lookup across "
    "dozens of providers, correlated and summarized by a local Ollama model "
    "(or AWS Bedrock/Gemini/Anthropic/Groq/OpenAI, configurable via AI_BACKEND).",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url="/docs",
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
    than silently issue forgeable tokens."""
    if settings.jwt_secret_key in _KNOWN_PLACEHOLDER_JWT_SECRETS:
        logging.getLogger(__name__).warning(
            "JWT_SECRET_KEY is still set to the placeholder value from .env.example. "
            "Every access/refresh token this server issues can be forged by anyone who "
            "knows this default. Generate a real random secret and set it in .env before "
            "exposing this instance to anything but localhost."
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
    from sqlalchemy import update

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
                .values(status=SecurityAssessmentRunStatus.FAILED, error_message="Orphaned by an unclean shutdown; recovered at startup.")
            )
            await db.commit()
        if result.rowcount:
            logging.getLogger(__name__).warning(
                "Recovered %d security assessment run(s) orphaned by an unclean shutdown", result.rowcount
            )
    except Exception:
        logging.getLogger(__name__).exception("Orphaned-security-assessment-run recovery sweep failed -- continuing without it.")


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.app_name}


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
