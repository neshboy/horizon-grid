# 🔒 Backend Security Architecture

This chapter documents the four security-relevant subsystems of the FastAPI backend that a backend engineer, DevOps operator, or security reviewer needs to reason about before deploying or auditing HORIZON GRID: **authentication**, **authorization (RBAC)**, **credential/secrets management**, and **audit logging**. Every claim below is traceable to a specific file and, where useful, a line reference, obtained by direct inspection of `backend/app/` and `windows/` in this repository.

Each section ends with two explicit lists:

- **Implemented** — mechanisms that exist in the running code today, verified by reading the implementation (not a comment, docstring, or marketing description of intent).
- **Recommended (not yet implemented)** — controls a production-security review would normally expect, confirmed absent by searching the same code paths (e.g. no revocation table, no rate limiter on a given route). These are documented as honest gaps, not hidden. One item, the Fernet key's default derivation, is called out separately below because it is a documented design tradeoff rather than a missing feature.

## 📋 Table of contents

- [1. Authentication](#1--authentication)
- [2. Authorization: Role-Based Access Control (RBAC)](#2--authorization-role-based-access-control-rbac)
- [3. Credential and Secrets Management](#3--credential-and-secrets-management)
- [4. Audit Logging](#4--audit-logging)
- [5. CORS and Network Reachability](#5--cors-and-network-reachability)
- [Summary: Implemented vs. Recommended](#-summary-implemented-vs-recommended)

## 1. 🔑 Authentication

Authentication is JWT-based. `backend/app/auth/security.py` issues tokens with `python-jose`, signing algorithm `HS256` (`jwt_algorithm` in `app/core/config.py:24`), and hashes passwords with `passlib`'s `bcrypt` scheme (`security.py:10`) — plaintext passwords are never persisted, only the bcrypt hash on `users.hashed_password`.

Two token types are minted together at `/auth/login` and `/auth/refresh`, both carrying `sub` (email), `role`, `token_version`, `type`, `iat`, and `exp` claims (`security.py`'s `_create_token`):

| Token | `type` claim | Default lifetime | Setting |
|---|---|---|---|
| Access token | `"access"` | 30 minutes | `access_token_expire_minutes` (`config.py:25`) |
| Refresh token | `"refresh"` | 7 days | `refresh_token_expire_days` (`config.py:26`) |

`GET /api/v1/auth/refresh` (`app/api/routes/auth.py:56-68`) only accepts a token whose decoded `type` claim is `"refresh"`; `get_current_user` (`app/auth/rbac.py:28-47`), used by every protected route, only accepts `type == "access"` — a refresh token cannot be used directly as a bearer credential, and vice versa. `get_current_user` re-checks `user.is_active` against the database on every request (`rbac.py:45`), so an account disabled after a token was issued is rejected on its very next request, without waiting for the token to expire.

The dependency is wired via FastAPI's `HTTPBearer(auto_error=False)` rather than `OAuth2PasswordBearer`, because `/auth/login` takes a JSON body, not an OAuth2 form-encoded grant (`rbac.py:14-18`).

**A deactivated account now gets a distinct `403 "Account disabled"`, not the generic `401 "Could not validate credentials"`** (v0.2.2). Previously `get_current_user` raised the same generic 401 for both "no such user" and "user exists but is inactive." Found via adversarial concurrency testing of the last-active-admin protection invariant (§ below): two admins simultaneously trying to disable each other is correctly resolved so the system never reaches zero active admins, but the losing caller's OWN account is what gets deactivated by the other request that won the race — so their own next request (still in flight) hit this exact check and got a 401 that read like a broken session, never even reaching the business-rule check that would have explained what actually happened. The distinction matters here specifically because the caller and the affected account are the same person in this race; a 403 with the existing "Account disabled" message (already used at `/auth/login` for the same underlying condition) is accurate and far less confusing than a generic credentials failure.

### First-user-becomes-admin bootstrap

`POST /auth/register` (`app/api/routes/auth.py:21-45`) contains a specific rule: the very first user ever created on an instance is granted `Role.ADMIN`; every registration attempt after that is rejected outright with `HTTP 403` and `detail="Self-registration is closed. Ask an administrator to create your account from the Administration page."` (`auth.py:27-35`, checked via `SELECT User.id` against an empty table) — it no longer falls back to creating a `Role.ANALYST` account. This is the platform's only way to obtain an initial administrator — there is no seed script or default account — and it is exactly the mechanism the Windows Setup Wizard drives when it creates the administrator account at install time. Every account created after that first admin must go through an existing admin, via `POST /admin/users` (§2) or the `/admin` frontend page, which lets the admin pick the new account's role up front.

### Password validation

| Field | Constraint | Where enforced |
|---|---|---|
| `RegisterRequest.password` | `min_length=8`, `max_length=72` | Pydantic `Field()`, `app/schemas/auth.py:18` |
| `LoginRequest.password` | `max_length=72` only (no minimum) | `app/schemas/auth.py:24` |

The 72-byte cap is bcrypt's own effective limit (bytes beyond 72 are silently ignored); a code comment records that an unconstrained password previously produced an *unhandled 500* from `passlib`'s `PasswordSizeError` on inputs over 4096 bytes before this constraint existed (`schemas/auth.py:5-13`). There is no complexity rule beyond the 8-character minimum.

**Implemented:**
- Bearer JWT access/refresh tokens (HS256), bcrypt password hashing, DB-backed `is_active` re-check on every authenticated request.
- Server-side minimum password length (8 characters) enforced by Pydantic on registration.
- First-user-becomes-admin bootstrap, removing any need for a manual database edit to obtain an administrator, with self-registration closing itself (`403`) the instant that first admin exists.

**Recommended (not yet implemented):**
- **No self-service token revocation.** `token_version` (`app/models/user.py`) gives one specific, admin-driven path to invalidate a user's existing tokens: `POST /api/v1/admin/users/{id}/reset-password` (§2's user-management subsection) increments it, and both `get_current_user` and `POST /auth/refresh` reject any token whose embedded `token_version` no longer matches the database value — closing the gap a stateless JWT would otherwise have, where an already-issued token stays valid under the OLD password until it naturally expires. What's still genuinely missing: a user cannot trigger this for their *own* sessions without changing their password (no self-service "log out everywhere"), and there is still no revocation for reasons other than a password reset short of rotating `jwt_secret_key`, which invalidates *every* session platform-wide.
- **`/auth/login` now has a real rate limiter, added in a later mission-critical-reliability review (v0.2.3):** a per-account Redis fixed-window limiter (`app/core/cache.py::RateLimiter`, keyed `login:{email}` rather than by source IP, since registration/login lookups are already keyed by email throughout the codebase) rejects further attempts against the same account with `429` once `login_rate_limit_max_attempts` (10 by default) is exceeded within `login_rate_limit_window_seconds` (60 by default), both configurable. **`/auth/register` still has no rate limiting** — the platform's other rate limiter (`POST /lookup/stream`) is unrelated and does not cover it, and the bootstrap-only self-registration gate (first bullet above) is not a throttle.
- **No account lockout after repeated failed logins**, and no multi-factor authentication — neither concept exists anywhere in `app/auth/` or `app/models/user.py`.
- **No password complexity rule beyond length** (no digit/symbol/case requirement).

## 2. 🔐 Authorization: Role-Based Access Control (RBAC)

The platform has exactly three roles, `Role.ADMIN`, `Role.ANALYST`, `Role.VIEWER` (`app/models/user.py:11-14`), stored on `users.role`. Authorization is a flat permission-string matrix, `ROLE_PERMISSIONS` (`app/models/user.py:31-44`), checked per-route by the `require_permission(permission: str)` dependency factory (`app/auth/rbac.py:50-62`): a route either declares a required permission string as a FastAPI dependency or it enforces none — there is no implicit default-deny/default-allow fallback beyond "no `require_permission` call means no permission check."

| Permission string | admin | analyst | viewer | Enforced by |
|---|---|---|---|---|
| `lookup:create` | ✓ | ✓ | | `POST /lookup/stream`, `POST /lookup/{id}/reanalyze` |
| `lookup:read` | ✓ | ✓ | ✓ | `GET /lookup/{id}`, `GET /lookup`, `GET /lookup/{id}/assessments`, `GET /providers/health`, `GET /lookup/{id}/pivots`, `GET /runtime/ai-active` |
| `lookup:export` | ✓ | ✓ | | **Defined in the matrix; no route calls `require_permission("lookup:export")`.** |
| `evidence:read` | ✓ | ✓ | ✓ | `GET /lookup/{id}/analysis/evidence` |
| `analysis:generate` | ✓ | ✓ | | all nine AI explanation endpoints under `/lookup/{id}/analysis/*` (why, what-is-this, disagreement, false-positive, challenge, next-actions, gaps, score-explanation) |
| `copilot:query` | ✓ | ✓ | | `POST /lookup/{id}/analysis/copilot` |
| `hunting:generate` | ✓ | ✓ | | `POST /lookup/{id}/hunt`, `POST /lookup/{id}/detection` |
| `basket:manage` | ✓ | ✓ | | all five `/basket*` routes |
| `case:create` / `case:read` / `case:write` / `case:close` | ✓ | ✓ | `case:read` only | the eight `/cases*` routes |
| `provider:manage` | ✓ | | | `POST /providers/{id}/test`, `POST /ai/test`, `POST /ai/{backend}/models`, and every `/runtime/ai-providers*` / `/runtime/ioc-providers*` route |
| `audit:read` | ✓ | | | `GET /runtime/audit-log` |
| `user:manage` | ✓ | | | Every route in `app/api/routes/admin.py`: `GET /admin/users`, `GET /admin/users/stats`, `GET /admin/roles`, `POST /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/active`, `POST /admin/users/{id}/reset-password`. |

A permission failure raises **HTTP 403** with `detail=f"Role '{user.role.value}' lacks permission '{permission}'"` (`rbac.py:56-59`) — naming both the caller's own role and the missing permission string, which is convenient for debugging and not a material information leak, since the caller already knows its own role from its own JWT.

[FIGURE: backend-06-security-architecture-diagram-1.png | Diagram: 2. Authorization: Role-Based Access Control (RBAC)]
Diagram: RBAC permission resolution -- role to permission-string to route. `require_permission` is the single dependency every gated route shares; a route with no `require_permission` call enforces no permission at all, and `viewer`'s permission set contains no create/write/manage/generate string anywhere in the matrix.

**Implemented:**
- Three fixed roles with a centralized, single-source-of-truth permission matrix (`app/models/user.py`), checked by one shared dependency (`require_permission`) rather than ad hoc per-route logic.
- `viewer` is provably read-only: its permission set (`lookup:read`, `evidence:read`, `case:read`) contains no create/write/manage/generate permission anywhere in the matrix.
- Every route that mutates state (auth aside) requires either `analyst`-or-above or `admin`-only, per the table above.

### Multi-admin user management (`app/core/users.py`, `app/api/routes/admin.py`)

Administrators are ordinary `User` rows with `role=ADMIN` — there is no separate hardcoded admin
account or username. Beyond the `/auth/register` bootstrap (§1), any existing admin can create
another admin directly (`POST /admin/users`), so there is no ceiling on how many active admins can
exist and no single-admin bottleneck.

Two protections stop an admin action from leaving the platform with zero administrators, both in
`update_user()` and `set_user_active()`:

- **Self-role-change is rejected** (`400`, `SelfRoleChangeError`) — `if user.id == actor_user_id` in
  `update_user()` — purely to prevent an accidental mid-session self-lockout, since role changes take
  effect immediately (below), not as an independent security boundary.
- **Last-admin protection is race-safe, not just check-then-act.** `_lock_all_admin_rows()`
  (`users.py:73-79`) takes a `SELECT ... FOR UPDATE` lock on **every** `ADMIN`-role row before
  `_remaining_active_admins()` (`users.py:81-82`) counts how many would stay active. A lock scoped to
  only the request's own target row would let two concurrent requests — each disabling a *different*
  one of exactly two remaining active admins — both succeed (each observes the other still active) and
  leave zero; locking the whole admin set serializes the second request behind the first's commit, so
  it re-evaluates against the post-commit state and correctly raises `LastAdminError` (`409`).

**No hard delete exists**, by necessity rather than by choice: `app/models/case.py`'s
`analyst_id`/`added_by`/`author_id`/`generated_by` and `app/models/basket.py`'s `owner_id` are all
`NOT NULL` foreign keys to `users.id`. Deleting a user who has ever created a case, added evidence,
or owned a basket would either violate those constraints or require cascading away real
investigation data; `set_user_active(..., False)` (disable) is the only account-removal mechanism,
which also preserves the audit trail's own actor references (`config_audit_log.actor_user_id` is
likewise a plain FK — even a disposable test account can't be hard-deleted once it has acted).

**Immediate effect, no session-cache to invalidate.** `get_current_user` already re-reads `role`
and `is_active` from the database on every request rather than trusting the JWT (§1) — so a role
change or a disable takes effect on the user's very next request with their existing token, with
zero new machinery required for either. Password resets are the one exception genuinely needing
new machinery (`token_version`, §1), since changing `hashed_password` alone does not invalidate an
already-issued JWT.

**Implemented (this subsection):**
- Full CRUD for user accounts via `app/api/routes/admin.py`, all gated by `user:manage`.
- Race-safe last-administrator protection and self-role-change prevention.
- Immediate effect of role/enable-disable changes; `token_version`-based immediate effect for
  password resets.
- No hard delete — disable-only, consistent with the same FK constraints that make hard delete
  unsafe for real investigation data.

**Recommended (not yet implemented):**
- **No row-level/ownership authorization beyond the basket.** `basket_items` is scoped to `owner_id` at the query level, but `cases` and `ioc_lookups` are visible to any authenticated user holding the relevant `*:read`/`*:write` permission — there is no per-case or per-lookup ACL, only the coarse role check. This is a documented design choice (cases/lookups are team-shared, not per-analyst), but worth stating plainly: any `analyst` can read and write any other analyst's cases and lookups.

## 3. 🔏 Credential and Secrets Management

There are two architecturally distinct places a secret can live, and a backend engineer needs to know which applies to a given credential before reasoning about exposure.

**Path A — `.env` (legacy, process-frozen).** `Settings` (`app/core/config.py:13-112`) is a `pydantic-settings` model loaded once from `.env` and cached for the process lifetime via `@lru_cache def get_settings()`. Every provider/AI credential field here (`virustotal_api_key`, `anthropic_api_key`, `jwt_secret_key`, etc.) is fixed at process start; changing `.env` requires a container restart to take effect for anything still reading `get_settings()` directly.

**Path B — DB-backed runtime configuration (encrypted).** The `provider_runtime_configs` table (`app/models/runtime_config.py:30-55`) lets an administrator add/change AI-backend and IOC-provider credentials through the Manage Providers UI while the platform is running, with no restart. Because this moves secret entry out of the git-ignored `.env` file into a database row, the credential dict is Fernet-encrypted before it is ever written: `app/core/crypto.py:49-54` (`encrypt_secret`), called from `runtime_config.py:234`/`:339`, storing ciphertext in `encrypted_credentials` (`Text`, nullable). Decryption (`crypto.py:57-67`) returns `""` on any `InvalidToken` rather than raising — a corrupted row or rotated key degrades to "not configured," not a 500.

### Key material and the HKDF fallback (a documented tradeoff, not a gap)

The Fernet key is resolved by `_fernet()` (`crypto.py:39-46`): if `settings.encryption_master_key` is explicitly set, that value is the key; otherwise a key is deterministically derived via HKDF-SHA256 from `settings.jwt_secret_key` (`crypto.py:33-36`), domain-separated by a fixed `info` string so it cannot collide with any other derivation of that same secret. The module's own docstring states the intent plainly (`crypto.py:1-20`): this fallback means every existing install already has a usable encryption key with zero migration effort, at the cost of key *independence* — compromising `jwt_secret_key` also exposes the derived Fernet key. That is defense-in-depth against a raw database leak, not HSM-grade key separation, and it is a documented tradeoff rather than an oversight: an operator wanting true separation sets `encryption_master_key` explicitly (`config.py:27-30`).

### Masked display — the API never returns a raw runtime-configured secret

Every read path for a runtime-configured provider (`GET /runtime/ai-providers`, `GET /runtime/ioc-providers`) goes through `_row_to_public_dict()` (`app/core/runtime_config.py:144-163`), which decrypts internally only to immediately re-mask: `masked_credentials = {k: mask_secret(v) for k, v in creds.items()}`. `mask_secret()` (`crypto.py:70-77`) replaces every character except the last four with `*` and is documented as intentionally non-reversible ("never round-trippable back to the real value, unlike returning a truncated real prefix"). No route in `app/api/routes/runtime.py` returns a decrypted credential to a client.

### Windows installer: file-level protection for `.env`

For Path A, the Windows Setup Wizard does two things a plain `.env.example`-copy would not. It generates `jwt_secret_key` (and the Postgres/Neo4j passwords) with .NET's cryptographically secure `RandomNumberGenerator`, not PowerShell's `Get-Random` (`windows/scripts/Write-EnvFile.ps1`'s `New-RandomSecret`/`New-DefaultPlatformSettings`, lines 133-176). It then restricts the written file's ACL immediately: `icacls.exe $Path /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F"` (`Write-EnvFile.ps1:130`) — breaking inheritance and granting Full Control only to Administrators (`S-1-5-32-544`) and SYSTEM (`S-1-5-18`); the same pattern is reused for the data directory in `windows/scripts/Common.ps1:95,233`. A separate fix, `ConvertTo-SafeEnvValue` (`Write-EnvFile.ps1:15-49`), strips CR/LF from every value and rejects any value containing `#` outright, since `#` starts a comment in `.env` syntax and would otherwise silently truncate a credential with no error downstream.

[FIGURE: backend-06-security-architecture-diagram-2.png | Diagram: Windows installer: file-level protection for `.env`]
Diagram: Credential lifecycle -- `.env` vs. the encrypted runtime store. Path A requires a restart to change and is protected only by filesystem ACLs; Path B is Fernet-encrypted at rest, never returns a decrypted value over the API, and is the only path that supports a live, no-restart credential change.

**Implemented:**
- Fernet symmetric encryption at rest for every runtime-configured (Path B) credential; ciphertext-only in the database, confirmed by direct model inspection (`encrypted_credentials: Text`).
- Masked-only credential display (`mask_secret`) — no API route returns a decrypted runtime-configured credential.
- Cryptographically secure secret generation and `icacls`-based NTFS permission lockdown (Administrators + SYSTEM only) for `.env` on Windows installs.
- `.env` value sanitization (`ConvertTo-SafeEnvValue`) preventing silent truncation/corruption of a written credential.
- `seed_from_env_if_empty()` (`app/core/runtime_config.py:398-448`) migrates existing `.env` credentials into the encrypted store exactly once, idempotently, on first startup of this feature — an upgrade never silently drops a previously configured key.

**Recommended (not yet implemented):**
- **`jwt_secret_key` defaults to the literal string `"change-me-in-production"`** if never set (`config.py:23`). Because the Fernet key for Path B falls back to a derivation of this same value, an unedited default does not just weaken JWT signing — by the tradeoff above, it also weakens runtime-credential encryption for any deployment that never sets `encryption_master_key`. (The Windows installer avoids this by always generating a real value; a bare `docker compose up` against `.env.example` without wizard involvement does not.)
- **No key-rotation procedure.** Neither `jwt_secret_key` nor `encryption_master_key` has a documented or coded rotation path; rotating either without a migration step would immediately invalidate all existing sessions and/or make every previously encrypted runtime credential undecryptable.
- **No secrets-manager integration** (Vault, AWS Secrets Manager, etc.) — both paths described above are self-contained (file-based or database-based), with no external secret store as an option.
- **No Linux/macOS equivalent of the `icacls` file-permission lockdown.** The ACL hardening described above is Windows-installer-specific; a `.env` file created by `docker compose` directly on Linux relies on the operator's own umask/filesystem permissions, which this platform does not set or verify.

> [!IMPORTANT]
> An unedited `jwt_secret_key` doesn't just weaken JWT signing on its own — because the Fernet key for Path B falls back to a derivation of this same value, it also weakens runtime-credential encryption for any deployment that never sets `encryption_master_key`. The Windows installer always generates a real value; a bare `docker compose up` against `.env.example` without wizard involvement does not.

## 4. 📝 Audit Logging

`config_audit_log` (`app/models/runtime_config.py:58-75`) is an append-only table — it uses only `UUIDPrimaryKeyMixin`, deliberately not the shared `TimestampMixin`, because it has its own explicit `timestamp` column set by application code rather than a DB `server_default`. Every row carries `actor_user_id` (nullable FK to `users.id`), a denormalized `actor_email` (so history stays readable if the account is later deleted), an `action` string, and a free-text `detail` (`String(1000)`).

All writes go through one function, `record_audit()` — originally defined inside
`app/core/runtime_config.py`, extracted into a dedicated `app/core/audit.py` (`record_audit()` at
line 20, `list_audit_log()` at line 39) once user-management code (`app/core/users.py`) needed the
same append-only sink without importing the entire provider-config service module for it. The model
itself (`ConfigAuditLog`) stays in `app/models/runtime_config.py` unchanged — only the two
functions moved; `app/core/runtime_config.py` re-exports both so `app/api/routes/runtime.py`'s
existing `svc.list_audit_log(...)` call needed no change. The docstring states the rule directly:
`detail` "must be human-readable description text ONLY — never a credential/password/token value."
This is a **coding convention enforced by review, not by a type or runtime check** — nothing in
`record_audit()` inspects `detail` for secret-shaped content. Every current call site passes a
hardcoded, credential-free f-string (e.g. `f"Configured AI provider '{backend}'."`); a future call
site that interpolated an untrusted value would not be caught automatically.

| `action` value | Emitted from | Actor recorded? |
|---|---|---|
| `ai_provider.configure` | `upsert_ai_provider` (`runtime_config.py`) | Yes |
| `ai_provider.activate` | `set_active_ai_backend` (`runtime_config.py`) | Yes |
| `ai_provider.test` | `record_ai_test_result` (`runtime_config.py`) | **No** — called without `actor_user_id`/`actor_email`, even though the calling route (`runtime.py`) has an authenticated `user` in scope |
| `ioc_provider.configure` | `upsert_ioc_provider` (`runtime_config.py`) | Yes |
| `ioc_provider.enable` / `.disable` | `set_ioc_provider_enabled` (`runtime_config.py`) | Yes |
| `ioc_provider.test` | `record_ioc_test_result` (`runtime_config.py`) | **No**, same gap |
| `system.seed` | `seed_from_env_if_empty` (`runtime_config.py`) | No (system-initiated) |
| `user.create` | `create_user` (`users.py:164-182`) | Yes |
| `user.update` | `update_user` (`users.py:185-224`) — only written if `full_name`/`role` actually changed | Yes |
| `user.enable` / `.disable` | `set_user_active` (`users.py:227-250`) | Yes |
| `user.password_reset` | `reset_password` (`users.py:254-272`) | Yes (the administrator performing the reset, never the affected user) |
| `auth.login` | `record_login_success`, called from `POST /auth/login` (`users.py:281-286`) | Yes — the logging-in user is recorded as their own actor |
| `auth.login_failed` | `record_login_failure`, called from `POST /auth/login` on bad credentials (`users.py:289-290`) | No (`actor_user_id=None`) — the email that was attempted is in `detail`, but there is no authenticated identity to attribute it to; the function's signature (`email: str` only) makes it structurally impossible to pass a password into `detail` |

The log is exposed read-only via `GET /api/v1/runtime/audit-log?limit=200` (`app/api/routes/runtime.py`), gated by `require_permission("audit:read")` — only `admin` holds this permission per the RBAC matrix in Section 2. This single endpoint and table now serve both the Providers page's audit tab and the Administration console's audit tab (`frontend/app/admin/page.tsx`) — user-management events were deliberately routed into the *existing* audit sink rather than a second, parallel table.

**Implemented:**
- A dedicated, queryable audit table for every AI-backend/IOC-provider configuration change **and** every user-management/authentication event (configure, enable/disable, activate, record-test, create/update/enable/disable/password-reset, login/login-failed), including the one-time `.env`-to-database migration event.
- Actor attribution (user id + denormalized email) recorded for every configure/activate/enable/disable/user-management action, and for successful logins (self-attributed).
- `admin`-only read access to the audit trail via a dedicated permission (`audit:read`), independent from `provider:manage`/`user:manage`.
- A documented, code-level convention against ever writing a credential or password value into `detail`, reinforced for login failures by a function signature (`record_login_failure(email: str)`) that has no password parameter to leak in the first place.

**Recommended (not yet implemented):**
- **Test-result audit rows have no actor.** `ai_provider.test` and `ioc_provider.test` entries record *what* happened but not *who* triggered it, unlike every other action type in the table above — a straightforward fix already available since both calling routes have the current user in scope.
- **No audit coverage for case, basket, or lookup activity.** Creating/closing a case, adding/removing a basket item, or running a lookup produces no row in any audit table — only the runtime-configuration subsystem is audited.
- **No tamper-evidence or immutability guarantee.** `config_audit_log` is "append-only" purely by convention (no code path updates or deletes a row); there is no database-level `REVOKE UPDATE/DELETE`, no cryptographic chaining/hashing between rows, and no export/retention policy.
- **No enforced redaction of `detail`.** As noted above, the "never a credential" rule is a comment and a code-review norm, not a validated constraint.

## 5. 🌐 CORS and Network Reachability

`backend/app/main.py` gates every browser-originated cross-origin request through `CORSMiddleware`, configured as a private-network-shaped regex rather than a fixed origin list:

```python
PRIVATE_NETWORK_ORIGIN_REGEX = (
    r"^http://("
    r"localhost"
    r"|127\.0\.0\.1"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=PRIVATE_NETWORK_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Why a regex over a static list.** The platform is designed to be reachable from any device on the operator's local network, not just the machine it's installed on -- and the exact LAN address varies per install and per network (DHCP-assigned, never hardcoded; see the Runtime Configuration chapter's discussion of why a container can't discover the host's real LAN IP itself). A static origin list would either have to be re-edited per deployment or fall back to `allow_origins=["*"]`, which this codebase deliberately does not do. Matching by IP-shape instead answers the actual question CORS needs answered -- "is this origin on a private network" -- without needing to know the specific address in advance. `settings.debug` (`config.py:19`) is no longer read anywhere in the backend as a result of this design (confirmed via `grep -rn "settings\.debug" backend/app`) -- it previously was the sole gate on a single-origin, dev-only CORS policy.

**This is a same-origin-policy relaxation, not the platform's authorization boundary.** A request from a matching origin still must carry a valid bearer token for every protected route (`app/auth/rbac.py`); CORS only controls whether a browser's JavaScript is allowed to *read* the response, not whether the request reaches the API. Matching by IP-shape only, not a specific port, is a deliberate simplification: restricting to a specific configured port was evaluated and would have been nearly free to add (`docker-compose.yml`'s `env_file: .env` already injects `HOST_PORT_FRONTEND` into the backend process with no additional wiring), but was judged to add plumbing without a real security improvement, since the actual boundary is authentication, not origin matching.

> [!NOTE]
> CORS here is a same-origin-policy relaxation, not the platform's authorization boundary. A request from a matching origin still must carry a valid bearer token for every protected route — CORS only controls whether a browser's JavaScript is allowed to read the response, not whether the request reaches the API.

**`GET /network-info`** (`main.py`, declared directly on `app`, no `api_v1_prefix`, no auth dependency -- the same unauthenticated pattern as `/health`) echoes three `Settings` fields for the frontend's Network Access panel:

```python
@app.get("/network-info")
async def network_info():
    return {
        "detected_lan_ip": settings.detected_lan_ip,
        "frontend_port": settings.host_port_frontend,
        "backend_port": settings.host_port_backend,
    }
```

`detected_lan_ip` (`DETECTED_LAN_IP` env var) is written once, at install/reconfigure time, by the Windows wizard's `Get-LanIpAddress` (`windows/scripts/Common.ps1`) -- confirmed empirically that the backend container cannot determine this itself: self-detecting the container's own outbound-route IP from inside a running instance returned Docker's bridge-network address (`172.21.0.7` in the environment this was verified against), and resolving `host.docker.internal` returned Docker Desktop's internal VM gateway address, neither of which is the host's real LAN-facing interface. `host_port_frontend`/`host_port_backend` (`HOST_PORT_FRONTEND`/`HOST_PORT_BACKEND`) populate from the same `.env` mechanism with no additional `docker-compose.yml` wiring. None of these three values are secret; the endpoint is unauthenticated by the same reasoning as `/health` -- a LAN IP and two port numbers reveal nothing an inbound port scan on the same network wouldn't already show.

**Implemented:**
- CORS restricted to loopback and RFC 1918 private-IP origins only, over `http://` only -- never `allow_origins=["*"]`.
- A Windows Firewall rule (`windows/scripts/Common.ps1`'s `New-AppFirewallRule`) scoped to the platform's two ports and the **Private** network profile only, created at install/reconfigure time and removed on uninstall (`windows/installer.iss`'s `InitializeUninstall`) -- never Domain or Public profiles.
- The frontend resolves the backend's address dynamically from the browser's own request (`frontend/lib/api.ts`'s `getApiUrl()`), rather than a value baked in at build or install time -- eliminating an entire class of "works on the install machine, not from another device" bugs without needing to know any LAN address in advance.
- No credential or secret is ever transmitted to or exposed by the LAN-access mechanism itself -- `/network-info` returns only a non-secret IP address and two port numbers.

**Recommended (not yet implemented):**
- **No port-specific CORS restriction.** As described above, matching is by IP-shape only, not a specific configured port -- a deliberate simplification, but a stricter deployment could add it with the `HOST_PORT_FRONTEND` value already available.
- **No HTTPS/TLS anywhere in this architecture.** LAN access is `http://` only; the platform is designed for a trusted local network, not a hostile one, and has no certificate provisioning story of its own.
- **`Get-LanIpAddress` is a point-in-time snapshot, not live.** A LAN IP change (common after a router restart) is not detected automatically; the operator must re-run the wizard's Configuration option. There is no background poller or scheduled re-detection.
- **The firewall rule creation is best-effort, not verified post-install.** `New-AppFirewallRule` is wrapped in try/catch and logs a warning on failure rather than blocking setup (a locked-down/GPO-managed machine that rejects `New-NetFirewallRule` should not prevent the rest of installation from completing) -- but nothing in the wizard re-checks afterward that the rule actually exists.

## 📋 Summary: Implemented vs. Recommended

| Area | Strongest implemented control | Most significant open recommendation |
|---|---|---|
| Authentication | JWT (HS256) + bcrypt, DB-checked `is_active` on every request; `token_version`-based immediate invalidation on admin-initiated password reset; per-account rate limiter on `/auth/login` (v0.2.3) | No self-service "log out everywhere"; no rate limiting or lockout on `/auth/register`; no account lockout on login |
| Authorization (RBAC) | Centralized `ROLE_PERMISSIONS` matrix, one shared `require_permission` dependency; full multi-admin user-management API (`admin.py`) with race-safe last-administrator protection; `lookup:export` enforced on the export route, distinct from `lookup:read` | No per-case/per-lookup ACL |
| Credentials/Secrets | Fernet-at-rest encryption for DB-backed provider/AI credentials; masked-only display; `icacls`-restricted `.env` on Windows | Default `jwt_secret_key` literal risk; encryption key derivation shares root secret with JWT signing unless `encryption_master_key` is set explicitly; no rotation procedure |
| Audit Logging | Actor-attributed log of every provider/AI configuration change **and** every user-management/login event, `admin`-only read | No coverage of case/lookup events; test-result entries lack actor attribution; append-only by convention only |
| CORS/Network | Private-network-only CORS regex + Private-profile-only Windows Firewall rule; never `allow_origins=["*"]` | No port-specific CORS restriction; no HTTPS/TLS; LAN-IP detection is a point-in-time snapshot with no live re-detection |

None of the "Recommended" items are claimed vulnerabilities being actively exploited in a deployed instance — they are the concrete, code-verified list of controls a production hardening pass would add next.
