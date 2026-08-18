# HORIZON GRID

*Every Signal. One Operational Picture.*

Enterprise threat-intelligence workbench. A single IOC search fans out to every
configured intelligence provider in parallel, results are correlated and
deduplicated, an AI backend summarizes each provider and produces a final
evidence-based assessment (verdict, risk score, MITRE ATT&CK mappings,
detection rules, recommended actions), and everything streams live into one
SOC dashboard over Server-Sent Events.

The AI backend defaults to a locally-hosted Ollama server (`AI_BACKEND=ollama`,
no API key, no cloud cost) and can be switched to AWS Bedrock, Google Gemini,
or Anthropic's direct API via `.env` — see `backend/app/ai/service.py`.

## What's actually built

- **One-search investigation pipeline.** `POST /api/v1/lookup/stream` detects
  the IOC type, fans it out to every provider that supports that type
  (concurrently, over a shared HTTP client, with Redis caching + retry/timeout
  handling), streams each provider's result and AI summary as they arrive,
  then runs a deterministic correlation pass and a final AI-generated
  assessment. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full
  request lifecycle.
- **15+ intelligence connectors**, one plugin interface: VirusTotal,
  AbuseIPDB, AlienVault OTX, URLhaus, ThreatFox, MalwareBazaar, crt.sh, NVD,
  CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Hybrid Analysis, Spamhaus, PhishTank,
  Censys, plus an OSINT crawler-as-provider (GitHub, Reddit, RSS, Pastebin).
  Providers without a configured API key report `not_configured` rather than
  failing the lookup. Full detail in [docs/PROVIDERS.md](docs/PROVIDERS.md).
- **Deterministic correlation + evidence ledger.** A pure, no-I/O correlation
  engine builds a relationship graph (IP resolutions, related hashes/URLs,
  certificates, ASN, malware families, threat actors, MITRE techniques, CVEs)
  and a factual evidence ledger that every AI-generated explanation must cite
  by ID — invented citations are stripped server-side. See
  [docs/DATA_MODEL.md](docs/DATA_MODEL.md) and
  [docs/THREAT_INTELLIGENCE_GUIDE.md](docs/THREAT_INTELLIGENCE_GUIDE.md).
  Note: despite an internal model docstring describing edges as "mirrored
  into Neo4j," Postgres is currently the sole store for the correlation graph
  — Neo4j and OpenSearch are provisioned in `docker-compose.yml` but have no
  code path calling into them today (**not implemented**).
- **On-demand AI analysis and hunting.** Evidence-grounded endpoints for "why
  is this malicious," "what is this," false-positive checks, verdict
  challenges, next actions, intelligence gaps, score explanations, a
  freeform copilot Q&A, and multi-format detection-rule generation (Sigma,
  Splunk SPL, Sentinel KQL, Elastic, QRadar AQL, Chronicle YARA-L, Suricata,
  Snort, Zeek). See [docs/AI_ENGINE.md](docs/AI_ENGINE.md) and
  [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md).
- **Auth/RBAC, basket, and case management.** JWT-based auth with three
  roles (`admin`, `analyst`, `viewer`); a per-analyst basket for scratch
  comparisons; shared, team-wide case management with notes and IOC
  attachment. Server-side PDF/CSV export, admin/user-management APIs, and MFA
  are **not implemented** — see
  [docs/DOCUMENTATION_GAPS.md](docs/DOCUMENTATION_GAPS.md) for the full,
  audited list of what's stubbed, partial, or missing.
- **Background OSINT refresh.** Celery beat runs an hourly job that
  re-crawls OSINT sources for recently-looked-up IOCs and warms the shared
  Redis provider cache — separate from, and not a substitute for, the
  interactive lookup path.

## Quick start

```bash
# install Ollama (https://ollama.com) and pull a model that fits your GPU's
# VRAM, e.g.:
ollama pull llama3.2:3b

cp .env.example .env
# edit .env: add provider API keys you have, and set OLLAMA_MODEL to match
# whatever you pulled above (see `ollama list`)
docker compose up --build
```

Frontend: http://localhost:3000
Backend API docs: http://localhost:8000/docs

No seed admin account exists — the **first** user you register (via the
frontend `/register` page or `POST /api/v1/auth/register`) automatically
becomes `admin`; every registration attempt after that is rejected with
`403 Forbidden` (ask that admin to create your account from the
Administration page instead). For the full
zero-to-first-lookup walkthrough (including the exact `curl` commands and
what each dashboard panel does as it streams in), see
[docs/QUICKSTART.md](docs/QUICKSTART.md).

## Documentation

Full index and known gaps: [docs/DOCUMENTATION_GAPS.md](docs/DOCUMENTATION_GAPS.md)
is the honest counterpart to every guide below — read it alongside any of
these to know what's real vs. aspirational.

Prefer one file? [docs/IOC-Intelligence-Platform-Documentation.pdf](docs/IOC-Intelligence-Platform-Documentation.pdf)
compiles every guide below (except screenshots) into a single 130+ page PDF.

### New user
- [docs/QUICKSTART.md](docs/QUICKSTART.md) — zero-to-first-lookup walkthrough.
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — every dashboard panel and what it does.
- [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md) — real captures of every page (login, live investigation, basket, cases).
- [docs/FAQ.md](docs/FAQ.md) / [docs/GLOSSARY.md](docs/GLOSSARY.md) — common questions and terminology.

### SOC analyst
- [docs/SOC_ANALYST_GUIDE.md](docs/SOC_ANALYST_GUIDE.md) — day-to-day investigation SOP: triage, pivoting, basket, cases, hunting.
- [docs/THREAT_INTELLIGENCE_GUIDE.md](docs/THREAT_INTELLIGENCE_GUIDE.md) — evidence quality, confidence scoring, and trust calibration.
- [docs/IOC_TYPES.md](docs/IOC_TYPES.md) — every supported IOC type, detection behavior, and which providers accept it.

### Administrator
- [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) — role assignment, enabling providers, provider health checks.
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — every `.env` / settings variable explained.
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Docker Compose and Kubernetes deployment reference.

### Developer
- [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) — local dev setup, code layout, adding a provider or route.
- [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) — full REST/SSE reference (canonical; supersedes the older `docs/API.md`).
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — schema, ERD, and migration history.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design, component and sequence diagrams.
- [docs/PROVIDERS.md](docs/PROVIDERS.md) / [docs/AI_ENGINE.md](docs/AI_ENGINE.md) — connector-by-connector and AI-prompting detail.
- [docs/TESTING.md](docs/TESTING.md) — how to run the test suite and known local-run gotchas.

### Security
- [docs/SECURITY.md](docs/SECURITY.md) — auth/JWT model, RBAC, rate limiting, secrets handling, and known gaps to close before production.

### Other references
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — symptom → cause → fix.
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — snapshot of what's implemented as of the current source tree.
- [docs/API.md](docs/API.md) / [docs/INSTALL.md](docs/INSTALL.md) — earlier drafts, kept for history; superseded by API_DOCUMENTATION.md / QUICKSTART.md + DEPLOYMENT.md respectively.

## Scope of this build

This is a full vertical-slice scaffold:

- **Every module exists**: frontend, backend, plugin-based provider connectors,
  correlation engine, OSINT crawler, AI service, auth/RBAC, background workers,
  Postgres/Redis/Neo4j/OpenSearch, Docker Compose, K8s manifests, tests.
- **Real, working connectors** for free/no-key sources: VirusTotal (public API),
  AbuseIPDB, AlienVault OTX, URLHaus, ThreatFox, MalwareBazaar, crt.sh, NVD,
  CISA KEV, MITRE ATT&CK/CAPEC/CWE, WHOIS/RDAP.
- **Stubbed plugins** (implement the same `BaseProvider` interface) for
  Hybrid Analysis, Spamhaus, PhishTank, Censys. Spamhaus and PhishTank work
  out of the box with no key (`configured = True` unconditionally; PhishTank
  accepts an optional key for higher rate limits). Hybrid Analysis and Censys
  compute `configured` from `.env` — add `HYBRID_ANALYSIS_API_KEY`, or both
  `CENSYS_PERSONAL_ACCESS_TOKEN` and `CENSYS_ORGANIZATION_ID`, to activate
  them. Adding a new provider is a two-line change in
  `app/providers/registry.py`.
- **End-to-end depth** on IPv4/IPv6, Domain, URL, and file-hash IOC types
  (detection → parallel fetch → correlation → AI summaries → final verdict →
  dashboard). Other IOC types in the enum route through the same pipeline;
  they light up automatically as matching providers/plugins are added.
- **Known, documented gaps**: server-side PDF/CSV export, admin/user-management
  UI, MFA, password reset, and a Neo4j/OpenSearch graph/search mirror are all
  provisioned or scaffolded but **not implemented** — see
  [docs/DOCUMENTATION_GAPS.md](docs/DOCUMENTATION_GAPS.md) for the full audit.
