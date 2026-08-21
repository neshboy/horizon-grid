# Changelog

All notable changes to HORIZON GRID are documented here. Every entry reflects a real, tested change confirmed against the actual codebase at release time — not a planned or aspirational one. Full narrative detail and evidence for each entry lives in `documentation/DOCUMENTATION_SOURCE/standalone-changelog.md` and, for the current release, `MISSION_CRITICAL_CERTIFICATION_REPORT.md`.

## [0.2.4] — 2026-08-21 — Original visual identity and branding pass

A professional branding + UI/UX pass across the entire frontend -- the product name and tagline
were previously barely visible anywhere in the application. No backend logic, database schema,
authentication, IOC processing, AI provider logic, provider API logic, port scanner logic, or admin
permissions were modified; this is presentation-only, verified by a full backend regression run
(383 passed, 39 skipped, zero regressions) and a clean `tsc --noEmit` frontend typecheck both before
and after.

### Added
- An original visual identity ("Datum Signal"): a CRT-phosphor teal-cyan primary color deliberately
  pulled off the generic-SaaS-blue hue most dashboards default to, a warm off-white foreground
  against a near-black anodized-steel-panel shell, and a six-state operational status language
  (OPERATIONAL/DEGRADED/WARNING/CRITICAL/OFFLINE/UNKNOWN) where every state pairs a distinct hue,
  fill density, border style, AND icon -- never color alone, so a colorblind viewer or a grayscale
  printout can still tell every state apart.
- An original, wholly geometric logo mark (`components/Logo.tsx`): a horizon line with two open
  "signal" nodes converging on one filled "detection" node -- literally depicting the tagline
  ("Every Signal. One Operational Picture.") rather than just looking generically tactical. No
  insignia, seal, shield, or existing company/military symbol of any kind. Works as a full lockup
  (mark + wordmark), a compact lockup (mark + "HG" in a corner-bracket badge), and a favicon
  (`app/icon.svg`, a 3-primitive degraded form legible at 16px).
- Three-typeface system: IBM Plex Sans Condensed for headings/wordmark/section labels, IBM Plex
  Mono for every raw technical value (hashes, IPs, timestamps, coordinates, counts, scores) with
  tabular numerals, and body text left completely unchanged (zero risk to existing dense data
  tables).
- A new, additive `/about` page -- version, live dependency status, supported platforms,
  documentation links. No existing route was touched to add it.
- A shared `BrandHeader` component (mark + a live SYSTEM STATUS indicator, read from the real
  `GET /health/detailed` response, polled every 60s -- never hardcoded) replacing the bare search
  bar + nav pair every page previously composed individually.
- HORIZON GRID branding, generation timestamp, and Investigation ID on every exported report (PDF
  header/footer with real page numbering; CSV and Markdown exports both gained a platform/
  investigation-ID field).

### Changed
- The radius-contrast rule: outer panels/cards keep the existing softer corner radius; every
  interactive/status element (buttons, inputs, badges, chips) tightens to a sharper radius --
  soft panels visibly containing precise controls, a stronger "operational instrument" signal than
  any single color choice.
- Card elevation is now a flat fill bounded by a hairline border; the previous drop-shadow was
  removed app-wide (one shared component change) so panels read as machined layers rather than
  "floating" the way a generic Bootstrap-style dashboard does.
- Section/column headers (`CardTitle`) now render as uppercase, tracked, muted "instrument-panel"
  labels by default instead of default-case bold headings -- applied once at the shared-component
  level, so it took effect consistently across every page without a per-page edit.
- The login and register screens got a full premium treatment: the mark, tagline, and a subtle
  (3% opacity, zero-animation) grid-and-horizon-line background.
- Provider health's existing 4-state badge (healthy/degraded/down/unknown) now renders through the
  same shared six-state status language as the rest of the app, mapped honestly (healthy-
  >operational, down->offline) -- no new states were invented for data the backend doesn't report.

### Fixed
- A real hydration-mismatch bug self-discovered while screenshotting the new `/about` page: reading
  client-only login state directly in a page's render body (rather than via `useState`+`useEffect`)
  made the server-rendered HTML disagree with the client's first paint whenever a session already
  existed, producing a genuine React hydration error. Fixed by deferring the check to a post-mount
  effect, matching the pattern already used correctly elsewhere in this codebase (`WorkspaceNav.tsx`).

### Documentation
- Fresh screenshots of the live v0.2.4 build (login, dashboard, provider health, AI/IOC provider
  configuration, admin, about, a full IOC investigation, and a report export) replace the previous
  release's screenshots wherever the visual identity changed.

### Testing
- Full backend suite re-run after every change in this release: 383 passed, 39 skipped, zero
  regressions. Frontend: `tsc --noEmit` clean across the whole app; no automated frontend test
  suite exists to run (a pre-existing, disclosed gap, not introduced by this release).

## [0.2.3] — 2026-08-20 — Mission-critical deployment hardening

A dedicated reliability and security review for unattended, remote-site deployment. 18 real gaps found and fixed (2 self-discovered during the review, not flagged by the initial assessment) — every item confirmed present before the fix and confirmed resolved after, via a real test, a live re-verification, or both.

### Added
- Real database restore scripts on both platforms (`Restore-Database.ps1`, `restore-database.sh`) — previously only backup scripts existed. Requires a typed `RESTORE` confirmation unless `-Force`/`--force` is passed.
- Scheduled daily database backups on both platforms (02:00 local time); a pre-upgrade backup added to the Linux wizard for parity with the existing Windows behavior.
- A real dependency-aware health endpoint, `GET /health/detailed` (Postgres + Redis checks), alongside the existing dependency-free `GET /health`.
- Boot-time auto-start (Windows Scheduled Task; Linux `systemctl enable`) and a 5-minute health watchdog on both platforms.
- A global 10 MB request-body-size limit and `max_length` constraints on every previously-unbounded free-text field.
- Login brute-force rate limiting (fixed-window, 10 attempts/60s default, keyed on the attempted email).

### Changed
- All 8 Docker Compose services now have `restart: unless-stopped` (previously only 2 of 8 did).
- Redis now has a persistent volume (previously reset to empty on every container recreation).
- Swagger UI, ReDoc, and the raw OpenAPI schema are now disabled whenever `ENVIRONMENT=production` (set by `docker-compose.prod.yml`, the override every real installer uses).
- Both setup wizards now gate configuration save on a real Test Connection result, and the install flow's Summary page runs an automatic post-health-check AI connectivity test.

### Fixed
- **Relationship Graph list-view crash**: `react-force-graph-2d`'s physics simulation mutates its input data in place; switching to "View as list" after the graph had rendered operated on already-mutated data and crashed the whole page. Fixed by isolating the force graph's data from the shared copy used by the list view.
- **Dead retry-code bug**: `BaseProvider.run()` silently caught the exact exception types the orchestrator's retry loop needed to see, so `provider_max_retries` had no real effect for most providers.
- **AI-outcome badge**: a genuine AI generation failure and a correct "no evidence to assess" decision rendered an identical badge; the frontend now reads the `ai_outcome` field the backend already tracked.
- **Linux boot-time auto-start** (self-discovered): the systemd unit's `WantedBy=` declaration did nothing because `systemctl enable` was never actually called anywhere in the codebase — a working install would silently not survive a reboot.
- **`check-prerequisites.sh`'s JSON output** (self-discovered): a bash→Python boolean-interpolation bug left its `checks` array permanently empty in every run, unnoticed because the human-readable output and exit code were computed independently.
- A customized `HOST_PORT_BACKEND`/`HOST_PORT_FRONTEND` was ignored by every unattended health check on both platforms, which hardcoded the default port.
- Self-contradictory manual restore documentation (told the operator to stop the platform, then restore into "the running" Postgres container).
- **Shipped Windows installer was stale** (found during a full functional-testing pass against a genuine clean install, not a synthetic test): `release/HORIZON-GRID-Setup-0.2.3.exe` had never actually been recompiled from current source and was missing `docker-compose.yml`/`docker-compose.prod.yml` entirely, so `docker compose up` failed immediately on a real install with no other symptom. Fixed by recompiling from current source; both platform installers (`.exe` and `.deb`) are rebuilt fresh in this release.
- **A leftover verification-harness registry entry silently redirected every install to a fake path** (found during the same testing pass, immediately after the fix above): Inno Setup's default `UsePreviousAppDir` behavior meant a stale `InstallLocation` value left behind by an earlier automated test run got silently reused by every subsequent install — including genuine ones — while the Setup Wizard's own path logic looked in the real `C:\Program Files\...`, a straight mismatch between the two halves of the installer. Fixed by removing the stale registry key; no code change was required, but this is now an explicit step in this release's own installer-verification process (see `FULL_FUNCTIONAL_TEST_REPORT.md`).
- **AI `threat_assessment` could contradict the validated `final_verdict`**: found live on a fresh install investigating `8.8.8.8` — Ollama returned `threat_assessment: "malicious"` (a bare one-word label) alongside a correctly-computed `final_verdict: "benign"` in the same response; the existing verdict/risk-agreement validator never checked `threat_assessment`'s own content. `FinalAssessmentPanel.tsx` renders the two in separately-labeled tabs, so an analyst reading either alone would see the platform's opposite conclusion. Fixed with a new, narrowly-scoped schema validator (only fires on a bare verdict-shaped word, never on ordinary narrative prose) plus two regression tests.

### Security
- SSRF guard extended to the actual production Ollama AI-call path (previously only checked on the Test-Connection convenience endpoint), including the `.env`-only fallback singleton used whenever no runtime-config DB row has been saved.
- Swagger/OpenAPI docs gated behind production mode (see Changed).
- Global request-body-size limit and per-field length caps (see Added).
- Login brute-force rate limiting (see Added).

### AI
- No new AI provider changes this release (still 11 backends, confirmed unchanged from v0.2.0's expansion — see AI-outcome badge fix under Fixed).

### IOC Intelligence
- No provider-list changes this release (still 18 registered providers).

### Port Scanner
- Added a concurrency cap (`_MAX_CONCURRENT_SCANS = 4`) on scan execution and CIDR-size-proportional nmap timeout scaling (a full /28 previously got the identical wall-clock budget as a single host).

### Reliability
- Restart policies, persistent Redis, boot auto-start, watchdog, scheduled backups, real restore, dead-retry-code fix (see Added/Changed/Fixed above).
- A 3-hour soak test against the live stack completed cleanly: memory flat throughout, zero spontaneous container restarts.

### Installation
- Linux's prerequisite check is now a real blocking gate in the setup wizard (previously an ignored informational check).
- Both wizards gate configuration save on a real Test Connection result.

### Documentation
- Added the Mission-Critical Operations Manual (new PDF/DOCX).
- Corrected stale restart-policy and health-endpoint claims in the existing Operations Guide.
- Added `MISSION_CRITICAL_CERTIFICATION_REPORT.md` and this rebuilt `CHANGELOG.md`/`README.md`/release-notes/version-audit/test-evidence set.

### Testing
- New regression tests for the retry-logic fix, the login rate limiter, and the SSRF guard on both the AI-call and config-save paths.
- Full backend suite: 380 passed, 39 skipped (up from 365 at the start of this review); 337 unit tests after adding the two `threat_assessment` regression tests below.
- Fixed two of the new SSRF regression tests that passed locally but failed on GitHub Actions' bare `unit` CI job: they resolved the real default `host.docker.internal` hostname via genuine DNS, which only resolves inside a Docker Desktop network, not on a bare Ubuntu runner. Now mocks the DNS-resolution step to a fixed, non-link-local address so the tests are deterministic across environments.
- **A full functional-testing pass against a genuine clean Windows install** (not the dev stack) — real elevated installer run, real `docker compose up`, real admin account creation and login, real IOC investigations across 5 IOC types, real AI-backend switching (including a specific check that a valid-but-wrong credential never reports as "API key not provided"), real threat scoring, provider health, executive dashboard, a real `nmap` port scan against `127.0.0.1`, real PDF/CSV export, and persistence across a real backend restart and a simulated AI-backend outage. Found and fixed the three bugs listed under Fixed above. Full evidence, including what was *not* yet covered (Linux, uninstall/reinstall, soak test, the Windows reboot test, and others), is in the new `FULL_FUNCTIONAL_TEST_REPORT.md` — an interim, not final, report.
- Two new regression tests for the `threat_assessment`/`final_verdict` contradiction bug: one asserting the exact reproduced payload is rejected, one asserting an ordinary narrative sentence containing the word "malicious" is not.

### Known Limitations
- No automated host-disk-space alerting.
- No retention/cleanup job for ever-growing investigation tables.
- No off-host/off-site backup copy option (backups are local-disk-only).
- A narrow DNS-rebinding TOCTOU window on the SSRF check (validates a resolution snapshot; the real call re-resolves independently afterward).
- Neo4j and OpenSearch remain fully provisioned with zero actual application traffic (confirmed via exhaustive search this release and independently re-confirmed by this changelog's own audit) — a real resource cost with no current benefit, flagged as an open product question, not resolved unilaterally.
- The Windows Setup Wizard's own WinForms GUI was not clicked through end-to-end during the functional-testing pass above — its underlying PowerShell functions were invoked directly instead (same code, but not the literal click-through experience). A live Windows reboot test, an uninstall/reinstall test, and a Linux install/reboot test for this specific build were deliberately deferred, not skipped — see `FULL_FUNCTIONAL_TEST_REPORT.md` for the full list of what is and isn't yet covered.
- No frontend test infrastructure exists (vitest is wired into `package.json` but zero test files exist anywhere in the tree).
- A live, elevated, end-to-end Windows installer run was not performed this release (requires an interactive UAC prompt); the installer's packaged contents were verified directly instead.

## [0.2.2] — Independent re-verification: 7 real bugs found and fixed

An independent, adversarial re-verification of the v0.2.1 port-scanning cancellation fix (nine parallel reviewers, each reading the real code fresh) found four new, real defects in the scanner and three unrelated ones surfaced during full-application regression.

### Fixed
- IPv6 scans silently never probed the target (missing a required nmap `-6` flag), yet reported an ordinary clean result.
- An unknown/mistyped scan profile id was silently accepted and reported as a clean scan.
- A malformed CIDR value could crash the endpoint with a raw 500.
- A run's own successful completion could silently overwrite a status another writer had already finalized (a real concurrency race).
- An empty `tool_ids` list is now rejected at the schema level (422) instead of producing a no-op "completed" run.
- Spamhaus DBL/ZEN misread a DNS query-rejection (common on containerized default DNS) as a positive "malicious" verdict.
- A confusing generic 401 on the losing side of a concurrent last-admin-protection race, instead of the accurate "Account disabled".
- An AI-generated assessment could cite specific findings while leaving its structured supporting-evidence list empty.

### Testing
- Full backend suite: 365 passed (up from 313 at v0.2.0), following the addition of regression tests for all seven fixes.

## [0.2.1] — Port scanning: real cancellation added

### Added
- `POST /api/v1/security-assessment/runs/{run_id}/cancel` and a "Cancel Scan" button — genuinely stops the underlying `nmap` OS process, not just the displayed status.

### Fixed
- `asyncio.CancelledError` (which does not inherit from `Exception` in Python 3.8+) was never caught by the scan orchestrator's generic error handler, so a cancelled run's database row would have stayed `running` forever without a dedicated fix.
- A database migration bug: the new `CANCELLED` enum value was initially added in lowercase, not matching the existing uppercase convention.
- A follow-up adversarial pass found and fixed a race where two concurrent cancel requests for the same run could each write a redundant audit-log entry.

### Testing
- 5 new integration tests covering in-flight cancellation, the backend-restart-orphan case, rejecting a cancel on an already-finished run, an unknown run id, and RBAC enforcement.

## [0.2.0] — AI provider ecosystem expansion, rebrand, deterministic scoring, executive dashboard

The renamed (from "IOC Intelligence Platform"), significantly extended release.

### Added
- Five new AI backends — Kimi (Moonshot AI), DeepSeek, xAI (Grok), Mistral AI, and OpenRouter — bringing the total from 6 to 11, each with a real live model-discovery endpoint and live connection test.
- Two new IOC providers: urlscan.io and Google Safe Browsing.
- A deterministic, versioned, auditable threat-scoring engine (`app/scoring/engine.py`, `SCORING_ENGINE_VERSION` "1.0"), replacing 100%-AI-generated risk scoring. The AI is given the score as a fixed input and cannot override it — the backend mechanically overwrites the AI's own numbers and re-validates before saving.
- AI-generation outcome tracking (`success`/`skipped_no_evidence`/`failed`), making an honest "AI success rate" metric possible.
- A new Executive Dashboard (`/dashboard`) with 7 real KPI tiles and an AI-generated (or plainly-labeled template-fallback) executive summary.
- A real, historical Provider Health page (replacing a dead, stub-data endpoint) — per-provider status/success-rate/latency/consecutive-failure-streak across 1h/24h/7d/30d windows.
- Reorganized global navigation into named groups (COMMAND/INTELLIGENCE/ANALYSIS/OPERATIONS/ADMINISTRATION).

### Changed
- Full visible rebrand to **HORIZON GRID** ("Every Signal. One Operational Picture."). Internal identifiers (data folder name, database name, package names, k8s namespace) deliberately left unchanged for upgrade safety.

### Fixed
- A provider correctly reporting "nothing found" was miscounted as a failure in Provider Health, making a healthy provider appear degraded.
- A same-day regression where the new Provider Health response initially dropped a field an existing page depended on.
- CSV formula-injection and PDF markup-injection/crash vulnerabilities in exported investigation data.
- An export permission-gate bug (was gated on `lookup:read`, should be `lookup:export`).
- A real, complete-failure concurrency bug: 25 concurrent Provider Health requests previously failed 100% of the time (timeout); fixed via query consolidation and connection-pool retuning — now completes in ~1.6 seconds at 100% success.
- A real scoring-manipulation vulnerability: a single free, unprivileged account on a community-sourced provider could flood correlation with fabricated relationship claims to inflate a score.
- A real Windows installer packaging bug: every prior build silently bundled the local development Python virtualenv, making the installer ~8x larger than necessary.

### Administration
- A new `dashboard:read` permission, granted to all three roles for broad, read-only operational visibility.

### Testing
- 31 new unit tests for the 5 new AI backends; full backend suite: 313 passed.

## Earlier history

Pre-0.2.0 work (initial platform build, GitHub scaffolding, early bug fixes) is captured in the git history itself (`9bee96c` onward) rather than a version-numbered changelog entry, since HORIZON GRID's first numbered release is 0.2.0.
