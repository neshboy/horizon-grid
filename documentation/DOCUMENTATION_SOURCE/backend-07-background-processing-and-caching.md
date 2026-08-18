# Background Processing and Caching

This chapter covers two backend subsystems that operate outside the hot path of an interactive lookup: the **Celery worker/beat stack** (`backend/app/workers/`) and **Redis** (`backend/app/core/cache.py`), which serves as the provider-result cache, the rate limiter, and the Celery message transport. They are covered together because they share one physical dependency — a single Redis container backs the cache, the rate limiter, and Celery's broker/result-backend, split across three logical database indexes.

The fact to internalize first: **`POST /api/v1/lookup/stream` — the core investigation endpoint — never touches Celery.** Provider fan-out, correlation, AI summarization, and the final assessment run entirely in-process inside the FastAPI request/response lifecycle and stream back as Server-Sent Events. Celery exists for exactly one job, described below, with no code path that can block or delay a live investigation.

## Celery: what actually runs

`backend/app/workers/celery_app.py` defines the Celery application:

```python
celery_app = Celery(
    "ioc_intel_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
```

Its module docstring describes the intended scope as "scheduled crawler runs, PDF/report export rendering, and any lookup re-processing that outlives an HTTP request lifecycle." Checked against the actual code in `app/workers/tasks.py`, two of those three named use cases — PDF/report export rendering and lookup re-processing — do not exist as implemented tasks. There is exactly **one** registered task in the codebase, `run_osint_crawl`, wired into a `beat_schedule` that fires it once an hour:

```python
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "crawl-osint-sources-hourly": {
            "task": "app.workers.tasks.run_osint_crawl",
            "schedule": 3600.0,
        },
    },
)
```

Stated plainly for capacity planning: **the Celery worker and beat containers exist and are actively used, but for a single low-volume hourly maintenance job, not a general-purpose task queue backing multiple product features.** Report generation (`case_reports` exists as a table — see the database chapter) and asynchronous lookup re-processing are not implemented as Celery tasks despite being named in the module's own docstring as in-scope; if either is added later, this is the natural place, but neither exists today.

### `run_osint_crawl` — the one scheduled job

Defined in `backend/app/workers/tasks.py`. Its own module docstring explains the design rationale directly: rather than crawl an arbitrary hardcoded list of search terms, the task re-runs the OSINT crawler (`app/crawler/collector.py`'s `internet_intelligence_provider`, the same "Internet Intelligence Collector" provider documented in the Providers chapter) against IOCs that were **actually looked up recently** by real users, so crawler capacity is spent on what analysts are investigating rather than on speculative targets.

Mechanics, in order, on each hourly tick:

1. `_recent_crawlable_iocs()` queries `ioc_lookups` for rows where `ioc_type` is one of the crawler-eligible types — `domain`, `ipv4`, `malware_family`, `threat_actor`, `campaign`, `cve`, `file_name` (must stay in sync with `app/crawler/collector.py`'s `_SUPPORTED_TYPES`, since free-text OSINT search on a raw hash or IP is treated as too noisy to be useful) — and `created_at` within the last **24 hours** (`_LOOKBACK_HOURS`). It over-fetches (`_MAX_IOCS_PER_RUN * 10` rows) and de-duplicates `(ioc_value, ioc_type)` pairs in Python (Postgres rejects `SELECT DISTINCT ... ORDER BY created_at` when `created_at` isn't in the select list), then caps the result at **25 IOCs per run** (`_MAX_IOCS_PER_RUN`) — a fixed bound so one beat tick never scales with lookup volume.
2. No crawlable IOCs in the window → logs `"no recently-investigated crawlable IOCs, nothing to do"` and returns `0`. This is the expected outcome on a lightly-used instance, not an error.
3. Otherwise it opens one shared `httpx.AsyncClient` (30s timeout, redirects followed) and calls `_crawl_one()` per target sequentially, each wrapped in its own `try/except` so one bad target cannot abort the run — logged as a warning and skipped.
4. `_crawl_one()` calls `internet_intelligence_provider.run(...)` — the same `BaseProvider.run()` entry point live investigations use — and, only if the result status is `ProviderStatus.OK`, writes it into the same Redis cache via `set_cached_result(...)` with `settings.provider_cache_ttl_seconds` (default 3600s) as TTL. Non-`OK` results are discarded, not cached.

Net effect: OSINT crawler results stay warm in the shared cache for IOCs users are actively investigating, so a second lookup within the TTL gets a cache hit instead of a fresh, rate-limit-sensitive crawl across GitHub/Reddit/RSS/Pastebin.

Concurrency note: the task function itself is synchronous (`def run_osint_crawl() -> int`), but its body is `async`. Since a Celery worker process has no running event loop to attach to, the task wraps its body in `asyncio.run(_run_osint_crawl_async())` — a fresh event loop per execution, per the module's own comment. It therefore cannot share a connection pool or event loop with the FastAPI process; it opens its own DB session (`new_session()`) and its own `httpx.AsyncClient` each run.

### Task registry — the full picture

| Task name | Trigger | Frequency | File |
|---|---|---|---|
| `app.workers.tasks.run_osint_crawl` | Celery Beat (`crawl-osint-sources-hourly` schedule entry) | Every 3600 seconds (1 hour) | `backend/app/workers/tasks.py:119-124` |

That is the entire task registry. No other `@celery_app.task` decorator exists anywhere in the backend codebase — confirmed by the fact that `celery_app.py`'s `include=["app.workers.tasks"]` names the only module Celery is told to import tasks from, and that module defines exactly one.

## How the worker and beat containers are wired

Both `celery_worker` and `celery_beat` in `docker-compose.yml` build from the **same backend image** as the FastAPI `backend` service (`build: {context: ./backend}`), and differ only in their `command:`:

| Container | Command | Role |
|---|---|---|
| `celery_worker` | `celery -A app.workers.celery_app worker --loglevel=info` | Executes tasks pulled from the broker queue. |
| `celery_beat` | `celery -A app.workers.celery_app beat --loglevel=info` | Emits the scheduled `run_osint_crawl` message onto the broker every hour; does not execute tasks itself. |

Both are started with `restart: unless-stopped`, and both depend on Redis being healthy (`depends_on: redis: condition: service_healthy`) before starting; `celery_worker` additionally depends on Postgres, since its one task reads `ioc_lookups`. Neither container runs `alembic upgrade head` — only the `backend` service's startup command does that, so the workers assume the schema is already current by the time they start.

The Kubernetes manifests (`k8s/base/celery-worker-deployment.yaml`, `k8s/base/celery-beat-deployment.yaml`) mirror this: same `ioc-intel-platform/backend:latest` image, same `celery ... worker`/`celery ... beat` commands, same `ioc-intel-config`/`ioc-intel-secrets` ConfigMap/Secret as the backend Deployment. Two operational details: **`celery-worker` is scaled to 2 replicas** (250m/512Mi requested, 1000m/1Gi limit) since multiple workers can safely share one queue; **`celery-beat` is pinned to 1 replica**, with a manifest comment explaining why — "celery beat is a singleton scheduler and running more than one replica would produce duplicate scheduled task dispatches."

Production Compose (`docker-compose.prod.yml`) leaves both commands unchanged and only strips bind-mounted `volumes:` (`volumes: !reset []`), the same treatment given to `backend`/`frontend`. Its header comment notes why: WSL2 bind-mount permissions under Program Files caused `celery_beat`'s schedule-file writes to fail with `PermissionError` in dev, motivating removing volumes across the board.

## Redis: the shared dependency

Redis (`redis:7-alpine`) is the one piece of infrastructure the two subsystems in this chapter share, partitioned into three logical database indexes on a single Redis instance/container rather than three separate processes:

| Redis URL (as set in `docker-compose.yml` / `config.py`) | Logical DB | Consumer | Purpose |
|---|---|---|---|
| `redis://redis:6379/0` (`settings.redis_url`) | `/0` | `app/core/cache.py`, read directly by the FastAPI backend process and by the `run_osint_crawl` Celery task | Provider-result cache + rate-limiter counters |
| `redis://redis:6379/1` (`settings.celery_broker_url`) | `/1` | Celery worker + beat | Message broker — task dispatch queue |
| `redis://redis:6379/2` (`settings.celery_result_backend`) | `/2` | Celery worker + beat | Result backend — stores task return values/state (`task_track_started=True` is set, so state transitions are recorded too) |

All three URLs are injected identically into `backend`, `celery_worker`, and `celery_beat` in `docker-compose.yml`'s `environment:` block — the FastAPI process and the Celery containers reach the same cache/broker/backend with no cross-container RPC, just three processes pointed at the same Redis host with three different `/N` suffixes. This separation means a `FLUSHDB` or eviction event against the cache (`/0`) cannot corrupt in-flight Celery task state (`/1`, `/2`), even though all three share one Redis process and memory budget.

### Client construction

`app/core/cache.py` builds its Redis connection lazily, once per process, via a module-level `_pool` global populated on first call to `get_redis()`: `aioredis.from_url(get_settings().redis_url, decode_responses=True)`. This is the async `redis.asyncio` client (package `redis==5.0.8` per `backend/requirements.txt`); `decode_responses=True` means every value this module handles is a Python `str`, not `bytes`. This client always talks to `/0` — it is unrelated to, and shares no connection with, Celery's own broker/backend clients (which Celery manages internally against `/1`/`/2`). There is exactly one `aioredis.Redis` client per backend/worker process, reused for the life of that process; it is never explicitly closed or recycled.

### Provider-result cache

`cache_key(provider_id, ioc_type, ioc_value)` builds keys of the form:

```
provider_cache:{provider_id}:{ioc_type}:{sha256(ioc_value)}
```

The IOC value itself is SHA-256-hashed before being embedded in the key — `hashlib.sha256(ioc_value.encode("utf-8")).hexdigest()` — rather than stored in the clear as part of the Redis key name. `get_cached_result()`/`set_cached_result()` are thin `GET`/`SET ... EX <ttl>` wrappers around that key, serializing the cached payload with `json.dumps(payload, default=str)` (the `default=str` handles any non-JSON-native Python value a provider's `ProviderResult.to_dict()` might contain, e.g. a `datetime`) and deserializing with `json.loads()` on read.

The cache is consulted from exactly two call sites, both of which use the identical key scheme so a write from one is visible to a read from the other:

1. **`app/providers/orchestrator.py`'s `_run_with_policy()`** — checked *before* any live HTTP call is attempted, for every applicable provider, on every investigation. A hit short-circuits the entire fetch/retry/timeout pipeline for that provider and is marked `result.from_cache = True` so the UI can distinguish a fresh answer from a cached one. A write only happens `if result.status == ProviderStatus.OK` — results with any other status (`NO_DATA`, `ERROR`, `TIMEOUT`, `RATE_LIMITED`, `NOT_CONFIGURED`, `UNSUPPORTED`) are never cached. This is a deliberate asymmetry worth knowing operationally: a provider that currently has no data for an IOC (`NO_DATA`) will be queried again, in full, on every subsequent lookup of that same IOC until it eventually returns `OK` — there is no negative-result caching.
2. **`app/workers/tasks.py`'s `_crawl_one()`** (the hourly OSINT job) — writes only, using the same `set_cached_result()` function and the same TTL setting, refreshing the crawler's entry in this same cache so a subsequent interactive lookup of that IOC can hit it.

TTL for both call sites is `settings.provider_cache_ttl_seconds`, defaulting to **3600 seconds (1 hour)** (`app/core/config.py:103`). There is no cache-busting endpoint or manual invalidation path anywhere in the API surface — the only way a stale cached provider result is refreshed before its TTL expires is if a provider's underlying data changes and someone explicitly needs a fresh read, in which case the only lever available today is waiting out the TTL (there is no "force refresh" flag on `POST /api/v1/lookup/stream`).

### Rate limiting

The same module defines `RateLimiter`, a Redis-backed fixed-window counter:

```python
class RateLimiter:
    def __init__(self, provider_id: str, max_calls: int, window_seconds: int) -> None:
        self._key = f"rate_limit:{provider_id}"
        self._max_calls = max_calls
        self._window_seconds = window_seconds

    async def allow(self) -> bool:
        r = get_redis()
        current = await r.incr(self._key)
        if current == 1:
            await r.expire(self._key, self._window_seconds)
        return current <= self._max_calls
```

The constructor parameter is named `provider_id`, but this is a generic identifier for whatever the caller wants to key the window by — it is not restricted to provider identifiers. The one place this class is actually instantiated in the codebase is `app/api/routes/lookup.py`'s `POST /api/v1/lookup/stream` handler, which keys it **per authenticated user**, not per provider:

```python
limiter = RateLimiter(
    f"lookup_create:{user.id}",
    max_calls=settings.lookup_rate_limit_max_calls,
    window_seconds=settings.lookup_rate_limit_window_seconds,
)
```

Defaults are `lookup_rate_limit_max_calls = 10` and `lookup_rate_limit_window_seconds = 60` (`config.py:106-107`) — at most 10 new lookups per user per rolling 60-second fixed window. `INCR` on a key that doesn't exist initializes it to `1`; the code sets the key's expiry only on that first increment (`if current == 1: await r.expire(...)`), the standard fixed-window pattern — a burst straddling a window boundary can momentarily exceed the nominal limit, a known fixed-window tradeoff the code does not correct for. Exceeding the limit returns `HTTP 429` with a detail message explaining why the limit exists: a single lookup fans out to every provider plus the crawler plus multiple AI calls, so the per-user cap bounds aggregate downstream cost/load, not just request count.

Being Redis-backed, this limiter stays correct if the FastAPI backend is horizontally scaled to multiple replicas — the module's stated reason for not using an in-process counter. Contrast the crawler's own **separate** in-process limiter, `AsyncMinIntervalLimiter` (`app/crawler/sources/rate_limit.py`), which spaces out GitHub (6.0s) and Reddit (1.1s) search calls within the crawler's OSINT sub-sources using a plain `asyncio.Lock` + monotonic clock. It is intentionally not Redis-backed and not shared with `RateLimiter`, since it only needs to bound one process's own outbound rate to a third-party API, not enforce a global cross-replica cap.

## Operational notes and gaps

- **No dedicated automated tests target `app/core/cache.py` or `app/workers/tasks.py` directly.** No `test_cache*.py` or `test_workers*.py`/`test_tasks*.py` file exists under `backend/app/tests/`. Cache coverage is indirect, via provider/orchestrator tests exercising cache-hit/miss branches as a side effect; the hourly task has no unit test of its own.
- **No cache metrics or hit/miss counters are exposed.** The only observability into cache behavior is the `from_cache` boolean on each `ProviderResult`, visible per-lookup — there is no aggregate hit-rate metric on the Prometheus `/metrics` endpoint.
- **No Flower (or equivalent) Celery monitoring UI exists anywhere in this codebase** — task history/state is inspectable only via the result backend (`/2`) directly or worker/beat container logs.
- **A Redis outage has two blast radii at once.** Because the cache/rate-limiter (`/0`) and the Celery broker/backend (`/1`, `/2`) share one physical Redis process, an outage fails both simultaneously — interactive lookups fail at `RateLimiter.allow()` before the cache is even consulted, and the hourly job fails to dispatch. No fallback path (fail-open limiter, in-memory cache) exists for a Redis-unavailable condition; Redis should be treated as a hard dependency of the lookup-creation endpoint, not merely a performance optimization.

[FIGURE: backend-07-background-processing-and-caching-diagram-1.png | Diagram: Operational notes and gaps]
Diagram: Celery worker/beat topology and the three logical Redis database indexes (`/0` cache + rate-limit, `/1` broker, `/2` result backend) shared between the FastAPI backend, the Celery worker, and the Celery beat scheduler. A single Redis outage takes down both the cache/rate-limiter and the Celery broker/backend at once, since all three indexes live in one physical process.

## Summary

Celery is real, running infrastructure in every deployment of this platform (Compose and Kubernetes alike), but currently backs exactly one job — an hourly re-crawl of OSINT sources for recently-investigated, crawler-eligible IOCs, capped at 25 per run — with no involvement in the interactive, SSE-streamed lookup pipeline, which runs entirely in-process. Redis is the shared substrate for both subsystems, split by logical index into a provider-result cache plus fixed-window rate limiter (`/0`) and a Celery broker/result-backend pair (`/1`, `/2`). The cache is positive-only (no `NO_DATA`/error caching) with a one-hour default TTL and no manual invalidation path; the rate limiter is per authenticated user on the lookup-creation endpoint, chosen specifically because a Redis-backed counter stays correct under horizontal scaling, unlike the crawler's separate, process-local `AsyncMinIntervalLimiter`. Redis should be treated as a hard dependency of the live lookup path via the rate limiter, not just a cache, and Celery should not be assumed to be doing more than this one documented hourly job.
