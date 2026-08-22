# HORIZON GRID — Hackathon Test Report

This is a summary index into this project's real QA history, not a new test pass — every claim below is sourced from a specific, dated report already in this repository, or from source code read directly. Full detail, including complete bug tables and every disclosed limitation, lives in `documentation/DOCUMENTATION_SOURCE/hackathon-07-testing-journey.md` (and the companion `hackathon-06-bug-history-narrative.md`), both included in `documentation/HORIZON_GRID_HACKATHON_SUBMISSION.pdf`.

## The Honest Bottom Line

There is no single document in this repository that states one final, all-encompassing release verdict — and this report does not manufacture one. The most recent QA document by date, `FULL_FUNCTIONAL_TEST_REPORT.md` (2026-08-21), states its own status as **"IN PROGRESS"** and its own verdict, **"FUNCTIONALLY VERIFIED WITH DOCUMENTED LIMITATIONS,"** as **"an interim, not final, verdict,"** with roughly two-thirds of a planned 33-phase mission explicitly not yet run. A separately scoped certification, `MISSION_CRITICAL_CERTIFICATION_REPORT.md`, states **"MISSION-CRITICAL READY WITH DOCUMENTED LIMITATIONS"** for unattended-remote-deployment reliability specifically. Both are reported here exactly as written, not upgraded or blended into something more polished-sounding.

## What Was Actually Tested

- **Automated regression suite**: pytest unit + integration tests, most recently reported at 383 passed / 39 skipped after the v0.2.4 branding pass (a presentation-only release, verified with zero regressions).
- **Adversarial red-team pass**: a 1241-line, 21-dimension live audit against the running stack (`ENTERPRISE_QA_PHASE1_FINDINGS.md`) covering auth/session lifecycle, RBAC/privilege escalation, cross-user isolation, AI-provider credential handling, AI-backend chaos/outage simulation, provider fan-out resilience, AI hallucination defenses, the Security Assessment Toolkit's safety boundaries (including live nmap scans against `127.0.0.1`), command-injection probing, path-traversal surface, real-browser Puppeteer chaos testing, audit-log integrity, secret scanning, and a live CVE/OSV.dev dependency cross-check. 74 findings recorded; the 7 most severe were independently re-confirmed in a follow-up pass.
- **Deterministic scoring engine**: a dedicated unit-test file exercising zero-evidence handling, corroboration scaling, conflicting-verdict confidence collapse, a documented single-provider-flood exploit fix, and the Security Assessment severity floor never inflating `malicious_probability`; a separate integration test asserts the persisted score matches the deterministic engine even when a stubbed AI client returns invented numbers.
- **Security Assessment Toolkit (port scanner)**: cancellation flow, IPv6 targeting, malformed-CIDR handling, profile-id validation, and a completion-status race guard — all independently re-confirmed this session by reading the actual source (`backend/app/core/security_assessment.py`, `backend/app/security_assessment/nmap_tool.py`).
- **Mission-critical reliability**: a 3-hour, 171-cycle soak test (flat memory, zero spontaneous container restarts), live database backup/restore, live Postgres-down health-check verification, and a real Linux `.deb` upgrade over a live existing instance inside WSL.
- **Installer testing**: recurring across nearly every phase; most recently found and fixed two P0 installer defects (a stale `.exe` missing `docker-compose.yml`, a leftover registry key silently redirecting installs) and one P1 AI-schema defect (a free-text field able to contradict a validated verdict).

## What Was Found and Fixed (Highlights)

See `hackathon-06-bug-history-narrative.md` for the full, phase-by-phase bug tables. Headline items: a password-reset that left old sessions valid (fixed with a `token_version` invalidation mechanism); an oversized-IOC crash that stuck an investigation at `status='running'` forever (found, disclosed, **not yet fixed**); a systemd unit that was defined but never actually enabled, meaning a working Linux install would silently not survive a reboot (fixed); a relationship-graph view-switch crash from in-place data mutation by the force-graph library (fixed); and a validator gap letting an AI's free-text `threat_assessment` contradict its own structured `final_verdict` (fixed, with regression tests for both the exact repro and a safe false-positive case).

## What Remains Open (Disclosed, Not Hidden)

No automated disk-space alerting or investigation-table retention job; a DNS-rebinding TOCTOU gap on the outbound SSRF check; no off-site backup copy; a ~26x login-timing side channel that leaks account existence; no rate limiting on `/auth/login`; several P2–P4 adversarial findings not independently re-verified a second time; and — per the most recent report — log rotation, performance-under-load testing, a broader security/RBAC sweep, a Windows reboot test, a Linux install-plus-reboot test, and uninstall/reinstall testing all explicitly not yet run. The full, attributed list (which report says what) is in the Known Limitations section of `hackathon-07-testing-journey.md`.

## Where to Look for More

- `documentation/HORIZON_GRID_HACKATHON_SUBMISSION.pdf` — the full narrative (development journey, bug history, testing journey) in one document.
- `FULL_FUNCTIONAL_TEST_REPORT.md`, `MISSION_CRITICAL_CERTIFICATION_REPORT.md`, `ENTERPRISE_QA_PHASE1_FINDINGS.md`, `HORIZON_GRID_PORT_SCANNING_QA_REPORT.md`, `SECURITY_ASSESSMENT_QA_REPORT.md` — the individual source reports, unedited.
- `CHANGELOG.md` — the version-by-version record of what shipped when.
