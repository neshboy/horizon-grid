# 🚀 Deployment and Troubleshooting

This chapter covers the two deployment paths that exist in this repository -- Docker Compose (development and production) and the Windows Inno Setup installer that wraps it -- how environment variables reach the running process, and a symptom-first troubleshooting reference keyed to real error strings and enum values. Performance/scaling claims are limited to what is actually configured in code or measured in the project's own QA pass; see the Performance chapter for the full measured-value table.

All facts below are drawn from `docker-compose.yml`, `docker-compose.prod.yml`, `backend/Dockerfile`, `backend/app/core/config.py`, `backend/app/core/db.py`, `backend/app/workers/celery_app.py`, `backend/app/providers/base.py`, `backend/app/providers/orchestrator.py`, `backend/app/main.py`, `k8s/base/*.yaml`, `windows/installer.iss`, `windows/wizard/Setup-Wizard.ps1`, `windows/scripts/*.ps1`, cross-checked against `docs/DEPLOYMENT.md`/`docs/TROUBLESHOOTING.md`, and this documentation set's Runtime Configuration Architecture and System Overview chapters, which this chapter does not re-derive.

## 📋 Table of contents

- [1. Docker Compose](#1--docker-compose)
  - [1.1 Dev vs. production](#11-dev-vs-production-what-docker-composeprodyml-changes)
  - [1.2 Kubernetes](#12-kubernetes-k8sbase)
- [2. The Windows Inno Setup Installer](#2--the-windows-inno-setup-installer)
- [3. Environment Variable Configuration](#3--environment-variable-configuration)
- [4. Troubleshooting](#4--troubleshooting)
  - [4.1 Where to look first](#41-where-to-look-first)
  - [4.2 Startup failures](#42-startup-failures)
  - [4.3 Provider and AI failures](#43-provider-and-ai-failures)
- [5. Performance and Scaling Notes](#5--performance-and-scaling-notes-evidenced-only)
- [6. Summary](#6--summary)

## 1. 🐳 Docker Compose

Compose is the only deployment path fully wired end-to-end and exercised by this project's own test suite. `docker-compose.yml` defines eight services: four datastores (`postgres`, `redis`, `neo4j`, `opensearch`, all published to `127.0.0.1` only -- an explicit fix after confirming each was reachable unauthenticated from other LAN devices under the old `0.0.0.0` shorthand), `backend`, two Celery roles (`celery_worker`, `celery_beat`), and `frontend`. `backend` and `celery_worker` wait on Postgres/Redis health checks (`pg_isready`/`redis-cli ping`, 5s interval, 10 retries); `celery_beat` waits only on Redis. Only the two Celery services carry `restart: unless-stopped` -- `backend`, the datastores, and `frontend` have no restart policy, so a crashed container stays down until manually recreated.

> [!NOTE]
> Only the two Celery services carry `restart: unless-stopped`. `backend`, the datastores, and `frontend` have no restart policy, so a crashed container stays down until it's manually recreated.

### 1.1 Dev vs. production: what `docker-compose.prod.yml` changes

Applied as an override, not a replacement: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. It touches only `backend`, `celery_worker`, `celery_beat`, and `frontend`:

| Change | Dev (base) | Prod (override) | Why |
|---|---|---|---|
| `backend` volumes | `./backend:/app` bind-mount | `!reset []` (none) | Runs entirely from the built image |
| `backend` command | `alembic upgrade head && uvicorn ... --reload` | same, minus `--reload` | No hot reload in production |
| `celery_worker`/`celery_beat` volumes | bind-mount | `!reset []` | Windows/WSL2 bind-mount permissions broke `celery_beat`'s schedule-file write (`PermissionError`) under an installed copy |
| `frontend` volumes | source + anonymous `node_modules`/`.next` volumes | `!reset []` | The anonymous volumes failed to mount at all under an installed copy -- confirmed live: container stuck at `Created`, never started |
| `frontend` command | `npm run dev` | `npm run build && ... && node .next/standalone/server.js` | Real production build, not the dev server |

The production frontend command works around two real gotchas: `next.config.js` sets `output: "standalone"`, which plain `next start` doesn't support (confirmed live: `"next start" does not work with "output: standalone" configuration"`), so it runs `node .next/standalone/server.js` directly; and since Next's standalone build excludes `public/`/`.next/static/`, the command copies them in by hand after building.

No datastore credential or networking behavior differs between the two files -- Postgres/Neo4j/OpenSearch still run with default/hardcoded credentials (`ioc`/`ioc`, `neo4j`/`changeme-neo4j`) and OpenSearch's security plugin is disabled in both; hardening those is an operator responsibility neither file addresses.

`backend/Dockerfile`'s baked-in `CMD` is plain `uvicorn app.main:app --host 0.0.0.0 --port 8000` -- it does **not** run `alembic upgrade head`; migration is a Compose-layer `command:` override, not an image-layer step, in both dev and prod. Running the built image directly (`docker run`, bypassing Compose) starts the API without applying pending migrations. `celery_worker`/`celery_beat` never run migrations themselves; they rely on `backend` to bring the schema current, since Alembic migrations are idempotent.

### 1.2 Kubernetes (`k8s/base/`)

A plain-YAML, kustomize-compatible, hand-translated mirror of the Compose services also exists, with no Helm templating and no CI/CD wiring anywhere in the repo. `backend`/`frontend` run 2 replicas; `celery-beat` is pinned to 1 (avoids duplicate scheduled dispatches). `backend` probes `GET /health` for readiness and liveness; resource requests/limits (`backend`/`celery-worker`: `250m`/`512Mi` request, `1000m`/`1Gi` limit; `frontend`: `100m`/`256Mi` request, `500m`/`512Mi` limit) are static manifest values, not load-test-derived. TLS is commented out in `ingress.yaml` and not implemented, and `frontend/Dockerfile` as committed is dev-mode only -- it cannot satisfy the Deployment's `npm start` without a separate production Dockerfile that does not exist in this repo.

**Migrations in this topology.** `k8s/base/backend-deployment.yaml:31-34` sets the same `command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"` used by Compose (minus `--reload`, per the manifest's own header comment, lines 1-5) -- there is no separate Kubernetes Job or init container that runs the migration once; each of the Deployment's individual pods runs `alembic upgrade head` itself, every time that pod starts. With `replicas: 2`, a rollout can start both pods within the same window, and nothing in the manifest serializes their two `alembic upgrade head` invocations against each other -- Alembic has no built-in cross-process lock, so two pods racing to apply the same not-yet-applied revision concurrently is a real, unmitigated possibility in this manifest as written, not merely a Compose-vs-K8s documentation gap. `celery-worker`'s Deployment does not run `alembic upgrade head` at all (same division of responsibility as Compose), so it depends on one of the two `backend` pods having already brought the schema current.

## 2. 🪟 The Windows Inno Setup Installer

Its scope is narrow: **the installer copies files and collects configuration; it does not itself start Docker.** `installer.iss` runs prerequisite checks (`Check-Prerequisites.ps1`: 64-bit Windows 10+, admin privileges, 8GB+ RAM soft check, disk space, Docker Desktop running, Compose v2, free ports -- failures prompt "Continue anyway?" rather than hard-aborting), copies `backend/`, `frontend/`, both compose files, `docs/`, `README.md`, and the wizard/scripts into `%ProgramFiles%\IOC Intelligence Platform\app\`, sets up Start Menu shortcuts, then launches the Setup Wizard (a WinForms app) -- the component that actually configures and starts anything.

> [!NOTE]
> The installer's job is narrow: it copies files and collects configuration. It does not itself start Docker -- that happens only once the Setup Wizard runs, specifically at the `docker compose ... up -d --build` step below.

On "Start Installation" the wizard runs, in order: (1) writes `.env` via `Write-PlatformEnvFile`, using collected values plus CSPRNG-generated secrets (`ConvertTo-SafeEnvValue` strips CR/LF and rejects any value containing `#`, since `#` opens a `.env` comment and would silently truncate the rest); (2) runs `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` -- **this is the moment Docker actually starts**, nothing before it brings up a single container; (3) polls `GET /health/detailed` for up to 3 minutes (updated in v0.2.3 -- the wizard needs to know Postgres is genuinely reachable before the very next step writes to it, not just that the process has started; see the System Health chapter for the plain-`/health`-vs-`/health/detailed` split); (4) registers the very first administrator account via `POST /api/v1/auth/register` and logs in -- self-registration is bootstrap-only: it succeeds only while the users table is empty, and every subsequent call (including a second install attempt against an already-configured database) is rejected with `403`, directing the caller to have an existing administrator create their account instead. Re-running the wizard via the **Configuration** shortcut on an existing install pre-populates fields from the existing `.env` and takes a `pg_dump` backup first (both platforms, as of v0.2.3 -- previously Windows-only).

Real secrets live at `%ProgramData%\IOC Intelligence Platform\config\.env`, locked to Administrators+SYSTEM via `icacls`. Because Compose's `env_file: .env` resolves relative to the project directory (`{app}\app\`), a helper copies that file into `{app}\app\.env` on every Compose invocation and re-applies the same ACL -- two on-disk `.env` files with real secrets, both locked down.

[FIGURE: backend-08-deployment-and-troubleshooting-diagram-1.png | Diagram: 2. The Windows Inno Setup Installer]
Diagram: Installer file-copy vs. Setup Wizard Docker/registration steps. Everything before step G is file staging and prerequisite checking only -- the installer itself never starts a container; that happens exclusively inside the wizard's second step.

## 3. 🧾 Environment Variable Configuration

`backend/app/core/config.py`'s `Settings` class (`pydantic-settings`, `env_file=".env"`) is the exhaustive list the legacy `.env` path supports; `.env.example` is the operator-facing template.

| Group | Representative fields | Notable default |
|---|---|---|
| App | `debug` | `True` -- undeclared `DEBUG=false` means CORS is restricted to only `http://localhost:3000` regardless of the real frontend host |
| Security | `jwt_secret_key`, `encryption_master_key` | `jwt_secret_key` defaults to the placeholder `"change-me-in-production"`; `encryption_master_key` falls back to an HKDF-derived key from the JWT secret if unset |
| Datastores/Celery | `database_url`, `redis_url`, `neo4j_*`, `opensearch_url`, `celery_broker_url`/`celery_result_backend` | Redis DB `1`/`2` for broker/result, DB `0` for app cache/rate-limiter |
| AI backends | `ai_backend` + per-backend key/model fields (Ollama/Anthropic/Bedrock/Gemini/Groq/OpenAI/Kimi/DeepSeek/xAI/Mistral/OpenRouter) | `ai_backend` defaults to `"ollama"` |
| IOC providers | one `..._api_key` per keyed provider (Censys needs a token + org ID pair) | All unset by default -- keyed providers report `not_configured` until set |
| Provider execution | `provider_timeout_seconds`, `provider_max_retries`, `provider_cache_ttl_seconds` | `20`, `2`, `3600` |
| Rate limiting | `lookup_rate_limit_max_calls`, `lookup_rate_limit_window_seconds` | `10`, `60` |

Two mechanisms govern whether a change actually takes effect, and they differ sharply. First, **a Compose `environment:` entry always wins over `env_file:`** -- `backend`'s `OLLAMA_BASE_URL` is set directly in `docker-compose.yml`'s `environment:` block rather than left to `.env` alone, so it silently overrides whatever `.env` says (it still respects a real *shell/host* `OLLAMA_BASE_URL`, just not one written only into `.env`). Second, **`Settings` is a process-lifetime, `@lru_cache`'d singleton**, read once at import time and never re-read: `docker compose restart backend` re-reads nothing, since Compose only re-reads `.env` at container *creation*; use `docker compose up -d backend` to force recreation.

This frozen-`.env` behavior is exactly the legacy path superseded, for provider/AI credentials specifically, by the database-backed runtime configuration system (`provider_runtime_configs`, the Manage Providers UI) covered in full in the Runtime Configuration Architecture chapter -- credentials saved there take effect on the next investigation or AI call, no restart. `.env` remains authoritative for everything that system doesn't cover (JWT key, datastore URLs, Celery broker/result, rate limits, provider timeouts/retries/cache TTL).

## 4. 🔧 Troubleshooting

### 4.1 Where to look first

1. **`docker compose ps`** -- which containers are actually running vs. exited (no `restart` policy on `backend`/datastores/`frontend`).
2. **`docker compose logs backend`** (or `celery_worker`/`celery_beat`/`frontend`) -- structured JSON (`structlog`, configured before anything else in `app/main.py`), so early startup failures land in the same format as runtime logs.
3. **`GET /health`** (no auth, outside `/api/v1`) -- `{"status": "ok", "service": "HORIZON GRID"}` the moment Uvicorn accepts connections; it does **not** check Postgres/Redis/Neo4j/OpenSearch, only that the process itself is up. This is what the Setup Wizard and the Kubernetes readiness/liveness probes poll.
4. **`GET /api/v1/providers/health`** -- which IOC providers are currently `configured`, distinct from container health.
5. **`GET /api/v1/runtime/audit-log`** -- every configure/enable/disable/activate/record-test action against a provider or AI backend, with actor/timestamp/descriptive detail (never a credential value). Fastest way to see whether "was working yesterday" correlates with a configuration change.
6. **`GET /metrics`** -- Prometheus-format, but no Prometheus/Grafana is bundled; useful only with your own scraper.
7. **Windows Diagnostics bundle** (`windows/scripts/Diagnostics.ps1`) -- zips `docker compose ps`/`logs`, the setup log, and a *redacted* `.env` (`***REDACTED***(set, N chars)` or `(not set)`, variable names only) to the Desktop; the real `.env` is never included.

### 4.2 Startup failures

| Symptom | Cause | Fix |
|---|---|---|
| `backend` exits immediately, non-zero, before Uvicorn logs anything | `alembic upgrade head` failed inside the `sh -c "alembic upgrade head && uvicorn ..."` wrapper -- migrations run synchronously before `uvicorn` even execs, so a failed migration means no API start at all (not a stale-schema start) | Check `docker compose logs backend` for the Alembic traceback; confirm `postgres` healthy first, then `docker compose up -d backend` |
| Missing/incomplete `.env` | Every `Settings` field has a code-level default, so a missing `.env` does **not** crash startup -- it starts with insecure defaults (placeholder JWT key) or providers reporting `not_configured` | Copy `.env.example` to `.env`, fill in real values, and recreate (not restart) `backend` |
| A `.env` edit has no visible effect | `docker compose restart` doesn't re-read `.env`; `Settings` is cached for the process's life regardless | `docker compose up -d backend` |
| `frontend`/`celery_beat` stuck at `Created` or `PermissionError` on an installed (Program Files) copy | Bind-mount/anonymous-volume permissions break under Windows/WSL2 outside a real git tree | Use `docker-compose.prod.yml` (what the wizard already does) |

### 4.3 Provider and AI failures

Every IOC provider call normalizes to one `ProviderStatus` enum value (`backend/app/providers/base.py`) -- the authoritative vocabulary for any provider symptom, visible in both the SSE `provider_result` payload and `GET /api/v1/lookup/{id}`:

| `ProviderStatus` | Meaning / typical trigger |
|---|---|
| `ok` | Usable data returned |
| `no_data` | Reached successfully, nothing on this IOC (404 or explicit "not found" field) |
| `error` | Non-2xx not classified as rate-limited, or unhandled exception (e.g. abuse.ch's auth-rejected statuses map here) |
| `timeout` | Exceeded `provider_timeout_seconds` (default `20`), enforced uniformly via `asyncio.wait_for` |
| `rate_limited` | Vendor returned `429`, `403`, or `509` (509 is PhishTank's documented over-limit code) |
| `not_configured` | `requires_key=True` with no effective credential -- key never set, or set in `.env` but the container hasn't been recreated yet |
| `unsupported_ioc` | Provider doesn't support the detected IOC type |
| `disabled` | Administrator turned it off at runtime (`enabled=false`) -- distinct from `not_configured`: a valid key can still be intentionally disabled |

Only connection-level failures (`httpx.ConnectError`/`ReadTimeout`/`PoolTimeout`) are retried, up to `provider_max_retries` additional attempts (default `2`, exponential backoff `wait_exponential(multiplier=0.5, max=4)`). A `429`/`403`/`509` is reported as `rate_limited` immediately, never retried.

**Test Connection succeeding while a real investigation still reports `not_configured`** is a specific, previously-real gap, now closed by the runtime configuration system (full root cause and fix in the Runtime Configuration Architecture chapter). Short version: a credential saved via the Manage Providers UI is visible to the next investigation immediately; one only ever written to `.env` by hand still needs `docker compose up -d backend`, not just a restart.

AI backend failures raise `RuntimeError` from the relevant client, caught by `app/ai/service.py` and converted to a degraded static result (verdict `unknown`, scores `0`) rather than failing the lookup. Only Bedrock retries (`botocore`-level, `BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"})`); every other backend makes exactly one attempt. Common real messages: `"Could not reach Ollama at http://host.docker.internal:11434 -- is it running?"` (Ollama not running on the host -- it's deliberately never containerized, since a large model's mmap load was observed dramatically slower through Docker Desktop's WSL2 volume layer); `"Ollama did not respond within 120s (model=llama3.2:3b) -- likely too slow for available hardware"` (hardcoded `_TIMEOUT_SECONDS`, not a `.env` setting -- fix with a smaller model, not a bigger timeout); and, for any backend, `"AI backend '{backend}' is not configured (missing API key/URL/model) -- ..."` if `is_configured` is still false after resolution.

**`429` on `POST /api/v1/lookup/stream`** is the platform's only rate limiter -- a Redis-backed fixed-window `RateLimiter` keyed `lookup_create:{user.id}`, per user across all workers, bounded by `lookup_rate_limit_max_calls`/`_window_seconds` (`10`/`60`). Exists because one lookup fans out to every provider plus the crawler plus multiple AI calls. No other endpoint (including login/register) has any rate limiting.

## 5. 📈 Performance and Scaling Notes (evidenced only)

Only what is actually configured in code or measured in the project's own QA pass -- see the Performance chapter for the full measured-value table and its single-machine, single-pass caveats.

- **DB connection pool**: `backend/app/core/db.py` creates one process-wide `AsyncEngine` (`create_async_engine(..., pool_pre_ping=True, echo=False)`), shared by `get_db()` and `new_session()`. No `pool_size`/`max_overflow` override is set -- SQLAlchemy's own library defaults govern the ceiling.
- **Provider fan-out**: `run_all_providers()` opens one `httpx.AsyncClient` per investigation with `httpx.Limits(max_connections=50, max_keepalive_connections=20)`, dispatching every applicable provider as a concurrent `asyncio.create_task` collected via `asyncio.as_completed` -- results stream as each finishes rather than waiting for the slowest.
- **Per-provider timeout/retry/cache**: `provider_timeout_seconds=20`, `provider_max_retries=2` (connection errors only), `provider_cache_ttl_seconds=3600` (Redis-cached `ok` results skip the outbound call entirely on a repeat lookup within the hour).
- **Celery concurrency**: no `--concurrency` flag is set anywhere in either compose file or `celery_app.py` -- Celery's own default (one prefork process per detected CPU core) governs it, not an application setting. The interactive SSE lookup path never goes through Celery at all, so this has no bearing on lookup latency.
- **Kubernetes-only figures**: `backend`/`celery-worker` request `250m`/`512Mi` (limit `1000m`/`1Gi`); `frontend` requests `100m`/`256Mi` (limit `500m`/`512Mi`); `backend`/`frontend` run 2 replicas, `celery-beat` is a pinned singleton. Static manifest values, not load-derived.
- **No load-testing infrastructure exists in this repository** -- no benchmark harness, no CI/CD to run one. Any broader concurrent-load characterization would not be traceable to evidence here and is intentionally omitted.

## 6. 📋 Summary

Two working deployment paths exist: Docker Compose (a small, surgical production override that drops dev bind-mounts and swaps in production start commands) and the Windows installer, which only copies files and launches the Setup Wizard -- the wizard, not the installer, writes `.env` and runs `docker compose up`. `Settings` is a process-lifetime singleton read once from `.env`, superseded for provider/AI credentials by the database-backed runtime configuration system covered elsewhere in this set. Troubleshoot in order: `docker compose ps`/`logs`, `/health`, `GET /api/v1/providers/health`, the runtime audit log -- and reason about provider failures via the eight `ProviderStatus` values, not raw HTTP codes. Performance/scaling statements here are limited to what is actually configured (pool defaults, a 20s/2-retry provider policy, a 1-hour result cache, per-core Celery concurrency, static Kubernetes resource requests) -- there is no load-testing harness in this repository to support any broader claim.
