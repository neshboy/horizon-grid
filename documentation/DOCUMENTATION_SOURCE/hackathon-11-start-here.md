# Start Here

**HORIZON GRID — Every Signal. One Operational Picture.**

## What Is HORIZON GRID?

A self-hosted threat-intelligence platform. Give it one indicator of compromise — an IP address, domain, URL, file hash, or CVE ID — and it queries 18 independent intelligence sources at once, correlates what they say about each other, computes a deterministic threat score from that evidence, and has an AI model explain the result in plain language, with every claim traceable back to the real data behind it.

## What Problem Does It Solve?

No single threat-intelligence source sees everything. Investigating one indicator properly means manually cross-referencing several independent sources, one browser tab at a time, and holding all of it in your head well enough to notice when two sources are describing the same underlying fact. HORIZON GRID collapses that into one search box.

## Major Capabilities

18 IOC providers queried in parallel; 11 interchangeable AI backends (local or cloud, switchable at runtime); a deterministic, versioned threat-scoring engine that computes the score *before* the AI narrates it; an Executive Dashboard of live KPIs; a Provider Health page tracking real uptime per provider; a Security Assessment Toolkit for authorized active scanning (Nmap, DNS, TLS, HTTP headers); case management and a personal IOC watchlist; three-role RBAC enforced on every backend route; and export to JSON/Markdown/CSV/PDF with tested injection defenses.

## How Does It Work?

FastAPI/Python backend, Next.js/TypeScript frontend, Postgres as the system of record, Redis for caching/rate-limiting, Docker Compose as the runtime on both Windows and Linux. See `03_TECHNICAL_DOCUMENTATION/` and `09_ARCHITECTURE/` for the full detail.

## What Makes It Interesting?

The threat score is computed by a fixed, versioned formula before the AI ever sees it — the AI narrates a number it cannot override, and the platform validates the AI's own stated verdict against that number before saving anything. That single design decision is what makes the score reproducible regardless of which of the eleven AI backends is active, and it's the thread running through this whole submission.

## How Do I Run It?

Windows: run `05_INSTALLERS/HORIZON-GRID-Setup-0.2.4.exe` and follow the guided Setup Wizard (creates the admin account, configures providers/AI, brings up the stack). Linux: install `05_INSTALLERS/horizon-grid_0.2.4_amd64.deb`. Full step-by-step instructions, system requirements, and SHA256 checksums are in `05_INSTALLERS/` and `03_TECHNICAL_DOCUMENTATION/`.

## Where Is Everything?

| Looking for... | Go to |
|---|---|
| Source code | `04_SOURCE_CODE/` |
| User manual (how to use every feature) | `02_PRODUCT_DOCUMENTATION/HORIZON_GRID_USER_MANUAL.pdf` |
| Technical / backend / API documentation | `03_TECHNICAL_DOCUMENTATION/` |
| Testing / QA evidence | `08_TESTING/` |
| Screenshots | `06_SCREENSHOTS/` |
| Live demo script | `07_DEMO/HORIZON_GRID_HACKATHON_DEMO_GUIDE.pdf` |
| Installers | `05_INSTALLERS/` |
| Architecture diagrams | `09_ARCHITECTURE/` |
| Version history | `10_CHANGELOG/` |
| License / third-party notices | `11_LICENSE_AND_NOTICES/` |
| The exact prompts used to build this submission | `00_START_HERE/MISSION_PROMPTS_USED.md` |

## Recommended Reading Order

1. This document (`00_START_HERE/START_HERE.pdf`)
2. `01_EXECUTIVE/HORIZON_GRID_EXECUTIVE_OVERVIEW.pdf`
3. `06_SCREENSHOTS/` (browse — two minutes, gives immediate visual context)
4. `07_DEMO/HORIZON_GRID_HACKATHON_DEMO_GUIDE.pdf`
5. `09_ARCHITECTURE/HORIZON_GRID_ARCHITECTURE.pdf`
6. `08_TESTING/HORIZON_GRID_FINAL_QA_REPORT.pdf` and `HORIZON_GRID_ENGINEERING_HISTORY.pdf`
7. `04_SOURCE_CODE/` (only if you want to read the actual code)
