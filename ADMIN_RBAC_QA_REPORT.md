# Multi-User + Multi-Admin RBAC Admin Console — QA Report

**Date:** 2026-08-14
**Scope:** A full Administration console (Users, Roles & Permissions, Audit Log, Overview) with genuine multi-admin support, backend-enforced authorization, and no manual database editing required — replacing the prior state where user management had no UI or API at all.

---

## 1. What Already Existed vs. What Was Built

Before touching any code, the existing auth architecture was inspected directly rather than assumed, per the master prompt's "do not build a second auth system" instruction. Two things were already correct and needed no change:

- **`get_current_user()` (`app/auth/rbac.py`) already re-reads `role` and `is_active` from the database on every request**, never trusting the JWT's embedded `role` claim. A role change or account disable already took effect on the very next request with no session-cache to invalidate.
- **The permission-string convention and matrix (`ROLE_PERMISSIONS`, `app/models/user.py`)** already correctly scoped `user:manage`/`audit:read` to `ADMIN` only — they were simply unused by any route.

What was actually missing and had to be built: the CRUD endpoints, the service layer, the frontend, and one real session-management gap (below).

### Backend (new/changed files)
- `app/core/audit.py` — extracted `record_audit()`/`list_audit_log()` out of `runtime_config.py` into a shared module (re-exported for backward compatibility), so user-management code didn't need to import an entire provider-config service to write an audit row.
- `app/core/users.py` — service layer: list/search/paginate, create, update (name/role), enable/disable, reset-password, stats. Race-safe last-admin protection (locks every `ADMIN`-role row before counting, not just the target row). Self-role-change blocked. No hard delete (see §5).
- `app/api/routes/admin.py` — 7 REST endpoints under `/api/v1/admin`, every one gated by `require_permission("user:manage")`.
- `app/models/user.py` — added `last_login_at`, `token_version`.
- Two Alembic migrations, both additive/nullable/defaulted (`7a1c2f9d4e6b`, `3b9e7a2c1d4f`).
- `app/auth/security.py`, `app/auth/rbac.py`, `app/api/routes/auth.py` — `token_version` embedded in every JWT and checked on every request and on refresh; bumped by password reset (§3). Also fixed a small pre-existing bug: `/auth/me` always returned `full_name: ""` regardless of the stored value.

### Frontend (new/changed files)
- `lib/types.ts`, `lib/api.ts` — types and 9 new API functions for the admin surface, plus `getCurrentUser()`.
- `components/ui/input.tsx`, `badge.tsx`, `dialog.tsx` — three new primitives (previously only `Button`/`Card` existed); `dialog.tsx` is the first real use of the already-installed-but-unused `@radix-ui/react-dialog`.
- `components/dashboard/UsersManagementPanel.tsx` — search/filter/sort/paginate table + 4 dialogs (create, edit, reset password, enable/disable confirmation).
- `app/admin/page.tsx` — the console itself: Overview / Users / Roles & Permissions / Audit Log tabs, double-guarded (`isLoggedIn()` then `role === "admin"`, both UX-only redirects — the real boundary is server-side).
- `components/dashboard/WorkspaceNav.tsx`, `app/page.tsx` — an "Administration" link, visible to admins only. The home-page link was added after live testing revealed the home page never rendered `WorkspaceNav` at all (a pre-existing gap for Basket/Cases/Providers too, but one with no other discovery path for this feature) — see §7.

## 2. Automated Test Results

```
202 passed, 10 skipped, 0 failed   (backend: app/tests/unit + app/tests/integration)
```

10 skips are pre-existing and unrelated (integration tests needing host-published DB ports unavailable inside the test container — unchanged from before this work). 21 new tests added this pass, covering:

- CRUD, duplicate-email rejection, password-reset hash verification (`test_admin_users.py`)
- **Last-admin protection under real concurrency**: two simultaneous requests each disabling a *different* one of exactly two remaining active admins — exactly one succeeds, one is rejected, and the database is checked afterward to confirm exactly one admin remains active. This specifically tests the race a naive per-row lock would miss.
- **RBAC matrix / privilege escalation / IDOR**, driven through real HTTP against the real FastAPI app (`test_admin_rbac_api.py`): an ANALYST cannot promote themselves to ADMIN via direct API call (403, role verified unchanged in the DB afterward); a VIEWER cannot disable another user's account (403, target verified untouched); unauthenticated requests are rejected.
- **Immediate effect, proven live**: disabling a user makes their existing, still-unexpired access token fail on its very next request; promoting/demoting a user's role changes what their *same* existing token can do, with no new login.
- **Session invalidation on password reset**: a token minted before an admin-initiated reset stops working immediately; a token reflecting the new `token_version` (as a real subsequent login would produce) keeps working.

Frontend: `npx tsc --noEmit` clean; `npm run build` clean (compiles, lints, generates all 11 routes including `/admin`).

## 3. A Real Bug Found and Fixed: Password Reset Didn't Invalidate Sessions

JWTs are stateless (signature + expiry only). Before this fix, resetting a user's password via the new admin console changed their `hashed_password` but left every already-issued access/refresh token valid until it naturally expired (refresh tokens default to 7 days) — the exact opposite of what an administrator resetting a password for security reasons would expect. Added `token_version` (int, default 0) to `User`; both `get_current_user()` and `POST /auth/refresh` now reject any token whose embedded `token_version` doesn't match the current column value; `reset_password()` increments it. A token issued before this feature existed has no such claim and is treated as version 0, matching every user's initial value — this shipped with zero forced logouts. Verified live and by automated test (§2).

## 4. Live Verification (Real HTTP, Real Browser — Not Just Automated Tests)

**Three real administrators, real HTTP, no minted tokens:** Admin A was bootstrapped, logged in via real `POST /auth/login`, and used its real session to create Admins B and C via the real `POST /api/v1/admin/users`. B and C each logged in independently and exercised admin-only endpoints. Admin A then disabled C; C's existing, still-valid token immediately got `401` on its next call while B's was unaffected; the audit log showed the exact sequence with no secrets in it. All test accounts were cleaned up afterward.

**Real browser (Chrome via `puppeteer-core`, already a doc-build dependency — `documentation/build/walkthrough-admin.js`):** logged in as a real admin, navigated the actual rendered UI, and — via genuine clicks, not API calls — created a user, searched/filtered for it, edited its role, reset its password, disabled it (with the confirmation dialog), re-enabled it, viewed the Roles & Permissions and Audit Log tabs, then logged in as that now-viewer user and confirmed the Administration link does not appear and a direct `/admin` URL visit redirects away. Screenshots captured and promoted into `documentation/SCREENSHOTS/` (`41`–`44`), referenced from the User Manual.

One incidental, pre-existing, out-of-scope finding surfaced by this walkthrough: `AiQuickSwitch` (an unrelated, pre-existing home-page widget) calls `GET /runtime/ai-providers` (`provider:manage`, admin-only) regardless of the signed-in user's role, producing a benign browser-console 403 for a non-admin. This predates this feature entirely and is not part of the Administration console; noted here for completeness, not fixed, per scope discipline.

## 5. Design Decisions Made (and Why)

- **Self-registration (`/auth/register`) stays open**, including after administrators exist — an explicit choice confirmed with the user rather than assumed, since closing it would have been a bigger behavior change than this mission asked for.
- **No hard delete.** `case.py`'s `analyst_id`/`added_by`/`author_id`/`generated_by` and `basket.py`'s `owner_id` are `NOT NULL` foreign keys to `users.id` — discovered while designing the delete flow, before any code was written. Deleting a user who ever created a case or added evidence would either violate those constraints or destroy real investigation data. Disable is the only removal mechanism — this also matches the master prompt's own "preserve audit integrity, prefer disable over delete" instruction.
- **Self-role-change is blocked** (an admin can't change their own role) purely to prevent an accidental mid-session self-lockout, since role changes take effect immediately with no re-login.
- **Last-admin protection locks the whole admin-role row set**, not just the target row, specifically to close the two-concurrent-requests race described in §2.

## 6. Migration / Installer Verification

- Both new columns are nullable/defaulted — applied live against the running installed copy's real database with zero data loss and zero forced re-login (`alembic current` confirmed at head both before and after; existing users' rows and sessions were unaffected).
- **Migrations already auto-apply with no manual step**, confirmed across every deployment path in this repo: `docker-compose.yml`, `docker-compose.prod.yml`, and `k8s/base/backend-deployment.yaml` all run `alembic upgrade head` as part of the backend container's own startup command, before `uvicorn` even starts.
- **No installer changes were needed.** `windows/installer.iss`'s `[Files]` section already packages `backend\*`/`frontend\*` with a recursive wildcard — every new file ships automatically in the next build. The Setup Wizard's existing "first user becomes admin" bootstrap (already backed by the same `/auth/register` rule) already satisfies "no hardcoded single admin" without any wizard change.
- Propagation to the installed copy (`C:\Program Files\IOC Intelligence Platform\app`) and each rebuild were done only after explicit user confirmation, consistent with this engagement's established pattern for touching that environment.

## 7. Known Limitations (Not Release Blockers)

- No self-service password reset/recovery for an unauthenticated user — an administrator must do it via the console. (Self-service "forgot password" was never in scope for this mission.)
- No self-service "log out everywhere" for a user's own other sessions independent of a password change.
- `AiQuickSwitch`'s non-admin 403 console error (§4) — pre-existing, unrelated, not fixed.
- No literal Windows installer GUI click-through was performed for this specific change (consistent with this engagement's established testing approach); verification here was via direct container rebuild/restart of the running installed copy plus real HTTP/browser testing against it.
- Manual UI verification for the interactive dialogs was performed via a scripted real-browser walkthrough (§4) rather than by the user personally clicking through in this exact review pass; the user was offered the option to additionally spot-check and chose to do so in parallel with this work.

## 8. Regression

Full backend suite (202 tests, unrelated to this feature) re-run after every propagation step: unaffected. Live-verified directly: an existing ANALYST account's login, `/auth/me`, case list, and basket list all continue to work exactly as before; the pre-existing 403 on `/runtime/ioc-providers` for a non-admin is original, correct, unchanged behavior (confirmed by reading `ROLE_PERMISSIONS`, not assumed).

---

## Final Verdict

# RELEASE READY

No P0, P1, authentication-bypass, privilege-escalation, unauthorized-admin-access, credential-exposure, database-corruption, or broken-existing-functionality issue was found. One real security-relevant gap (password reset not invalidating existing sessions) was found and fixed during this pass, not merely documented. All findings that were not fixed are pre-existing, out-of-scope, or genuinely non-blocking limitations, enumerated above rather than hidden.
