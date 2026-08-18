# Technical Architecture Overview

HORIZON GRID is a self-hosted tool that looks up an **IOC** (Indicator of Compromise — e.g. an IP address, domain, URL, or file hash) against many third-party threat-intelligence sources at once, then uses an AI model to summarize and correlate the results. The backend's own self-description (`backend/app/main.py`) puts it this way:

> "single-search IOC lookup across dozens of providers, correlated and summarized by a local Ollama model (or AWS Bedrock/Gemini/Anthropic)."

This section describes what the platform is built from at the container/process level, not the request-level data flow (covered elsewhere in this document) or the AI/provider internals (also covered elsewhere).

## Container Inventory

`docker-compose.yml` defines seven backing services — `postgres`, `redis`, `neo4j`, `opensearch`, `backend`, `celery_worker`, and `celery_beat` — plus the `frontend` container, for eight containers running the full stack.

| Container | Image / stack | Role | Implementation status |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | System of record: lookups, provider results, AI summaries, correlation edges, evidence, cases, users. | Actively used — the only datastore actually written to during a lookup. |
| `redis` | `redis:7-alpine` | Provider-result cache (logical DB `/0`), per-user rate limiter, Celery message broker (`/1`) and Celery result backend (`/2`). | Actively used. |
| `neo4j` | `neo4j:5-community` + APOC plugin | Config field and container exist to "mirror" correlation edges into a graph store, per two module docstrings. | Provisioned only — no driver instantiation, Cypher query, or read/write call exists anywhere in the backend code. Not used for anything today. |
| `opensearch` | `opensearchproject/opensearch:2.17.0` (`DISABLE_SECURITY_PLUGIN: "true"`) | Config field and container exist for an intended full-text/search index. | Provisioned only — no indexing or search client code exists in the backend. No search functionality is implemented against it. |
| `backend` | FastAPI, Python 3.12 | Core API server: IOC-type detection, provider orchestration, AI summarization/correlation, evidence building, auth, case management. | Actively used — the primary application process. |
| `celery_worker` | Celery 5.4 (same backend codebase) | Executes background jobs. | Actively used, but for exactly one job (see below). |
| `celery_beat` | Celery 5.4 beat scheduler | Triggers scheduled jobs on a timer. | Actively used, one scheduled job only. |
| `frontend` | Next.js 14.2.15 | Web UI. | Actively used. |

A second compose file, `docker-compose.prod.yml`, is layered on top of `docker-compose.yml` for production use (this is what the Windows installer runs): it strips the development bind-mounts and switches the `backend`/`frontend` containers to their production start commands rather than dev/hot-reload ones.

**Neo4j and OpenSearch, specifically:** both are real, running containers in every deployment of this stack, and both have a corresponding settings field in the backend config (`neo4j_uri`/`neo4j_user`/`neo4j_password`, `opensearch_url`). Neither is wired into any actual code path. The correlation graph that the product presents to users lives entirely in Postgres's `correlation_edges` table today. Any description of a "Neo4j-backed graph" or "OpenSearch-backed search" elsewhere should be read as an architecturally-provisioned but not-yet-integrated capability, not a working feature.

## Backend

The backend is a **FastAPI** application (`backend/app/main.py`) running on **Python 3.12**. Its notable stack choices:

- **SQLAlchemy 2.0**, async, with `asyncpg` as the Postgres driver.
- **Alembic** for schema migrations (`backend/alembic/`).
- **Celery 5.4** for the one background job described below.
- **structlog** and **prometheus-fastapi-instrumentator** for logging and metrics.

The backend is also where the 16 third-party data-source connectors ("providers"), the AI summarization/correlation logic, and the authentication/RBAC (role-based access control) system live — each of those is detailed in its own section of this document.

## Frontend

The frontend is a **Next.js 14.2.15** application using **React 18.3.1** and **TypeScript**, styled with **Tailwind**, with **Zustand** for client-side state, **Recharts** for charts, **react-force-graph-2d** for the relationship/correlation graph visualization, and **Radix UI** for primitive UI components (all per `frontend/package.json`).

`package.json` declares `vitest` as the test runner (`"test": "vitest run"`), but a repository-wide search found zero `*.test.*`/`*.spec.*` files under `frontend/` — the tooling is configured but no frontend automated tests currently exist. (See the Testing and Quality Assurance appendix for the full picture, including the backend's test suites.)

## Executive Dashboard and Deterministic Scoring Engine

A new **Executive Dashboard** (`GET /api/v1/dashboard/kpis`, backed by `app/core/dashboard.py::get_kpis()`) gives an at-a-glance operational view of the whole platform: real-time KPI tiles for active investigations, the count of critical/high-risk IOCs, open case count and open-critical case count (reported as two separate numbers, not collapsed into one), average threat score, provider health percentage, and AI analysis success rate. Every one of these is a live SQL aggregate computed against Postgres at request time — none is hardcoded, and none is cached client-side across page loads. A companion endpoint, `GET /api/v1/dashboard/executive-summary` (`app/ai/dashboard_summary.py`), layers an AI-generated 2–4 sentence narrative on top of the exact same KPI values, grounded exclusively in those numbers as given facts. If the AI backend is unreachable, or its structured response fails validation twice in a row, the endpoint falls back to a deterministic, template-generated sentence built directly from the same real KPI numbers — never an error message, and never fabricated data. This is disclosed to the user directly on the Dashboard itself: the Executive Summary card carries an "AI-generated" badge when the narrative came from the model, or a "Template fallback" badge when it didn't, so the source of the text is never ambiguous.

[FIGURE: dashboard-executive-overview.png | The Executive Dashboard shows real KPI tiles, an AI-generated (or template-fallback) executive summary, and a provider-health summary widget -- every number sourced live, never hardcoded.]

Underlying both the Dashboard's "average threat score" tile and every individual investigation's risk score is a new **deterministic (non-AI) scoring engine** (`app/scoring/engine.py`). Historically, `overall_risk_score`, `confidence_score`, `malicious_probability`, and the final verdict were 100% AI-generated in one call — prompt wording alone cannot reliably stop a model from overriding a number it was merely asked not to touch. The scoring engine instead computes all four values *before* any AI call runs, purely from already-fetched evidence: a cross-provider verdict-consensus component (weighted 65 of 100 points, with a corroboration multiplier so a single unconfirmed provider flag scores meaningfully lower than several providers agreeing) and a correlation-graph-evidence component (35 of 100 points, drawn from `app/correlation/engine.py`'s graph and given the same corroboration treatment to resist a single source flooding it with distinct, uncorroborated edges). The AI is then handed this already-decided score as a given fact and asked only to narrate a verdict/rationale consistent with it — it can never invent or override the number, and the platform's own final-assessment validation re-checks the AI's output against the deterministic result before persisting it. Every persisted assessment records `SCORING_ENGINE_VERSION`, the exact version of this weighting scheme that produced it, so any historical score can always be traced back to the logic that generated it.

## Celery: Scope and a Key Boundary

`celery_worker` and `celery_beat` both run the same task application, `app.workers.celery_app`. Exactly **one** scheduled task exists in the codebase: `run_osint_crawl`, triggered hourly by `celery_beat` (`backend/app/workers/celery_app.py`), which re-crawls OSINT (open-source intelligence) sources for IOCs that were looked up in the last 24 hours (`backend/app/workers/tasks.py`).

That is the entirety of what Celery does in this platform. **The main, user-facing IOC lookup pipeline — the synchronous, streamed lookup reachable at `POST /api/v1/lookup/stream` — does not go through Celery at all.** This is stated directly in a header comment in `celery_app.py`. A lookup request (provider fan-out, per-provider AI summarization, correlation, final AI assessment, and persistence) is handled entirely within the FastAPI backend process for the duration of that one HTTP connection, with results streamed to the browser as Server-Sent Events (SSE) as each step completes. Celery is reached only by the separate, unrelated hourly re-crawl job — never as part of answering a live lookup request.

## Deployment Paths

Two deployment paths are implemented and verified in the repository:

1. **Docker Compose** — `docker-compose.yml` (development) and `docker-compose.yml` + `docker-compose.prod.yml` (production). This is the path the Windows installer automates end-to-end (covered in the Windows Deployment / Installer section of this document).
2. **Kubernetes** — the `k8s/` directory contains a parallel, **Kustomize**-based Kubernetes deployment: StatefulSets for `postgres`, `neo4j`, and `opensearch`; Deployments for `backend`, `frontend`, and `celery`; and an Ingress resource. This is an alternative to the Docker Compose / Windows-installer path. Beyond its existence and the resource types listed above, further detail on this path (replica counts, resource limits, ingress rules, or how it is intended to be operated) is **Not confirmed** — it was not otherwise inspected as part of this documentation effort.

## Component Diagram

The diagram below reflects verified relationships only. Solid arrows are real, active data paths confirmed in code; dashed arrows into `neo4j` and `opensearch` represent the config fields and running containers that exist but have no consuming application code.

[FIGURE: tech-01-architecture-diagram-1.png | Diagram: Component Diagram]

Note what is *not* in this diagram: there is no edge from `backend` to `celery_worker`/`celery_beat` for the lookup pipeline, because none exists. The live IOC-lookup path is entirely `frontend <-> backend <-> postgres/redis`; the Celery containers are reached only by the independent, hourly-scheduled OSINT re-crawl job described above.
