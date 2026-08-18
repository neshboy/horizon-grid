# Release Manifest

| Field | Value |
|---|---|
| **Product name** | IOC Intelligence Platform |
| **Version** | 0.1.0 |
| **Build** | Post-ship-audit follow-up fix pass, compiled 2026-08-14 14:09:17 |
| **Release date** | 2026-08-14 |
| **Git commit** | N/A — this working directory has never been a git repository (confirmed: no `.git` at the repo root or any parent directory). Source revision is tracked only by this manifest and the QA/release reports below. |
| **Installer** | `IOC-Intelligence-Platform-Setup-0.1.0.exe` |
| **Installer size** | 62,673,709 bytes |
| **SHA256** | `1FD8349E6E2027B51F72485D74AB8EF6B1EF0281C74F86DEB2E66226CC6FCACD` |
| **Installer contents verified against source** | Yes — extracted via `innounp` and diffed byte-for-byte identical against the current, fixed `backend/app/core/runtime_config.py`, `backend/app/api/routes/lookup.py`, and `backend/requirements.txt`. Not merely hash-trusted. |

## Required Runtime

- Docker Desktop (containers: `postgres:16-alpine`, `redis:7-alpine`, `neo4j:5-community`, `opensearchproject/opensearch:2.17.0`, plus the app's own `backend`/`frontend`/`celery_worker`/`celery_beat` images)
- Backend: Python 3.12 (`python:3.12-slim` base image)
- Frontend: Next.js 14.2.15 / React 18.3.1

## Supported OS

Windows 10/11, 64-bit only (`ArchitecturesAllowed=x64compatible` in the installer; no 32-bit build produced).

## Database / Migration Version

Alembic head revision: `2652d888a33f`

## Major Features

- Multi-provider IOC investigation (16 built-in threat-intelligence providers) with parallel querying, correlation, and AI-generated final assessment.
- Runtime (no-restart) credential and provider/AI-backend configuration, with live Test Connection separate from persisted state.
- Live AI-backend switching mid-session, with per-backend credential isolation.
- Case management and an append-only configuration audit log.
- LAN-accessible deployment with auto-detected host IP, scoped Windows Firewall rule, and CORS restricted to private-network address ranges.
- Investigation export in all four formats the UI offers: JSON and Markdown (client-side), PDF and CSV (server-rendered, added this pass).

## AI Providers (5)

Ollama (local), Anthropic (Claude), Amazon Bedrock, Google Gemini, Groq.

## IOC Providers (16)

VirusTotal, AbuseIPDB, AlienVault OTX, URLhaus, ThreatFox, MalwareBazaar, crt.sh, NIST NVD, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Hybrid Analysis (Falcon Sandbox), Spamhaus, PhishTank, Censys, and the Internet Intelligence Collector.

## Known Limitations

See `KNOWN_LIMITATIONS.md` for the full, categorized list. Summary: AI verdict quality is model-dependent; Groq's shared-tier rate limit is a real external constraint; no literal GUI-driven installer click-through was performed (a limitation of the test environment, not the product); a pre-existing, already-disclosed plaintext-secret exposure in a dev-environment `.env` file requires credential rotation before real production use. (PDF/CSV export and the first-time-configure concurrency edge case, both listed here in the prior version of this manifest, were implemented/fixed in a follow-up pass — see Release Notes.)

## Security Notes

- All provider/AI credentials are encrypted at rest (Fernet) and masked in every API response — verified via source review and a live re-sweep of the running application's actual endpoints.
- CORS is restricted to a private-network-address regex (RFC 1918 ranges + localhost), not a wildcard.
- The database, cache, and graph services are never bound to a LAN-reachable interface — only the application's own frontend/backend ports are.
- No credentials found in Docker logs, the served frontend JS bundle, or any documentation file in a fresh, independent re-sweep performed as part of this release.
- **Action required before production use:** rotate the third-party API credentials disclosed in an earlier QA pass (see `KNOWN_LIMITATIONS.md`'s Security Action Required section) — this is a pre-existing dev-environment exposure, not something introduced by this release.

## Documentation Files

- `documentation/IOC_INTELLIGENCE_PLATFORM_USER_MANUAL.pdf` / `.docx` (22 sections, 56 figures)
- `documentation/IOC_INTELLIGENCE_PLATFORM_SOURCE_CODE_DOCUMENTATION.pdf` / `.docx` (8 sections, 6 figures)
- `documentation/IOC_INTELLIGENCE_PLATFORM_BACKEND_DOCUMENTATION.pdf` / `.docx` (8 sections, 9 figures)
- `KNOWN_LIMITATIONS.md`, `RELEASE_NOTES.md`, this manifest
- QA trail: `FINAL_QA_REPORT.md` → `RELEASE_BLOCKER_TRACKER.md` → `FINAL_RELEASE_QA_REPORT.md` → `FINAL_SHIP_AUDIT_REPORT.md` (this release's ship audit)
- LAN deployment: `LAN_DEPLOYMENT_QA_REPORT.md`, `LAN_REGRESSION_TEST_REPORT.md`

## Test Summary

- **Automated:** 180 passed, 0 failed, 10 skipped (unrelated — require host-published database ports unavailable from inside the test container), across `app/tests/unit` and `app/tests/integration`.
- **New regression tests this release cycle + follow-up fix pass:** 17 (4 credential-merge, 4 DB-integration/concurrency, 5 AI-pipeline, 4 export-format rendering).
- **Manual QA status:** full production user journey (install → login → configure provider → save/test credential → real IOC investigation → AI analysis → AI switch → AI analysis → provider switch → real IOC → case → report data → restart → persistence) executed live against the running application and passed.

## Final Verdict

**RELEASE READY WITH KNOWN LIMITATIONS** — see `FINAL_SHIP_AUDIT_REPORT.md` for the full audit and reasoning.
