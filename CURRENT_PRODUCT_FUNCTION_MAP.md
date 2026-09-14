# Current Product Function Map

Inventory of every capability in Horizon Grid v0.3.13, taken before the Omega rebuild, so nothing silently disappears. Compiled from a full read-only pass over `frontend/` and `backend/`.

## Auth & RBAC
- **UI:** `/login`, `/register`, `/about` (session/health info)
- **API:** `POST /auth/register` (bootstrap-only first admin), `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`, `POST /auth/logout`
- **Backend:** `app/api/routes/auth.py`, `app/auth/rbac.py` (JWT bearer + `require_permission()`)
- **DB:** `User` (email, hashed_password, role enum ADMIN/ANALYST/VIEWER, is_active, token_version)
- **Behavior:** JWT access+refresh in localStorage; `authedFetch()` auto-refreshes on 401, hard-redirects to `/login?sessionExpired=1` on unrecoverable failure. Role enforcement is server-side; client-side role checks are UX-only.
- **Status:** working, load-bearing. Do not weaken.

## Admin
- **UI:** `/admin`
- **API:** `GET/POST /admin/users`, `GET /admin/users/stats`, `GET /admin/roles`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/active`, `POST /admin/users/{id}/reset-password`
- **Backend:** `app/api/routes/admin.py`, `app/core/users.py`
- **Status:** working.

## IOC Investigation (primary analyst workspace)
- **UI:** `/lookup/new?value=` (live, SSE), `/lookup/[id]` (static replay, same components)
- **API:** `POST /lookup/stream` (SSE), `GET /lookup/{id}`, `GET /lookup`, `POST /lookup/{id}/reanalyze`, `GET /lookup/{id}/assessments`, `POST /lookup/{id}/export`
- **Backend:** `app/api/routes/lookup.py` -> `app/providers/orchestrator.py` -> `app/correlation/engine.py` -> `app/scoring/engine.py` -> `app/ai/service.py` -> `app/evidence/builder.py`
- **DB:** `IOCLookup`, `ProviderResultRecord`, `AISummaryRecord`, `CorrelationEdgeRecord`, `FinalAssessmentRecord`, `EvidenceItem`
- **Dependencies:** 18 provider integrations, 11 AI backends, deterministic scoring engine
- **Expected behavior:** concurrent provider fan-out (unbounded by count, bounded by shared HTTP connection pool), per-provider result persisted+streamed immediately, AI summary/final-assessment overlaid after, deterministic score never overridden by AI narrative, one provider/AI failure never breaks the investigation, orphaned RUNNING rows recovered on process boot.
- **Analyst-assist sub-features (all via `POST /lookup/{id}/analysis/*`):** explain-why-malicious, explain-what-is-this, explain-disagreement, false-positive check, challenge-verdict, next-actions, intelligence-gaps, score-explanation, copilot Q&A, hunting-center, pivot suggestions, detection-rule generation (Sigma/SPL/KQL), AI-backend comparison.
- **Status:** working, mature, well-tested (multiple real bugs found+fixed per CHANGELOG). Visual layer is the weakest part (`ProviderCard.tsx` explicitly generic) -- rebuild target.

## IOC classification
- **Backend:** `app/ioc/detector.py`, `app/ioc/types.py` (30 IOC types)
- **Status:** working.

## Threat-Intel Providers
- **UI:** `/providers` (IOC Providers tab), `/dashboard/provider-health`
- **API:** `GET /providers/health`, `POST /providers/{id}/test`, `GET/POST /runtime/ioc-providers`, `POST /runtime/ioc-providers/{id}/enabled`
- **Backend:** `app/providers/registry.py` (18 providers), `app/providers/base.py`, `app/providers/orchestrator.py`, `app/core/runtime_config.py`
- **Providers:** virustotal, abuseipdb, otx, urlhaus, threatfox, malwarebazaar, crtsh, nvd, cisa_kev, mitre_attack, whois_rdap, urlscan_io, google_safe_browsing, hybrid_analysis, spamhaus, phishtank, censys, internet_intelligence_provider (OSINT crawler)
- **Status:** all real integrations, no fakes. Load-bearing -- "don't rewrite casually."

## AI Engine
- **UI:** AI switching lives inside `/providers` (AI Providers tab), quick-switch on `/` for admins
- **API:** `POST /ai/test`, `POST /ai/{backend}/models`, `GET/POST /runtime/ai-providers`, `GET/POST /runtime/ai-active`
- **Backend:** `app/ai/service.py` (11 backend clients), `app/ai/analysis_service.py` (prompting)
- **Backends:** ollama (default/local), anthropic, bedrock, gemini, groq, openai, kimi, deepseek, xai, mistral, openrouter
- **Status:** all real, live-verified. Switching takes effect on next call, no restart. Local AI (Ollama) is genuinely first-class already (context-window fix, tuned timeouts, Docker networking handled).

## Executive Dashboard
- **UI:** `/dashboard`
- **API:** `GET /dashboard/kpis`, `GET /dashboard/executive-summary`, `GET /providers/health`
- **Backend:** `app/core/dashboard.py` (pure aggregation, real SQL, nothing stubbed), `app/ai/dashboard_summary.py` (AI narrative + deterministic template fallback)
- **Status:** working, all-real data, but visually thin -- 7 KPI tiles + 2 cards, zero timeseries/activity feed/live ticking data beyond a 60s health poll. Primary rebuild target.

## Basket & Cases
- **UI:** `/basket`, `/cases`, `/cases/[id]`
- **API:** basket CRUD + `POST /basket/compare`, case CRUD + notes/reports
- **DB:** `BasketItem`, `Case`, `CaseIOC`, `CaseNote`, `CaseReport`
- **Status:** working.

## Security Assessment Toolkit (per-investigation)
- **API:** `GET /security-assessment/profiles`, `/tool-health`, `POST /{lookup_id}/run`, `POST /runs/{id}/cancel`, `GET /{lookup_id}/runs`, `GET /runs/{id}`
- **Backend:** `app/security_assessment/*` (nmap/DNS/TLS/HTTP-headers/hash/vuln-intel tools), `app/core/security_assessment.py`
- **DB:** `SecurityAssessmentRun`, `Finding`
- **Status:** real, working, structurally injection-safe. Explicit scope confirmation required. Never auto-run.

## Pentest Suite (standalone)
- **UI:** `/pentest`, `/pentest/[id]`
- **API:** assessment CRUD/lifecycle, kill switch, exploit execution (gated)
- **Backend:** `app/pentest/orchestrator.py`, `exploit.py`, `msf_client.py`, `ai_analyst.py`
- **DB:** `PentestAssessment`, `Target`, `Finding`, `ExploitAttempt`, `GlobalKillSwitch`
- **Status:** real, working. Metasploit integration is genuine (msgpack-RPC), gated behind 5 independent checks + a dedicated permission. Kill switch synced across replicas.

## System health / observability
- **API:** `GET /health`, `GET /health/detailed`, `GET /network-info`, `GET /metrics` (Prometheus)
- **Status:** working.

## Background jobs
- **Backend:** Celery (`app/workers/`), one scheduled task (`run_osint_crawl`, hourly)
- **Status:** working.

## Deployment
- Docker Compose (dev + `docker-compose.prod.yml`), Windows installer (`windows/`), Linux `.deb` (`linux/`), Kubernetes manifests (`k8s/`)
- **Status:** not re-verified as part of this map; flagged for the fresh-install pass later in the rebuild.

---

**Nothing in this list is scheduled for removal.** The Omega rebuild's chosen deep-dive slice (see final report) touches only: the Executive Dashboard's visual/data-density layer, the IOC Investigation workspace's visual layer (`ProviderCard` + page composition), and the Relationship Graph's rendering technology (2D canvas -> 3D). All backend business logic, all other pages, and all data models are left untouched.
