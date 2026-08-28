# Testing and the Build Pipeline

This chapter documents three independent, non-overlapping pieces of tooling a maintainer needs to know: the backend's **pytest** suite (what exists, how it mocks the outside world, and the exact gotchas you will hit running it locally on this machine), the **Docker Compose / Windows Inno Setup** pipeline that turns the source tree into a running stack or an installable `.exe`, and the **documentation build pipeline** under `documentation/build/` that renders the very manual this chapter belongs to. There is no CI system anywhere in the repository -- no `.github/workflows/`, no `Makefile`, no other automation entry point was found -- so every command below is something a developer runs by hand.

## 📋 Table of contents

- [1. Backend Test Suite Layout](#1--backend-test-suite-layout)
  - [1.1 Unit tests](#11-unit-tests-backendapptestsunit)
  - [1.2 Integration tests](#12-integration-tests-backendapptestsintegration)
- [2. Mocking and Fixture Conventions](#2--mocking-and-fixture-conventions)
- [3. Running the Backend Tests](#3--running-the-backend-tests)
  - [3.1 A local virtualenv, and a still-live pytest-discovery gotcha](#31-a-local-virtualenv-and-a-still-live-pytest-discovery-gotcha)
- [4. Frontend Tests](#4--frontend-tests)
- [5. Docker Compose Build Pipeline](#5--docker-compose-build-pipeline)
- [6. Windows Installer Build](#6--windows-installer-build)
- [7. Documentation Build Pipeline](#7--documentation-build-pipeline-documentationbuild)
- [Summary](#-summary)

---

## 1. 🧪 Backend Test Suite Layout

Tests live under `backend/app/tests/`, split into `unit/` and `integration/`, each a real Python package (`__init__.py` present). **There is no `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, or `conftest.py` anywhere in the repository** -- confirmed by a direct search of the tree. Pytest therefore runs with bare default discovery: no custom markers, no `asyncio_mode=auto` (every async test is decorated explicitly with `@pytest.mark.asyncio`, pytest-asyncio's strict-mode requirement), and no coverage gate, even though `pytest-cov` is a pinned dependency (`requirements.txt:29`) -- it is never invoked with `--cov` anywhere in the source, so coverage measurement is available but unused.

| Layer | Location | Files |
|---|---|---|
| Unit | `backend/app/tests/unit/` | 33 |
| Integration | `backend/app/tests/integration/` | 15 |

The suite has grown considerably past its original size as the Security Assessment Toolkit, Pentest Suite, scoring engine, admin console, and executive dashboard were added, each with their own dedicated test files. Per the current README, the unit layer alone (335 test functions) needs no infrastructure at all and passes standalone; the full suite (unit + integration together) is 380 passed, 39 skipped -- the skips being intentional, environment-gated tests (see §1.2), not failures.

### 1.1 Unit tests (`backend/app/tests/unit/`)

No database, Redis, Docker, or network access is required for any file in this directory.

| File | What it exercises |
|---|---|
| `test_abusech.py` | `app.providers.abusech.map_query_status` -- the shared abuse.ch `query_status` mapping used by URLhaus/ThreatFox/MalwareBazaar |
| `test_ai_connection_test.py` | `app.ai.connection_test.test_ai_connection` for all 11 AI backends against **respx**-mocked HTTP: success, invalid-key/401, rate-limit/429, model-not-found/404, timeout, network error, plus backend-specific cases (Kimi's thinking-mode conflict, DeepSeek's 402, xAI's flat error body) (53 test functions) |
| `test_ai_schemas.py` | `app.ai.schemas.MitreMapping`'s enum/regex-free `technique_id` field and `FinalAssessment`'s grounding validator |
| `test_ai_service.py` | `app.ai.service.generate_final_assessment`'s no-real-evidence short-circuit -- the fix for a fabricated `highly_malicious` verdict against the EICAR hash with zero provider evidence |
| `test_analysis_service.py` | `app.ai.analysis_service._strip_invalid_evidence_ids`, the guard that drops any AI-cited `evidence_id` not present in the real evidence set |
| `test_connection_test.py` | `app.providers.connection_test.test_provider_connection` for the keyed real providers, against **respx**-mocked HTTP |
| `test_correlation_engine.py` | `app.correlation.engine.correlate` -- edge dedup/merge and provider-agreement bucketing from fake `ProviderResult` envelopes, no I/O |
| `test_crawler_collector.py` | `InternetIntelligenceCollector.fetch` -- distinguishing a rate-limited OSINT source from a genuinely empty result |
| `test_crawler_rate_limit.py` | `app.crawler.sources.rate_limit.AsyncMinIntervalLimiter` timing behavior |
| `test_crypto.py` | `app.core.crypto.encrypt_secret`/`decrypt_secret`/`mask_secret` (Fernet round-trip, invalid-token handling, masking) |
| `test_evidence_builder.py` | `app.evidence.builder` -- the deterministic, non-AI evidence-ledger extraction every later AI explanation must cite |
| `test_ioc_detector.py` | `app.ioc.detector.detect_ioc_type` across many IOC string patterns |
| `test_pivot.py` | `app.evidence.pivot.rank_pivots` -- pure ranking logic behind `GET /lookup/{id}/pivots` |
| `test_provider_base.py` | `app.providers.base.BaseProvider` contract: unsupported IOC types, missing credentials, error normalization |
| `test_runtime_context.py` | `app.core.runtime_context`'s per-investigation `ContextVar` snapshot/override mechanics |
| `test_whois_rdap.py` | The WHOIS half of `app.providers.whois_rdap.WhoisRdapProvider`, including socket-failure vs. genuine-no-record handling |

Seventeen further unit test files were added as the platform grew past its original provider/AI/evidence core:

| File | What it exercises |
|---|---|
| `test_ai_config_ollama_models.py` | `parse_ollama_tags_response` -- Ollama's live model-discovery response parsing behind `GET /api/v1/ai/ollama/models` |
| `test_ai_service_ollama_ssrf.py` | Regression coverage for a real SSRF gap in the Ollama backend's outbound `base_url` -- the guard that rejects a non-allow-listed host |
| `test_dashboard_service.py` | `app.core.dashboard`'s DB-free helper functions behind the executive dashboard's KPI tiles |
| `test_dashboard_summary.py` | `app.ai.dashboard_summary.generate_executive_summary` and its template fallback when AI generation is unavailable |
| `test_google_safe_browsing.py` | `app.providers.google_safe_browsing`'s threat-match mapping |
| `test_lookup_export.py` | `app.api.routes.lookup`'s server-rendered PDF/CSV export formats |
| `test_msf_client.py` | `MsfRpcClient`'s bytes→str normalization (the Pentest Suite's Metasploit RPC client wrapper) |
| `test_orchestrator_retry.py` | Regression coverage for a dead-retry-code bug in the provider orchestrator's retry policy |
| `test_pentest_exploit.py` | The Pentest Suite's gated exploit-validation pure logic (module-name/fullname validation) |
| `test_pentest_orchestrator.py` | The Pentest Suite orchestrator's pure logic: scope enforcement and pipeline-stage transitions |
| `test_runtime_config.py` | `app.core.runtime_config`'s credential-merge logic |
| `test_scoring_engine.py` | `app.scoring.engine.score_investigation` -- the deterministic risk/confidence/severity scoring engine |
| `test_security_assessment_service.py` | `app.core.security_assessment`'s scope/authorization gate |
| `test_security_assessment_tools.py` | The Security Assessment Toolkit's individual tool adapters |
| `test_spamhaus_provider.py` | The Spamhaus DBL/ZEN connector's query-error handling |
| `test_urlscan_io.py` | `app.providers.urlscan_io`'s submit-then-poll flow |
| `test_users_service.py` | `app.core.users`'s last-admin-protection counting logic |

### 1.2 Integration tests (`backend/app/tests/integration/`)

| File | Covers | Infra required |
|---|---|---|
| `test_api_health.py` | `GET /health`, `GET /docs`, and that the full OpenAPI schema (every DB-backed router included) serializes at app-construction time | None |
| `test_lookup_flow.py` | `app.providers.orchestrator.run_all_providers` / `run_all_providers_collected` fan-out, registered against **fake `BaseProvider` subclasses** via the orchestrator's `providers=` override parameter -- the real provider registry is never imported | Redis (`localhost:6379`) |
| `test_lookup_stream_persistence.py` | Regression coverage for a bug where every lookup stayed `status=RUNNING` forever because the route's DB session was torn down before the lazy SSE generator ran | Postgres (`localhost:5433`) + Redis (`localhost:6379`) |

`test_lookup_flow.py` and `test_lookup_stream_persistence.py` each perform a live TCP reachability probe at import time and use `pytest.mark.skipif` to **skip the whole module** (not fail the run) when the required service isn't reachable -- so running the suite with no Docker services up still passes, it just silently exercises fewer files.

Twelve further integration test files cover the features added since, all against a real Postgres (several also against Redis):

| File | Covers |
|---|---|
| `test_admin_rbac_api.py` | Permission-matrix enforcement and privilege-escalation/IDOR attempts against the Administration console's `/api/v1/admin/*` routes, via real HTTP |
| `test_admin_users.py` | `app.core.users` -- the Administration console's service layer against a real database |
| `test_auth_login_rate_limit.py` | Login brute-force rate limiting on `POST /api/v1/auth/login` |
| `test_auth_registration.py` | The first-user-becomes-admin bootstrap rule and the `403` every registration after that gets |
| `test_dashboard_api.py` | The `dashboard:read` permission and the executive dashboard's HTTP routes against a real, seeded database |
| `test_dashboard_service_db.py` | `app.core.dashboard`'s two DB-aggregation query paths against real fixture rows |
| `test_deterministic_scoring.py` | The scoring engine's end-to-end wiring into the live lookup/reanalyze path |
| `test_lookup_export_permissions.py` | Regression coverage for a bug where `POST /lookup/{id}/export` was gated on the wrong permission |
| `test_pentest_api.py` | RBAC enforcement, scope-bypass rejection, and a full Pentest Suite assessment lifecycle via real HTTP, with a fake tool substituted for any real nmap/network call |
| `test_pentest_exploit_api.py` | The Pentest Suite's gated, admin-only Metasploit exploit-validation API |
| `test_runtime_config_persistence.py` | `app.core.runtime_config`'s real, DB-backed upsert/merge round-tripping |
| `test_security_assessment_api.py` | RBAC enforcement and a full Security Assessment Toolkit run lifecycle via real HTTP |

## 2. 🧵 Mocking and Fixture Conventions

Three patterns recur across the suite and are worth knowing before adding a new test:

- **respx for HTTP.** `test_ai_connection_test.py` and `test_connection_test.py` mock outbound calls with `@respx.mock` decorators against the real vendor URLs (e.g. `respx.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(429))`) -- every credential value in these files is a placeholder string, never a real key. `test_lookup_flow.py` uses the same library for any HTTP its fake providers happen to trigger.
- **Monkeypatched AI client accessor, not the AI client itself.** Rather than mocking an HTTP call, `test_ai_service.py` replaces the *resolver function* directly: `monkeypatch.setattr("app.ai.service._get_ai_client", _fail_if_called)`, where `_fail_if_called` raises `AssertionError` if it is ever invoked -- proving the no-evidence short-circuit returns `verdict=unknown` without reaching any AI backend at all. `test_lookup_stream_persistence.py` uses the same seam the opposite way, substituting a `_StubAIClient` so the integration test never depends on a real Ollama/Groq/etc. connection: `monkeypatch.setattr(ai_service, "_get_ai_client", _stub_get_ai_client)`.
- **Fake providers via a constructor parameter, not monkeypatching.** `test_lookup_flow.py` and `test_lookup_stream_persistence.py` both pass `providers=[...]` (a list of hand-written `BaseProvider` subclasses) straight into the orchestrator functions, so the real 18-provider registry is never imported by these tests -- there is no risk of a real outbound call to VirusTotal, AbuseIPDB, etc. leaking into the suite.

**There is still no shared `conftest.py`.** Every infra-dependent integration file independently reimplements a near-identical Postgres/Redis-override and connection-pool-disposal fixture rather than sharing one -- a real, if minor, duplication now repeated across well over a dozen files, not just the original two.

**Auth's HTTP endpoints now have dedicated coverage.** `test_auth_registration.py` covers the first-user-becomes-admin bootstrap rule and the `403` every subsequent `POST /api/v1/auth/register` gets, and `test_auth_login_rate_limit.py` covers brute-force rate limiting on `POST /api/v1/auth/login` -- both added since this chapter originally noted the gap. `POST /api/v1/auth/refresh` remains exercised only indirectly, via `User` rows and tokens constructed directly inside other integration files' fixtures.

## 3. 🏃 Running the Backend Tests

For integration coverage, start the two infra services first (unit tests need neither):

```bash
docker compose up -d postgres redis
```

Then, from `backend/`:

```bash
cd backend
pytest                       # everything default-discovery finds
pytest app/tests/unit        # unit only
pytest app/tests/integration # integration only
```

### 3.1 A local virtualenv, and a still-live pytest-discovery gotcha

A single backend virtualenv, `backend/.venv_test`, exists on disk in this repository today (an earlier, second `backend/.venv` no longer exists); it is not committed, and which venv is the "intended" one for running tests is not documented anywhere. Checked directly against `requirements.txt` (via `importlib.metadata`, at time of writing), `.venv_test` currently matches every pinned version exactly -- pytest 8.3.3, pytest-asyncio 0.24.0, bcrypt 4.0.1, asyncpg 0.30.0, cryptography 50.0.0, python-whois 0.9.6, pytest-cov 5.0.0, respx 0.21.1 -- so there is no active dependency drift to report as of this writing.

> [!NOTE]
> This project's local virtualenvs have drifted from `requirements.txt` before, in ways that cascaded far wider than the one file that actually exercised the missing/wrong dependency (a missing `cryptography` install broke collection of every module that transitively imports the runtime-config layer; a wrong `python-whois` patch version broke collection the same way via the provider registry). **Before trusting any local pytest run's pass count on this project, reconcile whichever venv you're using against `requirements.txt` first** -- nothing currently enforces that they stay in sync.

A separate, code-level (not environment-dependent) gotcha remains live regardless of venv state: `app/ai/connection_test.py` and `app/providers/connection_test.py` are *production* modules (live candidate-credential checkers used by `routes/ai_config.py` and `routes/providers.py`), not test files -- but their filenames end in `_test.py` (one of pytest's two default `python_files` discovery patterns, `test_*.py` and `*_test.py`) and each defines a top-level function literally named `test_ai_connection(backend, credentials, model=None)` / `test_provider_connection(provider_id, credentials)`. With no `testpaths` restriction anywhere in the repo, bare `pytest` tries to collect and run these as real tests, and both fail identically at setup with `fixture 'backend' not found` (or `'provider_id'`) -- not a defect in the application, just a naming collision with pytest's default discovery. Scoping the run to `pytest app/tests` (as shown above) avoids this entirely; see the Developer Troubleshooting chapter for the full write-up and its fix (alias the import so the name in the test module's namespace no longer starts with `test_`).

## 4. 💻 Frontend Tests

`frontend/package.json` declares `"test": "vitest run"` and lists `vitest@4.1.10` as a devDependency, but a repository-wide search for `*.test.*` / `*.spec.*` under `frontend/` finds zero files, and no `vitest.config.*` exists either. Running `npm test` in `frontend/` executes Vitest against an empty suite. This is configured-but-unused tooling, not a working test suite -- see the Testing and Quality Assurance appendix for the fuller picture, including the separate manual QA pass that exercises the product end-to-end where automated frontend tests do not.

## 5. 🐳 Docker Compose Build Pipeline

`backend/Dockerfile` and `frontend/Dockerfile` are both single-stage (`python:3.12-slim` with `gcc`/`libpq-dev`/`curl`, and `node:20-alpine`, respectively) -- there is no multi-stage build anywhere in the repository; each image simply installs dependencies from `requirements.txt`/`package.json` and copies the full source tree in.

`docker-compose.yml` defines the eight containers described in the Technical Architecture Overview (`postgres`, `redis`, `neo4j`, `opensearch`, `backend`, `celery_worker`, `celery_beat`, `frontend`); in its current form every datastore port is bound to `127.0.0.1` only, and each of the four datastore services carries an inline comment explaining that a `0.0.0.0`-published equivalent was confirmed reachable, unauthenticated, from another device on the same LAN before this fix. For local development the `backend`/`frontend` services bind-mount the source tree and run `uvicorn ... --reload` / `npm run dev`.

`docker-compose.prod.yml` is a Compose **override** file, layered on top with `-f`, used for anything other than a live-reload dev checkout (this is the file the Windows installer drives):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

It resets every bind-mounted `volumes:` list to empty (`!reset []`, so each container runs entirely from what was baked into its image), and swaps the dev commands for: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000` for `backend`, and, for `frontend`, a multi-step shell command that runs `npm run build`, manually copies `.next/static/` into `.next/standalone/` (Next.js's `output: "standalone"` build intentionally excludes it), and finally launches `node .next/standalone/server.js` -- a workaround documented inline for a confirmed-live failure where `next start` refuses to run against a standalone build at all.

There is no k8s CI/build integration confirmed in the source; `k8s/` exists as a parallel Kustomize-based deployment path (StatefulSets/Deployments/Ingress) but is not otherwise inspected here.

## 6. 🪟 Windows Installer Build

`windows/installer.iss` (415 lines, Inno Setup 6 script) is compiled with:

```
ISCC.exe installer.iss
```

producing `release\HORIZON-GRID-Setup-{version}.exe` (both the `OutputBaseFilename` and the version string come from the `#define MyAppVersion` at the top of the script, currently `"0.3.8"` -- identical to the version pinned in `linux/debian/control` for the `.deb` package). The `[Files]` section stages `backend/`, `frontend/`, both compose files, `docs/`, and `README.md` into the package (`k8s/` is not included -- it's a parallel, Compose-independent deployment path this installer doesn't drive), with explicit excludes on each side: `.venv,.venv_test,__pycache__,*.pyc,.pytest_cache,celerybeat-schedule,nul,_qa_*.py,cleanup_qa_*.py,qa_halluc_out_*.json` for `backend/` (the trailing `nul` exclude exists because a stray file literally named `nul` -- a reserved Windows device name, left behind by some earlier `> nul` redirect -- otherwise aborts Inno Setup's compressor, which can't read its file time; the `.venv`/`.venv_test`/`_qa_*`/`cleanup_qa_*`/`qa_halluc_out_*` excludes strip local dev virtualenvs and ad hoc QA scratch scripts/output that have no business in a shipped package) and `node_modules,.next,*.tsbuildinfo` for `frontend/`. The installer requires 64-bit-compatible Windows (`ArchitecturesAllowed=x64compatible`) and admin privileges (`PrivilegesRequired=admin`); the runtime behavior of the resulting installer (prerequisite checks, the WinForms setup wizard's page flow, Program Files/ProgramData layout, and Start Menu shortcuts) is covered in full in the Windows Deployment Architecture chapter and is not repeated here -- this section is scoped to how the installer artifact itself gets built.

## 7. 📚 Documentation Build Pipeline (`documentation/build/`)

The documentation package you are reading is itself produced by a small Node.js toolchain, explicitly marked in its own `package.json` as `"Local build tooling for rendering the final PDF/DOCX documentation deliverables. Not part of the product."` Its dependencies: `puppeteer-core` (drives a local, already-installed Chrome or Edge to render HTML to PDF/PNG -- no bundled Chromium download), `marked` (Markdown to HTML), `mermaid` (diagram rendering), `html-to-docx` + `docx` + `@xmldom/xmldom` + `jszip` (DOCX generation, including hand-editing the generated `.docx`'s internal `word/document.xml` to inject a real, updatable Word Table-of-Contents field), `image-size` (figure-sizing decisions), and `pdf-parse` (reading rendered PDF text back out, described below).

Two generations of build script coexist:

- The original four (`assemble.js`, `build-html.js`, `render-pdf.js`, `build-docx.js`) read from a pre-baked cache, `sections.json`, which was assembled once from all `tech-*.md` and `user-*.md` files, and produce the combined `FINAL_PRODUCT_DOCUMENTATION.pdf`/`.docx`.
- The newer, generic `build-doc-generic.js` reads `DOCUMENTATION_SOURCE/*.md` **fresh on every run** (no cache) and is driven by one of three small config files -- `config-user-manual.json`, `config-backend.json`, `config-source-code.json` -- each listing an ordered `files` array. This chapter, `dev-06-testing-and-build.md`, is entry 6 of 8 in `config-source-code.json`'s list, which builds `IOC_INTELLIGENCE_PLATFORM_SOURCE_CODE_DOCUMENTATION.pdf`/`.docx`. It is invoked per deliverable:

```bash
cd documentation/build
npm install
node build-doc-generic.js config-source-code.json
```

Within a single run, `buildOne()` renders the PDF in **two passes**: pass 1 renders with a placeholder Table of Contents (each section's opening `<div>` carries an invisible `SECTIONMARK_N` marker span) to a throwaway PDF, which `pdf-parse` then re-reads page-by-page to resolve each marker's real printed page number; pass 2 re-renders the full document with those real page numbers filled into the Table of Contents. The FIGURE-placeholder convention used throughout the source chapters -- a bracketed tag naming an image filename and a caption, separated by a pipe -- is resolved by `resolveFigurePath()`: any filename matching `*-diagram-N.png` is loaded from `documentation/ARCHITECTURE_DIAGRAMS/`, everything else from `documentation/SCREENSHOTS/`; a missing file does not abort the build -- it renders a red inline missing-figure marker and logs an error to the console instead.

Diagrams are authored as fenced ` ```mermaid ` code blocks directly inside a `DOCUMENTATION_SOURCE/*.md` chapter, then converted with a separate script:

```bash
node render-diagrams.js
```

This scans every file matching `(tech|user|dev|backend)-\d+.*\.md` for ` ```mermaid ` blocks, renders each one via headless Chrome + `mermaid.js` to a standalone PNG named `{chapter-basename}-diagram-{n}.png` under `ARCHITECTURE_DIAGRAMS/`, and **rewrites the source chapter file in place**, replacing the raw Mermaid block with a resolved FIGURE placeholder captioned from the nearest preceding heading -- meaning a chapter's committed Markdown, once processed, never contains the original diagram source, only the rendered-image reference.

## 🧾 Summary

The backend carries a real, substantial automated safety net -- 335 unit test functions across 33 files that need no infrastructure at all, plus 15 integration files that bring the full suite to 380 passed / 39 intentionally-skipped, using respx for HTTP mocking, monkeypatched AI-client accessors and hand-written fake providers to keep the suite offline and deterministic, and live-reachability `skipif` guards so infra-dependent tests degrade to "skipped" rather than "failed" when Postgres/Redis aren't up. That safety net sits on top of a locally uncommitted, undocumented virtualenv story that has drifted from `requirements.txt` before (though not as of this writing) and a pytest-discovery quirk that mistakes two production modules for test files -- both independently reproduced above. The frontend has test tooling configured and zero tests to run. Shipping the product itself runs through two independent, uncoordinated pipelines with no CI gluing them together: `docker compose ... up -d --build` (optionally with the `docker-compose.prod.yml` overlay) for the running stack, and `ISCC.exe installer.iss` for the Windows-installable artifact that automates driving that same Compose command. This very documentation set is produced by a third, separate pipeline again -- a small, explicitly-not-part-of-the-product Node toolchain under `documentation/build/` that renders each audience-specific chapter list into a two-pass, page-numbered PDF and a TOC-enabled DOCX.
