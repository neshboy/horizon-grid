# Extension Points: Adding Providers, AI Backends, Endpoints, and Migrations

This chapter is a practical, step-by-step reference for the four kinds of change a maintainer is most likely to make to this codebase: adding a new IOC intelligence provider, adding a new AI backend, adding a new API endpoint, and adding a database migration. Each walkthrough cites the exact files, classes, and functions involved and points at an existing piece of code to use as a template. It assumes familiarity with the Provider Architecture, AI Architecture, and Database Architecture chapters elsewhere in this document, and focuses on *where to make the change*, not on re-explaining what each subsystem does.

## 📋 Table of contents

- [1. Adding a New IOC Provider](#1--adding-a-new-ioc-provider)
- [2. Adding a New AI Backend](#2--adding-a-new-ai-backend)
- [3. Adding a New API Endpoint](#3--adding-a-new-api-endpoint)
- [4. Adding a Database Migration](#4--adding-a-database-migration)

---

## 1. 🔌 Adding a New IOC Provider

Every provider is a subclass of `BaseProvider` (`backend/app/providers/base.py`), instantiated once as a module-level singleton and listed in `backend/app/providers/registry.py`. The orchestrator, correlation engine, and API layer never branch on which concrete provider answered — they only call the shared interface — so a fully working new connector is, by design, a self-contained, two-file change: the new connector module, plus one import and one list entry in `registry.py`.

**Choose a template.** For a keyless connector with a single simple HTTP GET, use `backend/app/providers/nvd.py` (`NVDProvider`): `requires_key = False`, `self.configured = True` set unconditionally in `__init__`, and a `fetch()` that is one `httpx.AsyncClient.get()` call, a 404-to-`NO_DATA` branch, and a `_map()` helper building the normalized `data` dict. For a provider requiring an API key sent as a header, use `backend/app/providers/virustotal.py` or `abuseipdb.py` — both read their key via `get_credential(provider_id, field_name, settings.<field>_api_key)` (`app/core/runtime_context.py`) rather than calling `get_settings()` directly, which is what makes the key hot-swappable at runtime. For a DNS-only connector with no HTTP call at all, use `backend/app/providers/stubs/spamhaus.py`.

**Implement the class.** At minimum, declare the class-level attributes `BaseProvider` expects and implement one async method:

| Attribute / method | Type | Example (`nvd.py`) |
|---|---|---|
| `provider_id` | `str`, unique in the registry | `"nvd"` |
| `provider_name` | `str`, human-readable | `"NIST NVD"` |
| `category` | `ProviderCategory` enum (`base.py`) | `ProviderCategory.VULNERABILITY` |
| `supported_types` | `set[IOCType]` (`app/ioc/types.py`) | `{IOCType.CVE}` |
| `requires_key` | `bool` | `False` |
| `configured` | `bool` | `True` |
| `base_url` | `str` | `"https://services.nvd.nist.gov/rest/json/cves/2.0"` |
| `async fetch(self, ioc_value, ioc_type, client) -> ProviderResult` | method | — |

`fetch()` must return a `ProviderResult` with `status` one of `OK`, `NO_DATA`, `ERROR`, `TIMEOUT`, `RATE_LIMITED`, or `UNSUPPORTED_IOC` — never raise for an expected "nothing found" case; return `NO_DATA` instead. Any `httpx.HTTPStatusError` that escapes `fetch()` is caught one layer up in `BaseProvider.run()` and mapped to `RATE_LIMITED` for HTTP 429/403/509 or `ERROR` otherwise, so a plain `response.raise_for_status()` needs no local try/except. Do **not** implement retry/backoff inside `fetch()` — that is applied uniformly in `backend/app/providers/orchestrator.py` (`asyncio.wait_for` + `tenacity`).

If the provider needs a credential, read it with `get_credential()`, not `get_settings()`:

```python
from app.core.runtime_context import get_credential
api_key = get_credential("my_new_provider", "api_key", settings.my_new_provider_api_key)
```

This is the pattern every keyed provider uses, and is what allows the credential to be swapped in per-investigation from the runtime-config database (via the `ContextVar` snapshot set in `orchestrator.py`) rather than being frozen at process start. The fallback field (`settings.my_new_provider_api_key`) must exist on `Settings` in `backend/app/core/config.py`, following the naming convention of `virustotal_api_key`/`nvd_api_key`; it is only used before the runtime-config table has been seeded, or if no runtime override exists yet for that provider.

**Register the provider** in `backend/app/providers/registry.py`:

```python
from app.providers.my_new_provider import my_new_provider

_ALL_PROVIDERS: list[BaseProvider] = [virustotal_provider, ..., my_new_provider]
```

That single list is the only place the orchestrator, `GET /api/v1/providers/health`, and `GET /api/v1/runtime/ioc-providers` look.

**Register credential fields (if keyed).** Add an entry to `IOC_PROVIDER_CREDENTIAL_FIELDS` in `backend/app/core/runtime_config.py` — `{"my_new_provider": ["api_key"]}` — which drives the dynamic field list on the Manage Providers UI's IOC Providers tab (`GET /api/v1/runtime/ioc-providers` appends `credential_fields = svc.IOC_PROVIDER_CREDENTIAL_FIELDS.get(provider_id, [])` to each row). Omitting it still lets the provider be enabled/disabled from the UI, but renders no credential input. For backward compatibility with an existing `.env` value, also add a matching entry to `_ENV_SEED_MAP` in the same file.

**Add a live connection test (optional but expected for keyed providers).** `backend/app/providers/connection_test.py` holds per-provider test handlers, dispatched from `POST /api/v1/providers/{provider_id}/test` — this powers the wizard's and Manage Providers UI's "Test" button, making one real outbound call with the *candidate* credentials from the request body, never the saved ones. A provider with no handler simply reports it requires no credential, as happens today for `crtsh`, `cisa_kev`, `mitre_attack`, `whois_rdap`, `spamhaus`, and `internet_intelligence`.

Nothing else needs to change: the orchestrator, correlation engine, evidence builder, and every API route operate purely off the `BaseProvider` interface and the `_ALL_PROVIDERS` list — exactly the guarantee `registry.py`'s module docstring states: "adding a new provider is a two-line change (import + append) and never touches the orchestrator, API routes, or correlation engine."

---

## 2. 🤖 Adding a New AI Backend

All eleven existing AI backends (Ollama, Anthropic, Bedrock, Gemini, Groq, OpenAI, Kimi, DeepSeek, xAI, Mistral, OpenRouter) expose an identical async contract, defined structurally as the `_AIClient` `Protocol` in `backend/app/ai/service.py`:

```python
class _AIClient(Protocol):
    is_configured: bool
    async def call_claude_json(
        self, system_prompt: str, user_prompt: str, json_schema: dict,
        tool_name: str = ..., max_tokens: int | None = ...,
    ) -> dict: ...
```

Nothing in `ai/service.py`, `ai/analysis_service.py`, or `ai/hunting_service.py` branches on which backend is active beyond resolving *which* client to construct.

**Implement the client class.** Create `backend/app/ai/my_backend_client.py` following `anthropic_client.py` (simplest real HTTP example) or `groq_client.py` (if the target API is OpenAI-tool-calling-compatible). It needs: a constructor `MyBackendClient(api_key: Optional[str] = None, model_id: Optional[str] = None, max_tokens: Optional[int] = None)` with every argument optional (falling back to `get_settings()` when omitted) — this dual mode is what lets `_build_client()` construct either a fresh, explicitly-credentialed instance or the legacy settings-derived singleton from the same class; an `is_configured` property; a `call_claude_json()` that forces structured JSON matching `json_schema` via whatever mechanism the backend supports — a forced tool call (Anthropic, Bedrock, Groq), a schema-constrained JSON response format (Gemini), or grammar-constrained decoding (Ollama's `format` field), flattening `$ref`/`$defs` first with `inline_refs()` (`app/ai/schema_utils.py`) if the schema dialect needs it; and a module-level singleton getter `get_my_backend_client()` mirroring `get_anthropic_client()`/`get_groq_client()`, returned by `_build_client()` when called with `credentials=None`. On any failure, raise `RuntimeError` — never return a partial or `None` result, since every caller treats `RuntimeError` as the uniform "this backend failed" signal.

**Wire it into `_build_client()`** in `backend/app/ai/service.py`:

```python
if backend == "my_backend":
    from app.ai.my_backend_client import MyBackendClient, get_my_backend_client
    if credentials is None:
        return get_my_backend_client()
    return MyBackendClient(api_key=credentials.get("api_key"), model_id=model_id)
```

This is called from `_get_ai_client()`, the single 3-tier backend-resolution point used everywhere: explicit `backend_override` → the active runtime-configured backend (fresh DB read via `runtime_config.get_active_ai_config()`) → the legacy frozen `settings.ai_backend`. A fresh client instance is deliberately constructed on every call (never a cached singleton) so switching backends takes effect on the very next AI call, with no restart.

**Register the backend name and its env-seed mapping.** Add `"my_backend"` to `AI_BACKENDS` in `backend/app/core/runtime_config.py` — `POST /api/v1/runtime/ai-active` validates against this list, so without this entry the backend can never become active and the route returns `400 f"Unknown AI backend {backend!r}"`. Then add an entry to `_AI_ENV_SEED_MAP` in the same file so an existing `.env` value is picked up once, on first startup, by `seed_from_env_if_empty()` (idempotent — only runs when `provider_runtime_configs` has zero rows, from `main.py`'s startup hook; it will not backfill a row added after the table already has data — configure such a backend once via the Manage Providers UI instead):

```python
AI_BACKENDS = ["ollama", "anthropic", "bedrock", "gemini", "groq", "my_backend"]
_AI_ENV_SEED_MAP = {..., "my_backend": {"credentials": {"api_key": "my_backend_api_key"}, "model": "my_backend_model_id"}}
```

The referenced `my_backend_api_key`/`my_backend_model_id` fields must exist on `Settings`.

**Update `_model_id_for_backend()`** in `ai/service.py` — its dict literal maps backend name to default model setting for AI-result traceability; add `"my_backend": settings.my_backend_model_id` alongside the other four.

**Live connection test and model listing (recommended).** Mirror the existing pattern in two files: `backend/app/ai/connection_test.py` (add a `_check_my_backend(credentials, model)` handler, register it in `test_ai_connection()`'s `handlers` dict, reached from `POST /api/v1/ai/test`, testing candidate credentials only) and `backend/app/api/routes/ai_config.py` (add `"my_backend"` to `_STATIC_MODEL_LISTS`, or implement live discovery in `POST /api/v1/ai/{backend}/models` following Groq's live `GET /models` or Ollama's live `GET {base_url}/api/tags`).

**Frontend mirror.** `frontend/lib/types.ts` and `lib/api.ts` do not introspect `AI_BACKENDS` — they are a manually-maintained mirror. Add the new name wherever the existing five are enumerated (e.g. `frontend/app/providers/page.tsx`, `AiQuickSwitch`), or it will be fully functional server-side but unreachable from the UI.

---

## 3. 🌐 Adding a New API Endpoint

Every route lives under `backend/app/api/routes/`, one file per resource area, registered exactly once in `backend/app/main.py`. The simplest existing router to use as a template is `backend/app/api/routes/pivot.py` — one `GET` route, one permission check, one 404 case.

**Create or extend a router file.** For a new resource area, create `backend/app/api/routes/my_resource.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from app.auth.rbac import CurrentUser, require_permission
from app.core.db import get_db

router = APIRouter(prefix="/my-resource", tags=["my-resource"])

@router.get("/{item_id}")
async def get_item(item_id: str, db=Depends(get_db),
                    user: CurrentUser = Depends(require_permission("my_resource:read"))):
    ...
```

For a new operation on an *existing* resource, add the function to the existing file (`cases.py`, `lookup.py`, etc.) instead — the pattern every multi-endpoint file already follows (all eight `cases.py` endpoints share one `router` and its `_load_case()` helper).

**Gate it with `require_permission(...)`.** This dependency factory (`backend/app/auth/rbac.py`) first resolves `get_current_user` (Bearer JWT, `401` if missing/invalid/inactive), then checks `permission in ROLE_PERMISSIONS.get(user.role, set())`, raising `403` otherwise. If the permission string doesn't already exist, add it to `ROLE_PERMISSIONS` in `backend/app/models/user.py`:

```python
ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: {..., "my_resource:read", "my_resource:write"},
    Role.ANALYST: {..., "my_resource:read"},
    Role.VIEWER: {..., "my_resource:read"},
}
```

This dict is the single source of truth for the entire authorization matrix. Only `/auth/register`, `/auth/login`, `/auth/refresh` (fully public) and `/auth/me` (bare `get_current_user`, no specific permission) skip this dependency.

**Define request/response Pydantic schemas** in `backend/app/schemas/` (e.g. `basket.py`, `case.py`, `lookup.py`) — separate from the AI-output schemas in `app/ai/schemas.py`/`app/ai/analysis_schemas.py`, which describe what an AI call must emit, not what the HTTP API accepts. Follow the existing plain-`BaseModel` style. Some endpoints deliberately accept a raw untyped `dict` instead (Copilot's `{"question": str, "notes": list[str]}` in `analysis.py`, basket-compare's `{"lookup_ids": list[str]}` in `basket.py`) — an accepted pattern for small, rarely-reused bodies, but a typed `BaseModel` is preferable for anything larger, since Pydantic then returns an automatic `422` on a bad shape.

**Register the router in `main.py`**, in the same style as the existing fifteen:

```python
from app.api.routes import (
    admin, ai_config, analysis, auth, basket, cases, dashboard, hunting,
    lookup, my_resource, pentest, pentest_exploit, pivot, providers,
    runtime, security_assessment,
)
app.include_router(my_resource.router, prefix=settings.api_v1_prefix)
```

`settings.api_v1_prefix` (`"/api/v1"`) is applied uniformly here — the router's own `prefix=` only needs the resource-relative path. There is no other registration step: FastAPI derives the OpenAPI schema and Swagger UI (`/docs`) from whatever is registered here.

**Update the frontend contract.** Add the call to `frontend/lib/api.ts` (the frontend's sole backend client) and the response shape to `frontend/lib/types.ts` (a hand-maintained mirror of the backend Pydantic schemas, explicitly commented as needing to stay in sync). Nothing enforces this automatically.

---

## 4. 🐘 Adding a Database Migration

Schema changes are managed with **Alembic** (`backend/alembic/`) against SQLAlchemy 2.0 async models. The migration history is a single linear chain of twelve revisions today: `660d2aa3bc20` (initial schema) → `a6d3ad2bb63c` (evidence, basket, case management) → `0f2dc283823e` (provider runtime config, audit log) → `2652d888a33f` (final assessment records) → `7a1c2f9d4e6b` (user last-login timestamp) → `3b9e7a2c1d4f` (user token version) → `5c8e1f3a9b2d` (security assessment tables) → `6d2f4b8e1a7c` (evidence provenance category) → `6716ed40b9f2` (final assessment AI outcome) → `8f4a1c2d9e6b` (cancelled security-assessment status) → `9273d7b21c79` (Pentest Suite tables) → `9123b075e962` (Pentest Suite exploit-attempts table, current head).

**Change the model.** Edit the relevant file under `backend/app/models/`. If it's a new table in a new module, make sure the module is imported from `backend/app/models/__init__.py` — its sole purpose is importing every model module so `Base.metadata` is fully populated before Alembic looks at it; a model class that exists but is never imported is invisible to autogenerate.

**Generate the migration** from `backend/`, with the database reachable (`Settings.database_url`, read by `alembic/env.py`):

```bash
cd backend
alembic revision --autogenerate -m "describe your change"
```

This produces a new file in `backend/alembic/versions/`, whose `down_revision` Alembic sets automatically to the current head (`9123b075e962` as of this writing). **Always open and read the generated file before applying it** — autogenerate diffs model metadata against the database's current shape column-by-column, but does not reliably detect every kind of change (a column rename shows up as a drop-and-add unless hand-edited to `op.alter_column`) and never writes data-migration logic for you.

**Apply it:**

```bash
alembic upgrade head
```

This is exactly the command every container in this platform already runs on every startup, before the application server: both `docker-compose.yml` and `docker-compose.prod.yml` set the backend service's `command` to `sh -c "alembic upgrade head && uvicorn app.main:app ..."`. The running database's `alembic_version` table always records exactly which migration it was last brought up to date with — which is also the root of the Windows-packaging gotcha below.

**The Windows installer "Can't locate revision" gotcha.** This project's Windows installer does not run the application out of the git working tree. `windows/installer.iss` copies the entire `backend/` directory — including `backend/alembic/versions/*.py` — into the installed Program Files tree at install time (`Source: "{#RepoRoot}backend\*"; DestDir: "{app}\app\backend"; ...`). `windows/scripts/Common.ps1` documents the resulting split: read-only application code under Program Files (`$script:InstallDir`), writable runtime data under `C:\ProgramData\IOC Intelligence Platform\` (`$script:DataDir`). In production, `docker-compose.prod.yml` additionally strips every bind-mount from the backend service (`volumes: !reset []`) and rebuilds the backend image from scratch (`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`) — so the installed container's copy of `alembic/versions/` is baked into its image from whatever `.py` files existed in the **Program Files** copy at build time, not from the developer's working tree.

> [!WARNING]
> The failure mode: a new migration generated and applied (steps above) against a database from
> one copy of the code advances that database's `alembic_version` row to the new revision hash.
> If the *installed* Program Files copy of `backend/alembic/versions/` isn't also updated with
> that same `.py` file — by copying it in directly, or by rebuilding and reinstalling the
> installer — before that installed stack's backend container is next rebuilt or restarted,
> Alembic has no script matching the revision hash already recorded in the database. Because both
> compose files run `alembic upgrade head` as the very first step of the container's startup
> command, before `uvicorn` ever starts, this is not a soft failure: the entrypoint fails
> immediately with Alembic's `Can't locate revision identified by '<hash>'` error, and the backend
> never comes up, taking `uvicorn` down with it since the two commands are chained with `&&`.
>
> **The practical rule:** every new file added to `backend/alembic/versions/` must reach every
> deployed copy of the application before, or at the same time as, any database that copy talks to
> is upgraded to that revision — by rebuilding and reinstalling the Windows installer package
> (which re-copies the current `backend/` tree per `installer.iss`), or, for a manual hotfix, by
> placing the new migration file directly into `{app}\app\backend\alembic\versions\` under Program
> Files and rebuilding the backend image before restarting the container.

| Order | Revision | Down-revision | Created |
|---|---|---|---|
| 1 | `660d2aa3bc20` | (root) | `users`, `ioc_lookups`, `ai_summaries`, `correlation_edges`, `provider_results` |
| 2 | `a6d3ad2bb63c` | `660d2aa3bc20` | `cases`, `basket_items`, `case_iocs`, `case_notes`, `case_reports`, `evidence_items` |
| 3 | `0f2dc283823e` | `a6d3ad2bb63c` | `config_audit_log`, `provider_runtime_configs` |
| 4 | `2652d888a33f` | `0f2dc283823e` | `final_assessment_records` |
| 5 | `7a1c2f9d4e6b` | `2652d888a33f` | `users.last_login_at` |
| 6 | `3b9e7a2c1d4f` | `7a1c2f9d4e6b` | `users.token_version` |
| 7 | `5c8e1f3a9b2d` | `3b9e7a2c1d4f` | Security Assessment Toolkit tables |
| 8 | `6d2f4b8e1a7c` | `5c8e1f3a9b2d` | Evidence `provenance`/`category` columns |
| 9 | `6716ed40b9f2` | `6d2f4b8e1a7c` | `final_assessment_records`' AI-outcome column |
| 10 | `8f4a1c2d9e6b` | `6716ed40b9f2` | Cancelled security-assessment status |
| 11 | `9273d7b21c79` | `8f4a1c2d9e6b` | Pentest Suite tables (scope, targets, findings, assessment runs) |
| 12 (head) | `9123b075e962` | `9273d7b21c79` | Pentest Suite exploit-attempts table |

A new migration's `down_revision` should always be `9123b075e962` unless a teammate has already generated and merged a different migration first, in which case Alembic requires a merge revision (`alembic merge heads`) — not otherwise seen in this project's history, which has maintained a single linear chain to date.
