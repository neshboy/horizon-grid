# Runtime Configuration and Credential Lifecycle

Every IOC provider connector and every AI backend in this platform needs at least one piece of configuration — usually an API key, sometimes a base URL or model id — before it can do real work. This chapter is the authoritative, line-cited account of where that configuration comes from, how it is stored, and how it is read back at the moment an investigation actually runs, for both of the two credential systems that coexist in this codebase today: the original `.env`-only design, and the encrypted, database-backed runtime layer that was later built on top of it without removing it. No git history exists in this repository (`git status` at the repo root returns `fatal: not a git repository`), so the "before" state below is reconstructed from the legacy code paths that are still present and still load-bearing as a fallback, not from commit history.

## Two Entry Points for a Credential

A credential can enter the running system in exactly two ways:

| Entry point | Destination | Mechanism | Restart required? |
|---|---|---|---|
| Windows Setup Wizard (Welcome → Admin → AI Configuration → Provider Configuration → Ports → Summary → Install) | `.env` file on disk | `Write-PlatformEnvFile` (`windows/scripts/Write-EnvFile.ps1:51`), invoked from `Setup-Wizard.ps1:998–1002` when the user clicks **Start Installation** | Yes — the backend container must (re)start to pick up a `.env` change, because settings are read once into a process-lifetime singleton (see below). |
| "Manage Providers" web UI (`/providers`) → `POST /api/v1/runtime/ai-providers/{backend}` or `POST /api/v1/runtime/ioc-providers/{provider_id}` | `provider_runtime_configs` table in Postgres, Fernet-encrypted | `backend/app/api/routes/runtime.py:38–48` (`configure_ai_provider`, calling `svc.upsert_ai_provider`) and `runtime.py:135–152` (`configure_ioc_provider`, calling `svc.upsert_ioc_provider`); frontend side is `configureAIProvider`/`configureIOCProvider` in `frontend/lib/api.ts:418–423` and `:482–487`, called from `frontend/app/providers/page.tsx:106–174` | No — the very next investigation or AI call after the save picks up the new value. |

Both configuration-mutating endpoints are gated by `require_permission("provider:manage")`. Wizard-collected values are sanitized before being written to disk: `ConvertTo-SafeEnvValue` (`Write-EnvFile.ps1:15–49`, applied to every field at `:62–66`) strips carriage returns/newlines and rejects any value containing `#`, since an unescaped `#` starts a comment in `.env` syntax and would silently truncate the rest of the line.

A third, deliberately non-persisting action exists on both sides: `POST /api/v1/providers/{provider_id}/test` (`backend/app/api/routes/providers.py:20–36`) and `POST /api/v1/ai/test` (`backend/app/api/routes/ai_config.py:39–56`) each make one real, minimal outbound call using whatever credential is currently sitting in the request body — never a value already saved anywhere — and never write it to `.env` or to the database. These are the endpoints behind every "Test Connection" button in both the wizard and the web UI.

## The Legacy Design: a Frozen Settings Singleton

Before the runtime layer existed, every provider's and every AI backend's configuration was `.env`-driven and fixed for the entire lifetime of the running backend process:

- `app/core/config.py:13` defines `class Settings(BaseSettings)` (pydantic-settings), populated once from `.env` and the process environment.
- `app/core/config.py:110–111` wraps construction in `@lru_cache def get_settings()` — the first call builds the one and only `Settings` instance for the process; every subsequent call anywhere in the codebase returns that same object, forever, until the process restarts.
- Each provider computed its own `configured` boolean **once, at module-import time**, directly from that frozen singleton — e.g. VirusTotal's connector reads `bool(get_settings().virustotal_api_key)` in its constructor. There was no code path that ever re-evaluated this flag after the process started.

The practical consequence: editing `.env` — whether by hand or via the wizard — had no effect on a backend process that was already running. This is the entire reason the runtime-config system described in the rest of this chapter exists, and it is also the exact root cause of a specific, documented behavioral gap covered in its own section below.

## The Current Design: Encrypted, Database-Backed, Runtime-Mutable

### Storage: `provider_runtime_configs`

`backend/app/models/runtime_config.py:30–55` defines `ProviderRuntimeConfig`, one row per `(kind, provider_id)` pair (`kind` is `ai` or `ioc`; unique constraint at `runtime_config.py:32`). The column that matters most for this chapter is `encrypted_credentials: Mapped[Optional[str]]` (`runtime_config.py:42`) — a `TEXT` column that only ever holds Fernet ciphertext, never plaintext. Alongside it: `enabled`, `is_active` (meaningful only for AI rows — exactly one AI row is meant to be active at a time, enforced in application code, not a database constraint), `model_id`, `extra_config` (JSONB, for non-secret extras such as a custom endpoint URL), `last_test_at`/`last_test_ok`/`last_test_message` (so the UI can show "last tested" status without re-testing), and `updated_by` (FK → `users.id`).

A second table, `config_audit_log` (`runtime_config.py:58–75`), records every configure/enable/disable/activate/test-result action: `timestamp`, `actor_user_id` (FK → `users.id`), a denormalized `actor_email` (so the log stays readable even if the account is later deleted), `action`, and a free-text `detail` field. The write path for `detail` only ever accepts descriptive text — it is not a location where a credential value can end up. `GET /api/v1/runtime/audit-log` (`runtime.py:185`, `require_permission("audit:read")`) exposes this table.

### Encryption: `app/core/crypto.py`

Credentials are Fernet-encrypted (symmetric, `cryptography.fernet.Fernet`) before they are written anywhere:

- `encrypt_secret()` (`crypto.py:49–54`) returns Fernet ciphertext, or `""` for falsy input.
- `decrypt_secret()` (`crypto.py:57–67`) returns `""` on any `InvalidToken` rather than raising — a corrupted or key-mismatched ciphertext degrades to "no credential" instead of crashing a request.
- The Fernet key itself comes from `_fernet()` (`crypto.py:39–46`): an explicit `encryption_master_key` setting (`config.py:30`) if the operator has set one, otherwise an HKDF-derived key from the existing `jwt_secret_key` (`config.py:23`, derivation at `crypto.py:33–36`). The HKDF fallback means every pre-existing installation already has a working encryption key with no migration step — but it also means that, absent an explicit `encryption_master_key`, compromising `jwt_secret_key` would expose the derived encryption key too. Operators wanting independent key separation must set `encryption_master_key` explicitly.
- `mask_secret()` (`crypto.py:70–77`) produces the `****…abcd`-style preview the UI displays; `_row_to_public_dict` (`runtime_config.py:167`) is the only place a stored credential is ever rendered back to a caller, and it always goes through this masking — no API response returns a decrypted credential.

`upsert_ai_provider` (`runtime_config.py:237`) and `upsert_ioc_provider` (`runtime_config.py:357`) both merge the incoming `credentials` dict onto whatever is already decrypted and stored (`_merge_credentials()`, `runtime_config.py:121–140`) before calling `encrypt_secret(json.dumps(merged))` and assigning `row.encrypted_credentials` — the encryption step happens on every write, with no unencrypted code path. The merge (rather than a blind overwrite) matters specifically because the settings UI's per-field inputs only ever populate a field the operator actually retypes that session — a plain overwrite with an empty or partial payload used to silently wipe whichever fields weren't retyped; see the regression tests in `app/tests/unit/test_runtime_config.py` and `app/tests/integration/test_runtime_config_persistence.py`.

### Bridging old installs: `seed_from_env_if_empty()`

`runtime_config.py:443–493` copies the legacy `.env` values into the new table exactly once, the first time it ever runs on a given database: if `provider_runtime_configs` already has any row at all, it is a no-op (`:454–455`, so it never overwrites a value an administrator has already configured through the UI); otherwise, for each of the 11 AI backends (`_AI_ENV_SEED_MAP`, `:62–76`) and each of the 18 registered IOC providers (`_ENV_SEED_MAP`, `:49–60`, sourced from `app.providers.registry.get_all_providers()`), it reads the matching field off `get_settings()` and inserts a pre-encrypted row (`:458–472`, `:476–488`). It is invoked once per process start, from `app/main.py:50–58` (`@app.on_event("startup") async def _seed_runtime_config()`), wrapped in a try/except so a seeding failure never blocks boot (`main.py:59–60`). The function's own docstring states it is "idempotent and safe to call on every startup" (`runtime_config.py:448`) — this is what lets an existing `.env`-configured deployment upgrade to the new system without losing its working credentials or requiring a manual one-time migration script.

### The Runtime API Surface

All ten endpoints below live in `backend/app/api/routes/runtime.py`, prefix `/api/v1/runtime`:

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /ai-providers` | `provider:manage` | List every AI backend's persisted runtime row (masked credentials). |
| `POST /ai-providers/{backend}` | `provider:manage` | Persist credentials/model for one AI backend (`svc.upsert_ai_provider`). |
| `POST /ai-active` | `provider:manage` | Switch the platform-wide active AI backend immediately. |
| `GET /ai-active` | `lookup:read` | Read the currently active AI backend + model. |
| `POST /ai-providers/{backend}/record-test` | `provider:manage` | Record a prior `/ai/test` outcome against the saved row. |
| `GET /ioc-providers` | `provider:manage` | List every known IOC provider merged with its runtime row (or a synthesized default). |
| `POST /ioc-providers/{provider_id}` | `provider:manage` | Persist credentials/extra config for one IOC provider. |
| `POST /ioc-providers/{provider_id}/enabled` | `provider:manage` | Enable/disable a provider platform-wide, effective on the next investigation. |
| `POST /ioc-providers/{provider_id}/record-test` | `provider:manage` | Record a prior `/providers/{id}/test` outcome. |
| `GET /audit-log` | `audit:read` | Retrieve the `config_audit_log` history. |

## Live Retrieval at Investigation Time: Two Different Mechanisms

Reading a credential back at the moment it is needed is handled differently for IOC providers than for AI backends, and the difference is deliberate.

### IOC providers: a per-investigation `ContextVar` snapshot

Every IOC provider connector (`app/providers/*.py`) is instantiated exactly once at import time and reused as a long-lived module-level singleton for the entire life of the process (`app/providers/registry.py`). That singleton is shared by every concurrent investigation the backend is handling at any given moment — which makes it unsafe to mutate directly.

**Why a naive "mutate the singleton" approach would be a concurrency bug:** if an administrator's `POST /ioc-providers/{id}` call (or the enable/disable toggle) simply wrote the new credential/enabled state onto the shared provider instance's own attributes, then two investigations in flight at the same time — one that started just before the change and is still mid-flight, another that starts just after — would both read from the *same* mutable object. There is no guarantee which investigation's provider task executes its credential read before or after the write lands, so the in-flight investigation could non-deterministically pick up the *new* credential mid-run (attributing its results to the wrong configuration state), or the administrator's own just-saved change could be transiently overwritten if two admin requests raced each other. Either way, "investigation A used configuration X" would stop being a reliable statement.

The fix is `app/core/runtime_context.py`, which never mutates the provider objects at all:

1. `_provider_overrides` (`runtime_context.py:19–21`) is a `contextvars.ContextVar[Optional[dict]]`, not an attribute on any provider.
2. At the start of every single investigation, before any per-provider task is spawned, `run_all_providers()` (`app/providers/orchestrator.py:112–113`) does exactly one fresh Postgres read — `snapshot = await get_ioc_provider_snapshot()` (`runtime_config.py:336–354`) — and calls `set_provider_overrides(snapshot)` to bind that snapshot into the current context.
3. Immediately after, `orchestrator.py:120` calls `asyncio.create_task()` once per eligible provider. Because `asyncio.create_task()` copies the *current* `contextvars.Context` into every task it spawns, every concurrent per-provider task belonging to that one investigation inherits the identical, frozen snapshot — regardless of what any administrator does to the underlying table while those tasks are still running. This is the concurrency-safety property the module's own docstring states outright (`runtime_context.py:1–14`).
4. `BaseProvider.run()` (`app/providers/base.py:104–111`) reads the override for its own `provider_id` from that context (`get_provider_override(self.provider_id)`); if the effective `configured` is false, it short-circuits (`base.py:135–146`) with `ProviderStatus.NOT_CONFIGURED` and the message `f"{self.provider_name} is not configured (missing API key/credentials)."` (`base.py:143`) before making any outbound call.
5. Inside `fetch()`, each connector reads its actual credential value through `get_credential(provider_id, field, fallback)` (`runtime_context.py:38–47`) — e.g. `app/providers/virustotal.py:44`: `api_key = get_credential("virustotal", "api_key", settings.virustotal_api_key)`. It returns the per-investigation override if one was set, otherwise the legacy `.env`-derived value, so an unconfigured runtime row degrades gracefully to whatever `Settings` still holds.

One immutable snapshot per investigation, read-only for the duration of that investigation, is the entire mechanism — no locking is needed because nothing shared is ever written to after the snapshot is taken.

### AI backends: a fresh client per call, not a `ContextVar`

The AI path does not need the snapshot pattern at all, because it takes a simpler route: it never keeps a long-lived, shared, mutable client instance in the request path in the first place. `_get_ai_client()` (`app/ai/service.py:102–145`) resolves the backend in three tiers — an explicit `backend_override` argument (used only by the AI-comparison "re-analyze with a different backend" feature, `service.py:125–126`) → the active runtime config, read fresh from Postgres on **every single call** via `get_active_ai_config()` (`service.py:128`, backed by `runtime_config.py:200–215`, which is not cached) → the legacy `Settings` singleton as a final fallback if no runtime row exists yet (`service.py:134–138`). `_build_client()` (`service.py:56–99`) then constructs a **brand-new client instance** for that one call — e.g. a fresh `AnthropicClient(api_key=..., model_id=...)` (`app/ai/anthropic_client.py:25–39`) — deliberately bypassing the module-level frozen singleton client (`get_anthropic_client()`, `anthropic_client.py:93–97`) that only reflects `Settings`. Because every call re-reads the database and rebuilds its own client from that read, switching the active AI backend via `POST /api/v1/runtime/ai-active` takes effect on the very next AI call made by *any* investigation, with no restart and no shared mutable state to protect. If the resolved client's `is_configured` is false, the call fails loudly: `RuntimeError(f"AI backend '{backend}' is not configured (missing API key/URL/model) -- configure it from the AI Providers panel or check .env")` (`service.py:140–144`).

## A Real, Documented Historical Bug: "Test Connection: SUCCESS" but the Investigation Still Failed

The codebase and its accompanying repo-root reports independently corroborate one specific, real architectural bug that predates the runtime-config system, distinct from the mechanisms above.

**Root cause.** `app/providers/connection_test.py`'s own module docstring (`:1–16`) states it plainly: connection-test handlers are "deliberately separate from the `BaseProvider.fetch()` code path," because `fetch()` reads the frozen `get_settings()` singleton (fixed for the process's lifetime), so there was no safe way to test a key the user had just typed into a form without either restarting the process or mutating shared global state under concurrent requests — so the test handlers make one real HTTP call with the *candidate* key and never touch `get_settings()` at all. Meanwhile, before the runtime-config system existed, each provider's `configured` flag was computed exactly once, at module-import time, from that same frozen singleton (e.g. `virustotal.py:24–26`: `self.configured = bool(get_settings().virustotal_api_key)`). The result: `POST /api/v1/providers/{id}/test` would correctly report success the instant a valid key was typed in — because it bypassed `get_settings()` — while a real investigation, routed through `BaseProvider.run()`, still saw the `configured` value frozen at process start. If the wizard wrote a new key to `.env` while the backend process was already running (the normal case, since Test Connection is meant to happen *before* a restart), the live investigation kept reporting `ProviderStatus.NOT_CONFIGURED` / `"is not configured (missing API key/credentials)"` immediately after a successful Test Connection.

This is independently confirmed in three separate, git-independent artifacts: `docs/PROVIDERS.md:375–378` ("Setting an API key in `.env` after the backend process has started will not retroactively flip `configured` for that provider — a process restart is required"), `docs/TROUBLESHOOTING.md:96–134` (same root cause under "A provider shows `not_configured`"), and `RUNTIME_PROVIDER_IMPLEMENTATION_REPORT.md:11–12` at the repo root ("Every AI backend, every provider's credential, and every 'configured' flag was read from this frozen snapshot... This was confirmed as the sole root cause \[of the original limitation\], not scattered logic, before any code was written.").

**The fix** is exactly the two mechanisms documented above in this chapter: the `ContextVar`-based per-investigation snapshot (`runtime_context.py`, fed by a fresh DB read in `orchestrator.py:112`) replaced the frozen `self.configured` as the value `base.py:109` actually checks, and `ai/service.py`'s `_get_ai_client()` replaced the frozen AI-client singleton with a fresh DB read plus a freshly-built client on every call. A credential saved through the Manage Providers UI today is therefore picked up by the very next investigation with no restart — closing the gap described above.

**Two things worth flagging so this is not overstated.** First, a *different* bug, with the opposite symptom (Test Connection *failing* despite a genuinely valid key), also exists and is separately self-documented in this codebase: every Test Connection button's request in the wizard required a session token (`$State.AccessToken`) that was previously only ever set inside the Summary page's "Start Installation" handler (`Setup-Wizard.ps1:211–236`, marked with an in-code "ROOT CAUSE" comment), so on a reconfigure run with no fresh login every Test Connection click failed with a "create the administrator account first" message even though the account and platform were already running — fixed by `Get-OrCreateWizardSession` (`Setup-Wizard.ps1:237–253`) and documented in `API_CONFIGURATION_FIX_REPORT.md:15–30` at the repo root. This is a distinct bug from the frozen-settings issue above and should not be conflated with it. Second, `test-provider-pipeline.sh` at the repo root contains a comment describing itself as reproducing "the reported 'API key test' bug using the REAL key already configured in the running container's own environment"; the script itself only re-runs `POST /providers/{id}/test` with various keys, and no further write-up tying that specific script to a named root cause was found beyond the frozen-settings-singleton issue documented above — it is noted here as existing evidence of *some* reported issue along these lines, not asserted to be definitively the same bug.

For completeness: the exact phrase "API key not provided" does not appear anywhere in this codebase's source or documentation (confirmed by a case-insensitive search of `backend/app`, `docs/`, `documentation/`, and `windows/`, excluding vendored dependencies). The real, verified error strings are `f"{self.provider_name} is not configured (missing API key/credentials)."` (`base.py:143`) and `f"AI backend '{backend}' is not configured (missing API key/URL/model) -- ..."` (`service.py:141–144`).

## Before / After Summary

| Aspect | Legacy (`.env` only) | Current (runtime-config layer) |
|---|---|---|
| Storage | Plaintext in `.env` on disk | Fernet-encrypted ciphertext in `provider_runtime_configs.encrypted_credentials` |
| Read by application code | `get_settings()`, an `@lru_cache` singleton fixed for the process's lifetime | Fresh Postgres read per investigation (IOC providers) or per AI call (AI backends) |
| Effect of a change | Requires editing `.env` and restarting the backend container | Effective on the very next investigation/AI call, no restart |
| Concurrency safety mechanism | None needed/possible — value never changed at runtime | `ContextVar` snapshot per investigation (IOC) / fresh client construction per call (AI) |
| Audit trail | None | `config_audit_log` table, one row per configure/enable/disable/activate/test-result action |
| Still in use today? | Yes — `Settings` remains the fallback when no runtime row exists, and is what `seed_from_env_if_empty()` reads from | Yes — the primary path once any row exists |

## Diagram

[FIGURE: dev-05-runtime-configuration-and-credentials-diagram-1.png | Diagram: Diagram]
Diagram: Credential lifecycle from wizard/UI entry through encrypted storage to per-investigation retrieval. Each investigation binds one immutable snapshot to its own `contextvars.Context` before spawning provider tasks, so two investigations racing across a credential change each see a single consistent configuration for their whole run -- never a mix of old and new mid-flight.
