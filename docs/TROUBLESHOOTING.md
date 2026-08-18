# Troubleshooting

Symptom -> Cause -> Fix, for failure modes confirmed in the actual source code and
tests. If your symptom isn't here, check the relevant reference doc first:
[PROVIDERS.md](PROVIDERS.md), [AI_ENGINE.md](AI_ENGINE.md), [SECURITY.md](SECURITY.md),
[TESTING.md](TESTING.md), [CONFIGURATION.md](CONFIGURATION.md).

---

## 1. AI assessment fails with "failed to parse grammar" / every `generate_final_assessment()` call breaks

**Symptom**

Final AI assessment (and/or provider summaries) come back as the degraded fallback
object, or backend logs show:

```
Ollama invocation failed: HTTP 400: ... failed to parse grammar ...
```

**Cause**

This is a real, documented gotcha in `backend/app/ai/schemas.py` (comment at
`schemas.py:62-71`). Ollama's structured-output mode (`format:` on `/api/chat`)
compiles the *entire* JSON schema into one llama.cpp decoding grammar
(`json-schema-to-grammar`, observed on server 0.32.6). If **any** field in that
schema has a regex `pattern=` constraint, the whole grammar fails to compile and
Ollama returns HTTP 400 "failed to parse grammar" — which breaks the call for
*every* field, not just the one with the pattern.

This is why `MitreMapping.technique_id` (`backend/app/ai/schemas.py`) is deliberately
typed as a plain `str` with no `pattern=`, even though it looks like it should be
constrained to something like `^T\d{4}(\.\d{3})?$`. Malformed technique IDs aren't a
safety issue here: `app/ai/service.py`'s `_ground_final_assessment()` only checks
`technique_id` membership against real correlation-graph technique IDs and sets
`grounded=False` on a mismatch — it doesn't care about ID format. `test_ai_schemas.py`
(`backend/app/tests/unit/test_ai_schemas.py`) pins this contract.

**Fix**

- If you see this error, you (or a change you made) added a `pattern=` (or similar
  grammar-incompatible constraint) to a Pydantic field on a schema that gets sent to
  Ollama (`ProviderSummary`, `FinalAssessment`, or anything under
  `backend/app/ai/analysis_schemas.py`). Remove the regex constraint and rely on
  `Literal`/enum fields plus the description text instead — enums compile fine into
  llama.cpp grammars; free-form regex does not.
  - Cloud backends (Anthropic, Gemini, Bedrock) don't compile schemas into a decoding
    grammar, so a `pattern=` constraint would work fine there — it only breaks Ollama.
- There is **no retry** for this failure. Every AI client (`ollama_client.py`,
  `anthropic_client.py`, `gemini_client.py`) makes exactly one HTTP attempt and raises
  `RuntimeError` on failure; `bedrock_client.py` is the only backend with retries, and
  those are botocore-level (`BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"})`),
  not application logic. On any exception, `generate_final_assessment()` /
  `summarize_provider()` (`backend/app/ai/service.py`) return a static degraded object
  instead of retrying — the lookup itself still completes.
- See [AI_ENGINE.md](AI_ENGINE.md) for the full grounding/fallback pipeline.

---

## 2. Ollama unreachable / times out

**Symptom**

```
Could not reach Ollama at http://host.docker.internal:11434 -- is it running?
```
or
```
Ollama did not respond within 120s (model=llama3.2:3b) -- likely too slow for available hardware
```

**Cause**

`backend/app/ai/ollama_client.py` maps `httpx.ConnectError` and `httpx.TimeoutException`
to these exact `RuntimeError` messages. `AI_BACKEND` defaults to `ollama`
(`backend/app/core/config.py`), and `OLLAMA_BASE_URL` defaults to
`http://host.docker.internal:11434` — Ollama is expected to run **on the host**, not
inside a container. The 120-second timeout (`_TIMEOUT_SECONDS` in `ollama_client.py`)
is sized for a model that fits fully in VRAM; a model that spills to CPU/mmap can
legitimately take minutes and will trip this.

**Fix**

- Confirm Ollama is running on the host and reachable: `ollama list`, then from inside
  the backend container `curl http://host.docker.internal:11434`.
- Confirm `OLLAMA_MODEL` in `.env` matches a model you've actually pulled
  (`ollama pull llama3.2:3b`).
- If your hardware is slow, use a smaller model rather than raising the timeout —
  `_TIMEOUT_SECONDS` is a hardcoded constant in `ollama_client.py`, not a `.env` setting.
- Either way, the lookup does not fail outright: `summarize_provider()` returns a
  degraded `ProviderSummary` and `generate_final_assessment()` returns a degraded
  `FinalAssessment` (verdict `unknown`, all scores `0`) rather than raising to the caller.

---

## 3. A provider shows `not_configured`

**Symptom**

`GET /api/v1/providers/health` (or a provider card in the UI) shows
`"configured": false` / status `not_configured` for a specific provider.

**Cause**

`BaseProvider.run()` (`backend/app/providers/base.py:112-123`) short-circuits to
`ProviderStatus.NOT_CONFIGURED` whenever `requires_key=True` and the connector's
`configured` flag is falsy. Each connector computes `configured` once, from
`get_settings()`, at **module import time** (the module-level singletons in
`backend/app/providers/registry.py` are constructed when the process starts) — so
adding a key to a running container's `.env` will not retroactively flip this without
a restart.

Common causes per provider (env var -> connector):

| Provider | Required env var(s) | Notes |
|---|---|---|
| VirusTotal | `VIRUSTOTAL_API_KEY` | |
| AbuseIPDB | `ABUSEIPDB_API_KEY` | |
| OTX | `OTX_API_KEY` | |
| URLhaus / ThreatFox / MalwareBazaar | `ABUSECH_AUTH_KEY` | one shared key across all three abuse.ch connectors |
| Hybrid Analysis | `HYBRID_ANALYSIS_API_KEY` | |
| Censys | `CENSYS_PERSONAL_ACCESS_TOKEN` **and** `CENSYS_ORGANIZATION_ID` | both must be set — either one alone leaves `configured=False` |

Providers that never show `not_configured` (no key required, `configured=True`
unconditionally): crt.sh, NVD (key optional, only raises the rate limit), CISA KEV,
MITRE ATT&CK, WHOIS/RDAP, Spamhaus, PhishTank, and the internet-intelligence crawler.

**Fix**

- Set the correct env var(s) in `.env` (see table above and
  [PROVIDERS.md](PROVIDERS.md) for the full per-provider reference) and **restart the
  backend container** — `docker compose up -d --build backend` (or
  `docker compose restart backend` if only `.env` changed and no image rebuild is
  needed) — since `configured` is fixed at import time.
- `not_configured` is a normal, expected state for any provider you haven't set a key
  for — it does not fail the lookup or block other providers.

---

## 4. `429 Rate limit exceeded` on `POST /api/v1/lookup/stream`

**Symptom**

```json
{"detail": "Rate limit exceeded: max 10 lookups per 60s. Each lookup fans out to every provider plus the crawler and multiple AI calls, so this bounds cost/load per user."}
```

**Cause**

`backend/app/api/routes/lookup.py` enforces a Redis-backed fixed-window `RateLimiter`
(`backend/app/core/cache.py`) keyed `lookup_create:{user.id}`, scoped per authenticated
user and enforced across all backend workers (not per-process, since it's Redis-backed).
This is the **only** rate limiter in the codebase — it applies to lookup *creation*
only, not to individual providers, and not to any other endpoint (login/register have
no rate limiting at all — see [SECURITY.md](SECURITY.md)).

Defaults (`backend/app/core/config.py`):

| Setting | Default |
|---|---|
| `lookup_rate_limit_max_calls` | `10` |
| `lookup_rate_limit_window_seconds` | `60` |

**Fix**

- Wait for the window to elapse (fixed window, so worst case up to 60s), or raise
  `LOOKUP_RATE_LIMIT_MAX_CALLS` / `LOOKUP_RATE_LIMIT_WINDOW_SECONDS` in `.env` and
  restart the backend.
- If you're load-testing or scripting bulk lookups, throttle client-side to stay under
  the configured window rather than raising the limit in production.

---

## 5. Lookup stuck at `status=RUNNING` forever

**Historical bug, now fixed** — included here because it's exactly the kind of symptom
worth recognizing if you're on an older checkout or debugging something similar.

**Symptom (historical)**

A lookup's SSE stream would open, and the `IOCLookup` row in Postgres would remain at
`status=RUNNING` indefinitely, even after all providers had finished.

**Cause (historical, fixed)**

The route's `Depends(get_db)` session was torn down (FastAPI closes the dependency's
session when the request handler returns) before the lazy `event_stream()` async
generator actually ran its body — so by the time the generator tried to update the
lookup's final status, its DB session was already closed.

**Fix (already applied)**

`app/api/routes/lookup.py`'s `event_stream()` now opens its **own** session via
`app.core.db.new_session()` and re-fetches the `IOCLookup` row through it, instead of
relying on the route-level `Depends(get_db)` session. `test_lookup_stream_persistence.py`
(`backend/app/tests/integration/test_lookup_stream_persistence.py`) is a regression test
for exactly this bug — run it against real Postgres/Redis (see
[TESTING.md](TESTING.md)) if you suspect a regression:

```bash
cd backend
docker compose up -d postgres redis
pytest app/tests/integration/test_lookup_stream_persistence.py
```

If you see `status=RUNNING` stuck lookups on the current code, it is **not** this bug —
check backend logs for an unhandled exception inside the streaming generator instead.

---

## 6. Local `pytest` run fails with a bcrypt/passlib error

**Symptom**

```
AttributeError: module 'bcrypt' has no attribute '__about__'
```
or
```
ValueError: password cannot be longer than 72 bytes, truncate manually if necessary
```

**Cause**

`backend/app/auth/security.py` builds `CryptContext(schemes=["bcrypt"], deprecated="auto")`
via passlib 1.7.4. Passlib's bcrypt handler reads `_bcrypt.__about__.__version__` to
detect the bcrypt version; `bcrypt>=4.1` (confirmed with `bcrypt==5.0.0`) no longer
exposes `__about__`, so this raises `AttributeError` (passlib logs it as "(trapped)
error reading bcrypt version" and falls through to an internal self-test that then hits
bcrypt 5.x's stricter 72-byte check, raising `ValueError`).

This repo has **two** backend venvs with drifted versions:

| Venv | bcrypt | Fails? |
|---|---|---|
| `backend/.venv` | `4.0.1` (matches `requirements.txt`) | No |
| `backend/.venv_test` | `5.0.0` | Yes, reproduced directly |

**Fix**

```bash
pip show bcrypt
pip install "bcrypt==4.0.1"
```

Pin to `bcrypt==4.0.1` to match `backend/requirements.txt`. Confirm which venv your
shell is actually activated into before debugging further — `python -c "import sys; print(sys.executable)"`.
See [TESTING.md](TESTING.md) for the full venv/version-drift table.

---

## 7. Local `pytest` run fails with `RuntimeError: Event loop is closed`

**Symptom**

Intermittent `RuntimeError: Event loop is closed` raised deep inside `asyncpg` or
`redis-py`, typically on the second (or later) test in an integration test module, not
the first.

**Cause**

`app.core.db`'s engine/pool and `app.core.cache`'s Redis pool are created lazily and
bound to whichever asyncio event loop was running when their connections were first
opened. `pytest-asyncio` (strict mode — no `asyncio_mode=auto` is configured anywhere,
so every async test needs an explicit `@pytest.mark.asyncio` marker) gives each test
function its own event loop, so a pool created in one test gets reused — against a
now-closed loop — by the next test.

**Fix**

Already handled by fixtures local to each integration test file (there is no shared
`conftest.py`):

- `test_lookup_flow.py`'s `clean_redis_cache` fixture clears the Redis client between tests.
- `test_lookup_stream_persistence.py`'s `_dispose_pools_after_each_test` (autouse) fixture
  disposes both `app.core.db`'s `_engine` and `app.core.cache`'s `_pool` after every test.

If you add a **new** integration test that touches Postgres or Redis directly, copy one
of these fixtures rather than assuming a shared one exists — see
[TESTING.md](TESTING.md).

---

## 8. Integration tests silently skip

**Symptom**

`pytest app/tests/integration` reports tests as `SKIPPED`, not `PASSED` or `FAILED`.

**Cause**

`test_lookup_flow.py` and `test_lookup_stream_persistence.py` each do a live TCP
reachability probe at import time and use `pytest.mark.skipif` to skip the whole module
if required infrastructure isn't up:

| Test file | Requires | Skip reason string |
|---|---|---|
| `test_lookup_flow.py` | Redis at `localhost:6379` | `Redis not reachable at {REDIS_HOST}:{REDIS_PORT} -- run \`docker compose up -d redis\` first.` |
| `test_lookup_stream_persistence.py` | Postgres at `localhost:5433` + Redis at `localhost:6379` | `Postgres/Redis not reachable -- run \`docker compose up -d postgres redis\` first.` |

`test_api_health.py` and everything under `app/tests/unit/` have no infrastructure
dependency and run unconditionally.

**Fix**

```bash
docker compose up -d postgres redis
cd backend
pytest app/tests
```

Note the Postgres host port is `5433` (docker-compose maps container `5432` ->
host `5433`), not the default `5432`.

---

## 9. Crawler / OSINT source shows rate-limited instead of "no results"

**Symptom**

A lookup's internet-intelligence provider (`internet_intelligence`) result has
`status=RATE_LIMITED` and `error_message` like `Rate-limited by: github, reddit`,
instead of a clean empty result.

**Cause**

This is the intended, fixed behavior (`backend/app/crawler/collector.py:112-133`) —
not a bug. Before this fix, a rate-limited source and a source that genuinely found
nothing both collapsed into `ProviderStatus.NO_DATA`, which is misleading (`NO_DATA` is
rendered as "nothing found" rather than "we couldn't check"). Now:

- If `merged` findings are non-empty -> `OK`.
- If `merged` is empty **and** at least one source raised `SourceRateLimitedError` ->
  `RATE_LIMITED`, with `error_message` listing which source(s).
- Otherwise -> `NO_DATA`.

Only `github.py` (403/429 -> `SourceRateLimitedError`) and `reddit.py` (429 ->
`SourceRateLimitedError`) implement this; `rss_news.py` and `pastebin_search.py` have
no rate limiter and never raise it, so in practice this status can only come from
GitHub or Reddit throttling. `test_crawler_collector.py`
(`backend/app/tests/unit/test_crawler_collector.py`) pins this contract.

**Fix**

- GitHub's unauthenticated search API allows ~10 req/min; the crawler self-throttles to
  one call every 6s via `AsyncMinIntervalLimiter` (`backend/app/crawler/sources/rate_limit.py`),
  but this is process-local, not Redis-backed, so multiple backend workers each keep
  their own clock.
- Setting a `GITHUB_TOKEN` environment variable (read via `os.getenv`, **not** a
  Settings field in `backend/app/core/config.py`, so it only works if present in the
  actual process environment, not via `.env`) raises the GitHub ceiling from 10 to
  30 req/min.
- This status is expected to appear occasionally under normal use; it is not something
  to "fix" beyond waiting or adding a `GITHUB_TOKEN`.

---

## 10. WHOIS/RDAP provider returns `NO_DATA` on what looks like a network failure

**Symptom**

A domain lookup's `whois_rdap` provider result is `NO_DATA` when you'd expect `ERROR`
or `TIMEOUT` (e.g., you know the WHOIS server was unreachable).

**Cause (fixed, pinned by test)**

`backend/app/providers/whois_rdap.py` runs the blocking `python-whois` library via
`asyncio.to_thread` with `ignore_socket_errors=False` — deliberately overriding that
library's own default of `True`. The library's default silently swallows socket-level
failures (timeout, connection refused) into unparseable text that looks identical to a
genuine "no WHOIS record" response. `test_whois_rdap.py`
(`backend/app/tests/unit/test_whois_rdap.py`) pins this fix — if you see a real
`NO_DATA` result for a domain you believe should have a WHOIS record and the
`ignore_socket_errors` override has since been removed or altered, that's a regression
of this fix, not a new issue.

**Fix**

No action needed for a correctly-behaving system — a true "no WHOIS record" result is
a valid `NO_DATA`. If you suspect the override regressed, check
`backend/app/providers/whois_rdap.py:28-36,62-94` for `ignore_socket_errors=False` and
run `test_whois_rdap.py`.

---

## 11. Frontend `npm test` — nothing to run

**Symptom**

`vitest run` reports zero test files (or the command appears to do nothing useful).

**Cause**

**NOT IMPLEMENTED**: `frontend/package.json` wires up `"test": "vitest run"` and lists
`vitest` as a devDependency, but there are zero `*.test.*`/`*.spec.*` files anywhere
under `frontend/app`, `frontend/components`, or `frontend/lib`, and no
`vitest.config.*` exists. This is configured-but-unused test infrastructure, not a
broken test suite — there is nothing to fix, because there is nothing written yet.

**Fix**

Not applicable. If you're adding frontend tests for the first time, you'll also need to
add a `vitest.config.*` — none exists to model against.

---

## Quick reference: HTTP status -> cause

| HTTP status | Where | Meaning |
|---|---|---|
| `429` on `/api/v1/lookup/stream` | `lookup.py` `RateLimiter` | Per-user lookup creation limit (§4 above) |
| `400` from Ollama (`/api/chat`) | `ollama_client.py` | Grammar compile failure — check for a `pattern=` constraint (§1 above) |
| `429`/`403`/`509` from a provider's own API | `BaseProvider.run()` | Normalized to `ProviderStatus.RATE_LIMITED` (509 is PhishTank's documented over-limit code) |
| Any other non-2xx from a provider | `BaseProvider.run()` | Normalized to `ProviderStatus.ERROR` |

## See also

- [PROVIDERS.md](PROVIDERS.md) — per-provider auth, status mapping, and quirks
- [AI_ENGINE.md](AI_ENGINE.md) — AI backend selection, grounding, and fallback behavior
- [SECURITY.md](SECURITY.md) — rate limiting, permissions, auth
- [TESTING.md](TESTING.md) — full test suite layout and venv gotchas
- [CONFIGURATION.md](CONFIGURATION.md) — every `.env` variable and its default
