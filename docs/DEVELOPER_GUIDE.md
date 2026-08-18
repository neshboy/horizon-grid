# Developer Guide

How to get the platform running locally, how the backend is organized, and the two most common
extension points: adding a provider connector and adding an API route.

Source of truth for everything below: `backend/app/*`, `backend/alembic/*`, `docker-compose.yml`,
`backend/requirements.txt`, `frontend/package.json`.

Related docs: [ARCHITECTURE.md](ARCHITECTURE.md) (system design), [DATA_MODEL.md](DATA_MODEL.md)
(schema/ERD), [PROVIDERS.md](PROVIDERS.md) (every connector in depth), [API_DOCUMENTATION.md](API_DOCUMENTATION.md)
(full route reference), [TESTING.md](TESTING.md) (test suite + Windows gotchas), [CONFIGURATION.md](CONFIGURATION.md)
(every setting), [AI_ENGINE.md](AI_ENGINE.md) (AI backend abstraction).

---

## 1. Repo layout

```
ioc-intel-platform/
├── backend/            # FastAPI app, Alembic migrations, tests
│   ├── app/
│   ├── alembic/
│   └── requirements.txt
├── frontend/           # Next.js App Router UI
├── k8s/                # Kubernetes manifests
├── docker-compose.yml  # postgres, redis, neo4j, opensearch, backend, celery_worker, celery_beat, frontend
├── .env.example
└── docs/
```

### `backend/app/` subpackages

| Directory | Contents |
|---|---|
| `api/routes/` | FastAPI routers: `analysis.py`, `auth.py`, `basket.py`, `cases.py`, `hunting.py`, `lookup.py`, `pivot.py`, `providers.py`. `api/routes/__init__.py` is empty — `main.py` imports each router module directly. |
| `models/` | SQLAlchemy models: `base.py` (mixins), `user.py`, `lookup.py`, `evidence.py`, `basket.py`, `case.py`. `models/__init__.py` imports every module so `Base.metadata` is fully populated for Alembic. |
| `schemas/` | Pydantic request/response schemas for the routes: `auth.py`, `basket.py`, `case.py`, `lookup.py`. |
| `providers/` | One module per intelligence connector, `base.py` (the `BaseProvider` contract), `orchestrator.py` (fan-out/cache/retry), `registry.py` (the single list of registered providers), `stubs/` (connectors gated behind API keys the reference deployment doesn't have configured). |
| `ai/` | AI backend abstraction: `service.py` (core per-provider + final-assessment prompting), `analysis_service.py` (WHY/Challenge/Copilot/etc.), `hunting_service.py` (hunting queries/detection rules), `schemas.py` / `analysis_schemas.py` (Pydantic output contracts), `schema_utils.py`, and one thin client per backend: `ollama_client.py`, `bedrock_client.py`, `gemini_client.py`, `anthropic_client.py`. |
| `correlation/` | `engine.py` — pure function (`correlate`) turning a batch of `ProviderResult`s into graph nodes/edges. No I/O. |
| `evidence/` | `builder.py` (deterministic `EvidenceItem` extraction from provider data + correlation edges, no AI), `loaders.py` (reconstructs in-memory graph/evidence structures from persisted rows for non-streaming routes), `pivot.py` (pure pivot-ranking logic behind `GET /lookup/{id}/pivots`). |
| `crawler/` | The OSINT crawler wrapped as a `BaseProvider` (`collector.py` → `internet_intelligence_provider`), plus `sources/` (`github.py`, `reddit.py`, `rss_news.py`, `pastebin_search.py`, `rate_limit.py`, `errors.py`). |
| `ioc/` | `types.py` (the canonical `IOCType` enum, 32 members, plus `HASH_TYPES`), `detector.py` (`detect_ioc_type`). |
| `auth/` | `security.py` (password hashing, JWT), `rbac.py` (`get_current_user`, `require_permission` dependency factory). |
| `core/` | `config.py` (`Settings` / `get_settings()`), `db.py` (async engine/session), `cache.py` (Redis client, `RateLimiter`). |
| `workers/` | `celery_app.py`, `tasks.py` — the hourly OSINT crawl (`run_osint_crawl`). Lookups themselves run in-process (SSE), not through Celery. |
| `tests/` | `unit/` (9 files, no infra needed), `integration/` (3 files, 2 need Docker services). See [TESTING.md](TESTING.md). |

---

## 2. Running the dev environment

### Prerequisites

- Docker (for `docker compose up`).
- [Ollama](https://ollama.com) installed **natively on the host** (not in Docker) with a model
  pulled, e.g. `ollama pull llama3.2:3b`. The backend container reaches it via
  `OLLAMA_BASE_URL=http://host.docker.internal:11434` — see `docker-compose.yml`'s comment on why
  Ollama is intentionally run outside Docker (large model mmap load is much slower through Docker
  Desktop's WSL2 volume layer on Windows/Mac).

### First run

```bash
cp .env.example .env
# edit .env: set JWT_SECRET_KEY, add any provider API keys you have,
# and set OLLAMA_MODEL to whatever `ollama list` shows for the model you pulled

docker compose up --build
```

This brings up (per `docker-compose.yml`): `postgres` (host port `5433` → container `5432`),
`redis` (`6379`), `neo4j` (`7475`/`7688` — provisioned but unused by app code, see
[ARCHITECTURE.md](ARCHITECTURE.md)), `opensearch` (`9200` — also unused by app code), `backend`
(`8000`), `celery_worker`, `celery_beat`, and `frontend` (`3000`).

The `backend` container's start command runs migrations before serving:

```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- Frontend: `http://localhost:3000`
- Backend Swagger UI: `http://localhost:8000/docs`
- Backend OpenAPI JSON: `http://localhost:8000/api/v1/openapi.json`
- Health check: `GET http://localhost:8000/health` → `{"status": "ok", "service": "..."}`
- Metrics: `GET http://localhost:8000/metrics` (Prometheus, via `prometheus-fastapi-instrumentator`)

### Running only infra (for local, non-Docker backend dev)

```bash
docker compose up -d postgres redis
```

Then run the backend directly from `backend/` with your own Python environment (see
`backend/requirements.txt` for pinned versions: FastAPI 0.115.0, SQLAlchemy 2.0.35, asyncpg
0.29.0, Alembic 1.13.2, etc.).

### Database migrations

```bash
cd backend
alembic upgrade head
```

The migration history has exactly two revisions today (`backend/alembic/versions/`):

| Order | Revision | Down-revision | Creates |
|---|---|---|---|
| 1 | `660d2aa3bc20` | `None` | `users`, `ioc_lookups`, `ai_summaries`, `correlation_edges`, `provider_results` |
| 2 (HEAD) | `a6d3ad2bb63c` | `660d2aa3bc20` | `cases`, `basket_items`, `case_iocs`, `case_notes`, `case_reports`, `evidence_items` |

The engine URL comes from `Settings.database_url` (`backend/app/core/config.py`, default
`postgresql+asyncpg://ioc:ioc@postgres:5432/ioc_intel`), read by `alembic/env.py` via
`get_settings().database_url` — override with a `.env` file or `DATABASE_URL` env var. Full
schema detail: [DATA_MODEL.md](DATA_MODEL.md).

To generate a new migration after changing a model (standard Alembic workflow; the repo relies on
`app/models/__init__.py` importing every model module so `Base.metadata` is complete):

```bash
cd backend
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

### Running tests

```bash
docker compose up -d postgres redis   # only needed for the two DB/Redis-backed integration tests
cd backend
pytest
```

There is no `pytest.ini`/`pyproject.toml`/`conftest.py` — this is a bare default-discovery run.
See [TESTING.md](TESTING.md) for the full test inventory and Windows-specific bcrypt/asyncpg
gotchas (two drifted local venvs, `backend/.venv` and `backend/.venv_test`, exist in this repo).

---

## 3. Adding a new provider connector

Every intelligence source — real or stub — implements `BaseProvider`
(`backend/app/providers/base.py`) and is registered as a module-level singleton in
`backend/app/providers/registry.py`. The orchestrator (`backend/app/providers/orchestrator.py`)
never imports a concrete provider; it only calls `BaseProvider.run()`. This is what makes adding a
provider a two-file change that touches no other code.

```mermaid
flowchart LR
    A["1. Create app/providers/your_provider.py<br/>subclass BaseProvider, implement fetch()"] --> B["2. Instantiate a module-level singleton<br/>e.g. your_provider = YourProvider()"]
    B --> C["3. Import + append to _ALL_PROVIDERS<br/>in app/providers/registry.py"]
    C --> D["Orchestrator picks it up automatically<br/>-- no other code touched"]
```

### Step 1 — subclass `BaseProvider`

```python
# backend/app/providers/your_provider.py
import httpx

from app.core.config import get_settings
from app.ioc.types import IOCType
from app.providers.base import BaseProvider, ProviderCategory, ProviderResult, ProviderStatus


class YourProvider(BaseProvider):
    provider_id = "your_provider"
    provider_name = "Your Provider"
    category = ProviderCategory.THREAT_INTEL  # or SANDBOX, PASSIVE_DNS, CERTIFICATE_INTEL,
                                               # WHOIS, VULNERABILITY, OSINT
    supported_types = {IOCType.IPV4, IOCType.DOMAIN}
    requires_key = True
    base_url = "https://api.example.com"

    def __init__(self) -> None:
        super().__init__()
        self.configured = bool(get_settings().your_provider_api_key)

    async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult:
        response = await client.get(
            f"{self.base_url}/lookup/{ioc_value}",
            headers={"Authorization": f"Bearer {get_settings().your_provider_api_key}"},
        )
        response.raise_for_status()
        payload = response.json()
        return ProviderResult(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            category=self.category,
            status=ProviderStatus.OK,
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            data={"verdict": "malicious"},  # whatever shape makes sense
            raw=payload,
            source_url=f"{self.base_url}/lookup/{ioc_value}",
        )


your_provider = YourProvider()
```

What `BaseProvider.run()` (which you do **not** override) already handles for you:

- Short-circuits to `ProviderStatus.UNSUPPORTED_IOC` if `ioc_type not in self.supported_types`.
- Short-circuits to `ProviderStatus.NOT_CONFIGURED` if `requires_key=True` and `self.configured`
  is falsy.
- Catches `httpx.HTTPStatusError`, mapping HTTP `429`/`403`/`509` → `RATE_LIMITED`, everything else
  → `ERROR`.
- Catches any other exception raised from `fetch()` → `ERROR`.
- Times the call (`latency_ms`).

Do **not** implement your own retry loop or `asyncio.wait_for` timeout inside `fetch()` — that's
the orchestrator's job (`asyncio.wait_for` + `tenacity` `AsyncRetrying`, retrying only on
`httpx.ConnectError`/`ReadTimeout`/`PoolTimeout`). See `backend/app/providers/crtsh.py` for a
minimal reference implementation (no-key connector) and `backend/app/providers/virustotal.py` for
a keyed one.

### Step 2 — add settings + `.env` entries (if the provider needs a key)

Add a field to `Settings` in `backend/app/core/config.py` (e.g. `your_provider_api_key:
Optional[str] = None`) and a matching blank line in `.env.example`. `pydantic-settings` maps the
field name to an uppercase env var (`YOUR_PROVIDER_API_KEY`) automatically.

### Step 3 — register in `registry.py`

```python
# backend/app/providers/registry.py
from app.providers.your_provider import your_provider

_ALL_PROVIDERS: list[BaseProvider] = [
    ...,
    your_provider,
]
```

That's it — `run_all_providers()` filters candidates by `p.supports(ioc_type)`, so your provider
is automatically included for any lookup whose `ioc_type` is in `supported_types`, and it
automatically shows up in `GET /api/v1/providers/health`.

### Caching note

Only `ProviderStatus.OK` results are cached in Redis (`orchestrator.py`), keyed as
`provider_cache:{provider_id}:{ioc_type}:{sha256(ioc_value)}` for `settings.provider_cache_ttl_seconds`
(default 3600s). You don't need to implement caching yourself.

Full connector-by-connector detail (VirusTotal, AbuseIPDB, OTX, URLhaus, ThreatFox, MalwareBazaar,
crt.sh, NVD, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, and the stub connectors Hybrid Analysis, Spamhaus,
PhishTank, Censys): [PROVIDERS.md](PROVIDERS.md).

---

## 4. Adding a new API route

Routers live in `backend/app/api/routes/` and are mounted directly in
`backend/app/main.py` — there is no router auto-discovery and `api/routes/__init__.py` is empty.

```mermaid
flowchart LR
    A["1. Create/extend a router file in<br/>app/api/routes/"] --> B["2. Add Pydantic request/response<br/>schemas in app/schemas/ if needed"]
    B --> C["3. Gate the route with<br/>Depends(require_permission('x:y'))"]
    C --> D["4. Import + app.include_router()<br/>in app/main.py"]
```

### Step 1 — write the router

```python
# backend/app/api/routes/your_feature.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import CurrentUser, require_permission
from app.core.db import get_db

router = APIRouter(prefix="/your-feature", tags=["your-feature"])


@router.get("")
async def list_things(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_permission("lookup:read")),
):
    ...
```

Existing routers all follow this shape — see `backend/app/api/routes/pivot.py` for a short,
representative example (path param + `Depends(get_db)` + `Depends(require_permission(...))` +
404 on missing resource).

### Step 2 — permissions

`require_permission(permission: str)` (`backend/app/auth/rbac.py`) is a dependency factory: it
resolves `get_current_user` from the bearer JWT, then raises `403` with detail
`"Role '{role}' lacks permission '{permission}'"` unless `permission` is in
`ROLE_PERMISSIONS[user.role]` (`backend/app/models/user.py`). Reuse one of the existing permission
strings (`lookup:create`, `lookup:read`, `evidence:read`, `analysis:generate`, `hunting:generate`,
`copilot:query`, `basket:manage`, `case:create`, `case:read`, `case:write`, `case:close`) or define
a new one and add it to `ROLE_PERMISSIONS` for the roles that should have it. Note:
`lookup:export`, `provider:manage`, `user:manage`, and `audit:read` are defined in
`ROLE_PERMISSIONS` but currently have **no route anywhere that checks them** — see
[API_DOCUMENTATION.md](API_DOCUMENTATION.md) for the full permission matrix and which permissions
are configured-but-unused.

Auth uses `HTTPBearer(auto_error=False)` rather than `OAuth2PasswordBearer`, deliberately, because
`/auth/login` takes a JSON body, not an OAuth2 form-encoded grant.

### Step 3 — mount it

```python
# backend/app/main.py
from app.api.routes import analysis, auth, basket, cases, hunting, lookup, pivot, providers, your_feature
...
app.include_router(your_feature.router, prefix=settings.api_v1_prefix)
```

Every router is mounted with `prefix=settings.api_v1_prefix` (`/api/v1`), so
`APIRouter(prefix="/your-feature")` becomes `GET /api/v1/your-feature`.

Full endpoint-by-endpoint reference (all 8 routers, request/response shapes, status codes):
[API_DOCUMENTATION.md](API_DOCUMENTATION.md).

---

## 5. Related docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — component diagram and end-to-end lookup flow.
- [DATA_MODEL.md](DATA_MODEL.md) — full schema, ERD, migration history.
- [PROVIDERS.md](PROVIDERS.md) — every connector's quirks, endpoints, and auth scheme.
- [AI_ENGINE.md](AI_ENGINE.md) — the `AI_BACKEND` abstraction (Ollama/Bedrock/Gemini/Anthropic)
  and grounding/anti-hallucination rules.
- [API_DOCUMENTATION.md](API_DOCUMENTATION.md) — full REST/SSE route reference.
- [TESTING.md](TESTING.md) — test inventory, how to run it, Windows-specific gotchas.
- [CONFIGURATION.md](CONFIGURATION.md) — every environment variable / `Settings` field.
