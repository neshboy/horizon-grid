# Backend Architecture and Request Flow

This chapter is a code-level reference for how the FastAPI backend is assembled and how one real request moves through it. It covers three things, in order: (1) how `backend/app/main.py` builds the application object — routers, middleware, and startup events; (2) the layering convention the codebase follows (`routes/` → `services/`-equivalent modules → `models/`); and (3) a full, file-and-line trace of `POST /api/v1/lookup/stream`, the platform's single most important endpoint, from the HTTP request to the closing SSE event. Every claim below is anchored to a specific file and, where useful, a line number, as of this codebase.

## 📋 Table of contents

- [1. Application assembly (`app/main.py`)](#1--application-assembly-appmainpy)
  - [Middleware](#middleware)
  - [Router registration](#router-registration)
  - [Startup events](#startup-events)
  - [Endpoints outside the versioned API](#endpoints-outside-the-versioned-api)
- [2. The layering convention: routes → domain services → models](#2--the-layering-convention-routes--domain-services--models)
- [3. Full trace: `POST /api/v1/lookup/stream`](#3--full-trace-post-apiv1lookupstream)
  - [Step 0 — Dependency resolution](#step-0--dependency-resolution-before-the-handler-body-runs)
  - [Step 1 — Rate limiting](#step-1--rate-limiting)
  - [Step 2 — IOC type detection and lookup row creation](#step-2--ioc-type-detection-and-lookup-row-creation)
  - [Step 3 — The SSE generator opens and emits `detected`](#step-3--the-sse-generator-opens-and-emits-detected)
  - [Step 4 — Provider fan-out](#step-4--provider-fan-out-detected--n--provider_resultprovider_summary)
  - [Step 5 — Correlation](#step-5--correlation-correlation-event)
  - [Step 6 — Final AI assessment](#step-6--final-ai-assessment-final_assessment-event)
  - [Step 7 — Evidence ledger build](#step-7--evidence-ledger-build-no-sse-event-of-its-own)
  - [Step 8 — Closing events and error/disconnect handling](#step-8--closing-events-and-errordisconnect-handling)
  - [Summary of the full path](#summary-of-the-full-path)

---

## 1. 📦 Application assembly (`app/main.py`)

The entire FastAPI app is built in one module (`app/main.py`, 398 lines). There is no application factory function and no per-environment app-building logic — `app` is a module-level object constructed at import time, from `settings = get_settings()` (`main.py:59`), the `@lru_cache`-decorated `Settings` singleton (`app/core/config.py:13,110-111`). `settings.api_v1_prefix` (`config.py:20`, value `"/api/v1"`) is baked into the OpenAPI URL and every router prefix below at import time, not re-read per request.

### Middleware

Three middlewares are registered, in this order:

```python
# app/main.py:108-115
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=PRIVATE_NETWORK_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

CORS no longer keys off `settings.debug`. `allow_origins` is always an empty list; instead, `allow_origin_regex` (`PRIVATE_NETWORK_ORIGIN_REGEX`, `main.py:98-106`) allow-lists `http://` requests from `localhost`, `127.0.0.1`, or any RFC 1918 private-range host (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) on any port — this is what lets one built frontend be opened from `localhost`, `127.0.0.1`, or another device's LAN address without a build-time CORS allow-list, while still rejecting an arbitrary public origin. The module's own comment is explicit that this only relaxes the browser's same-origin policy; the real authorization boundary is JWT auth (`app/auth/rbac.py`), not origin matching.

Two more `@app.middleware("http")` functions follow CORS: `request_id_middleware` (`main.py:118-141`) generates or forwards an `X-Request-Id`, binding it to a `ContextVar` that every log line in the process (including uvicorn's access log and httpx's outbound-call log) is filtered through, so concurrent requests' log lines are attributable; and `request_body_size_limit_middleware` (`main.py:156-168`) rejects any request whose `Content-Length` exceeds 10 MB with a `413`, checked before the body is read. No CSRF or security-headers middleware is registered.

The only other cross-cutting instrumentation is Prometheus metrics, attached immediately after the middleware stack: `Instrumentator().instrument(app).expose(app, endpoint="/metrics")` (`main.py:171`). This exposes `GET /metrics` with no auth dependency, no `/api/v1` prefix, and no permission check.

### Router registration

All fifteen route modules are imported in one statement and registered in a fixed order, each mounted under the same global prefix:

```python
# app/main.py:15-31, 173-187
from app.api.routes import (
    admin, ai_config, analysis, auth, basket, cases, dashboard, hunting,
    lookup, pentest, pentest_exploit, pivot, providers, runtime, security_assessment,
)
...
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
```

Each router carries its own sub-prefix declared where it's defined (e.g. `router = APIRouter(prefix="/lookup", tags=["lookup"])`, `app/api/routes/lookup.py:44`), so the final path is always `{api_v1_prefix}{router_prefix}{route_path}` — e.g. `/api/v1` + `/lookup` + `/stream` = `/api/v1/lookup/stream`. Registration order has no effect on route matching (FastAPI matches by path, and no paths overlap across these fifteen modules); it is simply the order this documentation set uses when enumerating endpoints. `admin.py`, `security_assessment.py`, `pentest.py`, `pentest_exploit.py`, and `dashboard.py` were added after the original ten — respectively the Administration console, the Security Assessment Toolkit, the Pentest Suite's own lifecycle, its admin-only Metasploit exploit-validation routes, and the executive dashboard's KPI/summary endpoints.

### Startup events

Four `@app.on_event("startup")` hooks exist, run in this order:

1. `_warn_if_jwt_secret_is_a_placeholder()` (`main.py:194-208`) — logs a warning if `jwt_secret_key` is still `.env.example`'s literal placeholder value.
2. `_warn_if_msf_rpc_password_is_a_placeholder()` (`main.py:211-223`) — same pattern for the Pentest Suite's Metasploit RPC password, mitigated by `msfrpcd` being bound to `127.0.0.1` only regardless.
3. `_seed_runtime_config()` (`main.py:226-236`), which calls `seed_from_env_if_empty()` (`app/core/runtime_config.py`) inside a `try/except Exception` that logs but never blocks boot on failure. That function is the bridge described in the credential-lifecycle chapter of this documentation set: if `provider_runtime_configs` already has any row, it no-ops; otherwise it reads every AI-backend/IOC-provider credential out of the frozen `Settings` singleton and inserts one encrypted row per provider/backend — a one-time migration from `.env`-driven to DB-driven configuration.
4. `_recover_orphaned_running_lookups()` (`main.py:239-294`) — on process start, flips any `IOCLookup` or `SecurityAssessmentRun` row still stuck `RUNNING` (or, for security-assessment runs, `PENDING`) to `FAILED`, since any such row still in that state at the instant this process just started cannot belong to a request this process is handling — it can only be orphaned by a previous process instance that was killed uncleanly (OOM-kill, `docker kill`, power loss) before its own `except`/`finally` cleanup ever ran.

There is no corresponding shutdown hook anywhere in `main.py`.

### Endpoints outside the versioned API

`GET /health`, `GET /health/detailed`, `GET /network-info` (all in `main.py`), and `GET /metrics` (`main.py:171`) are the HTTP-reachable endpoints defined directly in `main.py` rather than in `app/api/routes/*.py`. None carries the `/api/v1` prefix, and none has a `require_permission(...)` or `get_current_user` dependency — all are intentionally unauthenticated. `/health` (`main.py:324-341`) is a deliberately dependency-free liveness check (version + uptime only, no DB/Redis call) so it stays usable on a bare CI runner; `/health/detailed` (`main.py:344-381`) is the real dependency-aware check a watchdog should point at instead — it pings Postgres and Redis and reports `healthy`/`degraded`/`down` (Postgres failure is `down`/`503`; Redis-only failure is `degraded`/`200`, since caching and rate limiting break but most read-mostly endpoints still work); `/network-info` (`main.py:384-397`) serves the Windows wizard's last-detected LAN IP for the frontend's Network Access panel; and `/metrics` is for Prometheus scraping.

## 2. 🧩 The layering convention: routes → domain services → models

The codebase does not use a single `services/` package name; instead each concern has its own top-level `app/` package, and the convention is consistent regardless of package name: **route handlers in `app/api/routes/*.py` are thin** — they perform auth/permission checks, load/validate the request, and delegate to a domain module, then serialize that module's return value back into the response. Business logic does not live in the route file itself beyond that orchestration.

| Layer | Packages | Responsibility |
|---|---|---|
| **Routes** | `app/api/routes/*.py` | HTTP concerns only: request parsing (Pydantic schemas from `app/schemas/`), `Depends(require_permission(...))` / `Depends(get_current_user)` auth gates, calling into the layer below, shaping the JSON/SSE response, raising `HTTPException` for the handful of route-level error cases documented per-endpoint. |
| **Domain/"service" modules** | `app/ai/service.py`, `app/ai/analysis_service.py`, `app/ai/hunting_service.py`, `app/providers/orchestrator.py`, `app/correlation/engine.py`, `app/evidence/builder.py`, `app/evidence/loaders.py`, `app/evidence/pivot.py`, `app/core/runtime_config.py`, `app/core/users.py`, `app/core/audit.py` | The actual business logic: AI prompting/backend resolution, provider fan-out/caching/retry, correlation-graph construction, deterministic evidence extraction, runtime-config CRUD, and user-account management (create/edit/enable-disable/reset-password, last-admin protection). These modules are framework-agnostic — none of them import FastAPI, and several (`correlation/engine.py`, `evidence/builder.py`, `evidence/pivot.py`) are explicitly documented in their own module docstrings as pure, I/O-free functions kept that way specifically so they are unit-testable in isolation from the web layer. `app/core/audit.py` is the shared append-only audit-log writer both `runtime_config.py` and `users.py` call into — extracted from `runtime_config.py` (which re-exports both functions unchanged) specifically so a user-management module didn't need to import an entire provider-configuration service module just to write an audit row. |
| **Models** | `app/models/*.py` | SQLAlchemy 2.0 ORM entities (`IOCLookup`, `ProviderResultRecord`, `AISummaryRecord`, `CorrelationEdgeRecord`, `FinalAssessmentRecord`, `EvidenceItem`, `User`, `BasketItem`, `Case`/`CaseIOC`/`CaseNote`/`CaseReport`, `ProviderRuntimeConfig`/`ConfigAuditLog`) plus a handful of enums colocated with the model that owns them (e.g. `LookupStatus`/`Verdict` in `app/models/lookup.py`). No business logic lives on these classes beyond SQLAlchemy relationship/mixin declarations (`app/models/base.py`'s `UUIDPrimaryKeyMixin`/`TimestampMixin`). |

Two supporting packages sit underneath all three layers, imported by nearly everything above them without depending on any of it: `app/core/` (settings, DB session factory, Redis cache/rate-limiter, Fernet crypto, the per-investigation `ContextVar` credential snapshot) and the Pydantic schema modules (`app/ai/schemas.py`, `app/ai/analysis_schemas.py`, `app/schemas/*.py`) that both routes and domain modules validate against. `app/auth/rbac.py` is the one cross-cutting dependency every protected route imports directly rather than routing through a domain module, since permission-checking is itself an HTTP-layer concern.

Worth calling out for anyone extending the codebase: `app/api/routes/lookup.py` is the one route module that does **not** fully delegate to a single domain module for its core endpoint. `stream_lookup()` (traced in full below) directly orchestrates calls across four domain modules in sequence (`providers/orchestrator.py`, `ai/service.py`, `correlation/engine.py`, `evidence/builder.py`) plus raw SQLAlchemy session writes, inline in the route function, rather than through one composed "run a lookup" service function — a consequence of the SSE streaming requirement, since each domain call's result must be persisted and yielded before the next one starts. This makes it the least "thin" handler in the codebase, and the natural place to read to understand the whole pipeline.

## 3. 🔬 Full trace: `POST /api/v1/lookup/stream`

This section follows one request through every layer, in the exact order the code executes it. The route is defined in `app/api/routes/lookup.py:51-303` (`stream_lookup`), mounted at `/api/v1/lookup/stream` (prefix composition described in §1).

### Step 0 — Dependency resolution (before the handler body runs)

FastAPI resolves two `Depends(...)` parameters before `stream_lookup`'s body executes (`lookup.py:52-56`):

- `db: AsyncSession = Depends(get_db)` — opens a new `AsyncSession` from the process-wide `async_sessionmaker` (`app/core/db.py:8-14`), used only for the initial `IOCLookup` insert; it is explicitly **not** reused for the rest of the request (see Step 2).
- `user: CurrentUser = Depends(require_permission("lookup:create"))` — depends on `get_current_user` (`app/auth/rbac.py:28-47`), which extracts a Bearer token via `HTTPBearer(auto_error=False)` (`rbac.py:18`), decodes it with `decode_token()`, rejects it with `401 "Could not validate credentials"` if missing/undecodable/not an access token (`rbac.py:32-41`), then looks the user up by the token's `sub` (email) claim and rejects inactive/missing users the same way (`rbac.py:43-46`). `require_permission("lookup:create")` (`rbac.py:50-62`) then checks `"lookup:create" in ROLE_PERMISSIONS.get(user.role, set())` (`app/models/user.py`) and raises `403` if the caller's role lacks it — only `admin` and `analyst` carry `lookup:create`; `viewer` does not.

### Step 1 — Rate limiting

```python
# lookup.py:61-75
settings = get_settings()
limiter = RateLimiter(
    f"lookup_create:{user.id}",
    max_calls=settings.lookup_rate_limit_max_calls,
    window_seconds=settings.lookup_rate_limit_window_seconds,
)
if not await limiter.allow():
    raise HTTPException(status_code=429, detail=...)
```

`RateLimiter` (`app/core/cache.py:42-56`) is a fixed-window counter stored in Redis under key `rate_limit:lookup_create:{user_id}` (`cache.py:47`): `INCR` the key, and if this is the first increment in the window, set its TTL to `window_seconds` (`cache.py:53-55`). Defaults are `lookup_rate_limit_max_calls = 10` and `lookup_rate_limit_window_seconds = 60` (`app/core/config.py:106-107`) — 10 lookups per 60 seconds, per authenticated user, enforced centrally in Redis so it holds across every backend worker process, not just the one that happens to handle a given request.

### Step 2 — IOC type detection and lookup row creation

```python
# lookup.py:77-88
ioc_value = payload.value.strip()
ioc_type = payload.ioc_type_hint or detect_ioc_type(ioc_value)
if ioc_type == IOCType.UNKNOWN:
    raise HTTPException(status_code=422, detail="Could not determine IOC type; pass ioc_type_hint.")

lookup = IOCLookup(
    ioc_value=ioc_value, ioc_type=ioc_type.value, status=LookupStatus.RUNNING, requested_by=user.id
)
db.add(lookup)
await db.commit()
await db.refresh(lookup)
lookup_id = lookup.id
```

`detect_ioc_type()` (`app/ioc/detector.py`) runs an ordered regex/heuristic cascade against the raw string to classify it into one of the `IOCType` enum values (`app/ioc/types.py`) — an explicit client-supplied `ioc_type_hint` on the request body takes precedence and skips detection. The `IOCLookup` row (`app/models/lookup.py:37-66`) is inserted and committed using the request-scoped `db` session **before** the SSE generator below is even constructed, so the row (with `RUNNING` status) exists in Postgres before the first byte of the response body is sent.

A load-bearing implementation detail is documented in-line at `lookup.py:93-100`: the `Depends(get_db)` session is torn down as soon as the route function returns the `StreamingResponse`, because generators are lazy — that teardown happens *before* the generator body below ever runs. Using `db` inside the generator would therefore silently drop every later `lookup.status = ...` mutation once the session closes. The fix is that the generator opens and owns a brand-new, independent session (`stream_db`, via `app/core/db.py:17-22`'s `new_session()`) for its entire run. From here forward — every provider result, AI summary, correlation edge, the final assessment, and the evidence ledger — is persisted through `stream_db`, never through the original `db`.

### Step 3 — The SSE generator opens and emits `detected`

```python
# lookup.py:90-101
async def event_stream():
    yield _sse("detected", {"lookup_id": str(lookup_id), "ioc_value": ioc_value, "ioc_type": ioc_type.value})
    async with new_session() as stream_db:
        stream_lookup_row = await stream_db.get(IOCLookup, lookup_id)
        ...
```

`_sse()` (`lookup.py:47-48`) formats one SSE frame: `f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"`. The route returns immediately after defining this generator — `return StreamingResponse(event_stream(), media_type="text/event-stream")` (`lookup.py:303`) — so all pipeline work below happens lazily, as the ASGI server pulls values out of `event_stream()`.

### Step 4 — Provider fan-out (`detected` → N × `provider_result`/`provider_summary`)

The core loop (`lookup.py:104-150`, abridged):

```python
async for result in run_all_providers(ioc_value, ioc_type, candidate_providers):
    provider_results.append(result)
    stream_db.add(ProviderResultRecord(lookup_id=lookup_id, provider_id=result.provider_id, ...))
    if result.status.value == "ok":
        summary = await summarize_provider(ioc_value, ioc_type.value, result, backend_override=payload.ai_backend)
        stream_db.add(AISummaryRecord(lookup_id=lookup_id, provider_id=result.provider_id, summary=summary.model_dump()))
    await stream_db.commit()
    yield _sse("provider_result", result.to_dict())
    if result.status.value == "ok":
        yield _sse("provider_summary", summary.model_dump())
```

`candidate_providers` is `None` (all applicable providers) unless the request body's `provider_ids` narrows it to a client-selected subset (`lookup.py:104-107`). `run_all_providers()` (`app/providers/orchestrator.py:89-127`) is an `async` generator, not a batch call: it filters the 18 registered providers (`app/providers/registry.py`) to those whose `supports(ioc_type)` is true (`orchestrator.py:99-103`); takes **one** snapshot of every IOC provider's enabled/configured/credentials state (`get_ioc_provider_snapshot()`, `app/core/runtime_config.py:297-315`, a fresh DB read) and installs it into a `contextvars.ContextVar` via `set_provider_overrides()` (`app/core/runtime_context.py`), so every concurrently-spawned provider task sees identical configuration for this one investigation even if an admin changes a credential mid-run (`orchestrator.py:105-113`); then opens one shared, connection-pooled `httpx.AsyncClient` and spawns one `asyncio.create_task` per provider via `_run_with_policy()` (`orchestrator.py:115-122`). That function checks the Redis result cache first (`app/core/cache.py:29-31`, key `provider_cache:{provider_id}:{ioc_type}:{sha256(value)}`, default TTL 3600s), and on a miss calls `provider.run()` under a `tenacity` retry (only `httpx.ConnectError`/`ReadTimeout`/`PoolTimeout`, default 2 retries) plus an `asyncio.wait_for` timeout (default 20s; `orchestrator.py:29-86`, `config.py:101-103`). Results are yielded via `asyncio.as_completed(tasks)` (`orchestrator.py:123-127`) — completion order, not registration order — which is why the route can stream each `provider_result` the instant that provider finishes.

For each `ok`-status result, the route calls `summarize_provider()` (`app/ai/service.py:336-374`): one AI call grounded only in that provider's own JSON, pruned to a bounded per-field size first (`_prune_for_prompt()`, `service.py:273-325` — a long `str` field is capped at 2000 chars, a long `list`/`dict` field at 800, so a provider's oversized structural data can't bury its own short verdict/score fields under noise), using whichever backend `_get_ai_client()` resolves (explicit request override → active runtime-configured backend, fresh DB read → legacy `Settings.ai_backend`; `service.py:104-145`). A failed/malformed AI call degrades to a placeholder `ProviderSummary` rather than raising (`service.py:365-374`) — one provider's summarization failure never aborts the request.

Every iteration ends with `await stream_db.commit()` (`lookup.py:147`) — a commit **per provider**, not one at the end of the loop. Per the source comments, this was added after confirming live that a client disconnecting mid-investigation discarded every uncommitted `ProviderResultRecord`/`AISummaryRecord`: the lookup correctly flipped to `FAILED`, but `GET /lookup/{id}` came back with an empty `provider_results` list despite several real provider calls having already completed and streamed (`lookup.py:133-146`). Committing per-provider bounds that loss to at most the one result in flight at disconnect time.

### Step 5 — Correlation (`correlation` event)

`correlate(ioc_value, ioc_type, provider_results)` (`lookup.py:152`; `app/correlation/engine.py:97+`) runs once every provider task has resolved. It is a pure, I/O-free function: it walks a fixed table of known provider-response field names (`_RELATIONSHIP_EXTRACTORS`, `engine.py:57-70` — e.g. `resolved_ips`→`resolves_to`, `mitre_techniques`→`uses_technique`, `cves`→`exploits`) to extract typed `GraphEdge`s, assigns each a base confidence per source field (`_FIELD_BASE_CONFIDENCE`, `engine.py:77-90`), and boosts confidence `+0.15` per additional distinct provider independently asserting the identical `(source, target, relationship)` triple (`_CORROBORATION_BONUS_PER_PROVIDER`, `engine.py:94`), capped at `1.0`. The returned `CorrelationResult` (`engine.py:42-47`: `nodes`, `edges`, `deduplicated_facts`, `provider_agreement`) feeds Steps 6-7. Every edge is persisted as a `CorrelationEdgeRecord` (`app/models/lookup.py:100-118`, `lookup.py:153-165`) and the full node/edge set streamed in one `correlation` SSE event (`lookup.py:166-172`).

### Step 6 — Final AI assessment (`final_assessment` event)

The route re-reads AI summaries from Postgres rather than reusing the in-memory list from Step 4 (`lookup.py:174-185`) — a consistency choice ensuring the final assessment is grounded in exactly what was persisted. Rows that fail `ProviderSummary.model_validate()` are logged and skipped, not fatal (`lookup.py:179-185`). It also builds an `unavailable_providers` list distinguishing providers that errored/timed out/were rate-limited/disabled/unconfigured from providers that ran and genuinely found nothing (`lookup.py:192-203`) — a distinction `generate_final_assessment()`'s system prompt depends on to avoid describing an unavailable provider's silence as "clean."

`generate_final_assessment()` (`app/ai/service.py:378-540`) makes at most two AI calls (`for attempt in range(2)`, `service.py:488`) — a bounded retry scoped specifically to `pydantic.ValidationError` (`service.py:513`), which `FinalAssessment`'s own model validator raises when the model emits a self-contradictory verdict/probability pair (e.g. `final_verdict="malicious"` with a low `malicious_probability`) — not a generic retry-on-any-failure: any other exception (`service.py:517`) fails fast after one attempt, since retrying a rate-limit or network error immediately would just waste more of the same budget rather than fix anything. Grounded only in the per-provider summaries plus the correlation output, never raw provider JSON. Two more anti-hallucination controls wrap it:

- **A hard-coded empty-evidence short-circuit** (`service.py:334-370`): if both `provider_summaries` and `correlation.edges` are empty, the function returns a deterministic `FinalAssessment` with `final_verdict=Verdict.UNKNOWN` and never calls the AI. The in-line comment documents the incident that motivated this: a real EICAR-test-file hash, with zero configured providers, still produced `final_verdict="highly_malicious"` (`malicious_probability=92`) with a fabricated ransomware/trojan attribution — the model answered from pretrained knowledge of a famous test hash rather than the (empty) supplied evidence, despite being instructed not to. The fix is deterministic code rather than a prompt change, since the model had already been told not to do this and did it anyway.
- **`_ground_final_assessment()`** (`service.py:211-264`), run on every non-empty-evidence response: strips any provider named in `agreeing_providers`/`disagreeing_providers` not backed by a real correlation edge, `provider_agreement` entry, or per-provider summary (`known_provider_ids` is unioned in so providers like the OSINT crawler — which returns data but produces no correlation edge or verdict fact — aren't misclassified as hallucinated); and flags (rather than strips) any `mitre_mappings` entry not backed by a real `uses_technique` edge, by setting its `grounded` field to `False`.

The resolved `ai_backend`/`ai_model` actually used is written back onto the assessment object (`service.py:426-427`), overwriting whatever the model itself may have emitted — this is what makes `POST /lookup/{id}/reanalyze` (AI-comparison re-analysis) trustworthy even though it calls the same function. Back in the route, `IOCLookup`'s `status`/`final_verdict`/`risk_score`/`confidence_score`/`final_assessment` are updated in place, and a `FinalAssessmentRecord` (`app/models/lookup.py:121-144`) is inserted with `is_primary=True` — the row every later comparison run (`is_primary=False`) is diffed against (`lookup.py:214-228`).

### Step 7 — Evidence ledger build (no SSE event of its own)

`build_evidence(provider_results, provider_summaries, correlation)` (`lookup.py:235`; dispatcher at `app/evidence/builder.py:142-147`) concatenates `build_evidence_from_providers()` (one record per provider that returned OK data, plus one per interesting finding, `builder.py:65+`) with `build_evidence_from_correlation()` (one record per correlation edge, typed by target — `malware_association`, `threat_actor_association`, `campaign_association`, `mitre_technique`, `infrastructure`, or generic `relationship`; `_relationship_evidence_type()`, `builder.py:51-62`). Per the module docstring, this is a deliberately separate, deterministic pass, not folded into the AI call above, "so 'the AI made this up' and 'the AI cited real evidence' are mechanically distinguishable" (`builder.py:1-6`). The resulting `EvidenceItem` rows and the Step 6 `IOCLookup`/`FinalAssessmentRecord` mutations are all flushed in the same `stream_db.commit()` (`lookup.py:236-252`).

### Step 8 — Closing events and error/disconnect handling

`yield _sse("final_assessment", ...)` then `yield _sse("done", ...)` close a successful run (`lookup.py:254-255`). Any exception raised anywhere in Steps 4-7 is caught by one `except Exception` block (`lookup.py:256-260`), which marks the lookup `FAILED`, commits, and emits an `error` SSE event instead — the HTTP response itself stays `200 text/event-stream` throughout, since it has already started streaming by the time any pipeline code runs; failures are communicated only via the event stream, never an HTTP error status.

A second, separate failure mode lives in a `finally` block (`lookup.py:261-301`): a client disconnecting mid-stream raises `GeneratorExit` — a `BaseException`, not an `Exception` — at whichever `yield` is executing, so the `except Exception` above never sees it. Left unhandled, this was confirmed in testing to leave the lookup permanently `RUNNING`, with `GET /lookup/{id}` never transitioning to `completed`/`failed`. A first fix attempt (reusing `stream_db` inside a shielded commit) was confirmed *worse* — the enclosing `async with` block's own rollback raced the shielded task, producing an orphaned task and a `ResourceClosedError` (`lookup.py:275-287`). The working fix (`lookup.py:288-301`): if the lookup is still `RUNNING` when `finally` runs, a nested `_mark_failed()` coroutine opens a **fresh** `new_session()`, re-fetches the row, and flips it to `FAILED`, with the whole operation wrapped in `asyncio.shield()` so disconnect-driven task cancellation cannot cut off the cleanup write itself.

### Summary of the full path

| Step | Code location | I/O | Persists |
|---|---|---|---|
| Auth + permission check | `rbac.py:28-62` | Postgres (user lookup) | — |
| Rate limit | `lookup.py:61-75`, `cache.py:42-56` | Redis | — |
| IOC type detection + lookup row | `lookup.py:77-88`, `ioc/detector.py` | Postgres | `ioc_lookups` (status=RUNNING) |
| Provider fan-out | `orchestrator.py:89-127` | Redis (cache), N × external HTTP | `provider_results` (per provider) |
| Per-provider AI summary | `ai/service.py:336-374` | 1 AI call per OK provider | `ai_summaries` (per provider) |
| Correlation | `correlation/engine.py:97+` | none (pure function) | `correlation_edges` |
| Final AI assessment | `ai/service.py:378-540` | up to 2 AI calls (bounded retry on a validation failure) | `ioc_lookups` (final fields), `final_assessment_records` |
| Evidence build | `evidence/builder.py:142-147` | none (pure function) | `evidence_items` |
| SSE close | `lookup.py:254-301` | — | `ioc_lookups.status` (COMPLETED/FAILED) |

[FIGURE: dev-03-backend-architecture-and-request-flow-diagram-1.png | Diagram: Summary of the full path]
Diagram: `POST /api/v1/lookup/stream`, end-to-end sequence. Each stage after provider fan-out commits its own writes independently, so a mid-stream failure or disconnect only loses the one step in flight, never everything already completed.

Every other endpoint in the platform (`analysis.py`'s why/what-is/disagreement/etc., `hunting.py`, `pivot.py`, `basket.py`, `cases.py`) operates on an already-completed lookup's persisted rows and follows the same routes → domain-module → models layering, but without the streaming/session-ownership complexity described above, since none of them return a `StreamingResponse` — they load, call one domain function, and return a single JSON body.
