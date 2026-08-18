# Backend System Overview and Lifecycle

This chapter describes the backend as an *operational system*: which Docker containers exist and what each one does, the exact sequence of events between `docker compose up` and the first request being served, and the anatomy of a single HTTP request as it passes through authentication, routing, business logic, and the database. Provider connectors, the AI pipeline, the database schema, and security controls each have their own chapter; this one is the connective tissue a backend engineer or DevOps/SRE reader needs before touching any of those.

All facts below are drawn directly from `docker-compose.yml`, `docker-compose.prod.yml`, `backend/Dockerfile`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/core/db.py`, `backend/app/core/runtime_config.py`, `backend/app/auth/rbac.py`, and `backend/app/api/routes/lookup.py`.

## 1. Docker Service Inventory

`docker-compose.yml` defines eight services: four datastores, three backend-codebase processes (the FastAPI app plus two Celery roles), and the frontend. See the Database Architecture chapter for what Postgres/Redis/Neo4j/OpenSearch are actually used for, and the Security Architecture chapter for the network-exposure rationale behind the port bindings below.

| Service | Image / entrypoint | Depends on (health-gated) | Port binding (host) | Restart policy |
|---|---|---|---|---|
| `postgres` | `postgres:16-alpine` | -- | `127.0.0.1:${HOST_PORT_POSTGRES:-5433}:5432` | none set |
| `redis` | `redis:7-alpine` | -- | `127.0.0.1:${HOST_PORT_REDIS:-6379}:6379` | none set |
| `neo4j` | `neo4j:5-community` + APOC | -- | `127.0.0.1:${HOST_PORT_NEO4J_HTTP:-7475}:7474`, `127.0.0.1:${HOST_PORT_NEO4J_BOLT:-7688}:7687` | none set |
| `opensearch` | `opensearchproject/opensearch:2.17.0` | -- | `127.0.0.1:${HOST_PORT_OPENSEARCH:-9200}:9200` | none set |
| `backend` | built from `backend/Dockerfile` (`python:3.12-slim`) | `postgres`, `redis` (`service_healthy`) | `${HOST_PORT_BACKEND:-8000}:8000` | none set |
| `celery_worker` | same `backend/` build context | `postgres`, `redis` (`service_healthy`) | none published | `unless-stopped` |
| `celery_beat` | same `backend/` build context | `redis` (`service_healthy`) | none published | `unless-stopped` |
| `frontend` | built from `frontend/Dockerfile` (Next.js) | `backend` (existence only, not health) | `${HOST_PORT_FRONTEND:-3000}:3000` | none set |

Operationally relevant details:

- **All four datastore ports bind to `127.0.0.1` only**, not `0.0.0.0` -- the application itself never uses these host bindings, since `DATABASE_URL`/`REDIS_URL`/`NEO4J_URI`/`OPENSEARCH_URL` all address the internal Docker network by service name. The bindings only affect what can reach the datastore directly from the host machine.
- **`backend` and `celery_worker` wait on both Postgres and Redis health checks** (`pg_isready` / `redis-cli ping`) before Compose starts them; `celery_beat` only waits on Redis, since it schedules jobs but never queries Postgres.
- **Only `celery_worker`/`celery_beat` have `restart: unless-stopped`.** `backend`, the datastores, and `frontend` do not auto-restart on crash under the default compose file (`docker-compose.prod.yml` does not change this).
- **`backend`, `celery_worker`, and `celery_beat` build from the identical `backend/` context** and ship the same image; they differ only in the `command:` each service starts with (see §2), not in the code on disk.
- `OLLAMA_BASE_URL` is set directly in the `backend` service's `environment:` block rather than via `env_file: .env` like other credentials. A compose `environment:` entry always wins over `env_file:`, so this silently overrides whatever `OLLAMA_BASE_URL` is written into `.env`.
- `docker-compose.prod.yml` (used by the Windows installer) layers on top of the base file: it strips every bind-mount (`volumes: !reset []`) from `backend`, `celery_worker`, `celery_beat`, and `frontend`, and swaps their commands for non-hot-reload equivalents.

[FIGURE: backend-01-overview-and-lifecycle-diagram-1.png | Diagram: 1. Docker Service Inventory]
Diagram: Docker Service Topology and Dependency Graph. Dotted arrows are Compose `depends_on` health gates, not runtime data paths -- `backend` and `celery_worker` wait on Postgres and Redis health checks, `celery_beat` waits on Redis only, and `frontend` waits only for `backend` to exist, not to be healthy.

## 2. Application Startup Lifecycle

Startup happens in three layers, in this exact order, every time the `backend` container starts.

### 2.1 Container entrypoint: migrate, then serve

`backend/Dockerfile`'s baked-in `CMD` is simply `uvicorn app.main:app --host 0.0.0.0 --port 8000` -- **it does not run migrations**. The migration step is added at the Compose layer:

- Development: `sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"`
- Production: the same command, minus `--reload`.

Two consequences follow: running the built image directly (bypassing Compose) starts the API **without** applying pending migrations; and because `alembic upgrade head` runs synchronously before `uvicorn` is even exec'd, a failed migration exits the container non-zero and the API never starts against a stale schema. `celery_worker`/`celery_beat` do not run `alembic upgrade head` themselves (`celery -A app.workers.celery_app worker|beat --loglevel=info`) -- they rely on the `backend` container's migration having already brought the schema up to date, since Alembic migrations are idempotent and not tied to any one process.

### 2.2 FastAPI application construction (import time)

Everything in `backend/app/main.py` at module scope runs once, before Uvicorn accepts any connection: structured logging is configured first (`structlog.configure(processors=[JSONRenderer()])`); the `@lru_cache`'d `Settings` singleton is constructed and frozen for the process lifetime (`get_settings()`); the `FastAPI` app is built with `openapi_url=f"{settings.api_v1_prefix}/openapi.json"` and `docs_url="/docs"`; `CORSMiddleware` is added with `allow_origins=["http://localhost:3000"] if settings.debug else []` (since `debug` defaults to `True`, a deployment that never sets `DEBUG=false` will only ever allow `localhost:3000` as a CORS origin, regardless of where the frontend is actually hosted); `Instrumentator().instrument(app).expose(app, endpoint="/metrics")` is wired in ahead of every router so it observes all of them; then ten routers are registered via `app.include_router(..., prefix=settings.api_v1_prefix)` in this fixed order: `auth`, `lookup`, `providers`, `ai_config`, `analysis`, `hunting`, `pivot`, `basket`, `cases`, `runtime` (`app/main.py:38-47`). Finally, `GET /health` is registered directly on `app`, outside any router and outside the `/api/v1` prefix, requiring no authentication -- this is the endpoint a container healthcheck or load balancer should target.

### 2.3 The `startup` event: seeding runtime provider configuration

`app.main` registers exactly one `@app.on_event("startup")` handler, `_seed_runtime_config()`, calling `seed_from_env_if_empty()` (`app/core/runtime_config.py`), once per process start, after the app is fully constructed but before Uvicorn begins accepting connections. If `provider_runtime_configs` already has any row, this is a no-op. Otherwise, for each of the 5 AI backends and 16 registered IOC providers, it reads that backend's/provider's credential fields off the frozen `Settings` singleton (i.e. whatever was in `.env` at container start) and inserts a `ProviderRuntimeConfig` row, Fernet-encrypting credentials before writing (full mechanism in the Provider/AI Runtime Configuration chapter). The handler is wrapped in its own `try/except Exception`, logging and continuing rather than crashing the process on failure (`main.py:57-60`) -- a failed seed leaves providers reporting as unconfigured rather than blocking startup.

### 2.4 Uvicorn serving

Once the startup event completes, Uvicorn accepts TCP connections on `0.0.0.0:8000` (mapped to `${HOST_PORT_BACKEND:-8000}` on the host). In development, `--reload` restarts the worker process on any change under the bind-mounted `./backend` directory -- re-running §2.2 and §2.3, but **not** `alembic upgrade head`, which only ran once in the shell wrapper before Uvicorn was first exec'd. In production there is no bind-mount and no `--reload`; picking up new code requires rebuilding the image and recreating the container, re-running the full sequence from scratch.

[FIGURE: backend-01-overview-and-lifecycle-diagram-2.png | Diagram: 2.4 Uvicorn serving]
Diagram: Startup Sequence -- Migrate, Construct, Seed, Serve. Only step 1 is baked into the Compose `command:`, not the Docker image itself; steps 2-4 all happen inside the single `uvicorn app.main:app` process, in that fixed order, every time it starts.

## 3. Request Lifecycle: the General Case

Every protected endpoint (everything except `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, and the unauthenticated `GET /health`) follows the same shape: **authenticate -> authorize -> route handler -> persistence**.

1. **Authenticate** -- `Depends(get_current_user)` (`app/auth/rbac.py:28-47`) resolves before the route body runs. It extracts a bearer token via `HTTPBearer(auto_error=False)` (chosen over `OAuth2PasswordBearer` because `/auth/login` takes JSON, not an OAuth2 form-encoded grant); raises `401 Could not validate credentials` if no credentials were supplied, `decode_token()` fails, or the token's `type` claim isn't `"access"`; otherwise looks up the user by the token's `sub` (email) claim with one `SELECT`, raising the same `401` if the user is missing or inactive; and returns a lightweight `CurrentUser(id, email, role)` dataclass, not the full ORM `User` row.
2. **Authorize** -- most routes wrap that dependency in `require_permission(permission: str)` (`app/auth/rbac.py:50-62`), a dependency factory that checks `permission in ROLE_PERMISSIONS.get(user.role, set())` and raises `403 Role '{role}' lacks permission '{permission}'` on failure. The full permission matrix lives in `app/models/user.py` and is covered in the Security Architecture / RBAC chapter -- operationally, this is a single dictionary lookup keyed by role, evaluated fresh on every request with no caching beyond the JWT itself.
3. **Route handler** -- route functions (`app/api/routes/*.py`) are deliberately thin: validate/coerce the request, delegate real logic to a service module (`app/ai/*.py`, `app/providers/*.py`, `app/correlation/engine.py`, `app/evidence/*.py`, or `app/core/runtime_config.py`), and shape the return value. Multi-step logic (provider fan-out, AI calls, correlation) always lives in a dedicated module, never inline in the route.
4. **Persistence** -- most non-streaming routes take a single `AsyncSession` via `Depends(get_db)` (`app/core/db.py:12-14`), opened for the request and torn down automatically on return. `get_db()` and the standalone `new_session()` helper (used outside a request scope -- Celery tasks, and the SSE generator in §4) share one process-wide `async_sessionmaker`/`AsyncEngine` (`create_async_engine(get_settings().database_url, pool_pre_ping=True)`), so both draw from the same connection pool.

Example: `PATCH /api/v1/cases/{case_id}` resolves `require_permission("case:write")`, loads the case via `_load_case()` (`404` if missing), applies only the fields present in the body via `model_dump(exclude_unset=True)`, and returns the full serialized case -- all on the single request-scoped session, committed implicitly when it closes cleanly.

## 4. Request Lifecycle: the Streamed Lookup (`POST /api/v1/lookup/stream`)

The lookup-creation endpoint is the one exception to "single request-scoped session, return JSON," because it holds one HTTP connection open for the tens of seconds a full investigation takes (provider fan-out, per-provider AI summaries, correlation, final AI assessment) and streams progress as Server-Sent Events instead of blocking until completion. `stream_lookup()` (`app/api/routes/lookup.py:51-`):

1. **Rate limit** -- a Redis-backed fixed-window `RateLimiter` keyed `lookup_create:{user.id}` (`app/core/cache.py`), bounded by `lookup_rate_limit_max_calls`/`lookup_rate_limit_window_seconds` (10/60s by default); exceeding it raises `429` before any provider or AI call runs.
2. **IOC type detection** -- `detect_ioc_type()` classifies the value unless `ioc_type_hint` was given; an undetectable type raises `422` immediately.
3. **Row creation on the request-scoped session** -- an `IOCLookup` row is inserted with `status=RUNNING` and committed on the normal `Depends(get_db)` session, its `id` captured, before the streaming response is even constructed.
4. **A second, independent session is opened inside the generator itself**, via `new_session()`, not `get_db()`. This is deliberate: a `StreamingResponse` generator body only starts executing *after* the route function returns, by which point the request-scoped session is already torn down -- using it inside the generator would silently drop every later `lookup.status = ...` mutation (a fresh `db.add()` would still appear to work, since SQLAlchemy opens an implicit new transaction for it, which is exactly why provider/correlation rows previously persisted while the lookup's own terminal status did not). The generator therefore owns and commits its own session for its whole run.
5. **Commit after every single provider result**, not once at the end -- necessary because a client disconnecting mid-investigation discarded every uncommitted `ProviderResultRecord`/`AISummaryRecord` in the same transaction, even though those calls had genuinely completed and already been yielded over SSE.
6. **A fixed SSE event sequence**, over one long-lived `text/event-stream` response:

   | Event | Cardinality | Payload |
   |---|---|---|
   | `detected` | once | `{lookup_id, ioc_value, ioc_type}` |
   | `provider_result` | once per provider run | that provider's `ProviderResult.to_dict()` |
   | `provider_summary` | once per provider with an `OK` result | the per-provider AI summary |
   | `correlation` | once, after all providers finish | `{nodes, edges}` |
   | `final_assessment` | once | the consolidated `FinalAssessment` |
   | `done` | once | `{lookup_id}` |

   `provider_result`/`provider_summary` interleave per provider as each finishes, letting the frontend render provider cards incrementally.
7. **Two distinct failure modes.** A regular `Exception` anywhere in the pipeline is caught, logged, flips the lookup to `status=FAILED`, commits, and yields an `error` event in place of `final_assessment`/`done` -- the HTTP response still completes `200`, since the failure is communicated inside the stream. A client disconnecting mid-stream is different: Starlette raises `GeneratorExit` (a `BaseException`, not caught by `except Exception`) into the generator at whichever `yield` is executing; the generator's `finally` block is what still flips the lookup to `FAILED` and commits in that case, so an abandoned lookup never stays stuck in `RUNNING`.

Every other write in the pipeline -- `CorrelationEdgeRecord` rows, the `FinalAssessmentRecord` history row, and the deterministic `EvidenceItem` ledger built by `build_evidence()` -- goes through this same generator-owned session, per-step-then-commit, before its corresponding SSE event is yielded.

[FIGURE: backend-01-overview-and-lifecycle-diagram-3.png | Diagram: 4. Request Lifecycle: the Streamed Lookup (`POST /api/v1/lookup/stream`)]
Diagram: SSE Lookup Request Lifecycle. The generator commits after every single step rather than once at the end, and owns its own database session independent of the request-scoped one -- both choices exist specifically so a disconnect or mid-pipeline exception never leaves already-completed provider/correlation work uncommitted or the lookup stuck in `RUNNING`.

## 5. Summary

The backend's operational shape: eight Compose services (four datastores, the FastAPI process, two Celery roles that never touch the live lookup path, and the frontend), started with a migrate-then-serve sequence baked into the `backend`/`celery_*` commands rather than the container image, followed by a best-effort runtime-config seed on the FastAPI `startup` event. Every authenticated request follows authenticate -> authorize -> thin route handler -> service module -> persistence via a single request-scoped session -- except `POST /api/v1/lookup/stream`, which trades that simplicity for a self-managed, commit-per-step session and an SSE event stream engineered to survive both mid-pipeline exceptions and mid-stream client disconnects without losing already-completed work.
