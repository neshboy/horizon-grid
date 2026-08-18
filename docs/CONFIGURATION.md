# Configuration Reference

Every setting the backend reads lives in exactly one place:
[`backend/app/core/config.py`](../backend/app/core/config.py), a
`pydantic-settings` `Settings` class. It loads values from process
environment variables first, falling back to a `.env` file in the repo root
(`env_file=".env"`), and finally to the Python defaults shown below. There
is no other settings module, no per-provider config file, and no database
table of settings — this is the single source of truth every provider
connector and the AI service reads from.

Related docs: [ARCHITECTURE.md](ARCHITECTURE.md) for how these settings are
consumed by the request lifecycle, [INSTALL.md](INSTALL.md) for the
step-by-step local setup that produces a working `.env`, and [API.md](API.md)
for the endpoints these settings gate.

## How settings are loaded

```mermaid
flowchart LR
    A[Process environment] -->|highest precedence| D[Settings instance]
    B[".env file (repo root)"] -->|env_file=\".env\"| D
    C["Field default in config.py"] -->|fallback| D
    D --> E["get_settings() -- lru_cache singleton"]
    E --> F[Every provider / AI client / route reads from here]
```

- **Env var naming**: `pydantic-settings` matches environment variable
  names to `Settings` fields **case-insensitively** by default (no
  `case_sensitive` override is set in `model_config`), but by convention
  every var in `.env.example`, `docker-compose.yml`, and the Kubernetes
  manifests is written in `UPPER_SNAKE_CASE` matching the field name (e.g.
  field `jwt_secret_key` ↔ env var `JWT_SECRET_KEY`). Use the uppercase form.
- **Unknown keys are ignored** (`extra="ignore"`), so extra vars in `.env`
  (e.g. `GITHUB_TOKEN`, read directly via `os.getenv` in
  `app/crawler/sources/github.py`, not through `Settings`) don't cause
  startup errors.
- **`get_settings()` is `@lru_cache`d** — one `Settings` instance per process
  lifetime. This is the mechanical reason restart semantics matter (see
  below): a running container never re-reads `.env`.

## Restart semantics: `docker compose restart` vs `up -d`

`docker compose restart <service>` restarts the existing container process
but does **not** re-read `.env` or `environment:` values — Compose only
merges those in when a container is created. `docker compose up -d <service>`
recreates the container (picking up new `.env`/`environment:` values) if its
config changed, or is a no-op if nothing changed. **After editing `.env`,
always use `docker compose up -d <service>`, never `restart`.** This is
called out explicitly in [INSTALL.md](INSTALL.md)'s troubleshooting section
for the "provider shows `not_configured`" case. Every table below marks
which is required.

---

## App

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `APP_NAME` | Display name used in the FastAPI title and `/health` response. | `HORIZON GRID` | No | `up -d` |
| `ENVIRONMENT` | Free-text environment label (`development`, `production`, ...). Not read for branching logic beyond documentation/observability today. | `development` | No | `up -d` |
| `DEBUG` | No longer read anywhere in the backend (confirmed via grep) -- CORS is now a fixed private-network-origin regex, not gated on this flag. Left in place for backward compatibility; safe to ignore. | `true` | No | -- |
| `API_V1_PREFIX` | URL prefix every router (`auth`, `lookup`, `providers`, `analysis`, `hunting`, `pivot`, `basket`, `cases`) is mounted under. | `/api/v1` | No | `up -d` |

## Auth / Security

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `JWT_SECRET_KEY` | HMAC signing key for access/refresh JWTs (`app/auth/security.py`). **Must** be changed from the default before any non-local use — a leaked/default key lets an attacker forge tokens for any role. | `change-me-in-production` | **Yes (production)** | `up -d` |
| `JWT_ALGORITHM` | JWT signing algorithm passed to `python-jose`. | `HS256` | No | `up -d` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime in minutes. | `30` | No | `up -d` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime in days. | `7` | No | `up -d` |

See [ARCHITECTURE.md](ARCHITECTURE.md) and [API.md](API.md) for the
role/permission model (`admin`, `analyst`, `viewer`) these tokens carry.

## Datastores

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `DATABASE_URL` | Async Postgres connection string (SQLAlchemy + `asyncpg`), system of record for users, lookups, provider results, AI summaries, correlation edges. `docker-compose.yml` overrides this per-service to `postgresql+asyncpg://ioc:ioc@postgres:5432/ioc_intel`. | `postgresql+asyncpg://ioc:ioc@postgres:5432/ioc_intel` | No (Docker Compose) / Yes (bare-metal) | `up -d` |
| `REDIS_URL` | Provider-result cache (TTL `provider_cache_ttl_seconds`) and fixed-window rate limiter backend (`app/core/cache.py`). | `redis://redis:6379/0` | No | `up -d` |
| `NEO4J_URI` | Bolt URI for the graph store intended for correlation-edge traversal. Declared in `Settings` and provisioned in `docker-compose.yml`/K8s manifests; no connector code currently opens a `neo4j` driver session against it — Postgres (`correlation_edges` table) is the durable source of truth today. | `bolt://neo4j:7687` | No | `up -d` |
| `NEO4J_USER` | Neo4j username. | `neo4j` | No | `up -d` |
| `NEO4J_PASSWORD` | Neo4j password — must match the `NEO4J_AUTH` value set on the `neo4j` service in `docker-compose.yml` (`neo4j/changeme-neo4j` by default). | `changeme-neo4j` | No | `up -d` |
| `OPENSEARCH_URL` | Endpoint for the full-text/log search datastore. Declared in `Settings` and provisioned as core infrastructure (`opensearch-py` is a dependency); no route or service currently issues queries against it. | `http://opensearch:9200` | No | `up -d` |

Datastore roles are documented in more detail in
[ARCHITECTURE.md](ARCHITECTURE.md#datastore-roles).

### Celery (broker/backend, also datastore-adjacent)

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `CELERY_BROKER_URL` | Redis DB used as the Celery task broker. | `redis://redis:6379/1` | No | `up -d` |
| `CELERY_RESULT_BACKEND` | Redis DB used as the Celery result backend. | `redis://redis:6379/2` | No | `up -d` |

Celery runs only the hourly OSINT crawl (`crawl-osint-sources-hourly`) and
any future background/report jobs — the interactive lookup path does not use
Celery (see [ARCHITECTURE.md](ARCHITECTURE.md#celery-workers)).

## AI backends

`AI_BACKEND` selects one of four interchangeable clients, all exposing the
same `call_claude_json()` method (`app/ai/service.py:_get_ai_client()`).

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `AI_BACKEND` | Selects the active AI client: `ollama` (default), `bedrock`, `gemini`, or `anthropic`. | `ollama` | No | `up -d` |

### Ollama (default — local, no API key)

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `OLLAMA_BASE_URL` | Base URL of a locally-hosted Ollama server. `host.docker.internal` resolves to the Docker host from inside the backend container (Docker Desktop Windows/Mac). | `http://host.docker.internal:11434` | Only if `AI_BACKEND=ollama` | `up -d` |
| `OLLAMA_MODEL` | Model tag to request (must match what `ollama list` shows after `ollama pull <model>`). | `llama3.2:3b` | Only if `AI_BACKEND=ollama` | `up -d` |
| `OLLAMA_MAX_TOKENS` | `num_predict` cap passed to Ollama's `/api/chat`. | `8192` | No | `up -d` |

### AWS Bedrock (Claude)

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `BEDROCK_API_KEY` | Bearer token from IAM → Security credentials → "Generate API key" (preferred auth). Set into `AWS_BEARER_TOKEN_BEDROCK` at client-init time by `app/ai/bedrock_client.py`. | `None` | Only if `AI_BACKEND=bedrock` and not using access-key auth | `up -d` |
| `AWS_ACCESS_KEY_ID` | Classic SigV4 fallback, only used if `BEDROCK_API_KEY` is blank. | `None` | Only if `AI_BACKEND=bedrock` and no `BEDROCK_API_KEY` | `up -d` |
| `AWS_SECRET_ACCESS_KEY` | Paired with `AWS_ACCESS_KEY_ID`. | `None` | Same as above | `up -d` |
| `AWS_REGION` | Region for the Bedrock Converse API call. | `us-east-1` | No | `up -d` |
| `BEDROCK_MODEL_ID` | Bedrock model ID or cross-region inference profile (e.g. the `global.` prefix is required for Claude Sonnet 4.5 from regions with no in-region/Geo profile, such as `ap-southeast-1`). | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` | Only if `AI_BACKEND=bedrock` | `up -d` |
| `BEDROCK_MAX_TOKENS` | Max output tokens for the Converse API call. | `4096` | No | `up -d` |

`AccessDeniedException` means the IAM principal is valid but hasn't been
granted model access in **Bedrock → Model access** for that region — see
[INSTALL.md](INSTALL.md#troubleshooting).

### Google Gemini

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `GEMINI_API_KEY` | API key with quota for `generateContent`. | `None` | Only if `AI_BACKEND=gemini` | `up -d` |
| `GEMINI_MODEL_ID` | Gemini model ID. | `gemini-2.0-flash` | No | `up -d` |
| `GEMINI_MAX_TOKENS` | Max output tokens. | `8192` | No | `up -d` |

### Anthropic direct API

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` key with credit, sent to `api.anthropic.com/v1/messages`. | `None` | Only if `AI_BACKEND=anthropic` | `up -d` |
| `ANTHROPIC_MODEL_ID` | Anthropic model ID. | `claude-sonnet-4-5-20250929` | No | `up -d` |
| `ANTHROPIC_MAX_TOKENS` | Max output tokens. | `8192` | No | `up -d` |

If a backend's `is_configured` check fails (missing key/URL), `_get_ai_client()`
raises before making any HTTP call, degrading provider/final summaries to
"AI summarization unavailable" rather than reaching the UI unvalidated —
see [ARCHITECTURE.md](ARCHITECTURE.md#ai-service).

## Providers

Every free-tier connector computes its own `configured` flag from one of
these settings in `__init__`; a provider whose key is unset returns
`ProviderStatus.NOT_CONFIGURED` for every lookup rather than failing (see
`app/providers/base.py`).

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `VIRUSTOTAL_API_KEY` | VirusTotal public API v3 (free tier: 4 req/min, 500/day). Header `x-apikey`. | `None` | No (provider reports `not_configured` if unset) | `up -d` |
| `ABUSEIPDB_API_KEY` | AbuseIPDB v2 API (free tier: 1000 checks/day). Header `Key`. | `None` | No | `up -d` |
| `OTX_API_KEY` | AlienVault OTX. Header `X-OTX-API-KEY`. | `None` | No | `up -d` |
| `NVD_API_KEY` | NIST NVD CVE API v2.0. Works unauthenticated (~5 req/30s); setting this raises the rate limit (~50 req/30s) via the `apiKey` header. | `None` | No | `up -d` |
| `ABUSECH_AUTH_KEY` | Single abuse.ch Auth-Key shared across three connectors — URLHaus, ThreatFox, MalwareBazaar — sent via the `Auth-Key` header. | `None` | No | `up -d` |

### Stub / paid connectors

These implement the same `BaseProvider` interface as the free-tier
connectors above; add the corresponding key(s) to activate.

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `HYBRID_ANALYSIS_API_KEY` | Hybrid Analysis (CrowdStrike Falcon Sandbox), SHA256-only lookups via `GET /api/v2/overview/{sha256}/summary`. Header `api-key`. | `None` | No | `up -d` |
| `CENSYS_PERSONAL_ACCESS_TOKEN` | Censys Platform API Bearer token. | `None` | No — required **together with** `CENSYS_ORGANIZATION_ID` for `configured` to be `true` | `up -d` |
| `CENSYS_ORGANIZATION_ID` | Organization ID paired with the PAT above, sent as `X-Organization-ID`. | `None` | No — see above | `up -d` |
| `PHISHTANK_API_KEY` | Optional `app_key` for PhishTank's `checkurl` API — PhishTank works unauthenticated (`requires_key = False`, always `configured = True`); setting this only raises rate limits. | `None` | No | `up -d` |

Two provider connectors need **no** key at all and are always `configured =
True`: **Spamhaus** (DBL/ZEN DNSBL, queried via plain DNS, no HTTP/API key)
and **NVD** (`requires_key = False`, key only raises rate limit). **crt.sh**
(`configured = True`) and the **Internet Intelligence Collector** OSINT
crawler (`requires_key = False`) are likewise always active — see Crawler
below. Full connector inventory and how to add a new provider are documented
in [ARCHITECTURE.md](ARCHITECTURE.md#adding-a-new-provider) and
[PROVIDERS.md](PROVIDERS.md).

Not part of `Settings` / `.env`, mentioned for completeness: `GITHUB_TOKEN`
is read directly via `os.getenv("GITHUB_TOKEN")` in
`app/crawler/sources/github.py` (not through `Settings`, intentionally — the
platform must work fully without it). Setting it raises the GitHub Search
API's unauthenticated 10 req/min cap to 30 req/min.

## Crawler / OSINT

Consumed by the OSINT crawler provider (`InternetIntelligenceCollector` in
`app/crawler/collector.py`) and its four source modules (GitHub, Reddit, RSS
security news, best-effort paste-dump search).

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `CRAWLER_USER_AGENT` | `User-Agent` header sent by every crawler source request. | `IOC-Intel-Platform/1.0 (+https://github.com/your-org/ioc-intel-platform)` | No | `up -d` |
| `CRAWLER_REQUEST_TIMEOUT_SECONDS` | Per-request HTTP timeout for each crawler source. | `15` | No | `up -d` |
| `CRAWLER_MAX_RESULTS_PER_SOURCE` | Cap on findings kept per source before merge/dedupe; the collector's overall cap is this value × 4 sources. | `5` | No | `up -d` |

## Provider execution

Applies to every provider connector uniformly via the orchestrator
(`app/providers/orchestrator.py`), not configurable per-provider.

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `PROVIDER_TIMEOUT_SECONDS` | `asyncio.wait_for` timeout wrapped around each provider's `run()` call; exceeding it yields `ProviderStatus.TIMEOUT`. | `20` | No | `up -d` |
| `PROVIDER_MAX_RETRIES` | Extra attempts (via `tenacity`, exponential backoff) for connection-level failures (`ConnectError`, `ReadTimeout`, `PoolTimeout`) only — HTTP error responses are not retried. | `2` | No | `up -d` |
| `PROVIDER_CACHE_TTL_SECONDS` | TTL (seconds) for caching a provider's `OK` result in Redis, keyed by `provider_id` + `ioc_type` + a SHA-256 digest of the IOC value. | `3600` | No | `up -d` |

## Rate limiting

Per-user fixed-window limiter on the lookup-creation endpoint
(`POST /api/v1/lookup/stream`) only, enforced via Redis so it holds across
all backend workers (`app/core/cache.py:RateLimiter`, keyed
`rate_limit:lookup_create:<user_id>`).

| Variable | Purpose | Default | Required? | Restart-required |
|---|---|---|---|---|
| `LOOKUP_RATE_LIMIT_MAX_CALLS` | Max lookup-stream requests allowed per user per window. | `10` | No | `up -d` |
| `LOOKUP_RATE_LIMIT_WINDOW_SECONDS` | Window length in seconds. | `60` | No | `up -d` |

Exceeding the limit returns `HTTP 429` with a message stating the exact
`max_calls`/`window_seconds` in effect.

---

## Not part of `Settings` (other configuration surfaces)

These are real, working configuration values in the repo, but they are set
outside `backend/app/core/config.py` and therefore outside `.env` —
included here so this document is a complete map of "how to configure the
platform," not just of the `Settings` class.

| Variable | Where it's set | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `docker-compose.yml` (`frontend` service `environment:`, from `PUBLIC_API_URL` in `.env`), baked into the Next.js build | **Left empty by default.** When empty, `lib/api.ts`'s `getApiUrl()` derives the backend URL at runtime from whatever host the browser used to load the page (`window.location.hostname`) plus `NEXT_PUBLIC_BACKEND_PORT` -- this is what makes the platform work from `localhost` and from another device's LAN URL with the same build, no rebuild needed. Only set this explicitly for a reverse-proxy or other setup where the frontend and backend are not reachable at the same host. |
| `NEXT_PUBLIC_BACKEND_PORT` | `docker-compose.yml` (`frontend` service `environment:`, from `HOST_PORT_BACKEND`) | The port `getApiUrl()` appends to the detected host when `NEXT_PUBLIC_API_URL` is unset. Not a secret -- safe to bake into the client bundle. |
| `DETECTED_LAN_IP` | `.env`, written by the Windows wizard's `Get-LanIpAddress` (`windows/scripts/Common.ps1`) | A point-in-time snapshot of this machine's LAN-facing IPv4 address, detected on the Windows host at install/reconfigure time -- a container can never detect this itself (see `backend/app/main.py`'s `/network-info`). Powers the frontend's Network Access panel display only; re-run the wizard's Configuration option if the network changes. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `docker-compose.yml` (`postgres` service `environment:`) | Postgres container's own bootstrap credentials — must stay consistent with the credentials embedded in `DATABASE_URL`. |
| `NEO4J_AUTH` / `NEO4J_PLUGINS` | `docker-compose.yml` (`neo4j` service `environment:`) | Neo4j container bootstrap auth (`neo4j/changeme-neo4j`) and the `apoc` plugin. |
| `DISABLE_SECURITY_PLUGIN`, `OPENSEARCH_JAVA_OPTS`, `discovery.type` | `docker-compose.yml` (`opensearch` service `environment:`) | Single-node OpenSearch container tuning; security plugin disabled for local dev. |

For Kubernetes, the equivalent split is a `ConfigMap` (non-secret
hostnames/ports/URLs) plus a `Secret` (everything with a credential) — see
[k8s/README.md](../k8s/README.md) and `k8s/base/configmap.yaml` /
`k8s/base/secret.example.yaml`.

## Example `.env`

```bash
# --- Security ---
JWT_SECRET_KEY=<configure securely>

# --- Ollama (default AI backend) ---
AI_BACKEND=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.2:3b

# --- Free-tier providers (leave blank to skip) ---
VIRUSTOTAL_API_KEY=<your-key-here>
ABUSEIPDB_API_KEY=<your-key-here>
OTX_API_KEY=<your-key-here>
NVD_API_KEY=
ABUSECH_AUTH_KEY=<your-key-here>
```

Copy the full template from the repo root and fill in what you have:

```bash
cp .env.example .env
```

Then bring the stack up (first run builds images and applies Alembic
migrations automatically via the `backend` service's command):

```bash
docker compose up --build
```

After changing any value in `.env` on an already-running stack, recreate
just the affected service(s) rather than restarting:

```bash
docker compose up -d backend
```
