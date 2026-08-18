# Project Overview, Technology Stack, and Repository Structure

## 1. What This Project Is

HORIZON GRID is a self-hosted SOC (Security Operations Center) workbench for investigating **IOCs** (Indicators of Compromise — an IP address, domain, URL, file hash, CVE, or similar artifact). The backend's own FastAPI app description (`backend/app/main.py:20-22`, shown in the Swagger UI at `/docs`) describes the core loop as "single-search IOC lookup across dozens of providers, correlated and summarized by a local Ollama model (or AWS Bedrock/Gemini/Anthropic/Groq, configurable via AI_BACKEND)."

Concretely, one investigation does the following, all reachable from a single API call (`POST /api/v1/lookup/stream`):

1. A raw string is classified into a typed IOC (`backend/app/ioc/detector.py`).
2. The IOC is fanned out concurrently to as many of ~16 registered threat-intelligence providers as support that IOC type (`backend/app/providers/orchestrator.py`).
3. A deterministic correlation engine extracts relationships between the seed IOC and anything the providers returned (`backend/app/correlation/engine.py`).
4. A deterministic, non-AI evidence ledger is built from the raw provider data and correlation edges (`backend/app/evidence/builder.py`) — this ledger is what every later AI explanation must cite back to.
5. An AI backend (one of five interchangeable options, hot-swappable without a restart) summarizes each provider's result and then produces one final verdict/risk-score assessment grounded in the evidence (`backend/app/ai/service.py`).
6. Every step streams back to the browser as Server-Sent Events, and the whole run — provider results, AI summaries, correlation edges, evidence, final assessment — is persisted to PostgreSQL.

Beyond the core lookup, the platform layers analyst workflow on top: a persisted evidence ledger with on-demand AI explanations (why-malicious, disagreement, false-positive, red-team challenge, next-actions, intelligence gaps, score explanation, free-form "Copilot" Q&A), threat-hunting query generation (Sigma/Splunk/KQL/etc.), an IOC "basket" scratch space with AI-assisted comparison, case management, JWT-based auth with three roles, and a DB-backed runtime configuration system that lets an admin change AI/provider credentials from the UI with no container restart.

This is a real, running codebase — not a prototype: it ships as a Windows-installable product (Inno Setup + a PowerShell setup wizard over Docker Compose), has an async backend test suite (`backend/app/tests/`), and has two parallel deployment paths (Docker Compose and Kubernetes via `k8s/`).

## 2. Technology Stack

### 2.1 Backend

| Layer | Choice | Version (pinned) | Source |
|---|---|---|---|
| Language / runtime | Python | 3.12 (`python:3.12-slim` base image) | `backend/Dockerfile` |
| Web framework | FastAPI | 0.115.0 | `backend/requirements.txt` |
| ASGI server | Uvicorn (`[standard]`) | 0.30.6 | `backend/requirements.txt` |
| Validation / settings | Pydantic, pydantic-settings | 2.9.2, 2.5.2 | `backend/requirements.txt` |
| ORM | SQLAlchemy (`[asyncio]`) | 2.0.35 | `backend/requirements.txt` |
| Postgres driver | asyncpg | 0.29.0 | `backend/requirements.txt` |
| Migrations | Alembic | 1.13.2 | `backend/requirements.txt` |
| Cache / broker client | redis-py | 5.0.8 | `backend/requirements.txt` |
| HTTP client | httpx | 0.27.2 | `backend/requirements.txt` |
| Retry logic | tenacity | 9.0.0 | `backend/requirements.txt` |
| Graph DB driver (provisioned, unused — see Database chapter) | neo4j | 5.24.0 | `backend/requirements.txt` |
| Background jobs | Celery | 5.4.0 | `backend/requirements.txt` |
| Auth / JWT | python-jose (`[cryptography]`) | 3.3.0 | `backend/requirements.txt` |
| Credential encryption | cryptography | 43.0.1 | `backend/requirements.txt` |
| Password hashing | passlib, bcrypt | 1.7.4, 4.0.1 | `backend/requirements.txt` |
| Cloud SDK (Bedrock) | boto3 | 1.35.24 | `backend/requirements.txt` |
| Search client (provisioned, unused) | opensearch-py | 2.7.1 | `backend/requirements.txt` |
| OSINT feed parsing | feedparser, beautifulsoup4, lxml | 6.0.11, 4.12.3, 5.3.0 | `backend/requirements.txt` |
| WHOIS | python-whois | 0.9.6 | `backend/requirements.txt` |
| Logging | structlog | 24.4.0 | `backend/requirements.txt` |
| Metrics | prometheus-fastapi-instrumentator | 7.0.0 | `backend/requirements.txt` |
| Testing | pytest, pytest-asyncio, pytest-cov, respx | 8.3.3, 0.24.0, 5.0.0, 0.21.1 | `backend/requirements.txt` |

### 2.2 Frontend

| Layer | Choice | Version (pinned) | Source |
|---|---|---|---|
| Runtime (container) | Node.js | 20 (`node:20-alpine` base image) | `frontend/Dockerfile` |
| Framework | Next.js (App Router) | 14.2.15 | `frontend/package.json` |
| UI library | React / ReactDOM | 18.3.1 | `frontend/package.json` |
| Language | TypeScript | 5.6.2 | `frontend/package.json` |
| Styling | Tailwind CSS | 3.4.12 | `frontend/package.json` |
| Client state | Zustand | 4.5.5 | `frontend/package.json` |
| Charts | Recharts | 2.12.7 | `frontend/package.json` |
| Graph visualization | react-force-graph-2d | 1.25.4 | `frontend/package.json` |
| UI primitives | Radix UI (`react-tabs`, `react-dialog`, `react-progress`, `react-slot`, `react-tooltip`) | 1.0.x–1.1.x | `frontend/package.json` |
| Class variants / utility CSS | class-variance-authority, clsx, tailwind-merge | 0.7.0, 2.1.1, 2.5.2 | `frontend/package.json` |
| Icons | lucide-react | 0.446.0 | `frontend/package.json` |
| Test runner (configured, unused) | vitest | 2.1.1 | `frontend/package.json` — `"test": "vitest run"` is declared, but no `*.test.*`/`*.spec.*` files exist anywhere under `frontend/`; the tooling is present, no frontend automated tests currently exist. |

### 2.3 Datastores and infrastructure

| Component | Image | Actually used? |
|---|---|---|
| PostgreSQL | `postgres:16-alpine` | Yes — the sole system of record; every lookup, provider result, AI summary, correlation edge, evidence item, case, and user row lives here. |
| Redis | `redis:7-alpine` | Yes — three roles on separate logical DB indexes: provider-result cache + rate limiter (`/0`), Celery broker (`/1`), Celery result backend (`/2`). |
| Neo4j | `neo4j:5-community` + APOC | Container runs and a driver is in `requirements.txt`, but no Cypher query or driver instantiation exists anywhere in the application code — provisioned only. |
| OpenSearch | `opensearchproject/opensearch:2.17.0` | Container runs and `opensearch-py` is in `requirements.txt`, but no index/search client code exists — provisioned only. |
| Celery worker + beat | same backend image, `celery_worker`/`celery_beat` services | Yes, for exactly one scheduled job: hourly OSINT re-crawl (`run_osint_crawl`). The interactive `/lookup/stream` path never touches Celery. |

Orchestration is defined in `docker-compose.yml` (development, eight containers total including `frontend`) and layered with `docker-compose.prod.yml` for production (strips dev bind-mounts, switches to production start commands). A second, independent deployment path exists in `k8s/` — a Kustomize-based Kubernetes manifest set (`k8s/base/`) with StatefulSets for `postgres`/`neo4j`/`opensearch`, Deployments for `backend`/`frontend`/`celery`, and an Ingress resource.

## 3. Repository Structure

```
ioc-intel-platform/
├── .env / .env.example          Backend credential/URL defaults (Settings source); real .env is never committed
├── docker-compose.yml           Dev topology: postgres, redis, neo4j, opensearch, backend, celery_worker, celery_beat, frontend
├── docker-compose.prod.yml      Production overlay (no bind-mounts, prod start commands) — used by the Windows installer
├── README.md                   Top-level project summary
├── *_REPORT.md                 Root-level engineering session reports (bug/fix/test write-ups; not shipped documentation)
├── test-provider-pipeline.sh   Ad hoc shell script that re-runs provider connection tests against real container env
│
├── backend/                     FastAPI application (Python 3.12)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/                 Schema migrations
│   │   ├── env.py               Async-engine Alembic runner; imports app.models.Base
│   │   └── versions/            4 linear migrations (initial_schema → evidence/basket/case → provider_runtime_config/audit → final_assessment_records)
│   └── app/
│       ├── main.py               App assembly: router registration, CORS, startup hook (runtime-config seeding), /health, /metrics
│       ├── api/routes/           10 route modules — one per resource area (see §4)
│       ├── core/                 config.py (Settings), runtime_config.py (DB-backed config), runtime_context.py (ContextVar overrides), db.py, cache.py, crypto.py
│       ├── auth/                 security.py (bcrypt/JWT), rbac.py (get_current_user, require_permission)
│       ├── ioc/                  types.py (IOCType enum), detector.py (regex-cascade classifier)
│       ├── providers/            ~16 threat-intel connectors + base.py, orchestrator.py, registry.py, connection_test.py, stubs/
│       ├── ai/                   5 AI-backend clients + service.py, analysis_service.py, hunting_service.py, schemas, connection_test.py
│       ├── correlation/          engine.py — pure fact/relationship extraction, no I/O
│       ├── evidence/             builder.py, loaders.py, pivot.py — the citable, deterministic evidence ledger
│       ├── crawler/               OSINT collector provider + 4 sub-source modules (github, reddit, rss_news, pastebin_search)
│       ├── workers/               celery_app.py, tasks.py — the one hourly OSINT re-crawl job
│       ├── models/                SQLAlchemy ORM: user, lookup, evidence, basket, case, runtime_config, base
│       ├── schemas/                Pydantic request/response DTOs (lookup, basket, case, auth)
│       └── tests/                 unit/ (18 files) + integration/ (3 files), pytest + pytest-asyncio + respx
│
├── frontend/                     Next.js 14 application (TypeScript)
│   ├── Dockerfile
│   ├── package.json
│   ├── app/                      App Router pages: home, lookup/new, lookup/[id], basket, cases, cases/[id], providers, login, register
│   ├── components/
│   │   ├── dashboard/             ~22 investigation-workspace widgets (ProviderCardGrid, RelationshipGraph, EvidencePanel, HuntingCenterPanel, ...)
│   │   └── ui/                    shadcn-style primitives (button, card)
│   └── lib/                       api.ts (all backend calls + SSE consumer), types.ts (manual mirror of backend Pydantic schemas), utils.ts, aiPrompt.ts
│
├── docs/                          Hand-written engineering reference docs (ARCHITECTURE.md, API.md, DATA_MODEL.md, PROVIDERS.md, DEPLOYMENT.md, TESTING.md, TROUBLESHOOTING.md, ...)
├── documentation/                 Generated product-documentation pipeline (this chapter's home)
│   ├── DOCUMENTATION_SOURCE/       Markdown source chapters (tech-*.md, user-*.md, dev-*.md)
│   ├── ARCHITECTURE_DIAGRAMS/      Rendered diagram PNGs referenced by [FIGURE: ...] placeholders
│   ├── SCREENSHOTS/                Product screenshots for the user manual
│   └── build/                      Node.js scripts assembling source Markdown into PDF/DOCX deliverables
│
├── k8s/                           Kustomize-based Kubernetes manifests (alternative to Docker Compose)
├── windows/                        Windows packaging: Inno Setup script + PowerShell setup wizard + service/backup/diagnostic scripts
└── release/                       Built installer artifact (.exe) + checksums
```

## 4. The Backend API Surface, at a Glance

`backend/app/main.py` registers ten route modules under the global prefix `/api/v1` (`settings.api_v1_prefix`), in this order:

| Module | Base path | Endpoint count | Covers |
|---|---|---|---|
| `auth.py` | `/auth` | 4 | register / login / refresh / me |
| `lookup.py` | `/lookup` | 5 | the core SSE investigation stream, reanalyze, assessments, get/list |
| `providers.py` | `/providers` | 2 | provider health, live credential test |
| `ai_config.py` | `/ai` | 2 | AI backend live test, model-list discovery |
| `analysis.py` | `/lookup/{id}/analysis` | 10 | evidence + 9 AI explanation endpoints (why, what-is-this, disagreement, false-positive, challenge, next-actions, gaps, score-explanation, copilot) |
| `hunting.py` | `/lookup/{id}` | 2 | hunting-query package, detection-rule draft |
| `pivot.py` | `/lookup/{id}/pivots` | 1 | deterministic pivot ranking |
| `basket.py` | `/basket` | 5 | per-analyst scratch list + AI comparison |
| `cases.py` | `/cases` | 8 | case CRUD, IOCs, notes |
| `runtime.py` | `/runtime` | 10 | DB-backed AI/provider config, activation, audit log |

Total: 49 endpoints, all gated by `require_permission(...)` except the three public auth endpoints and `/auth/me` (identity-only). The full request/response contract for every one of these is documented in the API Reference chapter of this package; this chapter is concerned only with orienting a new engineer to where that code lives.

## 5. Files a New Engineer Should Read First

The following ~26 files, read roughly in this order, cover the entire system end to end. This list reflects the actual dependency order of the codebase, not an arbitrary tour.

**Entry point and configuration**

1. `backend/app/main.py` — app assembly, the full router list, and the startup hook; the map of everything else.
2. `backend/app/core/config.py` — every environment-driven setting (`Settings`, `@lru_cache`'d `get_settings()`); read before anything else that touches a credential or URL default.
3. `backend/app/core/runtime_config.py` — the DB-backed configuration system that overrides #2 at runtime without a restart; central to understanding how AI backends and provider credentials are actually managed in production.
4. `backend/app/core/runtime_context.py` — the small but easy-to-miss `ContextVar` mechanism that makes per-investigation provider-credential overrides safe under concurrent requests.

**The investigation pipeline — the actual product**

5. `backend/app/api/routes/lookup.py` — the single most important file: the whole SSE-streamed investigation lifecycle (`detect → fan-out → correlate → summarize → assess → persist`) lives here.
6. `backend/app/providers/base.py` — the `BaseProvider` contract every connector implements; read before any individual provider file.
7. `backend/app/providers/orchestrator.py` — how one IOC fans out to N providers concurrently, with caching, retry, and timeout.
8. `backend/app/providers/registry.py` — the flat list of all ~16 registered provider singletons; the extensibility seam for adding a new source.
9. `backend/app/providers/virustotal.py` — the most complete, documented reference connector to model new providers on.
10. `backend/app/ioc/detector.py` — how a raw string becomes a typed `IOCType`; determines which providers even run for a given input.
11. `backend/app/ioc/types.py` — the `IOCType` enum and `HASH_TYPES`/`NETWORK_TYPES` sets that every other module keys off of.
12. `backend/app/correlation/engine.py` — the pure, I/O-free function that turns N provider results into a relationship graph and provider-agreement data.
13. `backend/app/evidence/builder.py` — converts providers + correlation into the citable evidence ledger that grounds every later AI claim; the anti-hallucination foundation of the product.
14. `backend/app/ai/service.py` — the two-stage AI pipeline (per-provider summary → final assessment), the 3-tier backend-resolution logic (`_get_ai_client`), and the correlation-grounding cross-check.
15. `backend/app/ai/schemas.py` — the structured-output contracts every AI backend must satisfy; explains why the schemas use real `Literal`/enum types rather than prose.
16. `backend/app/ai/analysis_service.py` — the "explain this completed lookup" AI functions and the evidence-id grounding/stripping mechanism.

**Data model and authorization**

17. `backend/app/models/lookup.py` — the core persisted entities: `IOCLookup`, `ProviderResultRecord`, `AISummaryRecord`, `CorrelationEdgeRecord`, `FinalAssessmentRecord`.
18. `backend/app/models/evidence.py` — the evidence-ledger schema (`EvidenceItem`).
19. `backend/app/models/runtime_config.py` — the runtime provider/AI configuration schema backing #3.
20. `backend/app/models/user.py` — `Role` and `ROLE_PERMISSIONS`; the entire authorization matrix in one file.
21. `backend/app/auth/rbac.py` — how `get_current_user`/`require_permission(...)` actually gate every route.

**Frontend**

22. `frontend/lib/api.ts` — every backend interaction, including the hand-rolled SSE consumer (`streamLookup`) and 401-refresh-retry logic; the frontend's single point of coupling to the backend contract.
23. `frontend/lib/types.ts` — a manually-maintained TypeScript mirror of the backend's Pydantic schemas; read alongside #15/#17 to see the full contract from both sides.
24. `frontend/app/lookup/new/page.tsx` — the live-investigation composition root; shows how every dashboard widget consumes the SSE event stream.
25. `frontend/app/lookup/[id]/page.tsx` — the completed-lookup equivalent, useful as a diff against #24 for what the API reshapes once a lookup is persisted.

**Operations and packaging**

26. `docker-compose.yml` — the full local runtime topology and the `host.docker.internal` Ollama networking detail.
27. `windows/wizard/Setup-Wizard.ps1` (with `windows/scripts/Common.ps1`) — how the stack becomes an installable Windows product; explains the Program Files/ProgramData split and the live-provider-testing UX that mirrors `providers/connection_test.py`.

## 6. Cross-Cutting Facts Worth Internalizing Before Reading Further

- Every provider is a **module-level singleton**; per-investigation credential and enabled/disabled overrides flow through a `ContextVar` (`core/runtime_context.py`), never through mutated instance state — this is what makes concurrent investigations with different provider configs safe.
- Every AI call site resolves its backend the same three-tier way (`_get_ai_client`): explicit override → active DB-backed runtime config → legacy `Settings` fallback. This pattern repeats identically across `ai/service.py`, `ai/analysis_service.py`, and `ai/hunting_service.py`.
- Nothing the AI produces is trusted at face value: `evidence/builder.py` generates ground truth with zero AI involvement, and every AI explanation function strips citations that don't reference a real evidence id, a real correlation edge, or a real provider id.
- The frontend has no independent business logic. `frontend/lib/api.ts` is a pure pass-through to the FastAPI routes, and `frontend/lib/types.ts` is a hand-maintained mirror of the backend's Pydantic models — the two must be kept in sync manually; there is no code-generation step between them.
- Two containers in every deployment — `neo4j` and `opensearch` — are provisioned and running but have no consuming application code today (see the Database Architecture chapter for the full verification). Treat any reference to a "Neo4j-backed graph" or "OpenSearch-backed search" in older docstrings or comments as aspirational, not implemented.

[FIGURE: dev-01-overview-stack-repo-structure-diagram-1.png | Diagram: 6. Cross-Cutting Facts Worth Internalizing Before Reading Further]
Diagram: Repository and stack overview — solid lines are active data paths; dotted lines mark containers that run but have no consuming application code today.
