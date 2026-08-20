# HORIZON GRID v0.2.3 — Release Notes

**Release version:** 0.2.3
**Release date:** 2026-08-20
**Focus:** mission-critical deployment hardening for a one-time install at a remote, physically-inaccessible site with no developer access afterward.

## Major changes

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
