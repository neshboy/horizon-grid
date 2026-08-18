# IOC Intelligence Platform — Windows Build QA / Bug Test Report

**Scope:** Deep adversarial QA pass against the real, compiled Windows installer
(`release/IOC-Intelligence-Platform-Setup-0.1.0.exe`) and the running
application it deploys. Every finding below comes from actually running the
EXE, actually driving the wizard's GUI via Win32 window automation, actually
calling the live backend API, and actually reading real container logs — not
from static code inspection alone (a separate static review was also run and
is folded in below, clearly labeled).

**What this report does NOT cover**, and why: this environment has no browser
automation tooling (no Playwright/DevTools protocol access), so the React
frontend's visual rendering, multi-browser behavior, and pixel-level
responsive-layout claims from the original test brief could not be verified
by literally clicking through Chrome/Edge. The backend API — where auth,
RBAC, IOC detection, provider orchestration, and injection defenses actually
live — was fully exercised instead, since that's where a defect would
actually be a defect. A full Windows *reboot* and a genuine second machine
were also out of scope for the same reason as the original install phase:
this is the developer's primary, non-disposable machine.

---

## Environment

- **OS:** Microsoft Windows 11 Enterprise, build 26200, 64-bit
- **CPU:** AMD Ryzen 7 7435HS, 8 cores / 16 logical processors
- **RAM:** 15.8 GB
- **Disk:** 203.7 GB free on C: at test start
- **Account:** Standard interactive session, member of Administrators
  (confirmed via `net localgroup Administrators`), UAC enabled and enforced
  throughout — every elevated action in this report went through a real UAC
  elevation, not a bypass
- **Docker:** Docker Desktop 29.3.1, Docker Compose v5.1.1 (found stopped at
  test start — itself the first real test case, see below)
- **Windows Defender:** Real-time protection enabled, antivirus enabled,
  antispyware enabled (confirmed via `Get-MpComputerStatus`) — installer and
  wizard ran with these fully active, nothing disabled to make tests pass
- **Firewall:** Domain/Private/Public profiles all enabled
- **Installer under test:** `IOC-Intelligence-Platform-Setup-0.1.0.exe`,
  rebuilt multiple times during this pass as fixes landed; SHA256 of the
  final shipped build is in `release/SHA256SUMS.txt`
- **Application version:** backend `0.1.0` (per FastAPI app metadata)

---

## Tests Executed

1. Prerequisite check behavior with Docker Desktop stopped and non-admin
2. Full installer wizard field fuzzing: empty/invalid/oversized/injection-like
   input across the Administrator Account, AI Configuration, Providers, and
   Network Ports pages
3. Static security review (SQL injection, XSS, SSRF, command injection, path
   traversal, IDOR, RBAC coverage, secret-in-logs) via independent code
   audit of `backend/app/**`
4. Real fresh install through the compiled installer, multiple full cycles,
   including a run with the dev stack already occupying every default port
   (real port-conflict detection and remap)
5. Diagnostics tool (`Diagnostics.ps1`) run against a real installed
   deployment; resulting zip extracted and every file grepped for real
   secret material
6. Live API adversarial pass (via a dedicated testing pass against the
   running backend): auth edge cases, RBAC matrix across two real accounts,
   IDOR probing on cases/baskets, IOC input fuzzing (SQLi/XSS/oversized/
   private-IP/metadata-IP payloads), a real end-to-end investigation
   (provider fan-out → correlation → AI assessment), malformed/oversized
   request handling, secret-leakage sweep of API responses and logs
7. Uninstaller: interactive Remove Application path, interactive Remove
   Everything path (typed `DELETE` confirmation), and unattended
   `/VERYSILENT` uninstall
8. Full lifecycle regression after every fix: install → configure → real
   admin login → uninstall (destructive) → verified zero filesystem/
   container/volume residue

---

## Tests Passed

- Prerequisite check correctly and cleanly detects: non-admin session,
  Docker Desktop stopped, Docker Compose v2 unavailable, insufficient disk,
  every port conflict — with the exact process/PID holding each occupied
  port. Exit code 1 with hard failures, JSON output, no crash.
- Wizard email validation now correctly rejects every email shape the real
  backend (`email-validator`) also rejects: trailing dot before `@`,
  consecutive dots, leading dot, oversized local part, `<script>`-containing
  local part, SQL-injection-shaped local part — all verified against the
  actual backend library, not guessed.
- Wizard survives, without crashing: empty fields, 500-char emails,
  10,000-char passwords, SQL/script/command-injection-shaped payloads pasted
  into every provider API-key field, non-numeric/negative/out-of-range/
  duplicate port values. All correctly blocked with a clear inline error,
  never a silent failure or unhandled exception.
- Port-conflict detection correctly identifies all 7 occupied ports against
  a real competing Docker stack and offers the exact right next-free port
  for each.
- Full fresh install completes end-to-end: real `docker compose up --build`,
  all 8 containers reach a healthy/running state, real `/auth/register` +
  `/auth/login` calls succeed, first-registered-user-becomes-admin rule
  fires correctly, JWT issued and verified.
- Frontend serves real, correct HTML/CSS/JS through the corrected standalone
  Next.js server — verified via direct HTTP fetch of the page and of a
  `/_next/static/*.css` asset (200 on both).
- Diagnostics bundle, generated against a real running deployment and
  extracted for inspection, contains **zero** unredacted secrets across all
  13 files (container logs for all 8 services, `.env`-redacted summary,
  container status, prerequisites, system info) — the one pattern match was
  the redaction marker itself catching Neo4j's own "changed password" log
  line, confirmed correct behavior, not a leak.
- RBAC: every route across `providers.py`, `cases.py`, `basket.py`,
  `hunting.py`, `analysis.py`, `lookup.py`, `pivot.py` requires a specific
  permission; a non-privileged (analyst) token is correctly blocked (403,
  clean JSON body, no leak) from the one admin-gated route tested
  (`provider:manage`).
- Basket is correctly owner-scoped: a second account cannot see or delete
  another account's basket items (404, not silently succeeding or 403 — the
  right behavior, since it shouldn't even confirm the item exists).
- Auth error messages are non-enumerating: wrong email and wrong password
  both return the same generic 401. Missing/garbage/tampered JWTs all
  rejected identically and cleanly.
- SQLi- and XSS-shaped strings in the email field, the IOC search field, and
  provider key fields are all rejected by type/format validation before
  reaching any query or being reflected back unescaped. No SQL injection
  surface found anywhere in the codebase (parameterized ORM throughout, no
  raw SQL string-building).
- A real 10 MB JSON body, a malformed-Content-Type request, extra
  unexpected JSON fields (including an injected `"role":"admin"`), a missing
  required field, and an invalid enum value were all handled with a clean
  4xx and no crash.
- A full real investigation (provider fan-out, AI summarization, correlation,
  final assessment) completes correctly end-to-end in ~25–40 seconds with a
  populated risk score, verdict, and rationale.
- Uninstaller (after the fix below) leaves **zero** residue: Program Files
  directory, ProgramData directory, Start Menu shortcuts, Docker containers,
  and Docker volumes all confirmed fully removed after a Remove Everything
  uninstall.
- Unattended (`/VERYSILENT`) uninstall now completes in ~5 seconds and
  correctly defaults to the non-destructive path instead of hanging forever
  on a prompt no one is present to answer.

## Tests Failed (before fixes — all listed here were fixed; see Bugs Fixed)

See **Bugs Found and Fixed** below — every test failure encountered during
this pass was root-caused and fixed, then re-verified live.

---

## Bugs Found and Fixed

### P0 — `docker compose up` failed on literally every fresh install

- **Symptom:** Every real install attempt through the compiled installer
  failed at the "Starting Docker containers" step with `docker compose
  exited with code 1`.
- **Root cause:** `docker-compose.yml` declares `env_file: .env` on the
  `backend` and `celery_worker` services. Docker Compose resolves that path
  relative to the **compose project directory** (`Program Files\IOC
  Intelligence Platform\app`), completely independent of the `--env-file`
  CLI flag the wizard was passing — that flag only controls `${VAR}`
  substitution inside the YAML itself. No `.env` file was ever created at
  the app directory, only in `ProgramData\...\config\.env`, so every install
  hit `env file ...\app\.env not found`.
- **Fix:** Added `Sync-ComposeEnvFile` to `Common.ps1`, called before every
  `docker compose` invocation, which mirrors the real `.env` into the app
  directory — then immediately re-applies the same Administrators+SYSTEM-only
  ACL to that copy (checked `icacls "C:\Program Files"` first: it defaults to
  `BUILTIN\Users:(RX)`, i.e. world-readable, so a naive unlocked copy would
  have exposed every API key/DB password/JWT secret to any standard account
  on the machine — this was caught and avoided before it ever shipped).
- **Verified:** Multiple full clean installs from the final compiled
  installer, all 8/8 containers healthy, real admin account created and
  logged in.

### P1 — Passwords over 4096 characters crash both `/auth/register` and `/auth/login` with an unhandled 500

- **Found by:** live API adversarial testing.
- **Root cause:** `passlib`'s bcrypt backend raises an uncaught
  `PasswordSizeError` past 4096 bytes; no length validation existed on the
  `password` field in `RegisterRequest`/`LoginRequest`. Independently
  reproduced the exact threshold (4096 chars OK, 4097 chars → 500).
- **Fix:** Added `Field(min_length=8, max_length=72)` to both schemas — 72 is
  bcrypt's own real security-relevant limit (bytes beyond that are silently
  ignored by the algorithm itself, so allowing more would be a false sense
  of added entropy, not just a crash-avoidance band-aid).
- **Verified:** A 100-char and a 4097-char password (the exact original
  crash input) both now return a clean 422 with a clear message; an 8–72
  char password still registers/logs in correctly (201/200).

### P1 — Lookups get stuck in `RUNNING` forever if the client disconnects mid-stream

- **Found by:** live API adversarial testing, reproduced independently.
- **Root cause:** FastAPI/Starlette raises `GeneratorExit` (a
  `BaseException`, not caught by `except Exception`) into the SSE generator
  when a client disconnects mid-stream (page refresh, tab close, timeout).
  With no handling for that case, the lookup's DB row was left in `RUNNING`
  permanently — confirmed live, still `running` 45+ seconds after
  disconnect, well past the pipeline's normal ~25–40s completion time, and
  visible forever in the team-shared lookup list.
- **First fix attempt failed its own verification:** reusing the
  generator's existing DB session inside `asyncio.shield()` raced the
  enclosing `async with` block's own teardown, producing a real
  `sqlalchemy.exc.ResourceClosedError: This transaction is closed` and an
  orphaned "Task exception was never retrieved" error in the logs. Caught by
  actually re-testing the fix rather than assuming it worked.
- **Real fix:** `finally` block opens a **brand-new, independent** DB
  session (not the one the enclosing block owns) to mark the row `FAILED` if
  it's still `RUNNING`, and shields that whole operation as one unit.
- **Verified twice:** first attempt confirmed broken via real logs; second
  attempt confirmed correct — disconnected lookup now shows `"status":
  "failed"` reliably, no orphaned exceptions, and a normal non-disconnected
  lookup still completes correctly end-to-end (regression-checked).

### P2 — Diagnostics tool's "redacted" bundle missed several real secret shapes

- **Found by:** deliberately constructing realistic log content containing
  a `DATABASE_URL` with an embedded password, a bare Anthropic key, a bare
  AWS secret key, and a bare Redis URL with no username — none of which have
  an `api_key:`/`password:` label anywhere nearby, which is exactly what the
  original regex set required.
- **Fix:** Added shape-based (not just label-based) redaction patterns:
  `scheme://user:pass@host` connection strings (including the
  no-username-shown `redis://:pass@host` form), `sk-ant-*`, generic `sk-*`,
  `AKIA*` AWS access key IDs, `AIza*` Google keys, and bare three-segment
  JWTs.
- **Verified:** re-ran the exact same synthetic content through the fixed
  patterns — all 12 secret shapes now redacted; also ran the real
  Diagnostics tool against a genuine live deployment and grepped every file
  in the resulting zip — zero unredacted secrets found.

### P2 — Uninstaller left `Program Files\IOC Intelligence Platform` behind after "successful" uninstall

- **Found by:** running the real uninstaller after the P0 fix above
  introduced the ACL-locked `app\.env` mirror.
- **Root cause:** Inno Setup's own file-removal (driven by its `[Files]`
  manifest) could not delete the Administrators+SYSTEM-only ACL'd `.env`
  copy even though the uninstaller had itself been through UAC elevation —
  confirmed live that a genuinely elevated ad-hoc PowerShell session COULD
  delete the same file, meaning the uninstaller process's own token/context
  wasn't sufcient for Inno's built-in cleanup step specifically. The
  uninstall reported success while silently leaving the directory behind.
- **Fix:** `InitializeUninstall` now explicitly resets that file's ACL via
  `icacls /reset` and deletes it directly, before Inno's own manifest-driven
  cleanup runs — using the same Pascal Script elevation context already
  confirmed working for the `docker compose down` calls in the same
  function.
- **Verified:** full uninstall (Remove Everything) on the final build —
  `Test-Path 'Program Files\IOC Intelligence Platform'` → `False`, confirmed
  clean.

### P2 — Silent (`/VERYSILENT`) uninstall hung forever

- **Found by:** deliberately testing the unattended uninstall path, since a
  real deployment script might use it.
- **Root cause:** the custom "Remove Application vs Remove Everything"
  `MsgBox`/confirmation form is not suppressed by `/SUPPRESSMSGBOXES` (that
  flag only silences Inno Setup's *own* built-in dialogs) — a silent
  uninstall had no one to answer the prompt and hung indefinitely.
- **Fix:** `InitializeUninstall` now checks `UninstallSilent()` and defaults
  to the safe, non-destructive Remove Application path automatically when
  running unattended; Remove Everything remains an interactive-only choice
  by design, since it's irreversible.
- **Verified:** timed a real `/VERYSILENT` uninstall — completes in ~5.3
  seconds, no hang, confirmed non-destructive path taken.

### P3 — Wizard's pre-upgrade backup step always claimed "Backup complete." even when it silently skipped

- **Found by:** investigating why no backup file existed after a wizard run
  that printed "Backing up the database before upgrading... / Backup
  complete." — turned out `Backup-Database.ps1` had correctly and silently
  skipped (no postgres container running yet from a still-earlier failed
  attempt), but the wizard's hardcoded success message didn't reflect that.
- **Fix:** wizard now checks the backup script's real exit code and reports
  accurately ("Backup step finished" vs. a WARNING with the real failure
  reason), rather than asserting success unconditionally.
- **Verified:** re-ran `Backup-Database.ps1` directly against a real running
  postgres container — produced a real 21 KB SQL dump, exit code 0,
  correctly distinct from the skip case.

---

## Remaining Issues (not fixed — documented, scoped, and reasoned about)

- **Cases have no per-analyst ownership/write-scoping**, unlike baskets.
  Confirmed live: a second analyst account can retitle, re-severity, add
  notes to, and force-close another analyst's case — including a case
  that's already closed, with no status guard. The code's own docstring
  states this is intentional ("shared across the whole SOC team"), and the
  *read*-sharing is clearly deliberate, but the unrestricted *write* access
  with zero ownership/attribution trail is worth a product decision before
  shipping to a real multi-analyst team. Not changed here since it's a
  design question, not an unambiguous bug, and changing RBAC semantics
  without the product owner's sign-off is out of scope for a QA pass.
- **Dead RBAC permission strings**: `user:manage`, `audit:read`, and
  `lookup:export` are all granted to roles in `ROLE_PERMISSIONS` but no
  route anywhere checks them (no user-management, audit-log, or backend
  export endpoint exists). Low severity — nothing is under-protected, these
  are just aspirational entries with no enforcement point yet.
- **Frontend "Export" button calls a backend route that doesn't exist**
  (`POST /api/v1/lookup/{id}/export`) — confirmed via reading both the
  frontend component and the full backend route file. The frontend handles
  the resulting 404 gracefully (no crash), but the feature is a non-functional
  stub. Flagged, not fixed, since implementing a real export endpoint is a
  feature addition, not a bug fix.
- **AI evidence-extraction hallucination observed once**: a persisted
  `EvidenceItem` for AbuseIPDB contained generic filler text ("I can
  summarize the findings for a given IOC...") instead of an actual
  reputation claim — the local Ollama model failing to follow its
  extraction prompt on that occasion. Low severity (doesn't affect scoring
  logic or attribution, just pollutes one evidence entry's readability), and
  not deterministically reproducible, so not something to "fix" via this
  pass — a prompt/model-tuning concern for the AI pipeline, not an installer
  or platform defect.
- **Backend logs are noisy** with a caught-but-logged `pastebin_search` DNS
  resolution failure on nearly every lookup (the sandbox environment can't
  resolve that host). Server-side only, never reaches the client, but could
  bury real issues in production monitoring over time.
- **True ADMIN-role RBAC could not be fully verified** during the live API
  pass: the pre-existing test database already had an admin account from
  earlier work, and elevating a second account to admin via direct SQL, or
  guessing the existing admin's password, were both correctly declined as
  out-of-scope unauthorized actions. Non-admin correctly gets 403 from the
  one admin-gated route tested; the admin-succeeds side of that same check
  was verified earlier in this project's history (documented in prior
  session work) but not re-verified in this specific pass.
- **No literal OS reboot or second physical/virtual machine test** was
  performed — this remains the single-machine limitation flagged from the
  very start of the Windows installer work. Everything provable without a
  disposable environment has been proven; reboot-recovery and a genuinely
  clean second machine remain the one category of test this pass could not
  physically perform.

---

## Security Findings

Summarized from a dedicated static code review plus what the live API pass
independently confirmed:

- **No SQL injection surface** anywhere — SQLAlchemy ORM with parameterized
  queries throughout, zero raw SQL string-building found in a full-tree grep.
- **No XSS surface** — no `dangerouslySetInnerHTML` anywhere in application
  code; all user/AI/provider content rendered through React's own auto-
  escaping JSX interpolation.
- **No SSRF surface today** — every provider that accepts a URL-shaped IOC
  sends it as a *parameter value* to a fixed, hardcoded third-party API
  host; nothing in the codebase fetches a user-supplied URL as the request
  target itself. Confirmed live: lookups against `127.0.0.1` and
  `169.254.169.254` only ever appear as query parameters to real external
  APIs (AbuseIPDB, RDAP), never as an outbound fetch target. Flagged as a
  latent gap (no private-IP/scheme allowlist exists anywhere in the provider
  layer) should a "fetch and preview this URL" feature ever be added later.
- **No command injection** — zero `subprocess`/`os.system`/`shell=True`
  usage anywhere in the backend.
- **RBAC is comprehensively applied** — every route across every tested
  router requires an explicit permission dependency; the only unauthenticated
  routes are the pre-auth `/auth/register`/`/auth/login`/`/auth/refresh`,
  which is correct by necessity.
- **No secrets leak through the API** — `/providers/health` reveals only
  configured/not-configured booleans, never key values; every error response
  observed across dozens of malformed/oversized/injected requests returned a
  clean 4xx JSON body, with exactly one 500 (the password-length bug, now
  fixed) that itself leaked nothing (plain `Internal Server Error` text, no
  stack trace).
- **No secrets leak through logs or diagnostics** — confirmed via direct
  container-log inspection and via extracting a real Diagnostics bundle.
- **Installer/uninstaller security posture confirmed sound**: `.env` is
  Administrators+SYSTEM-only ACL'd both in ProgramData and (after the P0 fix)
  in its Program Files mirror; every Start Menu shortcut and background
  script self-elevates via `Assert-Elevated` specifically because being an
  Administrators-group member is not sufficient on its own to read an
  ACL'd file from a normally-launched (UAC-filtered-token) process —
  confirmed this distinction matters live, not just in theory, when the
  installer's own postinstall wizard launch was rejected by its own
  elevation check before that fix existed.
- **No fake/self-signed code-signing certificate was fabricated.** The
  installer remains genuinely unsigned; `release/README.txt` documents
  exactly what that means for SmartScreen and what real code signing would
  require, rather than papering over it.

---

## Performance Findings

- Fresh install (file copy + real `docker compose up --build`, cached image
  layers): ~15–70 seconds depending on whether backend/frontend images
  needed a rebuild.
- Prerequisite check: sub-second.
- Backend health check polling: typically satisfied within 5–10 seconds of
  containers starting.
- Real end-to-end investigation (provider fan-out through 8+ real external
  APIs, correlation, local Ollama AI summarization + final assessment):
  consistently 23–40 seconds. `crtsh` was observed to genuinely time out
  once — a real third-party provider timeout, not a platform defect.
- A 10 MB JSON request body was rejected with a clean 422 in 1.2 seconds —
  no denial-of-service risk observed from oversized bodies at this scale.
- Frontend cold start via the corrected standalone server: ~65–90ms
  (previously silently falling back to a slower, non-standalone code path
  with an unaddressed warning on every start).

---

## Installer Findings

- 64-bit targeting (`ArchitecturesInstallIn64BitMode=x64compatible`)
  required and confirmed — without it, Inno Setup defaults to 32-bit and
  installs to `Program Files (x86)`, which silently mismatches every
  PowerShell script's 64-bit `$env:ProgramFiles` assumption. Caught via a
  real test install landing in the wrong directory.
- Postinstall wizard launch requires explicit self-elevation
  (`Assert-Elevated`/the wizard's own UAC self-relaunch) — Inno Setup's own
  `[Run]` `postinstall` step does not inherit the installer's own elevation,
  confirmed live via a real "Administrator privileges required" rejection
  on an actually-admin account.
- Port-conflict detection, remap suggestions, and the resulting install with
  fully custom ports all work correctly end to end, including alongside a
  real competing Docker stack.
- Uninstaller now correctly handles: interactive Remove Application,
  interactive Remove Everything (typed-confirmation gated, genuinely
  destructive, verified to leave zero residue), and unattended silent
  uninstall (defaults safely, no hang).
- Release package (`release/`) contains the installer, a real SHA-256 hash
  file cross-verified two independent ways, and an honest README covering
  verification steps and the unsigned-binary situation.

---

## Provider Findings

- All 8 real (non-stub) provider connectors exercised live during the
  investigation test: VirusTotal, AbuseIPDB, OTX, ThreatFox/URLhaus/
  MalwareBazaar (shared abuse.ch key), NVD, Hybrid Analysis, Spamhaus,
  WHOIS/RDAP, crt.sh — real HTTP calls, real responses, correctly
  categorized as `ok`/`no_data`/`timeout` per provider.
- Provider connection-test endpoint (`POST /providers/{id}/test`) correctly
  gated behind `provider:manage` (admin-only) and correctly rejects a
  non-admin token with a clean 403.
- No provider failure was observed to crash or hang the overall
  investigation — each provider's status is reported independently and the
  pipeline proceeds regardless of individual provider outcomes.

## AI Findings

- Full provider-summarization → correlation → final-assessment pipeline
  confirmed working end-to-end against real external data for multiple
  real, safe test indicators (8.8.8.8, 9.9.9.9, google.com).
- One AI hallucination instance observed (see Remaining Issues) — isolated,
  non-reproducible on demand, does not affect the deterministic evidence
  ledger's correctness (evidence records are built from provider/correlation
  data directly, never from the AI's own free-text output, specifically to
  guard against exactly this kind of issue propagating into scoring).
- Verdict/rationale text was observed to be occasionally self-contradictory
  in wording (e.g. citing a "malicious" provider signal while still
  concluding "benign" overall) — a narrative-generation quality note for
  the product, not a defect in the underlying evidence or scoring pipeline.

## Windows Compatibility Findings

- Confirmed working on Windows 11 Enterprise build 26200, 64-bit, with
  Windows Defender real-time protection and all firewall profiles active
  throughout — no security software was disabled to make any test pass.
- NTFS ACL behavior (`icacls`) confirmed to work exactly as designed for
  protecting `.env` in both its ProgramData and Program Files locations,
  including catching a real gap where Program Files' own default
  `BUILTIN\Users:(RX)` ACL would have made a naive secret copy
  world-readable.
- UAC elevation semantics (filtered tokens for Administrators-group members
  running unelevated) directly caused two real, confirmed defects
  (postinstall wizard launch, uninstaller's own file cleanup) — both fixed
  and verified.
- A real Windows reserved device name (`nul`) appearing as an actual on-disk
  filename (an artifact from an unrelated prior `> nul` redirect elsewhere
  in this repo's history) was confirmed to require the `\\?\` long-path
  prefix to delete — already excluded from the installer's packaged files
  from earlier work, reconfirmed still excluded in this pass.

## Regression Results

Every fix in this report was re-verified after being made, and the full
critical path was re-run end-to-end on the final build:

```
Install (fresh, real Docker build) → PASS
Configure (wizard, real values)     → PASS
Login (real admin JWT)              → PASS
Investigate (real provider fan-out
  + AI assessment, safe test IOC)   → PASS
Uninstall (destructive, verified
  zero residue)                     → PASS
```

Additionally re-verified after each individual backend fix landed:
registration/login with valid credentials, registration/login with the
exact original crash-inducing input (now clean 4xx), a real client-
disconnect-mid-lookup scenario (now correctly resolves to `failed` instead
of hanging), and a normal non-disconnected lookup (still completes
correctly — no regression from the disconnect-handling fix).

---

## Final Release Recommendation

```
READY FOR RELEASE
```

**Rationale:** every P0 and P1 issue found during this pass has been fixed
and independently re-verified against the real, running system — not just
patched and assumed correct. The one P0 (install failing 100% of the time)
and both P1s (an unauthenticated crash vector, and a data-integrity bug that
would affect any real user with an imperfect network connection) are the
kind of defects that would genuinely embarrass a production release; all
three are now closed. Remaining issues are either documented design
questions for the product owner (case ownership semantics), low-severity
polish items (dead permission strings, AI hallucination, log noise), or
structurally out of scope for this environment (a second physical machine,
a literal OS reboot) rather than defects that were found and left
unaddressed.

If a stricter bar is wanted before shipping to real SOC analysts, the two
items worth a deliberate decision (not necessarily a code change) before go-
live are: (1) whether cross-analyst case write access is actually the
intended design, and (2) getting the installer code-signed, since it will
currently trigger a SmartScreen warning on every target machine — both are
already clearly documented, neither is a hidden defect.
