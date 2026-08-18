# IOC Intelligence Platform — Enterprise System Inventory

**Generated:** 2026-08-15, by direct inspection of the live installed system (not from memory/docs). Source: `C:\Program Files\IOC Intelligence Platform\app` (installed/running copy) cross-referenced against running Docker containers. Dev tree at `C:\Users\User\ioc-intel-platform` was not used as the source of truth for this document — only the installed copy, since that's what's actually live.

---

## 0. Host / Container Inventory (`docker ps`)

| Container | Image | Status | Ports | Role |
|---|---|---|---|---|
| `app-frontend-1` | `app-frontend` (local build) | Up 7h | `0.0.0.0:3000->3000` | Next.js UI |
| `app-backend-1` | `app-backend` (local build) | Up 7h | `0.0.0.0:8000->8000` | FastAPI API |
| `app-celery_worker-1` | `app-celery_worker` (local build) | Up 28h | (none published) | Celery worker |
| `app-celery_beat-1` | `app-celery_beat` (local build) | Up 28h | (none published) | Celery scheduler |
| `app-postgres-1` | `postgres:16-alpine` | Up 30h (healthy) | `127.0.0.1:5433->5432` | Primary DB |
| `app-redis-1` | `redis:7-alpine` | Up 30h (healthy) | `127.0.0.1:6379->6379` | Cache/broker/results |
| `app-opensearch-1` | `opensearchproject/opensearch:2.17.0` | Up 38h | `127.0.0.1:9200->9200` | Search/index store |
| `app-neo4j-1` | `neo4j:5-community` | Up 38h | `127.0.0.1:7475->7474`, `127.0.0.1:7688->7687` | Graph DB |

All of the above run on Docker network `app_default`.

**Other containers present on this host, NOT part of the IOC Intelligence Platform stack** (found via `docker ps`, listed here for completeness/honesty since the task asked for the real `docker ps` output): `pgexporter` (Prometheus Postgres exporter), `scraper` (`vxcontrol/scraper:latest`), `pgvector` (`vxcontrol/pgvector:latest`). All three were created 2026-04-04 from Docker volumes named `installer-latest_scraper-ssl` / `installer-latest_pentagi-postgres-data`, and all three run on a separate Docker network, `pentagi-network` — they belong to an unrelated tool (PentAGI, an autonomous-pentest-agent stack) that happens to be co-located on this machine. They are **not** attached to `app_default` and have no visible network path to the IOC platform's containers. Flagging only for inventory completeness/transparency, not as a platform finding.

**Versions confirmed live (not from package manifests):**
- Python (backend container): `3.12.14`
- PostgreSQL: `16.14` (Alpine build, `postgres:16-alpine`)
- Neo4j: reports `5.26.29` internally (image tag `neo4j:5-community`)
- OpenSearch: `2.17.0` (confirmed via live `GET http://localhost:9200/`, `docker-cluster`, Lucene `9.11.1`, security plugin disabled)
- Redis: `7-alpine`

---

## 1. Frontend

- **Framework:** Next.js `14.2.15`, React `18.3.1` / `react-dom 18.3.1`, TypeScript `5.6.2`. App Router (`frontend/app/`), not Pages Router.
- **UI stack:** Tailwind CSS `3.4.12`, Radix UI primitives (`react-tabs`, `react-dialog`, `react-progress`, `react-slot`, `react-tooltip`), `lucide-react` icons, `class-variance-authority` + `tailwind-merge` for variant styling, `recharts` for charts, `react-force-graph-2d` for the correlation/relationship graph view, `zustand` for client state.
- **Testing:** `vitest 2.1.1`.
- **Structure** (`frontend/`):
  - `app/` — route segments: `admin/`, `basket/`, `cases/`, `login/`, `lookup/`, `providers/`, `register/`, plus root `layout.tsx` / `page.tsx`, `globals.css`.
  - `components/` — `dashboard/`, `ui/`.
  - `lib/` — `api.ts` (API client / `getApiUrl()` origin auto-detection), `aiPrompt.ts`, `types.ts`, `utils.ts`.
  - No `src/` directory — flat `app/`/`components/`/`lib/` at the project root.
- **Dev command:** `npm run dev` (container runs Next in dev mode, not a production build — confirmed via `docker-compose.yml`'s `command: npm run dev`).
- **API origin handling:** frontend auto-detects its own origin unless `NEXT_PUBLIC_API_URL` is explicitly set (for reverse-proxy setups).

## 2. Backend

- **Framework:** FastAPI `0.115.0` on Uvicorn `0.30.6` (`--reload` enabled — dev mode, matching the frontend). Pydantic `2.9.2` / `pydantic-settings 2.5.2`.
- **App entrypoint:** `backend/app/main.py`. Title/description confirm the product framing: "Unified threat intelligence workbench... correlated and summarized by a local Ollama model (or AWS Bedrock/Gemini/Anthropic/Groq)."
- **CORS:** `allow_origin_regex` restricted to RFC1918 private ranges + loopback + literal `localhost`, HTTP only (no TLS termination in-app); `allow_credentials=True`. Explicitly documented in code as relying on JWT auth as the real authorization boundary, not origin matching.
- **Observability:** `prometheus-fastapi-instrumentator 7.0.0` exposed at `GET /metrics`; `structlog 24.4.0` configured with `JSONRenderer`.
- **Unauthenticated endpoints:** `GET /health`, `GET /network-info` (point-in-time LAN IP snapshot from the Windows wizard, not live), `GET /docs`, `/redoc`, `/api/v1/openapi.json`, `GET /metrics`.
- **Structure** (`backend/app/`): `ai/`, `api/routes/`, `auth/`, `core/`, `correlation/`, `crawler/`, `evidence/`, `ioc/`, `models/`, `providers/`, `schemas/`, `security_assessment/`, `tests/`, `workers/`.
- **Full registered API surface** (from live route table, `app/main.py`), grouped by router:
  - `auth`: `POST /register`, `POST /login`, `POST /refresh`, `GET /me`
  - `lookup`: `POST /lookup/stream`, `GET /lookup`, `GET /lookup/{id}`, `POST /lookup/{id}/reanalyze`, `GET /lookup/{id}/assessments`, `POST /lookup/{id}/export`
  - `providers`: `GET /providers/health`, `POST /providers/{id}/test`
  - `ai_config`: `POST /ai/test`, `POST /ai/{backend}/models`
  - `analysis`: `GET .../analysis/evidence`, `POST .../analysis/{why,what-is-this,disagreement,false-positive,challenge,next-actions,gaps,score-explanation,copilot}`
  - `hunting`: `POST /lookup/{id}/hunt`, `POST /lookup/{id}/detection`
  - `pivot`: `GET /lookup/{id}/pivots`
  - `basket`: `GET/POST /basket`, `DELETE /basket/{item_id}`, `DELETE /basket`, `POST /basket/compare`
  - `cases`: `GET/POST /cases`, `GET/PATCH /cases/{id}`, `POST /cases/{id}/close`, `POST/DELETE /cases/{id}/iocs[/{ioc_id}]`, `POST /cases/{id}/notes`
  - `runtime`: `GET/POST /runtime/ai-providers[/{backend}]`, `GET/POST /runtime/ai-active`, `POST /runtime/ai-providers/{backend}/record-test`, `GET/POST /runtime/ioc-providers[/{id}]`, `POST /runtime/ioc-providers/{id}/enabled`, `POST /runtime/ioc-providers/{id}/record-test`, `GET /runtime/audit-log`
  - `admin`: `GET /admin/users[/stats]`, `GET /admin/roles`, `POST /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/active`, `POST /admin/users/{id}/reset-password`
  - `security_assessment`: `GET /security-assessment/profiles`, `GET /security-assessment/tool-health`, `POST /security-assessment/{lookup_id}/run`, `GET /security-assessment/{lookup_id}/runs`, `GET /security-assessment/runs/{run_id}`
- **Key backend dependency versions** (`requirements.txt`): `sqlalchemy[asyncio]==2.0.35`, `asyncpg==0.29.0`, `alembic==1.13.2`, `redis==5.0.8`, `httpx==0.27.2`, `tenacity==9.0.0`, `neo4j==5.24.0` (driver), `celery==5.4.0`, `python-jose[cryptography]==3.3.0`, `cryptography==43.0.1`, `passlib==1.7.4`, `bcrypt==4.0.1`, `boto3==1.35.24`, `opensearch-py==2.7.1`, `feedparser==6.0.11`, `beautifulsoup4==4.12.3`, `lxml==5.3.0`, `python-whois==0.9.6`, `dnspython==2.7.0`, `structlog==24.4.0`, `reportlab==4.2.5`, test stack: `pytest==8.3.3`, `pytest-asyncio==0.24.0`, `pytest-cov==5.0.0`, `respx==0.21.1`.

## 3. Database

- **Engine:** PostgreSQL `16.14` (Alpine), accessed via SQLAlchemy 2.0 async + `asyncpg`. Also Neo4j `5.x` (graph relationships/correlation) and OpenSearch `2.17.0` (indexing/search) as secondary datastores.
- **Migration tool:** Alembic. **Current head, live-confirmed on the running DB:** `6d2f4b8e1a7c` — both `alembic current`/`alembic heads` inside `app-backend-1` and the DB's own `alembic_version` table agree (single head, no drift).
- **Live schema (17 tables):** `users`, `ioc_lookups`, `provider_results`, `provider_runtime_configs`, `ai_summaries`, `evidence_items`, `correlation_edges`, `final_assessment_records`, `security_assessment_runs`, `security_assessment_findings`, `basket_items`, `cases`, `case_iocs`, `case_notes`, `case_reports`, `config_audit_log`, `alembic_version`.
- Notable columns: `provider_runtime_configs.encrypted_credentials` (Fernet-encrypted, see §4/§13), `evidence_items.provenance_category`, `case_reports.content_markdown` (reports are stored as Markdown text + JSON `context`, not as binary blobs — see §11).

## 4. Authentication

- **Mechanism:** JWT (HS256) via `python-jose`, issued by `app/auth/security.py`. Access tokens (`access_token_expire_minutes`, default 30 min) and refresh tokens (`refresh_token_expire_days`, default 7 days), each carrying `sub` (email), `role`, `token_version`, `type`, `iat`, `exp`.
- **Password hashing:** bcrypt via `passlib.CryptContext`.
- **Forced-logout mechanism:** `users.token_version` (int, default 0) is embedded in every issued JWT and re-checked on every request by `get_current_user()`; an admin-initiated password reset bumps it, immediately invalidating every previously-issued token for that user (not just future logins). A JWT with no `token_version` claim at all is treated as `0` (backward compatible, zero forced logouts on upgrade).
- **Secret material:** `jwt_secret_key` (Settings field, default placeholder `"change-me-in-production"` — real installs get one generated by the Windows wizard). Same signing key for both access and refresh tokens; `jwt_algorithm` fixed to HS256 (no algorithm confusion surface since `jwt.decode` is called with an explicit single algorithm).

## 5. RBAC Model

Three roles (`app/models/user.py`, `enum Role`): **`admin`**, **`analyst`**, **`viewer`**. Permission matrix (`ROLE_PERMISSIONS`), consumed by `app/auth/rbac.py`'s `require_role` dependency:

| Permission string | admin | analyst | viewer |
|---|---|---|---|
| `lookup:create` | ✓ | ✓ | |
| `lookup:read` | ✓ | ✓ | ✓ |
| `lookup:export` | ✓ | ✓ | |
| `provider:manage` | ✓ | | |
| `user:manage` | ✓ | | |
| `audit:read` | ✓ | | |
| `evidence:read` | ✓ | ✓ | ✓ |
| `analysis:generate` | ✓ | ✓ | |
| `hunting:generate` | ✓ | ✓ | |
| `copilot:query` | ✓ | ✓ | |
| `basket:manage` | ✓ | ✓ | |
| `case:create` | ✓ | ✓ | |
| `case:read` | ✓ | ✓ | ✓ |
| `case:write` | ✓ | ✓ | |
| `case:close` | ✓ | ✓ | |
| `security_assessment:create` | ✓ | ✓ | |
| `security_assessment:read` | ✓ | ✓ | ✓ |

Notes: `analyst` and `admin` differ only by the four admin-only permissions (`provider:manage`, `user:manage`, `audit:read`, plus admin has none exclusive beyond those three since `security_assessment:create`/case perms are shared). `viewer` is strictly read-only (4 permissions, all `*:read`). This is an exhaustive list of every permission string defined in the model — there are 17 distinct permission strings total.

## 6. AI Layer

Five interchangeable backends, all exposing an identical `call_claude_json()` interface so the summarization/assessment code never branches on which is active (`app/ai/service.py`): **Ollama** (local, default/no-API-key), **Anthropic** (direct API), **AWS Bedrock**, **Google Gemini**, **Groq**.

**Live configuration right now** (via `list_ai_providers()`, actually queried against the running backend — not inferred):

| Provider | Enabled | **Active** | Configured | Model | Last test |
|---|---|---|---|---|---|
| `anthropic` | ✓ | | ✗ | `claude-sonnet-4-5-20250929` | never tested |
| `bedrock` | ✓ | | ✗ | `anthropic.claude-sonnet-4-5-20250929-v1:0` | never tested |
| `gemini` | ✓ | | ✗ | `gemini-2.0-flash` | never tested |
| `groq` | ✓ | | ✓ | `llama-3.3-70b-versatile` | **2026-08-12: OK** ("Connected. Model replied: 'pong'") |
| `ollama` | ✓ | **✓ (active)** | ✓ | `gemma2:2b` | **2026-08-15: FAILED** — "Ollama base URL and model are both required." |

**Operational note (live-observed, not hypothetical):** the platform's currently-*active* AI backend (`ollama`) has a failing last-recorded connectivity test, while a *configured-but-inactive* backend (`groq`) has a passing one. Any assessment/summarization call right now would attempt Ollama first per the active-backend resolution order in `_get_ai_client()`. This is a live state observation as of the query time above, not a code defect — the fallback/config logic itself already handles a missing backend by raising a clear `RuntimeError` rather than failing silently.

- **Credential storage:** runtime-configured provider/AI credentials are encrypted at rest with Fernet symmetric encryption (`app/core/crypto.py`) before being written to `provider_runtime_configs.encrypted_credentials`. Key material is `encryption_master_key` if explicitly set (Windows wizard generates one for new installs), else HKDF-derived from `jwt_secret_key` — documented in-code as "defense-in-depth, not HSM-grade key separation."
- **Anti-hallucination controls observed in `app/ai/service.py`:** (1) grounding pass (`_ground_final_assessment`) that strips AI-claimed provider agreement/disagreement not backed by the deterministic correlation engine; (2) hard field-length pruning before prompts (`_prune_for_prompt`) — tuned through two documented live-bug rounds (NVD `configurations` field burying real CVSS severity; MITRE ATT&CK descriptions needing a taller cap that broke NVD again; final fix caps `list`/`dict` fields at 800 chars but `str` fields at 2000, since prose fields carry real signal and structural fields don't); (3) a hard-coded short-circuit that skips calling the AI entirely when there is zero provider evidence, in response to a documented reproduced bug where a small model fabricated a "highly_malicious"/92% verdict for the EICAR test hash from pretrained knowledge alone; (4) one bounded retry on Pydantic `ValidationError` only (not on rate-limit/network errors, to avoid compounding an exhausted quota).

## 7. IOC Providers

`app/providers/registry.py` — 16 registered providers (11 real connectors + 4 "stub" connectors + 1 in-house OSINT crawler), live-queried via `get_provider_health()`:

| provider_id | category | key required | configured (live) | supported IOC types |
|---|---|---|---|---|
| `virustotal` | threat_intel | yes | **NOT configured** | domain, ipv4, ipv6, md5, sha1, sha256, sha512, url |
| `abuseipdb` | threat_intel | yes | **NOT configured** | ipv4, ipv6 |
| `otx` (AlienVault) | threat_intel | yes | **NOT configured** | domain, hostname, ipv4, ipv6, md5, sha1, sha256, sha512, url |
| `urlhaus` | threat_intel | yes | **NOT configured** | domain, ipv4, url |
| `threatfox` | threat_intel | yes | **NOT configured** | domain, ipv4, ipv6, md5, sha256, url |
| `malwarebazaar` | threat_intel | yes | **NOT configured** | md5, sha1, sha256, sha512 |
| `crtsh` | certificate_intel | no | configured | domain, tls_certificate |
| `nvd` | vulnerability | no (optional key raises rate limit) | configured | cve |
| `cisa_kev` | vulnerability | no | configured | cve |
| `mitre_attack` | threat_intel | no | configured | mitre_technique |
| `whois_rdap` | whois | no | configured | asn, domain, ipv4, ipv6 |
| `hybrid_analysis` (stub) | sandbox | yes | **NOT configured** | sha256 |
| `spamhaus` (stub) | threat_intel | no | configured | domain, ipv4 |
| `phishtank` (stub) | threat_intel | no | configured | url |
| `censys` (stub) | passive_dns | yes | **NOT configured** | ipv4, ipv6 |
| `internet_intelligence` (in-house crawler, `app/crawler`) | osint | no | configured | campaign, cve, domain, file_name, ipv4, malware_family, threat_actor |

URLhaus/ThreatFox/MalwareBazaar share a single `abusech_auth_key`. Registry architecture is deliberately a flat list built by import — "adding a provider is a two-line change" per its own docstring — and never touches the orchestrator/API/correlation engine.

## 8. Security Assessment Toolkit

`app/security_assessment/registry.py` — deliberately a **separate** registry from the IOC-provider one so these tools are never picked up by the automatic per-investigation orchestrator fan-out (they're user/admin-invoked only, via `POST /security-assessment/{lookup_id}/run`). 5 user-selectable tools:

- `nmap_tool` — port/service scanning (calls `vuln_intel.py` internally as an enrichment helper; `vuln_intel` is explicitly *not* itself a standalone registry entry)
- `dns_tool`
- `tls_tool`
- `http_headers_tool`
- `hash_tool`

Findings persist to `security_assessment_runs` / `security_assessment_findings`; results are also cross-referenced to `final_assessment_records` (per the FK-cleanup note already known from the test suite). Per the environment's own safety convention (and this task's instruction), no live scan was run against any third-party host during this inventory pass — tool presence/wiring was confirmed by reading `registry.py` and the DB schema only.

## 9. Background Workers / Queues

- **Broker/result backend:** Redis, via Celery `5.4.0` — `celery_broker_url` = `redis://redis:6379/1` (DB 1), `celery_result_backend` = `redis://redis:6379/2` (DB 2). Separate Redis logical DB (`/0`) used for the app-level cache (see §10) so cache and broker traffic don't collide.
- **App name:** `ioc_intel_platform` (`app/workers/celery_app.py`).
- **Scheduled job (Celery Beat):** `crawl-osint-sources-hourly` → `app.workers.tasks.run_osint_crawl`, every 3600s.
- **Live-confirmed registered tasks** (via `celery inspect`/introspection against the running worker): `app.workers.tasks.run_osint_crawl` plus Celery's built-ins (`celery.group`, `celery.chain`, `celery.chord`, etc.) — i.e. exactly one real application task is currently registered.
- **1 worker node online** at inspection time (`celery@36b65f79fd82`), one active queue (`celery`, default).
- **Design note from code comments:** the interactive/synchronous IOC-lookup path (SSE streaming to the UI for live per-provider updates) deliberately does **not** go through Celery — it runs in-process async. Celery is reserved for fire-and-forget/scheduled work (scheduled crawls, PDF/report export rendering, lookup re-processing that outlives the HTTP request lifecycle).

## 10. Caching

- **Backend:** Redis (logical DB `0`), via `redis.asyncio`, module `app/core/cache.py`.
- **Provider-result cache:** key format `provider_cache:{provider_id}:{ioc_type}:{sha256(ioc_value)}` — IOC values are hashed before being used as a cache key, not stored in plaintext in the key itself. TTL controlled by `provider_cache_ttl_seconds` (default 3600s).
- **Rate limiting:** a Redis-backed fixed-window limiter (`RateLimiter` class), one window key per provider (`rate_limit:{provider_id}`), enforced across all worker processes rather than per-process. Also a separate per-user rate limit on the lookup-creation endpoint (`lookup_rate_limit_max_calls`=10 / `lookup_rate_limit_window_seconds`=60).

## 11. File Storage

There is **no persistent object/file storage layer** (no S3 bucket, no local upload directory found in config or route code). Specifically:
- `boto3` (in `requirements.txt`) is used only for the AWS Bedrock AI client and its connection test (`app/ai/bedrock_client.py`, `app/ai/connection_test.py`) — not for any S3/file storage.
- `reportlab` (PDF generation) is used only in `app/api/routes/lookup.py`'s export endpoint (`POST /lookup/{id}/export`) — PDFs are generated on-demand in-memory and streamed back in the HTTP response, not written to disk or object storage.
- Case reports (`case_reports` table) are stored as **Markdown text** (`content_markdown` column) + a `context` JSONB blob, not as binary/blob files.
- Evidence (`evidence_items`) stores structured claims/JSON (`raw_data` JSONB), not files.

## 12. Configuration Sources

- **Primary config:** `app/core/config.py`'s `Settings` (pydantic-settings `BaseSettings`), loaded from environment variables and/or a `.env` file (`env_file=".env"`).
- **.env file location (installed copy):** `C:\Program Files\IOC Intelligence Platform\app\.env` — confirmed to exist (last modified 2026-08-14) but **not readable by the current shell user** (`Permission denied` on direct read attempt), consistent with the Windows wizard's documented `icacls`-locked-down `Program Files`/`ProgramData` write model. Variable *names* only were enumerated via `docker inspect` on the container's resolved environment instead of reading the file directly (values never retrieved): `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `REDIS_URL`, `NEO4J_URI`, `NEO4J_PASSWORD`, `OPENSEARCH_URL` present as container env.
- **docker-compose.yml overlay behavior (installed copy, confirmed live):** the `backend` service's explicit `environment:` block in `docker-compose.yml` always wins over `env_file: .env` for the same key. One key, `OLLAMA_BASE_URL`, is hardcoded there (`host.docker.internal:11434` default) rather than using the `${VAR:-default}` pattern every other setting uses — the file's own inline comment documents this as a confirmed-live bug where a user-configured Ollama host written correctly to `.env` by the setup wizard was silently never honored, because the compose-level `environment:` entry overrides it regardless. (This is pre-existing/documented in the file itself, not a new finding from this pass.)
- **Datastore network exposure (installed copy, confirmed live, already fixed):** Postgres/Redis/Neo4j/OpenSearch host ports are explicitly bound to `127.0.0.1` only, each with an inline comment stating that the default Docker shorthand (`0.0.0.0`-equivalent publish) was confirmed live to be LAN-reachable with zero authentication for OpenSearch specifically (security plugin disabled — `DISABLE_SECURITY_PLUGIN: "true"`) and reachable-metadata-only for Neo4j — i.e., this is a documented-and-already-remediated issue in the running config, not an open one.
- **Full settings surface** (`Settings` class) covers: app metadata, LAN network-info fields (written by the Windows wizard), JWT/encryption keys, 4 datastore URLs, 2 Celery URLs, credentials/model IDs for all 5 AI backends, credentials for all 11 real+stub IOC providers, crawler tuning (user-agent, timeout, max results/source), provider execution tuning (timeout, retries, cache TTL), and lookup-endpoint rate-limit tuning.

## 13. Logging

- **Framework:** Python stdlib `logging` (`basicConfig(level=logging.INFO)`) + `structlog 24.4.0` configured with `JSONRenderer` (structured/JSON log lines), set up once at `app/main.py` import time.
- **Metrics (adjacent to logging):** `prometheus-fastapi-instrumentator 7.0.0`, exposing `GET /metrics` on the backend for scraping; there's also a standalone `pgexporter` (Postgres exporter) container on the host — but that belongs to the separate PentAGI stack noted in §0, not to this app's own compose file (the IOC platform's own `docker-compose.yml` doesn't define a Postgres exporter).
- **Audit trail:** `app/core/audit.py` + `config_audit_log` table — captures administrator-driven config/provider/user changes (referenced by the task's own note about `actor_user_id`'s FK constraint).
- Application code logs failures with context rather than swallowing them silently in the key places inspected (e.g. AI generation failures, runtime-config seeding failures at startup are caught and logged via `logging.getLogger(__name__).exception(...)` rather than crashing app boot).

## 14. Windows Installer (`windows/`)

- **`windows/wizard/Setup-Wizard.ps1`:** a real WinForms GUI (explicitly documented in its own header as "no HTML/Electron"), launched by the Inno Setup installer's `[Run]` step post-copy, and re-launchable later from the Start Menu ("Configuration"). Flow: **Welcome → Admin Account → AI Configuration → Provider Configuration → Port Review → Summary → Install/Start → Health Check → Finish**.
  - Self-elevates via UAC re-launch if not already running with an unfiltered admin token — the script's own comment explains this is necessary because being in the Administrators group is insufficient on its own (a normally-launched process under UAC gets a filtered token), and this was "confirmed live" to reject a real admin account when launched from the installer's postinstall step.
  - "Test Connection" buttons in the wizard make real HTTP calls to the running backend's own `POST /api/v1/providers/{id}/test` endpoint (added specifically to support this wizard) — i.e. provider/AI validation during setup exercises the real backend, not a mock.
  - Sequencing: collects ports/secrets first → writes them → starts `docker compose` → *then* runs provider testing/admin-account creation against the now-live backend.
- **`windows/scripts/`:** `Backup-Database.ps1`, `Check-Prerequisites.ps1`, `Common.ps1` (shared helpers, incl. `Get-LanIpAddress` consumed by `/network-info`), `Diagnostics.ps1`, `Open-Platform.ps1`, `Service-Restart.ps1`, `Service-Start.ps1`, `Service-Status.ps1`, `Service-Stop.ps1`, `Write-EnvFile.ps1` (writes the `.env` consumed by `docker-compose.yml`'s `env_file:`).

## 15. Third-Party API Dependencies

Grouped by what an operator must actually provision externally for full functionality:

- **AI backends (need external account/key unless using local Ollama):** Anthropic (direct API), AWS Bedrock, Google Gemini, Groq. Ollama is local/self-hosted, no external dependency, no API key/quota.
- **IOC/threat-intel providers requiring an API key:** VirusTotal, AbuseIPDB, AlienVault OTX, abuse.ch family (URLhaus/ThreatFox/MalwareBazaar share one `abusech_auth_key`), Hybrid Analysis (stub), Censys (stub, needs both a Platform PAT and an org ID).
- **No-key/free-tier providers:** crt.sh, NVD (key optional, raises rate limit), CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Spamhaus (stub), PhishTank (stub, key optional).
- **In-house, no external API:** `internet_intelligence` OSINT crawler (`app/crawler`, uses `feedparser`/`beautifulsoup4`/`lxml` against public feeds directly, no paid API).

---

## Explicit Scope Limitations (Honesty Notes)

- **NOT TESTED — ENVIRONMENT LIMITATION:** True multi-machine HA/failover behavior, since this is a single-host Docker Compose deployment with no clustering configured anywhere in the compose files inspected.
- **NOT TESTED:** Real load/performance numbers were not gathered as part of this inventory task — none are reported here, and none should be assumed; this document is a static/config/schema inventory, not a load test.
- **NOT VERIFIED:** The `.env` file's actual contents (values) — deliberately not read, both because direct filesystem access was denied by OS permissions and per this task's own instruction to never surface secret values; only variable *names* (via container env) and *presence/configured-boolean* (via the live `list_ai_providers()`/`get_provider_health()` calls) were used.
- Everything else in this document was obtained by direct, live inspection during this session: reading the installed copy's source files, querying the running Postgres DB, calling into the running backend container's Python environment, and calling the live `docker ps`/`docker inspect`/OpenSearch HTTP API — not recalled from training data or prior conversation memory.

---

**Key file paths referenced (installed/running copy, all under `C:\Program Files\IOC Intelligence Platform\app\`):**
`backend/app/main.py`, `backend/app/models/user.py`, `backend/app/auth/security.py`, `backend/app/core/config.py`, `backend/app/core/cache.py`, `backend/app/core/crypto.py`, `backend/app/providers/registry.py`, `backend/app/security_assessment/registry.py`, `backend/app/workers/celery_app.py`, `backend/app/ai/service.py`, `frontend/package.json`, `docker-compose.yml`, `windows/wizard/Setup-Wizard.ps1`, `.env` (present, permission-restricted).