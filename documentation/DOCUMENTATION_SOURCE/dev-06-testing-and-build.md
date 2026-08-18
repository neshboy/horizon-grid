# Testing and the Build Pipeline

This chapter documents three independent, non-overlapping pieces of tooling a maintainer needs to know: the backend's **pytest** suite (what exists, how it mocks the outside world, and the exact gotchas you will hit running it locally on this machine), the **Docker Compose / Windows Inno Setup** pipeline that turns the source tree into a running stack or an installable `.exe`, and the **documentation build pipeline** under `documentation/build/` that renders the very manual this chapter belongs to. There is no CI system anywhere in the repository -- no `.github/workflows/`, no `Makefile`, no other automation entry point was found -- so every command below is something a developer runs by hand.

## 1. Backend Test Suite Layout

Tests live under `backend/app/tests/`, split into `unit/` and `integration/`, each a real Python package (`__init__.py` present). **There is no `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, or `conftest.py` anywhere in the repository** -- confirmed by a direct search of the tree. Pytest therefore runs with bare default discovery: no custom markers, no `asyncio_mode=auto` (every async test is decorated explicitly with `@pytest.mark.asyncio`, pytest-asyncio's strict-mode requirement), and no coverage gate, even though `pytest-cov` is a pinned dependency (`requirements.txt:29`) -- it is never invoked with `--cov` anywhere in the source, so coverage measurement is available but unused.

| Layer | Location | Files | Lines (incl. blanks) |
|---|---|---|---|
| Unit | `backend/app/tests/unit/` | 16 | ~1,800 |
| Integration | `backend/app/tests/integration/` | 3 | ~1,015 |

A direct count of `def test_...`/`async def test_...` function definitions across those 19 files puts the suite at **144 automated test functions** -- independently consistent with the "144 tests total" figure a later engineering pass reports after adding one of those files (`test_ai_connection_test.py`; see the Testing and Quality Assurance appendix for that pass's own account).

### 1.1 Unit tests (`backend/app/tests/unit/`)

No database, Redis, Docker, or network access is required for any file in this directory.

| File | What it exercises |
|---|---|
| `test_abusech.py` | `app.providers.abusech.map_query_status` -- the shared abuse.ch `query_status` mapping used by URLhaus/ThreatFox/MalwareBazaar |
| `test_ai_connection_test.py` | `app.ai.connection_test.test_ai_connection` for all 5 AI backends against **respx**-mocked HTTP: success, invalid-key/401, rate-limit/429, model-not-found/404, timeout, network error (16 test functions) |
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

### 1.2 Integration tests (`backend/app/tests/integration/`)

| File | Covers | Infra required |
|---|---|---|
| `test_api_health.py` | `GET /health`, `GET /docs`, and that the full OpenAPI schema (every DB-backed router included) serializes at app-construction time | None |
| `test_lookup_flow.py` | `app.providers.orchestrator.run_all_providers` / `run_all_providers_collected` fan-out, registered against **fake `BaseProvider` subclasses** via the orchestrator's `providers=` override parameter -- the real provider registry is never imported | Redis (`localhost:6379`) |
| `test_lookup_stream_persistence.py` | Regression coverage for a bug where every lookup stayed `status=RUNNING` forever because the route's DB session was torn down before the lazy SSE generator ran | Postgres (`localhost:5433`) + Redis (`localhost:6379`) |

`test_lookup_flow.py` and `test_lookup_stream_persistence.py` each perform a live TCP reachability probe at import time and use `pytest.mark.skipif` to **skip the whole module** (not fail the run) when the required service isn't reachable -- so running the suite with no Docker services up still passes, it just silently exercises fewer files.

## 2. Mocking and Fixture Conventions

Three patterns recur across the suite and are worth knowing before adding a new test:

- **respx for HTTP.** `test_ai_connection_test.py` and `test_connection_test.py` mock outbound calls with `@respx.mock` decorators against the real vendor URLs (e.g. `respx.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(429))`) -- every credential value in these files is a placeholder string, never a real key. `test_lookup_flow.py` uses the same library for any HTTP its fake providers happen to trigger.
- **Monkeypatched AI client accessor, not the AI client itself.** Rather than mocking an HTTP call, `test_ai_service.py` replaces the *resolver function* directly: `monkeypatch.setattr("app.ai.service._get_ai_client", _fail_if_called)`, where `_fail_if_called` raises `AssertionError` if it is ever invoked -- proving the no-evidence short-circuit returns `verdict=unknown` without reaching any AI backend at all. `test_lookup_stream_persistence.py` uses the same seam the opposite way, substituting a `_StubAIClient` so the integration test never depends on a real Ollama/Groq/etc. connection: `monkeypatch.setattr(ai_service, "_get_ai_client", _stub_get_ai_client)`.
- **Fake providers via a constructor parameter, not monkeypatching.** `test_lookup_flow.py` and `test_lookup_stream_persistence.py` both pass `providers=[...]` (a list of hand-written `BaseProvider` subclasses) straight into the orchestrator functions, so the real 16-provider registry is never imported by these tests -- there is no risk of a real outbound call to VirusTotal, AbuseIPDB, etc. leaking into the suite.

**There is no shared `conftest.py`.** Both infra-dependent integration files independently reimplement near-identical Postgres/Redis-override and connection-pool-disposal fixtures rather than sharing one -- a real, if minor, duplication a maintainer adding a fourth integration file should be aware of before copy-pasting a fifth copy of the same fixture.

**There is no dedicated test for auth's HTTP endpoints.** `POST /api/v1/auth/register` and `POST /api/v1/auth/login` are exercised only indirectly, via `User` rows and tokens constructed directly inside `test_lookup_stream_persistence.py`'s fixtures.

## 3. Running the Backend Tests

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

### 3.1 Two drifted local virtualenvs

Two backend virtualenvs exist on disk in this repository, `backend/.venv` and `backend/.venv_test`; neither is committed, and which one is the "intended" one for running tests is not documented anywhere. Directly comparing both against the versions actually pinned in `requirements.txt` (verified with `pip show` in each, at time of writing):

| Package | Pinned (`requirements.txt`) | `backend/.venv` | `backend/.venv_test` |
|---|---|---|---|
| pytest | 8.3.3 | 9.1.1 | 8.3.3 |
| pytest-asyncio | 0.24.0 | 1.4.0 | 0.24.0 |
| bcrypt | 4.0.1 | 4.0.1 | 5.0.0 |
| asyncpg | 0.29.0 | 0.31.0 | 0.30.0 |
| cryptography | 43.0.1 | **not installed** | 50.0.0 |
| python-whois | 0.9.6 | 0.9.6 | 0.9.4 |

Running the full suite (`pytest --continue-on-collection-errors`, bare, from `backend/`) against each venv, with the Postgres/Redis containers from `docker-compose.yml` up, produced:

- `.venv`: **150 passed, 9 errors**
- `.venv_test`: **153 passed, 9 errors**

Every single one of those 9 errors decomposes into just two root causes, not nine unrelated bugs:

1. **Two are a pytest-discovery false positive, present in both venvs, unrelated to any dependency drift.** `app/ai/connection_test.py` and `app/providers/connection_test.py` are *production* modules (live candidate-credential checkers used by `routes/ai_config.py` and `routes/providers.py`), not test files -- but their filenames end in `_test.py` (pytest's default `*_test.py` discovery pattern) and each defines a top-level function literally named `test_ai_connection(backend, credentials, model=None)` / `test_provider_connection(provider_id, credentials)`. With no `testpaths` restriction anywhere in the repo, bare `pytest` tries to collect and run these as real tests, and both fail identically at setup with `fixture 'backend' not found` (or `'provider_id'`) -- not a defect in the application, just a naming collision with pytest's default discovery. Scoping the run to `pytest app/tests` (as shown above) avoids this entirely.
2. **The remaining 7 trace to exactly one drifted or missing package per venv**, because the affected module sits on the import path of nearly the whole app. In `.venv`, `cryptography` is not installed at all, and `app/core/crypto.py` imports it unconditionally -- this breaks collection of `test_crypto.py` directly, and also `test_api_health.py`/`test_lookup_flow.py`, since both import the FastAPI app object, which transitively imports the runtime-config module, which imports `crypto.py`. In `.venv_test`, `python-whois==0.9.4` is installed instead of the pinned `0.9.6`; `0.9.4` has no `whois.exceptions` submodule, and `app/providers/whois_rdap.py:23`'s `from whois.exceptions import PywhoisError` fails -- breaking collection of `test_whois_rdap.py` directly, `test_api_health.py`/`test_lookup_flow.py` the same transitive way, and causing 4 of `test_lookup_stream_persistence.py`'s 5 tests to fail specifically at the `monkeypatch.setattr("app.api.routes.lookup...", ...)` setup step, since that import chain also runs through the provider registry.

This is a distinct, additional pair of environment gotchas beyond the bcrypt/passlib version issue and the asyncio event-loop-pool issue already written up in `docs/TESTING.md` (both of which remain accurate: `bcrypt>=4.1`'s missing `__about__` attribute breaks passlib's `CryptContext.hash()` reproducibly in `.venv_test`'s bcrypt 5.0.0, and both infra-touching integration files carry their own `autouse` pool-disposal fixtures specifically to avoid "Event loop is closed" errors on the second test in a module). The practical takeaway for a maintainer: **before trusting any local pytest run's pass count on this project, reconcile whichever venv you're using against `requirements.txt` first** -- the drift is real, silent, and (as shown above) cascades far wider than the one file that actually exercises the missing/wrong dependency.

## 4. Frontend Tests

`frontend/package.json` declares `"test": "vitest run"` and lists `vitest@2.1.1` as a devDependency, but a repository-wide search for `*.test.*` / `*.spec.*` under `frontend/` finds zero files, and no `vitest.config.*` exists either. Running `npm test` in `frontend/` executes Vitest against an empty suite. This is configured-but-unused tooling, not a working test suite -- see the Testing and Quality Assurance appendix for the fuller picture, including the separate manual QA pass that exercises the product end-to-end where automated frontend tests do not.

## 5. Docker Compose Build Pipeline

`backend/Dockerfile` and `frontend/Dockerfile` are both single-stage (`python:3.12-slim` with `gcc`/`libpq-dev`/`curl`, and `node:20-alpine`, respectively) -- there is no multi-stage build anywhere in the repository; each image simply installs dependencies from `requirements.txt`/`package.json` and copies the full source tree in.

`docker-compose.yml` defines the eight containers described in the Technical Architecture Overview (`postgres`, `redis`, `neo4j`, `opensearch`, `backend`, `celery_worker`, `celery_beat`, `frontend`); in its current form every datastore port is bound to `127.0.0.1` only, and each of the four datastore services carries an inline comment explaining that a `0.0.0.0`-published equivalent was confirmed reachable, unauthenticated, from another device on the same LAN before this fix. For local development the `backend`/`frontend` services bind-mount the source tree and run `uvicorn ... --reload` / `npm run dev`.

`docker-compose.prod.yml` is a Compose **override** file, layered on top with `-f`, used for anything other than a live-reload dev checkout (this is the file the Windows installer drives):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

It resets every bind-mounted `volumes:` list to empty (`!reset []`, so each container runs entirely from what was baked into its image), and swaps the dev commands for: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000` for `backend`, and, for `frontend`, a multi-step shell command that runs `npm run build`, manually copies `.next/static/` into `.next/standalone/` (Next.js's `output: "standalone"` build intentionally excludes it), and finally launches `node .next/standalone/server.js` -- a workaround documented inline for a confirmed-live failure where `next start` refuses to run against a standalone build at all.

There is no k8s CI/build integration confirmed in the source; `k8s/` exists as a parallel Kustomize-based deployment path (StatefulSets/Deployments/Ingress) but is not otherwise inspected here.

## 6. Windows Installer Build

`windows/installer.iss` (359 lines, Inno Setup 6 script) is compiled with:

```
ISCC.exe installer.iss
```

producing `release\IOC-Intelligence-Platform-Setup-{version}.exe` (version string taken from the `#define MyAppVersion` at the top of the script, currently `"0.1.0"`). The `[Files]` section stages `backend/`, `frontend/`, both compose files, `k8s/`, `docs/`, and `README.md` into the package, with explicit excludes on each side: `__pycache__,*.pyc,.pytest_cache,celerybeat-schedule,nul` for `backend/` (the trailing `nul` exclude exists because a stray file literally named `nul` -- a reserved Windows device name, left behind by some earlier `> nul` redirect -- otherwise aborts Inno Setup's compressor, which can't read its file time) and `node_modules,.next,*.tsbuildinfo` for `frontend/`. The installer requires 64-bit-compatible Windows (`ArchitecturesAllowed=x64compatible`) and admin privileges (`PrivilegesRequired=admin`); the runtime behavior of the resulting installer (prerequisite checks, the WinForms setup wizard's page flow, Program Files/ProgramData layout, and Start Menu shortcuts) is covered in full in the Windows Deployment Architecture chapter and is not repeated here -- this section is scoped to how the installer artifact itself gets built.

## 7. Documentation Build Pipeline (`documentation/build/`)

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

## Summary

The backend carries a real, if partial, automated safety net -- 144 pytest test functions across 16 unit and 3 integration files, using respx for HTTP mocking, monkeypatched AI-client accessors and hand-written fake providers to keep the suite offline and deterministic, and live-reachability `skipif` guards so infra-dependent tests degrade to "skipped" rather than "failed" when Postgres/Redis aren't up. That safety net sits on top of a genuinely inconsistent local environment story, though: two undocumented, uncommitted virtualenvs, each drifted from `requirements.txt` in a different way, plus a pytest-discovery quirk that mistakes two production modules for test files -- all independently reproduced above. The frontend has test tooling configured and zero tests to run. Shipping the product itself runs through two independent, uncoordinated pipelines with no CI gluing them together: `docker compose ... up -d --build` (optionally with the `docker-compose.prod.yml` overlay) for the running stack, and `ISCC.exe installer.iss` for the Windows-installable artifact that automates driving that same Compose command. This very documentation set is produced by a third, separate pipeline again -- a small, explicitly-not-part-of-the-product Node toolchain under `documentation/build/` that renders each audience-specific chapter list into a two-pass, page-numbered PDF and a TOC-enabled DOCX.
