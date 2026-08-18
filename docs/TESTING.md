# Testing

This document describes the actual test suite in the repo: what exists, how to run it, and
the Windows-specific gotchas you will hit if you run it locally rather than in CI/Docker.

There is **no pytest.ini, pyproject.toml, setup.cfg, tox.ini, or conftest.py** anywhere in the
repo. Pytest runs with default discovery and configuration. There is also no frontend test
config file (no `vitest.config.*` / `jest.config.*`).

## Backend test suite

Tests live under `backend/app/tests/`, structured as a proper Python package
(`app/tests/__init__.py`, `app/tests/unit/__init__.py`, `app/tests/integration/__init__.py`).

```
backend/app/tests/
├── unit/          # 9 test files, no network/DB/Redis required
└── integration/   # 3 test files, 2 of which need Docker services
```

### Unit tests (`backend/app/tests/unit/`)

No database, Redis, or provider credentials required. Run unconditionally.

| File | Covers |
|---|---|
| `test_abusech.py` | `app.providers.abusech.map_query_status` -- shared abuse.ch `query_status` mapping used by URLhaus/ThreatFox/MalwareBazaar; pins a fix where auth/config failures collapsed into `ProviderStatus.NO_DATA` |
| `test_ai_schemas.py` | `app.ai.schemas.MitreMapping` (ATT&CK tactic enum; `technique_id` is a plain `str` with no regex, because Ollama's grammar compiler can't compile that constraint) and `FinalAssessment`'s grounding validator |
| `test_analysis_service.py` | `app.ai.analysis_service._strip_invalid_evidence_ids` -- the guardrail that prevents the AI from citing `evidence_id`s not present in the supplied evidence, using the real `WhyMaliciousExplanation`/`ReasonWithEvidence` schemas |
| `test_correlation_engine.py` | `app.correlation.engine.correlate` -- pure function building the correlation graph node/edge structure, edge dedup/merge, and provider-agreement bucketing from fake `ProviderResult` envelopes (no network I/O) |
| `test_crawler_collector.py` | `InternetIntelligenceCollector.fetch` (`app/crawler/collector.py`); pins a fix where rate-limited crawler sources were indistinguishable from "found nothing" (both previously collapsed to `NO_DATA`); exercises `app/crawler/sources/errors.py`'s `SourceRateLimitedError` |
| `test_crawler_rate_limit.py` | `app.crawler.sources.rate_limit.AsyncMinIntervalLimiter` timing behavior |
| `test_evidence_builder.py` | `app.evidence.builder` (`build_evidence`, `build_evidence_from_correlation`, `build_evidence_from_providers`) -- the deterministic, non-AI evidence extraction that WHY/Challenge/Score Explanation/Copilot AI features must cite |
| `test_ioc_detector.py` | `app.ioc.detector.detect_ioc_type` contract across many IOC string patterns (IPs, hashes, CVEs, wallets, Windows file paths/registry keys, user agents, MITRE technique IDs, etc.) |
| `test_pivot.py` | `app.evidence.pivot.rank_pivots` -- the pure ranking logic behind `GET /lookup/{id}/pivots` and the "Recommended pivots" panel |
| `test_provider_base.py` | `app.providers.base.BaseProvider` contract (unsupported IOC types, missing credentials, error normalization) shared by every provider connector |
| `test_whois_rdap.py` | WHOIS half of `app/providers/whois_rdap.py`'s `WhoisRdapProvider`; pins a fix where socket-level failures (timeout, connection refused) were mapped to `NO_DATA` identically to a genuine "no WHOIS record" response |

### Integration tests (`backend/app/tests/integration/`)

| File | Covers | Infra required |
|---|---|---|
| `test_api_health.py` | Smoke test for the FastAPI app object: `GET /health` and `GET /docs`. Also proves the OpenAPI schema (including DB-backed lookup/auth/providers routers) serializes correctly at app-construction time | None |
| `test_lookup_flow.py` | `app.providers.orchestrator.run_all_providers` / `run_all_providers_collected` fan-out pipeline, using fake `BaseProvider` subclasses registered via the `providers=` override param (the real registry is never imported). httpx calls are mocked with `respx` | Redis (`localhost:6379`) |
| `test_lookup_stream_persistence.py` | Regression test for a bug where every lookup was stuck at `status=RUNNING` forever because the route's `Depends(get_db)` session was torn down before the lazy `event_stream()` generator ran. Fix: `app/api/routes/lookup.py`'s `event_stream()` now opens its own session via `app.core.db.new_session()` and re-fetches the `IOCLookup` row through it. Uses real Postgres over ASGI transport, a fake provider, and a stubbed AI client | Postgres (`localhost:5433`) + Redis (`localhost:6379`) |

`test_lookup_flow.py` and `test_lookup_stream_persistence.py` each do a live TCP reachability
probe at import time and use `pytest.mark.skipif` to skip the whole module (not fail) if the
required service isn't up. There is no shared `conftest.py`, so each file reimplements very
similar Postgres/Redis-override and connection-pool-disposal fixture logic independently.

```mermaid
flowchart TD
    A["pytest (run from backend/)"] --> B["unit/*.py"]
    A --> C["integration/test_api_health.py"]
    A --> D["integration/test_lookup_flow.py"]
    A --> E["integration/test_lookup_stream_persistence.py"]
    B --> B1["No infra dependency -- always runs"]
    C --> C1["No infra dependency -- always runs"]
    D --> D1{"Redis reachable at\nlocalhost:6379?"}
    D1 -- no --> D2["Module SKIPPED"]
    D1 -- yes --> D3["Runs: fake providers,\nrespx-mocked httpx, real Redis"]
    E --> E1{"Postgres :5433 AND\nRedis :6379 reachable?"}
    E1 -- no --> E2["Module SKIPPED"]
    E1 -- yes --> E3["Runs: real Postgres via ASGI transport,\nfake provider, stubbed AI client"]
```

### There is no test for auth's HTTP endpoints

There is no dedicated unit or integration test that hits `POST /api/v1/auth/register` or
`POST /api/v1/auth/login` directly. Auth is only exercised indirectly, by constructing `User`
rows and tokens directly inside `test_lookup_stream_persistence.py`'s fixtures. **NOT
IMPLEMENTED.**

## Running the backend tests

Start the infra the integration tests need (skip this if you only want unit tests + the
health-check integration test), **then apply migrations** -- `postgres`/`redis` alone give you
an empty schema; migrations normally only run automatically when the `backend` service itself
starts, which you haven't started here:

```bash
docker compose up -d postgres redis
cd backend
DATABASE_URL=postgresql+asyncpg://ioc:ioc@localhost:5433/ioc_intel .venv_test/Scripts/python -m alembic upgrade head
```

Skipping the migration step doesn't make tests skip -- it makes several of them fail with
`relation "users" does not exist` (or similar), which looks like an application bug but is just
a missing setup step.

Run the full suite from `backend/`:

```bash
cd backend
pytest
```

Or explicitly target a subdirectory:

```bash
cd backend
pytest app/tests/unit
pytest app/tests/integration
```

There is no pytest config file, so this is a bare default-discovery run -- no custom markers,
no coverage gate, no `asyncio_mode=auto`. Async tests are marked explicitly with
`@pytest.mark.asyncio` throughout (pytest-asyncio's default "strict" mode requires this on
every async test function).

Test-tooling dependencies, pinned in `backend/requirements.txt`:

| Package | Version |
|---|---|
| pytest | 8.3.3 |
| pytest-asyncio | 0.24.0 |
| pytest-cov | 5.0.0 |
| respx | 0.21.1 |

`pytest-cov` is pinned in `requirements.txt`, but there is no documented `--cov` invocation
anywhere in the repo (no CI config, no Makefile, no doc referencing it) -- coverage reporting
is available but unused. **NOT IMPLEMENTED** as a documented workflow.

## Frontend test suite

**There is no frontend test suite.** `frontend/package.json` defines `"test": "vitest run"`
and lists `vitest@2.1.1` as a devDependency, but there are zero `*.test.*` / `*.spec.*` files
anywhere under `frontend/app`, `frontend/components`, or `frontend/lib`, and no
`vitest.config.*` exists. Running `npm test` invokes vitest against an empty test suite --
this is configured-but-unused test infrastructure, **NOT IMPLEMENTED** as an actual test
suite.

## Things to know (Windows-specific gotchas)

**Update (backend test root-cause investigation):** this repo used to have two divergent
backend virtualenvs, `backend/.venv` and `backend/.venv_test`, with neither documented as "the"
canonical one -- exactly the kind of ambient drift that made tests pass or fail depending on
which one happened to be active, and made a full delete-and-reinstall look like a fix (a fresh
install naturally created one venv correctly resolved from `requirements.txt`, sidestepping the
inconsistency rather than fixing it). `backend/.venv` was the broken one (missing `cryptography`
entirely, causing a deterministic `ModuleNotFoundError` on collection, on top of being drifted
to unpinned, much newer package versions across the board -- e.g. `fastapi==0.141.1` instead of
the pinned `0.115.0`) and has been deleted. **`backend/.venv_test` is the one canonical backend
virtualenv for this repo.** Set it up with:

```bash
cd backend
python -m venv .venv_test
.venv_test/Scripts/pip install -r requirements.txt   # Windows
# .venv_test/bin/pip install -r requirements.txt     # macOS/Linux
```

See `BACKEND_TEST_ROOT_CAUSE_REPORT.md` at the repo root for the full investigation.

### Historical: bcrypt/passlib version mismatch breaks password hashing

`app/auth/security.py` builds its password context with
`CryptContext(schemes=["bcrypt"], deprecated="auto")` via passlib 1.7.4. If your environment
ever has `bcrypt>=4.1` (this was previously reproduced with a stray `bcrypt==5.0.0` in
`backend/.venv_test`, since fixed by reinstalling exactly `requirements.txt`'s pinned
`bcrypt==4.0.1`), calling `ctx.hash()` fails:

- passlib's bcrypt handler reads `_bcrypt.__about__.__version__` to detect the bcrypt version.
  `bcrypt>=4.1` no longer exposes `__about__`, so this raises
  `AttributeError: module 'bcrypt' has no attribute '__about__'` (passlib logs this as
  "(trapped) error reading bcrypt version" and falls through).
- passlib's subsequent internal wrap-bug self-test then hits bcrypt 5.x's stricter 72-byte
  check and fails with `ValueError: password cannot be longer than 72 bytes, truncate
  manually if necessary`.

If any test in your environment starts failing with either error above, check `pip show bcrypt`
and pin it to `4.0.1` to match `requirements.txt`.

### Gotcha 2: "Event loop is closed" from Postgres/Redis connection pools

Both `app.core.db`'s SQLAlchemy engine/pool and `app.core.cache`'s Redis pool are bound to
whichever asyncio event loop was running when their connections were first opened.
pytest-asyncio (in strict/function mode) gives each test function its own event loop, so a
pool created in one test would otherwise be reused -- against a now-closed loop -- by the
next test, raising `RuntimeError: Event loop is closed` deep inside asyncpg or redis-py.

Both integration test files that touch real infra work around this explicitly:

- `test_lookup_flow.py`'s `clean_redis_cache` fixture clears `app.core.cache`'s pool so each
  test gets a fresh Redis client.
- `test_lookup_stream_persistence.py`'s `_dispose_pools_after_each_test` fixture
  (`autouse=True`) disposes both `app.core.db`'s engine and `app.core.cache`'s pool after
  every test.

If you write a new integration test against real Postgres/Redis without this pattern, expect
intermittent `Event loop is closed` failures on the second test in a module, not the first.

## Related docs

- [ARCHITECTURE.md](ARCHITECTURE.md) -- system design, including the orchestrator and SSE
  lookup flow exercised by the integration tests
- [API.md](API.md) -- REST/SSE endpoints referenced by `test_api_health.py` and
  `test_lookup_stream_persistence.py`
- [INSTALL.md](INSTALL.md) -- how to run `docker compose` locally (the same services the
  integration tests probe for)
