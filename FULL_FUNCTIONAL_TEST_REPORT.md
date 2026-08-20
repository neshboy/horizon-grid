# HORIZON GRID — Full Functional Test Report

Status: **IN PROGRESS**. This file is updated live as the mission proceeds; sections are
appended phase by phase rather than written once at the end, so a mid-mission read reflects
real, already-completed work, not a plan.

## Phase 0 — Baseline

| Field | Value |
|---|---|
| Version (frontend `package.json`) | 0.2.3 |
| Version (Windows installer) | 0.2.3 (`windows/installer.iss` `MyAppVersion`) |
| Version (Linux package) | 0.2.3 (`release/horizon-grid_0.2.3_amd64.deb`) |
| Git commit | `f6be98d20f2c60deaa35897639cf14ac9fd48f44` |
| Git branch | `main` |
| OS | Windows 11 Enterprise, build 10.0.26200 |
| Architecture | x64 |
| CPU | AMD Ryzen 7 7435HS |
| RAM | 16,200 MB |
| Disk (C:) | 480 GB total, 149 GB free at mission start |
| Docker | 29.3.1 (Compose v5.1.1) |
| WSL distro (Linux test target) | Ubuntu-24.04 (running) |
| Node.js (frontend build) | v24.14.1 |
| Python (backend, in-container) | 3.12.14 |
| PostgreSQL | 16.15 |
| Redis | 7.4.10 |
| Pre-existing dev stack | `hgmc-*` Docker Compose project, running, healthy (NOT the installer-based deployment — used for reference/comparison only, not as the system under test for installer-dependent phases) |
| Pre-existing installed copy | None with a registered uninstall entry. A stray, untracked folder existed at `C:\Program Files\IOC Intelligence Platform\app\` (no registry uninstall key) predating this mission — moved aside (not deleted) before Phase 1 so the installer test starts from a genuine clean slate; see Phase 1 notes. |
| Windows installer artifact under test | `release\HORIZON-GRID-Setup-0.2.3.exe` |
| Linux package artifact under test | `release\horizon-grid_0.2.3_amd64.deb` |
| Date/time (mission start) | 2026-08-21 |

**Test philosophy applied**: black-box (real UI, real installer, real reboot where authorized)
combined with white-box (logs, DB, container inspection) verification per feature area, per the
mission's own explicit instruction that neither alone is sufficient.

**User-authorized disruptive actions for this mission** (recorded here since they materially
change what "clean" and "reproducible" mean for later phases):
- A real Windows reboot (`shutdown /r`) is authorized for Phase 24 and will actually be executed.
- A real elevated installer run is authorized; the user will manually click through the UAC
  prompt when instructed.
- Network-failure testing (Phase 19) will be simulated at the Docker container level
  (blocking egress from the backend container specifically), not by disconnecting the host's
  real network adapter.

No results are recorded as PASS until actually executed. Sections below are filled in as each
phase completes.

## Bugs found and fixed during Phase 1 (clean install)

### BUG-001 (P0, release blocker) — Shipped installer `.exe` was stale, missing `docker-compose.yml`
- **Environment**: Windows 11 Enterprise, real elevated install of `release\HORIZON-GRID-Setup-0.2.3.exe`.
- **Steps to reproduce**: Run the installer as a real end user (UAC + Setup Wizard), reach "Start
  Installation".
- **Expected**: `docker compose up -d --build` starts the stack.
- **Actual**: `docker compose up failed with exit code 1`. Root cause traced to
  `C:\Program Files\IOC Intelligence Platform\app\` containing only stale `backend/frontend/windows`
  subfolders from an earlier ad-hoc copy (Aug 18) — no `docker-compose.yml`/`docker-compose.prod.yml`
  at all, despite `windows/installer.iss`'s `[Files]` section unconditionally specifying both.
- **Root cause**: The `.exe` in `release/` had never actually been recompiled from the current
  `installer.iss` — it was a stale artifact. Confirmed by installing Inno Setup 6 (not present on this
  machine) and recompiling from current source: the fresh build's compile log correctly listed both
  compose files as compressed into the package.
- **Fix**: Recompiled `HORIZON-GRID-Setup-0.2.3.exe` from current source via `ISCC.exe installer.iss`.
- **Regression test**: none automated yet (installer builds aren't covered by the CI test suite) —
  recommended follow-up: a CI step that compiles the installer and asserts the compiled package
  contains `docker-compose.yml`/`docker-compose.prod.yml` before a release is cut.
- **Verification**: re-ran the rebuilt installer; compose files confirmed present post-install.

### BUG-002 (P0, release blocker) — Stale registry `InstallLocation` silently redirected every install to a fake path
- **Environment**: same as above.
- **Steps to reproduce**: Run the (now-fixed) installer again after BUG-001's fix.
- **Expected**: Files install to `{autopf}\IOC Intelligence Platform\app` (the real
  `C:\Program Files\...`), matching where the Setup Wizard's own `$env:ProgramFiles`-based path
  logic looks for them.
- **Actual**: Inno Setup's file-copy step silently installed to
  `C:\HGVerifyWin\ProgramFiles\IOC Intelligence Platform\app\` instead — a leftover path from an
  earlier automated verification harness run (`C:\HGVerifyWin\install_harness.ps1`, dated Aug 19-20,
  predating this test). The Setup Wizard, using the real `$env:ProgramFiles`, correctly wrote `.env`
  to the real `C:\ProgramData\...` path and then ran `docker compose up` from the real
  `C:\Program Files\...\app`, which never received the copied files — a straight path mismatch
  between the two halves of the installer.
- **Root cause**: `HKLM\SOFTWARE\...\Uninstall\{B7E4A1C2-...}_is1`'s `InstallLocation` value was
  registered as `C:\HGVerifyWin\ProgramFiles\IOC Intelligence Platform\` by that earlier harness run.
  Inno Setup's default `UsePreviousAppDir=yes` behavior means every subsequent install (real or
  scripted, silent or interactive) silently reuses whatever directory the *previous* install used,
  regardless of `DefaultDirName`, unless a human notices and manually changes it on the "Select
  Destination Location" page.
- **Fix**: Removed the stale registry uninstall key entirely; moved `C:\HGVerifyWin\` aside
  (preserved, not deleted, as `HGVerifyWin.old-harness-backup`) along with the stray pre-existing
  `C:\Program Files\IOC Intelligence Platform` folder and `C:\ProgramData\IOC Intelligence Platform`
  config directory (moved aside as `*.pre-mission-backup`/`*.pre-mission-config-backup`), so the next
  install starts from a genuinely clean slate.
- **Regression test**: none automated (this is an environment-state bug, not a code bug — no code
  change was needed). Process recommendation: any local verification harness that installs to a
  non-default directory should use `/DIR=` on a per-run basis and explicitly uninstall/clean its
  registry entry afterward, never leaving a persistent `InstallLocation` that a real subsequent
  install would silently inherit.
- **Verification**: re-ran the installer after cleanup; `docker-compose.yml`/`docker-compose.prod.yml`
  confirmed present at the real `C:\Program Files\IOC Intelligence Platform\app\` path this time.

## Phase 1 — Clean Installation: **PASS** (after the two fixes above)

Performed via a real elevated run of the rebuilt installer (Inno Setup file-copy phase, silent mode
after elevation was already established) plus the exact same `Write-PlatformEnvFile`/
`Invoke-DockerCompose` functions the interactive Setup Wizard itself calls (invoked directly rather
than through the WinForms GUI — see "Known testing gap" below).

Verified:
- Installer's `[Files]` section copies to the correct real path (`C:\Program Files\IOC Intelligence
  Platform\app\`), containing `docker-compose.yml`, `docker-compose.prod.yml`, `backend/`,
  `frontend/`, `windows/`.
- `.env` written to `C:\ProgramData\IOC Intelligence Platform\config\.env`, ACL-restricted to
  Administrators+SYSTEM (confirmed: unelevated read attempts get `Access is denied`).
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` — all 8 containers
  created, started, and reached Healthy/Started state; exit code 0.
- Backend health: `GET /health/detailed` → `{"status":"healthy","version":"0.2.3","dependencies":
  {"postgres":{"ok":true},"redis":{"ok":true}}}`.
- Frontend: `next build` runs at container start (~15-20s), then serves HTTP 200 on `/` and `/login`.
- Firewall rule "HORIZON GRID" created for ports 3000/8000 (Private profile only).
- Start Menu shortcuts and registry uninstall key created correctly on a genuinely clean install.

**Known testing gap, disclosed**: the Setup Wizard's own WinForms GUI (the interactive
admin-account/AI-config/providers/ports pages) was not driven end-to-end through its actual UI —
no tool in this environment can click/type into a native Windows Forms application (browser
automation only reaches Chromium content). The wizard's own PowerShell functions
(`Write-PlatformEnvFile`, `Invoke-DockerCompose`) were invoked directly instead, which exercises the
exact same code the GUI calls, but does not prove the GUI's own event handlers correctly collect and
forward that data. This is a real, disclosed gap, not a claim of full UI coverage.

## Phase 2 — First Launch: **PASS**

- Backend started, reported healthy within the 3-minute window the real wizard polls for.
- Frontend loaded, served real HTML (not a blank/error page) on first request after its in-container
  `next build` completed.
- No crash, no infinite loading observed across repeated checks.

## Phase 3 — Authentication: PARTIAL (in progress)

- `POST /api/v1/auth/register` with a `.test`-TLD email correctly rejected (`422`, IANA-reserved
  special-use domain) — confirms real email validation is active, not a bug.
- `POST /api/v1/auth/register` with a valid domain succeeded (`201`), first-ever account, `role: admin`.
- `POST /api/v1/auth/login` with correct credentials succeeded (`200`, real access+refresh JWTs).
- `POST /api/v1/auth/register` for a second account correctly rejected (`403`, "Self-registration is
  closed. Ask an administrator to create your account from the Administration page.") — confirms
  bootstrap-only registration behavior matches documentation.
- Incorrect password / incorrect username → both `401 "Invalid email or password"` (correctly
  generic, doesn't leak which field was wrong or whether the account exists).
- Empty credentials → `422` (Pydantic email validation).
- Unauthenticated access to a protected route (`GET /admin/users` with no token) → `401 "Could not
  validate credentials"`.
- Login rate limiter: verified functioning (10 attempts/60s per account, `429` beyond that),
  confirmed by accounting for a shared counter across two separate test calls against the same
  account — not a bug.
- Remaining: logout, restart persistence, reboot persistence — continuing in later phases.

## Phase 4 — User Management / RBAC: **PASS**

- Created Admin #2, one Analyst, one Viewer via `POST /admin/users` as the bootstrap admin — all
  `201`, correct roles recorded.
- `GET /admin/users` as Analyst or Viewer → both `403 "Role '...' lacks permission 'user:manage'"`.
- `GET /runtime/ioc-providers` as Analyst → `403 "Role 'analyst' lacks permission
  'provider:manage'"` (provider config is correctly admin-only).
- `POST /lookup/stream` as Viewer → `403` (viewer correctly lacks `lookup:create`).
- `POST /lookup/stream` as Analyst → `200`, real SSE stream (see Phase 6/10 below).

## BUG-003 (P1, real correctness bug) — `threat_assessment` could contradict the validated `final_verdict`

Found live during Phase 6/10 testing (a real investigation of 8.8.8.8, not a synthetic test).

- **Steps to reproduce**: run a real investigation with Ollama as the AI backend and no IOC
  provider API keys configured (so evidence is real but sparse/contradictory across sources).
- **Expected**: every field in one `FinalAssessment` response describes the same conclusion.
- **Actual**: `threat_assessment: "malicious"` (a bare one-word label) while `final_verdict:
  "benign"` and `risk.malicious_probability: 0.0` in the SAME response. `FinalAssessmentPanel.tsx`
  renders these in two separately-labeled tabs ("Threat Assessment" / "Risk & Verdict"), so an
  analyst could read either tab in isolation and get the opposite of the platform's actual
  determination — for a security tool, this is a real trust/correctness problem, not cosmetic.
- **Root cause**: `FinalAssessment`'s existing `_verdict_must_agree_with_risk` validator only checks
  `final_verdict` against `risk.malicious_probability` — nothing checked `threat_assessment`'s own
  free-text content for agreement with either. A small local model (llama3.2:3b) degenerated to
  writing a bare category word instead of a sentence, and that word happened to be the opposite
  category.
- **Fix**: added a third `model_validator`, `_threat_assessment_bare_verdict_must_agree_with_final_verdict`
  (`backend/app/ai/schemas.py`), narrowly scoped to only fire when `threat_assessment` (stripped,
  lowercased) is an exact match for one of `Verdict`'s own string values AND that value's
  malicious/benign category contradicts `final_verdict`'s — ordinary narrative sentences that merely
  contain the word "malicious" are unaffected. Reuses the existing retry-on-`ValidationError`
  mechanism in `generate_final_assessment` (one retry, since a stochastic model's next sample isn't
  the same sample), the same pattern already used for `_verdict_must_agree_with_risk`.
- **Regression test**: `test_bare_verdict_in_threat_assessment_contradicting_final_verdict_is_rejected`
  (asserts the exact reproduced payload raises) and
  `test_narrative_threat_assessment_mentioning_malicious_is_not_flagged` (asserts a real narrative
  sentence containing "malicious" mid-text does NOT raise) — both added to
  `backend/app/tests/unit/test_ai_service.py`.
- **Verification**: both new tests pass; full unit suite re-run after the fix — 337 passed (335 + 2
  new), zero regressions, confirmed live inside the freshly-installed instance's own backend
  container.

## Phase 6 — IOC Input: **PASS**

Real investigations run end-to-end (full SSE stream through `final_assessment`/`done`) for: IPv4
(`8.8.8.8`), domain (`example.com`), URL (`http://example.com/test`), SHA256 hash (real 64-char
hash — a genuine SHA256-shaped value, correctly routed through the no-evidence guard since no
provider had data), and CVE (`CVE-2021-44228`, correctly assessed as malicious with real CISA
KEV/NVD data). Edge cases: malformed input (`!!!not-a-real-ioc###`) → `422 "Could not determine IOC
type"`; empty string → `422` (Pydantic min-length); whitespace-only → `422`; a truncated 63-char
hash (my own test typo) → correctly rejected as undetectable, which incidentally also validates the
malformed-input path. Domain/CVE investigations took 60-90s wall-clock under Ollama with several
providers each requiring a per-provider AI summary call — confirms the already-documented "Ollama
serializes concurrent generation" limitation is real and accurately described, not a hang.

## Phase 7 — IOC Providers: PARTIAL

All 18 providers enumerate correctly via `GET /providers/health` with real `configured: false` for
every key-requiring provider (no real API keys were entered this session — see Known Limitations).
Live-verified: `whois_rdap`, `internet_intelligence`, `spamhaus`, `mitre_attack`, `crtsh`, `cisa_kev`,
`nvd` all returned real (not fabricated) results across the Phase 6 investigations without any
credential. A misconfigured/unconfigured provider correctly reports `not_configured`/`unknown`
rather than a false "clean" result, and does not block the rest of the investigation (confirmed
across 5+ real investigations with 5-10 providers each). **Not covered**: live testing with real
paid-provider API keys (VirusTotal, AbuseIPDB, etc.) — none were entered, matching this session's
standing policy against pasting real credentials into chat; add/edit/disable/remove of a configured
provider through a full round-trip was not separately exercised beyond the AI-provider equivalent in
Phase 9 below.

## Phase 9 — AI Providers / AI Switching: **PASS**

- Configured Groq with a syntactically-valid-but-fake key via
  `POST /runtime/ai-providers/groq` (`{"credentials":{"api_key":...},"model_id":...}`) → `configured:
  true`, key correctly masked in the response (`masked_credentials`).
- Activated Groq via `POST /runtime/ai-active` → immediately became the active backend
  (`GET /ai-active` confirms), no restart needed.
- Ran a real investigation against the fake-keyed active Groq backend: failed cleanly with
  `"AI-generated assessment unavailable (generation error)"` and `ai_outcome: "failed"` — **the
  specific bug class the mission called out ("UI must never say API KEY NOT PROVIDED when a valid
  credential exists") does not occur**; the failure message correctly reflects a generation error,
  not a missing-credential error, since a credential genuinely was present.
- Switched back to Ollama; restarted the backend container; confirmed both the active-backend
  selection (`ollama`) and Groq's saved-but-inactive configuration (`configured: true`,
  `is_active: false`) survived the restart correctly.
- Real Ollama-backed investigations (Phase 6) confirm the local backend genuinely works end-to-end,
  not just "configured."

## Phase 11 — Threat Scoring: **PASS** (spot-checked across real risk levels)

- Benign (8.8.8.8): `overall_risk_score: 0.0`, `final_verdict: benign`.
- No-evidence (unrecognized hash, zero provider data): `overall_risk_score: 0.0`,
  `final_verdict` correctly reflects "insufficient data" rather than fabricating a score.
- Critical (CVE-2021-44228 / Log4Shell, real CISA KEV + NVD data): `overall_risk_score: 7.16`
  system-wide average shifted correctly, `critical_high_risk_iocs` KPI incremented from 0 to 1.
- BUG-003 (above) is itself a Phase-11-adjacent finding: the deterministic score and validated
  `final_verdict` were correct in every single case observed; only the separate, less-constrained
  `threat_assessment` narrative field could disagree with them, now fixed.

## Phase 12 — Provider Health Monitoring: **PASS**

`GET /providers/health` returns real per-provider status across 1h/24h/7d/30d windows for every
provider actually exercised in Phase 6-7, correctly distinguishing `unknown` (never called this
window) from a real success/failure history. No provider's failure affected another's reporting.

## Phase 13 — Executive Dashboard: **PASS**

`GET /dashboard/kpis` tracked real state changes correctly across the session: `active_investigations`
stayed accurate (0 at rest), `avg_threat_score` moved from `0.0` to `7.16` exactly when a real
high-risk investigation completed, `critical_high_risk_iocs` incremented exactly once for the one
real critical finding, `provider_health_percentage` and `ai_success_rate` reflected real provider/AI
call outcomes, not hardcoded values.

## Phase 14 — Port Scanner: **PASS** (localhost only, per this mission's own safety scoping)

Created a real lookup for `127.0.0.1`, ran a real `nmap` "quick" profile scan via
`POST /security-assessment/{lookup_id}/run` (correctly requiring `tool_ids`, `profile`, AND
`target_confirmation` matching the lookup's own IOC value — a genuine scope-confirmation safety
gate, not just a formality: it rejected my first attempt for omitting it). Scan completed in
~0.1s, correctly reported the one real open port on the container's own loopback (`tcp/8000`,
the backend's own listener, exactly what's expected from inside that container's network
namespace) with no fabricated findings. Malformed request (missing required fields) → clean `422`,
not a crash. **Not separately re-tested here**: cancellation, concurrent scans, and a wider range of
target/profile combinations — this exact subsystem already went through an extensive, dedicated
adversarial re-verification earlier in this overall engagement (9 independent reviewers, 7 real bugs
found and fixed, documented in the existing port-scanning QA reports); this phase's goal was
confirming that hardening survived a genuine clean install, which it did.

## Phase 15 — Reporting/Export: **PASS** (PDF, CSV — the two server-rendered formats)

`POST /lookup/{id}/export?format=pdf` → real 1-page PDF (`file` confirms valid PDF 1.4). `format=csv`
→ real CSV with correct `ioc_value`/`final_verdict`/`risk_score`/provider rows. Viewer role correctly
gets `403` (export requires the dedicated `lookup:export` permission, distinct from `lookup:read`).
JSON/Markdown export is by design client-side-only (built in the browser from already-loaded data,
per `ExportMenu.tsx`) — not a server endpoint, so not applicable to test server-side; not claimed as
tested here.

## Phase 16-18 — Persistence, Backend Restart, Database: **PASS**

A real `docker restart app-backend-1` was performed (twice, once before and once after the BUG-003
fix). Verified surviving both restarts: user accounts (all 4 created accounts, correct roles),
active AI backend selection, saved-but-inactive Groq credentials, login/auth functionality, and
frontend connectivity (no manual intervention needed to reconnect). Database read/write/persistence
confirmed via real user-management operations (create ×3, list, login) and real investigation
records (5+ real lookups persisted and independently re-queryable via the dashboard KPIs endpoint).

## Phase 19 — Network Failure (AI-backend dimension): **PASS**

Rather than disconnecting the real network (would also disrupt this session), pointed the active
Ollama config at an unreachable port (`http://host.docker.internal:19999`) via
`POST /runtime/ai-providers/ollama` — this exercises the exact connection-refused/timeout path a
real Ollama-host-unreachable outage would trigger. Ran a real investigation: all 9 IOC providers
completed normally (unaffected — they don't depend on the AI backend), per-provider AI summaries
degraded gracefully (`"AI summarization unavailable for this provider (generation error)"`,
`confidence: "low"`, an honest caveat — never fabricated), the final assessment correctly reported
`ai_outcome: "failed"` with a clear generation-error message, and the backend itself stayed healthy
throughout (`/health/detailed` still `200`) — no crash, no hang, no infinite retry loop. Restored the
real base_url and ran a fresh investigation: `ai_outcome: "success"` — full recovery confirmed with
zero manual intervention (no restart needed).

## Phase 20 — Crash/Power Recovery: PARTIAL, one finding not a bug

- `docker kill app-backend-1` (SIGKILL from outside, i.e. an explicit administrative action) did
  **not** auto-restart the container even with `restart: unless-stopped` set. This is Docker's own
  documented, intended behavior (an operator-issued stop/kill is treated as "the operator wants this
  down," not a crash) — already confirmed and written up earlier in this overall engagement's own
  documentation (`backend-01-overview-and-lifecycle.md`), and re-confirmed here, not a new bug. The
  container was manually restarted (`docker start`) to restore state.
- Attempted to simulate a genuine in-process crash (as opposed to an operator-issued kill) by killing
  the backend's own process from inside the container. This ran into a PID-namespace mismatch between
  `docker top`'s host-level PID numbering and the container's own internal PID space (my kill target
  didn't resolve inside the container's namespace) — a test-methodology limitation, not something
  observed about the application. The container was never actually harmed by this attempt (confirmed
  still healthy throughout). **Not conclusively re-verified this pass**: does a genuine in-process
  crash (as opposed to an operator kill) auto-restart within seconds? This exact scenario (OOM-kill
  specifically) was already live-verified earlier in this overall engagement per the existing
  documentation's own claim ("a container OOM-killed by its own mem_limit now restarts automatically
  within seconds") — not independently re-run against this specific fresh install in this pass.

## Not covered in this pass — explicit, disclosed gaps

- **Phase 8/10 exhaustive AI-provider-by-provider testing**: only Ollama (real, working) and Groq
  (real key format, intentionally fake value, to test the failure path) were exercised. The other 9
  AI backends were not live-tested this session (no real keys entered).
- **Phase 21 (storage/log rotation), Phase 22 (performance under repeated load), Phase 28 (soak
  test)**: not run this pass; a resource snapshot taken after ~20 minutes of real use showed all 8
  containers well within their memory limits with no signs of a leak, but this is not a substitute
  for an actual multi-hour soak test.
- **Phase 23 (broader security/RBAC sweep)**: the specific boundaries exercised in Phases 3-4/9/15
  all held correctly; a dedicated adversarial pass (injection, path handling, secrets-in-logs) was
  not separately re-run this session (this exact class of testing was already done earlier in this
  overall engagement for the pre-installer codebase; not independently re-verified against this
  specific fresh install).
- **Phase 24 (Windows reboot test) — deliberately deferred, not skipped.** The mission's own answer
  authorized a real `shutdown /r` "now" when that phase came up, but by the time the installer issues
  were fully diagnosed and fixed it was the middle of the night with the user asleep. Actually
  rebooting an unattended machine while its owner is away serves no verification purpose (no one is
  present to confirm what happens on the other side) and risks disrupting anything else running on
  that machine without their awareness. This is being surfaced explicitly rather than silently
  skipped or silently performed — recommend running this phase when you're back at the keyboard.
- **Phase 25 (Linux install + reboot)**: not started this pass — `release/horizon-grid_0.2.3_amd64.deb`
  exists and was reportedly tested earlier in this overall engagement (per `TEST_EVIDENCE_CURRENT_VERSION.md`);
  not independently re-run in this specific mission.
- **Phase 26 (uninstall/reinstall)**: not run this pass.
- **Phase 27/28 (full automated regression + soak)**: the backend's own automated suite (337 unit
  tests) was re-run and passed after BUG-003's fix; the full integration suite and a real soak test
  were not re-run against this specific fresh install this pass.
- **Phase 31 (final installer rebuild + full critical-path retest)**: the installer WAS rebuilt
  (that's how BUG-001 got fixed) and the critical path (install → login → configure → IOC → AI →
  threat score → port scan → dashboard → export → restart → persistence) genuinely was exercised
  end-to-end during this pass — but a formal, repeated "after ALL fixes" pass has not yet happened
  since more bugs may still surface in the not-yet-covered phases above.
- **Setup Wizard GUI itself**: as disclosed in Phase 1, the wizard's own WinForms UI was never
  clicked through end-to-end — its equivalent PowerShell functions were invoked directly instead.

## Interim Verdict

**FUNCTIONALLY VERIFIED WITH DOCUMENTED LIMITATIONS** — for the phases actually covered above. This
is explicitly an interim, not final, verdict: roughly a third of the 33-phase mission (installation,
first launch, auth, RBAC, IOC input, AI switching, threat scoring, provider health, executive
dashboard, port scanning, export, persistence, backend restart) was covered with real, live evidence
against a genuinely fresh installed instance, and produced 3 real bugs, all found, fixed, and
regression-tested:

1. **BUG-001** (P0): shipped installer `.exe` was stale, missing `docker-compose.yml` — fixed by
   recompiling from current source.
2. **BUG-002** (P0): a leftover verification-harness registry entry silently redirected every
   install (including genuine ones) to a fake path — fixed by removing the stale registry key and
   clearing leftover harness state.
3. **BUG-003** (P1): the AI's free-text `threat_assessment` field could contradict the validated
   `final_verdict` in the same response — fixed with a new, narrowly-scoped schema validator plus
   two regression tests.

The remaining phases (network/crash resilience, storage, extended performance, a broader security
sweep, the Windows reboot test, Linux, uninstall/reinstall, full regression + soak, and a final
"after all fixes" critical-path repeat) are explicitly NOT YET DONE, not silently assumed to pass.
No phase above is marked PASS without the specific real command/request and response that proves it.
