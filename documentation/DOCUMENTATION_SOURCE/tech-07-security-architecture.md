# Security Architecture

This appendix section documents the authentication, authorization, secrets-handling, network-exposure, rate-limiting, and CORS behavior of the HORIZON GRID backend (the FastAPI service that receives IOC — Indicator of Compromise — lookup requests from the web client). All claims below are traceable to source-code inspection of the platform's backend and Windows installer; anything not directly confirmed in code is marked "Not confirmed" rather than estimated.

## 📋 Table of contents

- [🔑 Authentication](#-authentication)
  - [First-user-becomes-admin bootstrap](#first-user-becomes-admin-bootstrap)
- [🔐 Role-Based Access Control (RBAC)](#-role-based-access-control-rbac)
- [🔒 Secrets Management](#-secrets-management)
  - [Setup Wizard credential-testing reliability fix](#setup-wizard-credential-testing-reliability-fix)
  - [Encryption at rest for runtime-configured provider and AI credentials](#encryption-at-rest-for-runtime-configured-provider-and-ai-credentials)
- [🌐 Network Exposure](#-network-exposure)
- [🚦 Rate Limiting](#-rate-limiting)
- [🔀 CORS Behavior](#-cors-behavior)
- [📝 Other Input-Handling Notes](#-other-input-handling-notes)
- [🛠️ Areas for Future Hardening](#️-areas-for-future-hardening)

---

## 🔑 Authentication

The backend issues JSON Web Tokens (JWT) using `python-jose` with the HS256 signing algorithm (`backend/app/auth/security.py`). Two token types are issued on login:

| Token | Lifetime |
|---|---|
| Access token | 30 minutes |
| Refresh token | 7 days |

Password storage uses `passlib` with `bcrypt` hashing — plaintext passwords are never persisted; only the bcrypt hash is stored on the `users` table.

### First-user-becomes-admin bootstrap

`POST /auth/register` contains a specific bootstrap rule: **the first user ever registered on a given instance is automatically granted the `admin` role; every registration attempt after that is rejected with `403 Forbidden`** ("Self-registration is closed. Ask an administrator to create your account from the Administration page.") rather than being granted a lesser role. No manual database edit is required to stand up an initial administrator account — this is also how the Windows Setup Wizard provisions the admin account at the end of installation (it calls this same registration endpoint). Every account after that first admin must be created by an existing admin, via `POST /api/v1/admin/users` or the `/admin` frontend page, which lets the admin choose the new account's role up front. `docs/SECURITY.md` describes this identical mechanism.

## 🔐 Role-Based Access Control (RBAC)

The platform has exactly **three roles**: `admin`, `analyst`, and `viewer`. Permissions are modeled as a permission-string matrix (`ROLE_PERMISSIONS` in `app/models/user.py`) and enforced per-route by a `require_permission()` dependency (`app/auth/rbac.py`) — a route either declares a required permission string or it doesn't; there is no implicit fallback check.

> [!NOTE]
> **Documentation correction made during this review:** `docs/SECURITY.md` states that no route enforces the `provider:manage` permission. That claim is stale. The provider-credential test endpoint, `POST /api/v1/providers/{provider_id}/test` (`backend/app/api/routes/providers.py`), does call `require_permission("provider:manage")` — confirmed directly in the route code. This endpoint is what the Setup Wizard's per-provider "Test" button invokes, so the permission gate is exercised as part of the normal install flow, not a dead code path.

All three admin-tier permissions defined in the matrix now have at least one enforcing route:

| Permission | Status |
|---|---|
| `provider:manage` | Enforced — gates `POST /api/v1/providers/{provider_id}/test` and the `/api/v1/runtime/*` provider- and AI-configuration endpoints |
| `user:manage` | Enforced — gates every route in `app/api/routes/admin.py` (list users, create user, update user, roles, stats, set-active) |
| `audit:read` | Enforced — gates `GET /api/v1/runtime/audit-log` |

[FIGURE: tech-07-security-architecture-diagram-1.png | Diagram: Role-Based Access Control (RBAC)]

## 🔒 Secrets Management

Runtime configuration, including secrets, is loaded from a `.env` file via `pydantic-settings`. `.env` itself is git-ignored; only a `.env.example` template is tracked in source control.

> [!WARNING]
> One default value is a genuine risk if left unchanged: `jwt_secret_key` falls back to the literal string `"change-me-in-production"` when no value is set (`backend/app/core/config.py`). Any deployment that ships with this default unedited would have a publicly-known JWT signing secret.

On Windows installs, the Setup Wizard avoids this by generating secrets itself rather than relying on the code default: it uses a cryptographically secure random number generator (`New-RandomSecret`, backed by .NET's `RandomNumberGenerator` — explicitly *not* PowerShell's `Get-Random`, which is not cryptographically secure) and writes the result via `Write-EnvFile.ps1`. The resulting `.env` file's filesystem permissions are then locked down to the Administrators and SYSTEM accounts only, via `icacls`.

### Setup Wizard credential-testing reliability fix

A review of the Setup Wizard's per-credential "Test Connection" buttons — used to validate both third-party provider API keys and AI-backend credentials (at the time, the five backends the wizard supported: Ollama, Anthropic, Bedrock, Gemini, Groq) before installation is finalized — found two distinct root causes for unreliable behavior in this flow, both corrected during this review.

**Session-acquisition bug.** Every Test Connection button's request depends on an authenticated session token (`$State.AccessToken`). That token was previously set in exactly one place in the wizard: deep inside the "Start Installation" button's click handler on the final Summary page. As a result, no credential could be tested until installation had already been fully completed. On a reconfigure run in particular — where an administrator deliberately leaves the Admin Account page blank in order to keep an existing account unchanged — no login request was issued at all, so every Test Connection click failed with a "create the admin account first" message even though a working admin account and platform were already running. The fix is a new function, `Get-OrCreateWizardSession` (`windows/wizard/Setup-Wizard.ps1`), invoked on demand directly from each Test Connection click handler. It performs a login only, using whatever email and password are currently typed into the Admin Account page fields, and never registers or modifies an account.

**`.env` serialization hardening.** A second, independent bug existed in the writer responsible for persisting configuration values to disk, `windows/scripts/Write-EnvFile.ps1`: values were written without any escaping. A `#` character occurring anywhere inside a password or API key was interpreted by the `.env` parser as the start of a comment, silently truncating the remainder of that line, and an embedded newline in a value could similarly corrupt the file's line structure. This is fixed with a new `ConvertTo-SafeEnvValue` helper, applied to every value before it is written.

Neither issue involved the JWT signing or RBAC mechanisms described elsewhere in this document; both were specific to the Windows installer's wizard-to-backend session handling and its own configuration-file writer.

### Encryption at rest for runtime-configured provider and AI credentials

A newer capability lets an administrator add, configure, enable/disable, and switch AI-backend and IOC-provider credentials at runtime through a Manage Providers UI, without editing `.env` or restarting the containers. Because this moves credential entry out of the git-ignored `.env` file and into the database, those values are encrypted before they are ever written.

Credentials submitted through this flow are encrypted with Fernet symmetric encryption (`backend/app/core/crypto.py`) and persisted as ciphertext in the `provider_runtime_configs` table's `encrypted_credentials` column — the database never holds a plaintext runtime-configured credential. This is not merely an inference from reading the code: a direct SQL query against the running database showed only Fernet-format tokens (the `gAAAAAB...` prefix), never a real key value.

The Fernet key used for this encryption is resolved one of two ways: an explicit, separately-configured `encryption_master_key` setting, if the operator has set one, or — by default — a key deterministically derived via HKDF from the platform's existing `jwt_secret_key`. The HKDF fallback means every existing installation already has a usable encryption key with no migration step required, but it is worth stating plainly what this tradeoff is: because the fallback key is derived from `jwt_secret_key` rather than generated and stored independently, it is defense-in-depth against exposure of the raw database, not HSM-grade key separation — compromise of `jwt_secret_key` would also expose the derived encryption key. An operator wanting stronger separation should set `encryption_master_key` explicitly.

Every configure, enable/disable, activate, and test-connection action taken against a provider or AI backend through this flow is separately recorded in a new `config_audit_log` table (timestamp, actor email, action, and a human-readable `detail` field). The write path for that table only ever accepts descriptive text as `detail` — it is not a place a credential value can be written. This was checked directly, not just by reading the code: after exercising the full configure/enable/disable/test/activate flow, a grep of the audit log table's contents and of the backend logs found no real secret value in either.

## 🌐 Network Exposure

Every datastore container's port mapping in `docker-compose.yml` — Postgres, Redis, both Neo4j ports, and OpenSearch — uses the explicit `127.0.0.1:<host_port>:<container_port>` binding form, which restricts that port to the loopback interface only (not reachable from other machines on the network as ordinarily configured).

> [!CAUTION]
> The `backend` and `frontend` containers are published differently: their compose entries use the shorthand form (e.g. `"${HOST_PORT_BACKEND:-8000}:8000"`) with no explicit host-IP prefix. Docker's shorthand publishing binds to all host network interfaces by default — so, unlike the datastores, the backend API and frontend web app are reachable from other machines on the local network unless something else (a firewall rule, router configuration, etc.) restricts that.

> [!NOTE]
> `docker-compose.yml` contains first-person comments asserting that live testing confirmed specific network-reachability behavior from another LAN machine. This section does not rely on that narrative comment as evidence — only the literal, machine-checkable YAML binding syntax described above was treated as verified fact.

[FIGURE: tech-07-security-architecture-diagram-2.png | Diagram: Network Exposure]

## 🚦 Rate Limiting

The codebase implements exactly **one** rate limiter: a Redis fixed-window limiter that applies solely to `POST /lookup/stream` (the IOC lookup endpoint), defaulting to 10 calls per 60 seconds per authenticated user — both figures are configurable.

`/auth/login` has a second limiter, added in a later mission-critical-reliability review (v0.2.3): a per-account Redis fixed-window limiter keyed by email (`login:{email}`, not source IP), defaulting to 10 attempts per 60 seconds, both configurable, returning `429` once exceeded. `/auth/register` still has no rate limiting of any kind.

## 🔀 CORS Behavior

Cross-Origin Resource Sharing is configured in `backend/app/main.py` and its behavior depends entirely on the `debug` setting:

- When `settings.debug` is `True` (the default), `allow_origins` is set to `["http://localhost:3000"]`.
- When `debug` is `False`, `allow_origins` is set to `[]` — an empty list, meaning **zero** cross-origin browser requests are permitted.

> [!NOTE]
> There is no `CORS_ORIGINS` environment variable or other configuration knob to adjust this. Practically, this means a `DEBUG=false` production deployment cannot serve a browser frontend from any other origin than the backend itself without a source-code change.

## 📝 Other Input-Handling Notes

Two related facts are worth surfacing here because they feed directly into the hardening list below:

- `LookupCreateRequest.value` (the raw IOC string submitted for lookup) is an unconstrained `str` on the server side. Classification into an IOC type happens via regex-based heuristics (`app/ioc/detector.py`), which is pattern classification, not input sanitization.
- `RegisterRequest.password` carries a server-side 8-character minimum (`Field(min_length=8, ...)`, `app/schemas/auth.py`), enforced by Pydantic for every account, not just the bootstrap admin — but no complexity rule (digit/symbol/case) beyond that length floor. The Setup Wizard's own UI also enforces an 8-character minimum when creating the bootstrap admin account, matching the backend constraint rather than substituting for it.

## 🛠️ Areas for Future Hardening

Based only on the facts established above:

- **Default JWT secret is a known literal.** `jwt_secret_key` defaults to `"change-me-in-production"` if the operator never sets it explicitly — any instance that ships with this unedited has a predictable signing key.
- **No rate limiting on `/auth/register`.** `/auth/login` gained a real per-account rate limiter in v0.2.3 (see Rate Limiting above); registration has no throttling against repeated attempts.
- **No server-side password complexity rule beyond length.** The backend enforces an 8-character minimum for every account (`app/schemas/auth.py`), but no digit/symbol/case requirement on top of that.
- **Backend and frontend ports are not loopback-restricted by default.** Datastores (Postgres, Redis, Neo4j, OpenSearch) are bound to `127.0.0.1` only; the backend API and frontend web app publish on all host interfaces by default, unless the operator adds their own network restriction.
- **Runtime-credential encryption key defaults to a derived, not independently-generated, secret.** Unless an operator explicitly sets `encryption_master_key`, the Fernet key protecting runtime-configured provider/AI credentials (see Secrets Management above) is deterministically derived via HKDF from `jwt_secret_key` rather than generated and stored separately. That is a reasonable defense-in-depth default — it means every existing install already has a working encryption key — but it is not equivalent to HSM-grade key separation: compromise of `jwt_secret_key` would also expose the derived encryption key.
