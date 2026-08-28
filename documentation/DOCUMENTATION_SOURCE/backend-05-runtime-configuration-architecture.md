# Runtime Configuration Architecture

Every provider credential, every AI backend key, and the choice of which AI backend is active right now are all governed by one subsystem: the runtime configuration layer built around `backend/app/core/runtime_config.py`, `backend/app/core/runtime_context.py`, and the `provider_runtime_configs` / `config_audit_log` tables. This chapter is the authoritative reference for that subsystem because nearly every operational question a backend engineer or security reviewer will eventually ask — where does this API key live, will changing a key require a restart, can two investigations racing at once see two different credentials, what happens to configuration if the container is destroyed and recreated — is answered here.

The short version, expanded in full below: configuration used to be a frozen, `.env`-derived, process-lifetime singleton (`app/core/config.py`'s `@lru_cache`'d `get_settings()`). It has been replaced, without removing that legacy path, by a database-backed store that is read fresh on every relevant call, encrypted at rest, and audit-logged. The legacy path still exists as a fallback for installs that have never touched the new system.

## 📋 Table of contents

- [Two ways configuration enters the system](#-two-ways-configuration-enters-the-system)
- [Where configuration is stored](#-where-configuration-is-stored)
- [Protecting the secrets themselves](#-protecting-the-secrets-themselves)
- [Bridging existing .env installs: seed_from_env_if_empty()](#-bridging-existing-env-installs-seed_from_env_if_empty)
- [How configuration is loaded — the part that actually matters](#-how-configuration-is-loaded--the-part-that-actually-matters)
  - [IOC providers: a ContextVar snapshot taken once per investigation](#ioc-providers-a-contextvar-snapshot-taken-once-per-investigation)
  - [AI backends: a fresh client built on every single call, not a snapshot](#ai-backends-a-fresh-client-built-on-every-single-call-not-a-snapshot)
- [How a runtime update actually propagates, step by step](#-how-a-runtime-update-actually-propagates-step-by-step)
- [Why this replaced a frozen-singleton design, and the exact bug that motivated it](#-why-this-replaced-a-frozen-singleton-design-and-the-exact-bug-that-motivated-it)
- [Surviving a restart](#-surviving-a-restart)
- [Audit trail](#-audit-trail)
- [Summary](#-summary)

## 🚪 Two ways configuration enters the system

| Entry point | Where it writes | Who uses it | Restart required? |
|---|---|---|---|
| Windows Setup Wizard (`windows/wizard/Setup-Wizard.ps1`) | `.env` file, via `Write-PlatformEnvFile` (`windows/scripts/Write-EnvFile.ps1:51`) | First-time installers, and anyone re-running the wizard | Yes, implicitly — `.env` is only read once, at process start, by `get_settings()` |
| Manage Providers UI → Runtime API (`POST /api/v1/runtime/ai-providers/{backend}`, `POST /api/v1/runtime/ioc-providers/{provider_id}`) | `provider_runtime_configs` table (Postgres), encrypted | Any admin/analyst with `provider:manage`, at any time after first boot | No |

The wizard path is the one-time bootstrap: `Setup-Wizard.ps1` collects values across its AI Configuration and Provider Configuration pages into `$State.Settings`, then on the Summary page's "Start Installation" click writes them all to `.env` in one pass (`Setup-Wizard.ps1:998-1002`). `Write-EnvFile.ps1:15-49` (`ConvertTo-SafeEnvValue`) strips CR/LF and rejects any value containing `#` before writing, since `#` opens a comment in `.env` syntax and would silently truncate everything after it (`Write-EnvFile.ps1:62-66`). This is the *only* code path that populates `.env` with provider/AI secrets; the backend loads that file once, at import time, through `app/core/config.py`'s `Settings(BaseSettings)` class and its `@lru_cache`'d `get_settings()` accessor (`config.py:110-111`).

The runtime-API path is what makes the platform's "no restart" claim true. The `/providers` page in the frontend (`frontend/app/providers/page.tsx:106-174`) calls `configureAIProvider` / `configureIOCProvider` (`frontend/lib/api.ts:418-423`, `:482-487`), which hit `backend/app/api/routes/runtime.py:38-48` (`configure_ai_provider`) and `runtime.py:135-152` (`configure_ioc_provider`), both gated by `require_permission("provider:manage")` and both delegating to `runtime_config.py`'s `upsert_ai_provider()` / `upsert_ioc_provider()`.

A third, deliberately separate action exists at each layer: **Test Connection** (`POST /api/v1/ai/test`, `POST /api/v1/providers/{id}/test`). It never writes anywhere — it makes one live call using whatever credentials are currently sitting in the form, before the analyst has clicked Save. This "test" vs. "save" distinction is structural, not cosmetic, and is the key to the historical bug discussed later in this chapter.

## 💾 Where configuration is stored

`provider_runtime_configs` (`backend/app/models/runtime_config.py:30-55`) holds one row per `(kind, provider_id)` pair — `kind` is `ai` or `ioc` (`ProviderKind` enum), and the pair is enforced unique by `UniqueConstraint(kind, provider_id, name="uq_provider_runtime_kind_id")` (`runtime_config.py:32`). Relevant columns:

| Column | Purpose |
|---|---|
| `enabled` | IOC providers only, in practice — whether this provider participates in the next fan-out. |
| `is_active` | AI backends only, in practice — exactly one AI row is meant to be active at a time; enforced in application code, not by a DB constraint. |
| `encrypted_credentials` | Fernet ciphertext of a JSON object (e.g. `{"api_key": "..."}`). Never plaintext, never returned by any API response. |
| `model_id` | The selected model for an AI backend, or provider-specific model/tier info. |
| `extra_config` | Non-secret extras (e.g. a custom endpoint URL) as JSONB. |
| `last_test_at` / `last_test_ok` / `last_test_message` | Recorded separately, by the `/record-test` endpoints, after a Test Connection call — not derived automatically from the test itself. |
| `updated_by` | FK to `users.id`. |

A second table, `config_audit_log` (`runtime_config.py:58-75`), is append-only and intentionally has no `created_at`/`updated_at` — it carries its own explicit `timestamp` column, plus `actor_user_id` (FK, nullable), a denormalized `actor_email` (so the log stays readable even if the account is later deleted), `action`, and `detail`. `detail` only ever accepts descriptive text — e.g. "configured AI backend anthropic" — never a credential value; verified by exercising the configure/enable/disable/test/activate flow and grepping the resulting audit rows and backend logs for any real secret, with no hits (see Audit trail below).

## 🔐 Protecting the secrets themselves

Credentials submitted through the runtime API are encrypted before the `upsert_ai_provider()` / `upsert_ioc_provider()` calls persist them: `row.encrypted_credentials = encrypt_secret(json.dumps(credentials))` (`runtime_config.py:234`, `:339`). `encrypt_secret()` / `decrypt_secret()` (`backend/app/core/crypto.py:49-54`, `:57-67`) use `cryptography.fernet.Fernet` — symmetric, authenticated encryption. `decrypt_secret()` returns `""` on any `InvalidToken` rather than raising, so a corrupted or key-mismatched row degrades to "no credential" instead of crashing a request.

The Fernet key itself comes from one of two sources, resolved in `crypto.py:39-46` (`_fernet()`):

1. `settings.encryption_master_key`, if the operator has explicitly set it (`config.py:30`), or
2. an HKDF-derived key from `settings.jwt_secret_key` (`config.py:23`) if no master key is configured (`crypto.py:33-36`, `_derive_key_from_jwt_secret`).

> [!IMPORTANT]
> This fallback is a real, worth-stating tradeoff rather than a hidden detail: it means every existing installation already has a usable encryption key with no migration step, but it is defense-in-depth, not independent key separation — compromise of `jwt_secret_key` also exposes the derived encryption key. An operator who wants the two secrets to be independently rotatable and independently compromised should set `encryption_master_key` explicitly rather than rely on the derived default.

`mask_secret()` (`crypto.py:70-77`) is the only thing the UI is ever shown for an already-saved credential — a `****...`-style preview, used in `_row_to_public_dict` (`runtime_config.py:148`); the plaintext or ciphertext is never returned by any API response.

## 🌱 Bridging existing `.env` installs: `seed_from_env_if_empty()`

An install that has been running purely on `.env` since before this table existed does not start with an empty configuration UI. `seed_from_env_if_empty()` (`runtime_config.py:398-448`) checks whether `provider_runtime_configs` has any rows at all; if it does, it is a strict no-op (`:408-410`). If the table is empty, it walks the eleven AI backends (`_AI_ENV_SEED_MAP`, `:62-76`) and all eighteen registered IOC providers (`_ENV_SEED_MAP`, `:49-60`, sourced from `app.providers.registry.get_all_providers()`), reads each one's corresponding field off the frozen `get_settings()` singleton, and inserts a pre-encrypted row for each (`:417-427`, `:435-443`). It runs once at process startup (`backend/app/main.py:226-236`, the `_seed_runtime_config` startup event — one of four `@app.on_event("startup")` handlers now registered, not the only one; see the Overview and Lifecycle chapter for the other three), wrapped in a try/except so a seeding failure never blocks boot (`main.py:235-236`), and is explicitly documented as idempotent — safe to call on every restart because it only acts on an empty table (`runtime_config.py:404`).

The practical effect: an operator who has only ever used `.env` gets a populated, editable Manage Providers screen the first time they upgrade to a build that has this table, with zero manual data entry — and every subsequent edit through the UI takes over from `.env` for that specific provider/backend from that point forward.

## 🔄 How configuration is loaded — the part that actually matters

This is the section that determines whether "I changed a key" and "the platform used the new key" are the same statement. The platform resolves configuration completely differently depending on whether the caller is an IOC provider or an AI backend, but both share one property: **neither path trusts a value cached in process memory beyond the scope of a single investigation or a single AI call.**

### IOC providers: a `ContextVar` snapshot taken once per investigation

IOC provider connectors (`VirusTotal`, `AbuseIPDB`, etc.) are module-level singletons — one Python object per provider, reused for the life of the backend process (`backend/app/providers/registry.py`). Mutating a shared attribute on that singleton the moment a request needs it would be unsafe under concurrency: two investigations could be in flight at once, one started right after an administrator changed a provider's credentials, one already mid-flight — a naive shared-state write could let them see each other's configuration.

Instead, `run_all_providers()` (`backend/app/providers/orchestrator.py:112-113`) takes one fresh read from the database — `snapshot = await get_ioc_provider_snapshot()` (`runtime_config.py:336-354`) — at the very start of a single investigation's fan-out, and stores it via `set_provider_overrides(snapshot)` into a module-level `contextvars.ContextVar` (`runtime_context.py:19-21`). Because `asyncio.create_task()` copies the current `contextvars.Context` into every task it spawns (`orchestrator.py:120`), every concurrent per-provider task belonging to that one investigation inherits the identical, frozen snapshot — regardless of what happens to the underlying table while those tasks are still running. Two investigations running concurrently, each configured differently, therefore never cross-contaminate.

Each provider's `BaseProvider.run()` reads that snapshot before doing anything else (`backend/app/providers/base.py:104-111`): `override = get_provider_override(self.provider_id)`, and `effective_configured` prefers the override's `configured` flag over the object's own frozen `self.configured`. If the effective state is "not configured," the call short-circuits with `ProviderStatus.NOT_CONFIGURED` and the message `f"{self.provider_name} is not configured (missing API key/credentials)."` (`base.py:143`) — no HTTP call is attempted. If configured, the provider's `fetch()` pulls the actual credential value through `get_credential(provider_id, field, fallback)` (`runtime_context.py:38-47`), which returns the per-investigation override if one exists, otherwise falls back to whatever `.env` provided via `get_settings()` — for example `virustotal.py:44`: `api_key = get_credential("virustotal", "api_key", settings.virustotal_api_key)`.

### AI backends: a fresh client built on every single call, not a snapshot

AI backend resolution goes further than a per-investigation snapshot — it is refreshed on every individual AI call, not once per investigation. `_get_ai_client()` (`backend/app/ai/service.py:102-145`) resolves the backend in this order:

1. an explicit `backend_override` parameter, used only by the AI-comparison / re-analyze feature (`service.py:125-126`);
2. `app.core.runtime_config.get_active_ai_config()` — a fresh database read, every call, no caching (`service.py:128`; the read itself is `runtime_config.py:200-215`);
3. the legacy `Settings`-derived value, only if no runtime config row exists yet (`service.py:134-138`).

Whichever backend wins, `_build_client()` (`service.py:56-99`) constructs a **new client instance** for that call — e.g. `AnthropicClient(api_key=..., model_id=...)` (`anthropic_client.py:25-39`) — using the credentials the DB read just returned, rather than reusing the process-lifetime singleton each client module also exposes (e.g. `get_anthropic_client()`, `anthropic_client.py:93-97`). This is the single design decision that makes "switch the active AI backend, no restart" true in practice: there is no cached client object anywhere holding a stale key or a stale backend choice. If the resolved client's `is_configured` still comes back false, the call raises `RuntimeError(f"AI backend '{backend}' is not configured (missing API key/URL/model) -- configure it from the AI Providers panel or check .env")` (`service.py:140-144`) rather than silently proceeding.

## 📶 How a runtime update actually propagates, step by step

1. An admin submits new credentials for, say, Anthropic on the Manage Providers screen.
2. `POST /api/v1/runtime/ai-providers/anthropic` runs; `upsert_ai_provider()` encrypts and writes the row, and `config_audit_log` gets an entry describing the action (never the value).
3. Nothing currently running is affected — no in-flight investigation's `ContextVar` snapshot changes, and no cached AI client is invalidated, because none exists to invalidate.
4. The *next* IOC lookup's `run_all_providers()` call takes a brand-new `get_ioc_provider_snapshot()` read, and the *next* AI call (in that same lookup or an unrelated one) calls `get_active_ai_config()` fresh. Both see the row written in step 2 immediately.

No cache invalidation, no signal, and no process-wide lock is needed anywhere in this sequence — correctness comes entirely from *never caching* the value past the lifetime of one investigation (providers) or one call (AI backends).

## 🐛 Why this replaced a frozen-singleton design, and the exact bug that motivated it

Before this system existed, every provider's `configured` flag was computed exactly once, at module-import time, from the frozen `get_settings()` singleton — for example `virustotal.py:24-26` originally read `self.configured = bool(get_settings().virustotal_api_key)` at construction. `get_settings()` is `@lru_cache`'d (`config.py:110-111`), meaning it evaluates `.env` exactly once per process and returns the identical object for the rest of that process's life. That is fine for values that genuinely never change, but it is the wrong model for a value an operator expects to change without restarting a container.

This produced a specific, git-independently-documented divergence: **Test Connection would report success, and the very next real investigation would still report the provider as not configured.** Confirmed from `connection_test.py`'s own module docstring plus three independent write-ups (`docs/PROVIDERS.md:375-378`, `docs/TROUBLESHOOTING.md:96-134`, `RUNTIME_PROVIDER_IMPLEMENTATION_REPORT.md:11-12`): `POST /api/v1/providers/{id}/test` makes one live HTTP call using the *candidate* key from the request body, never reading `get_settings()` at all, so it always correctly reflects whatever key was just typed in. A real investigation, however, went through `BaseProvider.run()`, which — before this system existed — had nothing else to check but `self.configured`, frozen at process start. If the key was added to `.env` *after* the backend process had already started — the normal sequence, since Test Connection happens before any save/restart — the real investigation still saw `configured=False` and short-circuited to `NOT_CONFIGURED`, immediately after a Test Connection that had just reported success for the same credential.

The fix is exactly the mechanism described above: the frozen `self.configured` check was replaced by the `ContextVar` snapshot fed from a fresh per-investigation database read (`runtime_context.py`, `orchestrator.py:112-113`), and the AI side's cached client singleton was replaced by `_get_ai_client()`'s fresh-DB-read-plus-fresh-construction pattern (`service.py:56-63`, `:102-138`). A credential saved through the Manage Providers UI is now visible to the very next investigation or AI call, closing the exact gap that used to let Test Connection and a live investigation disagree.

Two things are worth being precise about, so this section doesn't overstate what was found. First, the literal phrase "API key not provided" does not appear anywhere in this codebase's source or documentation — the real, current error strings are `f"{self.provider_name} is not configured (missing API key/credentials)."` (`base.py:143`, also asserted against in `backend/app/tests/unit/test_provider_base.py:55-61`) for providers, and the `RuntimeError` text quoted above for AI backends. Second, a separate, unrelated bug with the *opposite* symptom — Test Connection *failing* despite a valid key — is self-documented in `Setup-Wizard.ps1:211-236` (an in-code "ROOT CAUSE" comment) and `API_CONFIGURATION_FIX_REPORT.md:15-30`: every Test Connection button required a wizard session token (`$State.AccessToken`) that was only ever set during the Summary page's "Start Installation" step, so re-running the wizard to reconfigure an already-installed platform (without re-logging-in) made every Test Connection click fail with a misleading "create the administrator account first" message, even though the account already existed. This is a wizard-session bug, not a configuration-freshness bug, and should not be conflated with the frozen-singleton issue above — different symptom, different fix (`Get-OrCreateWizardSession`, `Setup-Wizard.ps1:237-253`).

## 🔁 Surviving a restart

Because runtime-configured credentials live in `provider_runtime_configs` in Postgres — a container that, in the Docker Compose and Kubernetes topologies alike, persists its data volume independently of the `backend` container's lifecycle — stopping, recreating, or upgrading the `backend` container does **not** lose or reset any runtime-configured provider or AI credential. This is the inverse of the pre-existing `.env` behavior, where a value only ever took effect after a restart; here, a restart is *not required* for a change to take effect, and *is safe* in the sense that it does not roll configuration back to whatever `.env` says. On a fresh backend process start, `seed_from_env_if_empty()` runs again but is a no-op the moment any row already exists (`runtime_config.py:408-410`), so an established runtime configuration is never overwritten by `.env` on restart. Only a genuinely empty `provider_runtime_configs` table — a brand-new database volume — would cause `.env` values to be (re-)seeded.

## 🧾 Audit trail

Every configure, enable/disable, activate, and record-test action against a provider or AI backend is written to `config_audit_log` with a timestamp, the acting user's ID and email, an `action` string, and a `detail` string, retrievable via `GET /api/v1/runtime/audit-log` (gated by `require_permission("audit:read")`). The table's write path accepts only descriptive text for `detail` — there is no code path that interpolates a credential value into it, and this was checked empirically (not just read from source) by exercising the full configure/test/enable/activate sequence and grepping both the audit rows and the backend logs for any real secret, with no hits either place.

[FIGURE: backend-05-runtime-configuration-architecture-diagram-1.png | Diagram: Audit trail]
Diagram: Credential lifecycle -- wizard/`.env` and runtime-API entry points, encrypted storage, the per-investigation `ContextVar` snapshot for IOC providers, and the per-call fresh client construction for AI backends. The two right-hand branches are why a saved credential change needs no restart: neither path ever reads a value cached longer than one investigation (providers) or one call (AI backends).

## ✅ Summary

Configuration enters the platform two ways — a one-time `.env` write from the Windows wizard, or a live, encrypted database write from the Manage Providers UI — and the database path is the one that matters for "no restart" claims. Credentials are Fernet-encrypted before they are stored, using either an explicitly configured master key or one derived from the JWT signing secret as a fallback with a stated tradeoff. Every read that actually gates behavior — a provider's `configured` check, an AI call's backend/client resolution — is a fresh read scoped to the current investigation (providers, via a `ContextVar` snapshot) or the current call (AI backends, via fresh client construction), never a value cached for the life of the process. That design directly closes a real, documented historical bug in which Test Connection and a live investigation could disagree about whether a provider was configured, and it is also why configuration now survives a backend restart intact rather than requiring one to take effect.
