# HORIZON GRID v0.3.0 — Release Notes

**Release version:** 0.3.0
**Release date:** 2026-08-24
**Focus:** a new, standalone Pentest Suite (scope-enforced assessments, DISCOVER→ENUMERATE→ASSESS→REPORT) plus a heavily gated, real Metasploit exploit-validation capability for administrators.

## v0.3.0: Pentest Suite — scope-enforced assessments and gated real-exploit validation

A new assessment subsystem, separate from the existing per-investigation Security Assessment Toolkit (untouched by this release): declare a scope, add targets inside it, run an automated discovery/enumeration/vulnerability-assessment pipeline, review findings with a confidence rating alongside severity, and get an AI-written executive summary grounded strictly in real findings. Full pause/resume/cancel/emergency-stop control, plus a global admin-only kill switch.

The one genuinely new, real capability: administrators can run an actual Metasploit exploit module against a finding that has a matched CVE. This is real execution, not a simulation, gated by five independent checks with no shortcut past any of them — a declared scope, a target inside it, a completed scan producing a CVE-matched finding, a manually selected specific module, and (for real execution, not the safe non-exploiting "check" mode) an explicit confirmation on every single request. The target host is always locked to the finding's own real target regardless of what's entered in the options form.

A dedicated adversarial security review ran before release specifically to try to break these guarantees. It found and closed one real confidentiality bug (exploit-attempt transcripts — which can contain genuine post-exploitation output — were briefly readable by the Analyst/Viewer roles instead of admin-only) and hardened several defense-in-depth points (a redundant role check inside the service layer, and the global kill switch now aborting an in-flight run within about a second instead of only blocking the next one). Two further real bugs were found and fixed during live testing against an actual running Metasploit instance: a message-encoding mismatch that permanently made Metasploit look unreachable even while running correctly, and a shared UI dialog component with no scroll handling that could hide a long module's own action buttons below the screen. Full detail in `CHANGELOG.md`'s `[0.3.0]` entry, `docs/PENTEST_SUITE.md`, and the Security documentation's new §13.

Explicitly verified, not just claimed: the backend test suite grew from 404 to 432 passing tests, zero regressions. Verified live end-to-end against a real, running Metasploit installation — a real module search by CVE, real module metadata retrieval, and a real non-exploiting check run against an authorized test target, honestly reporting what it actually found. This subsystem requires the backend's Docker image to include Metasploit Framework at build time (a large, ~1-2 GB addition); a fresh install that hasn't finished that build degrades gracefully — the feature reports itself unavailable rather than failing.

Everything below this line describes the prior v0.2.5 UI-fix release and earlier, which v0.3.0 builds on unchanged — none of it was affected by this release's work.

## Major changes (v0.2.5)

Two bugs were found while live-testing the Security Assessment Toolkit against a fresh install. First, the entire Security Assessment panel — including its "Run" trigger form — silently disappeared with no explanation whenever an investigation's overall status ended up `FAILED`, even when every provider had succeeded; it was gated on `status === "completed"` alongside panels that genuinely depend on a successful AI final assessment, but Security Assessment doesn't read that data at all. Second, the target-confirmation field required retyping the exact IOC value with zero feedback on any mismatch — a stray space silently kept the Run button disabled forever. Full detail in `CHANGELOG.md`'s `[0.2.5]` entry and `documentation/DOCUMENTATION_SOURCE/standalone-changelog.md`.

Explicitly verified, not just claimed: both bugs were reproduced live against a real investigation and a real Nmap scan (not just unit tests) — confirmed broken before the fix, confirmed working after. Full backend regression suite re-run clean after each change: 383 passed, 39 skipped, zero regressions. The Windows installer was verified via an isolated silent install confirming the fix is actually packaged, then fully cleaned up.

Everything below this line describes the prior v0.2.4 branding pass and v0.2.3 mission-critical hardening release, which v0.2.5 builds on unchanged — neither was affected by these two UI fixes.

## Major changes (v0.2.4)

The product name and tagline ("Every Signal. One Operational Picture.") were previously barely visible anywhere in the running application. v0.2.4 added an original visual identity ("Datum Signal": a CRT-phosphor teal-cyan primary color against a near-black anodized-steel shell), an original geometric logo mark that depicts the tagline itself, a six-state accessible operational-status language used consistently everywhere a status appears, a new `/about` page, and HORIZON GRID branding plus page numbering and Investigation IDs on every exported report. Full detail in `CHANGELOG.md`'s `[0.2.4]` entry.

Explicitly verified at the time: a full backend regression run (383 passed, 39 skipped, zero regressions) and a clean frontend `tsc --noEmit` typecheck, both before and after every change in that release. One real bug was self-discovered and fixed during that release's own screenshot QA (a React hydration mismatch on the new `/about` page).

Everything below this line describes the prior v0.2.3 mission-critical hardening release, which v0.2.4 built on unchanged — none of it was affected by the branding pass.

## Major changes (v0.2.3)

This release closes 18 real reliability and security gaps found during a dedicated review — 2 of them self-discovered during the review itself, not flagged by the initial structured assessment. Every item was confirmed present before the fix (via live reproduction or direct code-path tracing) and confirmed resolved after (a real test, a live re-verification, or both). Full evidence for every claim below is in `MISSION_CRITICAL_CERTIFICATION_REPORT.md`.

## Reliability

- **Every one of the 8 Docker Compose services now restarts automatically on a crash.** Previously only 2 of 8 did — a crashed backend, database, or frontend stayed down until a human intervened.
- **A real dependency-aware health endpoint** (`GET /health/detailed`) was added. The existing `GET /health` stays a pure liveness check on purpose (CI and simple reachability probes depend on that); the new endpoint genuinely pings Postgres and Redis.
- **Boot-time auto-start and a 5-minute health watchdog** were added on both platforms. A self-discovered bug meant Linux's systemd unit was never actually enabled at boot, despite the unit file itself being correct — a working install would silently not survive a reboot.
- **Redis now persists across a container restart.** Previously, a routine reconfigure silently reset every rate limiter and the entire provider-result cache.

## Backup and disaster recovery

- **A real restore procedure was added on both platforms** — previously only backup scripts existed, and the one documented manual procedure was self-contradictory. The new procedure requires a typed confirmation and was verified end to end: backed up, corrupted the data, restored, confirmed correct.
- **Scheduled nightly database backups** were added on both platforms (previously manual/pre-upgrade-only).

## Security

- **The SSRF guard on the Ollama AI backend now covers the real call path**, not just the connection-test convenience endpoint — including the common case of a wizard-driven install that never touches the web configuration panel afterward.
- **Login brute-force rate limiting** was added (a rate limit, not a hard lockout, so it cannot itself be used to lock out a real administrator).
- **Swagger UI, ReDoc, and the raw OpenAPI schema are now disabled in production.**
- **A global request-body-size limit and per-field length caps** were added; none existed before.

## AI

No new AI backends this release (still 11: Ollama, Anthropic, Bedrock, Gemini, Groq, OpenAI, Kimi, DeepSeek, xAI, Mistral, OpenRouter). Fixed a real bug where a genuine AI generation failure and a correct "nothing to assess" decision rendered an identical, misleading badge on the Final Assessment panel.

## IOC Intelligence

No provider-list changes this release (still 18 registered providers across 7 categories).

## Port scanning

Added a concurrency cap on scan execution and CIDR-size-proportional timeout scaling, so a full /28 target no longer gets the identical wall-clock budget as a single host.

## Administration

No RBAC/permission changes this release. (Multiple-administrator support, race-safe last-admin protection, and the 3-role/28-permission matrix are unchanged and were independently re-confirmed by this release's audit.)

## Reliability (fix, not feature)

Fixed a dead-retry-code bug: the provider-fetch retry mechanism had no real effect for most providers because a generic exception handler was silently catching the exact errors the retry loop needed to see.

## Installation

- Linux's prerequisite check is now a real blocking gate in the setup wizard — previously an ignored informational check, and its own JSON output had a self-discovered bug leaving it silently empty in every run.
- Both setup wizards now gate configuration save on a real Test Connection result.

## Windows

Windows installer rebuilt and its packaged contents verified directly (every new script confirmed present via the Inno Setup build log). A live, elevated, end-to-end install was not performed this release — it requires an interactive UAC prompt unavailable in this review's environment; every individual component script was verified independently instead.

## Linux

The `.deb` package was rebuilt and installed as a **real upgrade** over a live existing v0.2.1 instance: the full reconfigure wizard ran end to end (prerequisite gate passed, pre-upgrade backup ran, boot/watchdog/backup systemd units all confirmed enabled), and the resulting instance was confirmed genuinely healthy afterward via `/health/detailed`.

## Known limitations

- No automated host-disk-space alerting.
- No retention/cleanup job for ever-growing investigation tables.
- No off-host/off-site backup copy option — backups are local-disk-only, which does not protect a genuinely remote site against the host/disk itself failing.
- A narrow DNS-rebinding TOCTOU window remains on the SSRF check.
- Neo4j and OpenSearch remain fully provisioned (~1.5–2 GB RAM) with zero actual application traffic — a real resource cost with no current benefit, independently re-confirmed by this release's audit. Flagged as an open product question, not resolved unilaterally.
- No frontend test infrastructure exists (`vitest` is wired into `package.json`, but zero test files exist anywhere in the tree).
- A live elevated Windows installer run was not performed this release (see Windows, above).

## Upgrade notes

No manual upgrade step is required. Re-running the installer/package on an existing install preserves configuration, credentials, and all investigation/case data. A pre-upgrade backup is taken automatically on both platforms (new on Linux this release — previously Windows-only).

## Testing status

Full backend suite: **380 passed, 39 skipped** (up from 365 at the start of this review; the 39 skips are intentional, environment-gated tests, not failures). New regression tests were added for every fix in this release that didn't already have coverage. A 3-hour soak test against the live stack completed cleanly: memory flat throughout, zero spontaneous container restarts. See `TEST_EVIDENCE_CURRENT_VERSION.md` for the full breakdown.

## Verdict

**MISSION-CRITICAL READY WITH DOCUMENTED LIMITATIONS.** See `MISSION_CRITICAL_CERTIFICATION_REPORT.md` for the full evidence and reasoning behind this verdict.
