# HORIZON GRID — Release Version Audit

**Update note (2026-08-24):** the application version has since moved to **0.3.0** — unlike every
prior update note below, this one is NOT a no-op for the subsystems this audit describes: v0.3.0 adds
a wholly new backend module (`backend/app/pentest/`), three new database tables plus a fourth added in
a follow-up migration, five new permission strings, and two new API route files. None of it modifies
anything this audit already covers (IOC investigation, AI/provider architecture, the existing Security
Assessment Toolkit, RBAC for the roles/permissions already listed below all remain exactly as audited).
For the new subsystem itself, see `docs/PENTEST_SUITE.md`, `documentation/DOCUMENTATION_SOURCE/
backend-10-pentest-suite.md`, and the Security documentation's new §13 -- not duplicated here, since
this file's own scope is a point-in-time audit of the codebase as it stood before that work began.

**Update note (2026-08-23):** the application version has since moved to **0.2.5** (two frontend-only
Security Assessment UI fixes -- see `CHANGELOG.md`'s `[0.2.5]` entry; no backend/database/auth/IOC/AI/
provider/scanner logic changed). Everything else in this audit document below remains accurate, since
none of the subsystems it describes were touched by either the v0.2.5 fixes or the v0.2.4 branding
pass -- only the version string itself and the four files listed in "Application version" below moved
from 0.2.4 to 0.2.5.

**Update note (2026-08-21):** the application version has since moved to **0.2.4** (a presentation-
only branding/UI pass -- see `CHANGELOG.md`'s `[0.2.4]` entry; no backend/database/auth/IOC/AI/
provider/scanner logic changed). Everything else in this audit document below was captured against
v0.2.3 and remains accurate for every subsystem it describes, since none of them were touched by the
v0.2.4 branding pass -- only the version string itself and the four files listed in "Application
version" below moved from 0.2.3 to 0.2.4.

Audited directly against the current working tree (not against prior documentation, prior CHANGELOG, or prior claims). Every entry below is backed by a file:line citation from a real source-code read performed during this audit.

## Version identity

| Field | Value |
|---|---|
| Application version | 0.2.3 (`backend/app/main.py:59` `_APP_VERSION`; `windows/installer.iss:19` `MyAppVersion`; `linux/debian/control:2` `Version`; `frontend/package.json:3` — **note:** the frontend's version string was set in the same commit that bumped the others, but 2 further commits have landed since with no corresponding version bump; treat 0.2.3 as "the release this audit covers," not "guaranteed to match every file's own version string forever") |
| Git branch | `main` |
| Git commit (HEAD at time of audit) | `f2b61f9d19cebed02ebd83b9d353107721619256` |
| Total commits in repository history | 23 |
| Commits ahead of `origin/main` (unpushed at time of audit) | 9 |
| Frontend framework | Next.js 14.2.15, React 18.3.1, TypeScript 5.6.2, Tailwind 3.4.12 (`frontend/package.json`) |
| Backend framework | FastAPI, SQLAlchemy 2.0.35 (async, `sqlalchemy[asyncio]==2.0.35`), asyncpg 0.30.0, Alembic 1.13.2 (`backend/requirements.txt`) |
| Database | PostgreSQL 16 (`postgres:16-alpine`, `docker-compose.yml`) |
| Database schema version | 10 linear Alembic migrations, single head, no branching (see Database section) |
| Windows installer | Inno Setup, `HORIZON-GRID-Setup-0.2.3.exe` |
| Linux package | `.deb`, `horizon-grid_0.2.3_amd64.deb` |
| AI subsystem | 11 real backend clients (see AI Providers section) |
| IOC subsystem | 18 registered providers (see IOC Providers section) |
| Scanner subsystem | Security Assessment Toolkit (nmap-based); full detail pending retry (see note at end) |

## What changed from the previous version (v0.2.2 → v0.2.3)

9 commits, all landed 2026-08-20, all real code/doc changes (no empty or reverted commits):

1. `5491332` — mission-critical reliability hardening (restart policies, `/health/detailed`, boot auto-start, watchdog, backups)
2. `057404e` — real database restore scripts, persistent Redis, customized-port health-check fix
3. `20fc3cc` — AI-outcome badge fix, request-body/field size limits
4. `5052813` — Swagger/OpenAPI gated behind `ENVIRONMENT=production`
5. `6aaffb8` — Mission-Critical Operations Manual added, stale Operations Guide claims corrected
6. `997f6b8` — version bump to 0.2.3
7. `2702ca0` — mission-critical certification report added
8. `d7f13ae` — RelationshipGraph list-view crash fixed
9. `f2b61f9` — certification report corrected with final soak-test results

Full detail on each is in `documentation/DOCUMENTATION_SOURCE/standalone-changelog.md`'s new v0.2.3 entry and `MISSION_CRITICAL_CERTIFICATION_REPORT.md`.

## Frontend

A real, mature Next.js 14 App Router application — 12 pages, 27 dashboard components, 5 UI primitives, one hand-written API client (`frontend/lib/api.ts`).

**Verified real and working:** Executive Dashboard (7 KPI tiles + AI-or-template-fallback narrative + provider-health widget, all from real API calls); SSE streaming via `fetch()`+`ReadableStream` (not `EventSource`, specifically because `EventSource` can't send an `Authorization` header) with transparent 401-refresh-and-retry; the Relationship Graph (force-directed + accessible list-view fallback, its data-mutation crash fixed this release); AI provider runtime-switching across all 11 backends with no restart; an AI-backend-comparison feature (re-run the same evidence against a different backend); an Investigation Copilot (evidence-scoped Q&A chat); the Security Assessment panel (typed target confirmation + explicit authorization checkbox required before a scan can start, live cancellation); case management; the IOC Basket (multi-select investigate-all, cross-IOC AI comparison); an Admin console (client-side role gate is explicitly documented as UX-only, server enforces the real boundary); export (client-side Markdown/JSON, server-side PDF/CSV with graceful 404 degradation); a Provider Health page rendering `null` success-rate/latency as "N/A", never a fabricated "0%".

**Real gaps found by this audit:**
- **No frontend test infrastructure exists at all.** `vitest` is wired into `package.json`'s `test` script and installed in `node_modules`, but zero `*.test.ts(x)`/`*.spec.ts(x)` files and no `vitest.config.*` exist anywhere in the tree. Running `npm test` finds nothing to run.
- **Three declared npm dependencies are dead code**, confirmed by zero source imports anywhere: `zustand` (state management is 100% local `useState`/`useEffect`/prop-drilling, no store), `recharts` (the threat-score gauge deliberately uses raw SVG instead, per its own code comment), `@radix-ui/react-progress`.
- **Two stale code comments actively mislead a reader**: `app/lookup/new/page.tsx` and `app/lookup/[id]/page.tsx` both still carry header comments describing the page as rendering "placeholder `<div>`s" pending real components — the real components (15+ of them) have been implemented for some time. Corrected as part of this release's documentation pass (see Known Issues).
- `GET /api/v1/dashboard/executive-summary` is called out in the frontend's own code comment as possibly not existing in every deployed environment (404) — it has a graceful fallback, but its availability is not guaranteed everywhere.

## Backend core, database, and datastores

**Database (PostgreSQL 16, async SQLAlchemy):** 16 real tables across 8 model files — `users`, `ioc_lookups`, `provider_results`, `ai_summaries`, `correlation_edges`, `final_assessment_records`, `evidence_items`, `basket_items`, `cases`, `case_iocs`, `case_notes`, `case_reports`, `provider_runtime_configs`, `config_audit_log`, `security_assessment_runs`, `security_assessment_findings`. 10 linear Alembic migrations, single head chain, no branching — including a documented Postgres enum-casing gotcha (`sa.Enum` sends the Python enum member's `.name`, uppercase, not `.value`).

**Neo4j and OpenSearch are provisioned in `docker-compose.yml` but have zero real client code anywhere in the backend application** — confirmed via exhaustive grep for driver imports, client construction, and query calls; the only hits are unused `Settings` fields and two docstring comments describing Neo4j persistence as a future aspiration, not implemented behavior. This independently re-confirms a finding from the mission-critical hardening review: both services are a real, ongoing resource cost (~1.5–2 GB RAM reserved) with zero current application benefit.

## Authentication and RBAC

JWT (HS256) access (30 min default) + refresh (7 days default) tokens, bcrypt password hashing, a `token_version` column giving immediate server-side revocation on password reset (a stale refresh token cannot keep minting new access tokens after a reset). Three roles — **Admin** (18 permissions), **Analyst** (15 — everything Admin has except `provider:manage`, `user:manage`, `audit:read`), **Viewer** (5, read-only) — enforced server-side via a dependency that re-reads role/`is_active` from the database on every request, not just at login.

**Multiple administrators are genuinely, race-safely supported**: no uniqueness constraint on the Admin role, and both demoting the last Admin and disabling the last active Admin are blocked via `SELECT ... FOR UPDATE` row-locking (closes a real concurrency race, not just a check-then-act pattern that could still race). An admin cannot change their own role even if other admins exist. Self-registration is open only for the very first user (who becomes Admin); every subsequent registration attempt is rejected with 403. Login brute-force protection is a Redis-backed fixed-window limiter (10 attempts/60s default) keyed on the *attempted* email, not source IP — a deliberate, disclosed tradeoff, since there is no trusted-IP-extraction configuration to safely key on instead.

**No hard user-delete route exists** — disabling (`is_active=false`) is the only removal mechanism, by design (case/basket foreign keys to `users.id` are `NOT NULL`).

## IOC intelligence providers

**Exactly 18 registered providers**, confirmed against `backend/app/providers/registry.py`'s definitive list — 13 live directly under `providers/`, 4 under `providers/stubs/` (a misleading directory name: all 4 — Censys, Hybrid Analysis, PhishTank, Spamhaus — are fully real, working connectors, not placeholders), and 1 (the Internet Intelligence Collector, an OSINT crawler) registered from `app/crawler/collector.py`.

By category: Threat Intel (10) — VirusTotal, AbuseIPDB, AlienVault OTX, URLhaus, ThreatFox, MalwareBazaar, MITRE ATT&CK, Google Safe Browsing, PhishTank, Spamhaus. Sandbox (2) — urlscan.io, Hybrid Analysis. Certificate Intel (1) — crt.sh. WHOIS (1) — WHOIS/RDAP. Vulnerability (2) — NVD, CISA KEV. Passive DNS (1) — Censys. OSINT (1) — Internet Intelligence Collector.

10 require an API key (VirusTotal, AbuseIPDB, OTX, URLhaus, ThreatFox, MalwareBazaar, urlscan.io, Google Safe Browsing, Hybrid Analysis, Censys); 8 do not (crt.sh, NVD, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Spamhaus, PhishTank, Internet Intelligence Collector).

The orchestrator (`app/providers/orchestrator.py`) fans out one `asyncio` task per applicable provider, retries only `httpx.ConnectError`/`ReadTimeout`/`PoolTimeout` via `tenacity` (this release fixed a real bug where this retry path was dead code for most providers — see the v0.2.3 changelog entry), and caches `OK` results in Redis (default: 20s timeout, 2 retries, 3600s cache TTL). Provider credentials and enabled-state are runtime-configurable via a DB-backed table, snapshotted once per investigation into a `ContextVar` so every concurrent provider call in one investigation sees a consistent view even if configuration changes mid-investigation.

## AI abstraction layer

**Exactly 11 AI backend clients, all real** (confirmed: no stub files, no backend named only in a comment): Ollama (local, no API key), Anthropic, AWS Bedrock, Google Gemini, Groq, OpenAI, Kimi (Moonshot AI), DeepSeek, xAI (Grok), Mistral AI, OpenRouter. Every one has a real async HTTP call implementation (or, for Bedrock, a real `boto3` `converse()` call), forced structured tool-calling, and real error handling — not a placeholder.

The active backend is switchable platform-wide with **no restart**: the active-backend row is read fresh from the database on every single AI call, and a fresh client is constructed per call.

**Risk scoring is deterministic, not AI-generated.** `app/scoring/engine.py::score_investigation()` computes `overall_risk_score`/`confidence_score`/`malicious_probability`/`severity` from provider-verdict votes and correlation-edge confidence, with zero AI or network calls, *before* the AI is ever invoked. The AI is given this score as a stated fact in its prompt; the backend then mechanically overwrites the AI's own emitted risk numbers with the deterministic ones and re-validates the full assessment against them (a real Pydantic validator, not just a prompt instruction) before persisting — an AI model cannot override the number even if it tries to.

**AI outcome tracking** (`ai_outcome`) is set at exactly 3 return sites in `generate_final_assessment()`: `skipped_no_evidence` (a correct decision, AI never called — no provider data existed), `success`, and `failed` (a genuine generation failure, with a deterministic-score-based fallback narrative, never fabricated). This release fixed a real bug where the frontend rendered `failed` and `skipped_no_evidence` with the identical badge.

**The SSRF guard is confirmed wired into exactly 4 real call sites**, including the actual production Ollama-call construction path (`OllamaClient.__init__`) and the config-save path (`upsert_ai_provider`) — the fix made during this session's mission-critical review, independently re-confirmed by this audit.

## Executive dashboard and Provider Health

7 real KPIs (`app/core/dashboard.py::get_kpis()`), all genuine SQL aggregations over `IOCLookup`/`Case`/`ProviderResultRecord`/`FinalAssessmentRecord` — no hardcoded or mocked values: active investigations, critical/high-risk IOC count (30-day window), open cases, open critical cases, average threat score, provider health percentage (24h window, excludes `not_configured`/disabled providers), AI success rate (excludes `skipped_no_evidence`, returns `None` rather than `0` when there's no data to compute from).

Provider Health is genuinely historical, not live-only: 4 rolling windows (1h/24h/7d/30d) per provider, each with status/success-rate/average-latency/consecutive-failure-streak/rate-limited-count, computed via one batched conditional-aggregation SQL query plus a bounded (500-row) per-provider walk for the consecutive-failure streak.

## Installation and deployment

**Windows**: Inno Setup installer, 7-page WinForms wizard (Welcome → Administrator Account → AI Configuration → Threat Intelligence Providers → Network Ports → Ready to Install/Summary → Setup Complete/Finish — note: the wizard file's own header docstring describes a 9-stage flow including separate "Install/Start" and "Health Check" stages; those run inside the Summary page's own button handler, not as separate wizard pages — a documentation/implementation mismatch corrected as part of this release's doc pass). 12 Start Menu/desktop shortcuts. 3 SYSTEM-level Scheduled Tasks (boot startup, 5-minute watchdog, 02:00 daily backup). Both backup and restore scripts exist; restore requires typing the literal string `RESTORE` unless `-Force` is passed. The prerequisite check is an **overridable warning** at install time (a Yes/No dialog lets an operator proceed past a failed check), not a hard block — this is a real, disclosed difference from the Linux installer's behavior (see below).

**Linux**: `.deb` package, a single `horizon-grid` CLI with 13 subcommands (`configure`, `start`, `stop`, `restart`, `status`, `open`, `backup`, `restore`, `diagnostics`, `watchdog`, `check`, `uninstall`, `version`), a 6-page terminal wizard mirroring the Windows flow, 5 systemd units (main service + watchdog service/timer + backup service/timer, schedules matching Windows exactly), and — unlike Windows — **the prerequisite check is a genuine hard blocking gate**: `run_prerequisite_checks()` is called before any configuration directory is even created, and calls `sys.exit(1)` on any hard-check failure. `systemctl enable horizon-grid.service` (the real fix for the "service never survives a reboot" bug found during this review) is confirmed present and called from the install flow, alongside enabling both timers with `--now`.

## Configuration, secrets, and health monitoring

Settings load via `pydantic-settings` from `.env`. Runtime-configured provider/AI credentials are encrypted at rest with Fernet (AES-128-CBC+HMAC), keyed by an explicit `encryption_master_key` or an HKDF-SHA256 key derived from `jwt_secret_key` if that's unset — the code's own docstring honestly flags this fallback as "defense-in-depth, not HSM-grade key separation" (if `encryption_master_key` is never set, compromising `jwt_secret_key` also yields the credential-encryption key). The audit log only ever stores actor/action/human-readable-detail strings — confirmed no call site interpolates a raw secret — but this is enforced by code-review discipline at each call site, not a runtime scrubber inside the audit function itself. Windows and Linux diagnostics bundles both redact `.env` to `NAME=***REDACTED***(set, N chars)` and run a second, shape-based regex pass over collected logs (Bearer tokens, `sk-*` keys, AWS key IDs, JWT triples, etc.) — a mitigation, not an ironclad guarantee, against a secret appearing in an application log with no recognizable shape.

`/health` (dependency-free liveness) and `/health/detailed` (real Postgres+Redis check, 503 if Postgres is down) are both confirmed exactly as designed. A 10 MB request-body-size limit and per-field `max_length` constraints (IOC value 2048, case description 20000, case note body 10000, passwords 72 — bcrypt's real limit) are new this release. Swagger/ReDoc/OpenAPI are gated off when `ENVIRONMENT=production`, which is set **only** by `docker-compose.prod.yml` — a real, worth-disclosing operational detail: an operator who runs plain `docker compose -f docker-compose.yml up` (skipping the `.prod.yml` override) gets `development` mode and exposed docs even if they intend a production-like run. This is a deliberate tradeoff (documented in `main.py`'s own comments), not a bug, but is exactly the kind of thing that belongs in operator-facing documentation rather than left implicit.

## Backend core architecture

FastAPI 0.115.0, uvicorn 0.30.6, pydantic 2.9.2, pydantic-settings 2.5.2 (`backend/requirements.txt`). 13 API route modules registered (`admin`, `ai_config`, `analysis`, `auth`, `basket`, `cases`, `dashboard`, `hunting`, `lookup`, `pivot`, `providers`, `runtime`, `security_assessment`) — every route module present on disk is registered, none orphaned. Middleware stack: CORS restricted to a private-network-only regex (RFC1918/loopback/`localhost`, HTTP only — this app terminates no TLS of its own), a request-ID context-var middleware (every log line, including uvicorn's own access log, carries a correlating `X-Request-Id`), and the request-body-size-limit middleware added this release.

**Two real, minor code-quality notes surfaced by this audit, not affecting correctness:** `structlog` is configured at startup but has zero real call sites anywhere in application code (stdlib `logging` is what's actually used, in ~30 files) — dead configuration, pre-existing, not introduced this release. Three startup handlers use FastAPI's deprecated `@app.on_event("startup")` decorator rather than the current `lifespan` context-manager pattern — functionally fine under the pinned FastAPI version, but the officially deprecated style.

## Security Assessment Toolkit (port scanning)

**Five real tools, not one** — this is a correction to prior documentation, which described this module primarily around Nmap: `nmap_tool.py` (port/service scanning, 3 profiles — quick/standard/web, exact argv confirmed hardcoded per profile with no shell and no NSE/`-O`/`-sS`/`-sU`/evasion flags), `dns_tool.py`, `tls_tool.py`, `http_headers_tool.py`, and `hash_tool.py` (each with exactly one "standard" profile). All five are registered separately from the auto-run IOC-provider orchestrator and never fan out automatically — they only run when explicitly requested and authorized.

Authorization requires the operator to retype the exact target string plus check an explicit authorization box, enforced server-side (`_validate_scope()`), not just in the UI. Concurrency is capped at 4 simultaneous tool executions (`_MAX_CONCURRENT_SCANS`, a semaphore around the execution phase only — queuing/acceptance is unbounded, only real subprocess execution is capped). CIDR targets are capped at 16 addresses (a /28). Cancellation genuinely kills the underlying OS subprocess (confirmed: `proc.kill()` + `proc.wait()` inside the `CancelledError` handler), not just the asyncio `Task` wrapping it.

**One disclosed, by-design network-security nuance found by this audit**: the TLS tool disables certificate verification for its primary handshake (deliberately, so it can inspect self-signed/expired certificates as findings in their own right), performing a second, strict handshake separately to compute real trust status. Documented in the tool's own docstring; not a defect, but worth stating plainly in security documentation rather than leaving implicit.

## Export and reporting

**Only PDF and CSV are server-rendered** (`POST /lookup/{id}/export?format=pdf|csv`), gated by the `lookup:export` permission (Admin and Analyst hold it; Viewer does not) — a deliberately stricter gate than the `lookup:read` permission used by the read endpoints. **Markdown and JSON "exports" are built entirely client-side** in the frontend from data already loaded into the browser (no backend export endpoint exists for either format) — this means they are not gated by `lookup:export` specifically, though this is not a real privilege escalation: anyone who can view a lookup at all (i.e., holds `lookup:read`, which every role including Viewer has) already has that same data in their browser regardless.

Both previously-fixed export security issues remain fixed in the current code: CSV formula-injection neutralization (a leading `=`/`+`/`-`/`@` gets a neutralizing leading apostrophe) and PDF XML/markup escaping (every interpolated IOC-value/AI-generated field is XML-escaped before reaching ReportLab's `Paragraph()`). Both are covered by `backend/app/tests/unit/test_lookup_export.py`'s 11 tests, confirmed passing live during this audit.

## Testing and CI/CD

**Backend**: 29 unit test files (303 `def test_` occurrences) + 13 integration test files (86 `def test_` occurrences) by static count. The authoritative, actually-*executed* numbers from this session's own live test runs: **335 tests pass standalone with no infrastructure** (`python -m pytest app/tests/unit`), and **380 pass + 39 skip** in the full suite run inside the backend container with real Postgres/Redis (`python -m pytest app/tests`) — the 39 skips are intentional (host-only/environment-gated tests, not failures; 6 specific integration files are documented as `skipif`-guarded on a host-published-port pattern that doesn't apply inside the container). The static grep count (389) and the live pytest count differ because of test parametrization (one `def test_` can expand to several actual test cases) — the live pytest number is the one that matters operationally.

**Frontend**: `vitest` is wired into `package.json`'s `test` script and installed as a dependency, but zero test files exist anywhere in the tree — confirmed independently by two separate audit passes. `frontend-build.yml`'s own comment explicitly acknowledges this: "zero `*.test.ts(x)`/`*.spec.ts(x)` files exist... `npm test` today would just fail/error with 'No test files found'."

**CI**: 3 GitHub Actions workflows. `backend-tests.yml` — a bare-runner `unit` job (`pytest app/tests/unit` + the one dependency-free integration test) plus a `integration-docker` job (builds the full Compose stack, waits for health, runs the real integration suite inside the container). `dependency-audit.yml` — weekly (`0 3 * * 1`) `pip-audit`/`npm audit`, both `continue-on-error: true` (informational, not a merge gate). `frontend-build.yml` — lint + build only, triggered on push/PR to `frontend/**`; it does **not** run `npm test` — consistent with there being nothing to test.
