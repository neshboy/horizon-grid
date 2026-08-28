<div align="center">

# 🛰️ HORIZON GRID

### *Every Signal. One Operational Picture.*

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
![Windows](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)
![Linux](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)
![Version](https://img.shields.io/badge/version-0.3.8-brightgreen)
![Python](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/frontend-Next.js-000000?logo=next.js&logoColor=white)
![Docker](https://img.shields.io/badge/deploy-Docker%20Compose-2496ED?logo=docker&logoColor=white)
![Postgres](https://img.shields.io/badge/store-PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![AI](https://img.shields.io/badge/AI-11%20backends%20incl.%20local%20Ollama-6E56CF)

**[Quick Start](#-installation--quick-start)** · **[Features](#-features)** · **[Providers](#-provider-intelligence)** · **[Docs](#-documentation)** · **[Security](#-security)**

</div>

---

## 📋 Table of contents

- [What it is](#-what-it-is)
- [What problem it solves](#-what-problem-it-solves)
- [Who it's for](#-who-its-for)
- [How it works](#️-how-it-works-at-a-high-level)
- [Features](#-features)
  - [IOC investigation and threat scoring](#ioc-investigation-and-threat-scoring)
  - [Provider intelligence](#-provider-intelligence)
  - [AI analysis](#-ai-analysis)
  - [Executive dashboard](#-executive-dashboard)
  - [Admin and RBAC](#-admin-and-rbac)
  - [Security Assessment Toolkit](#️-security-assessment-toolkit)
  - [Pentest Suite](#️-pentest-suite)
  - [Reliability](#-reliability-and-mission-critical-deployment)
- [Platform support](#-platform-support)
- [Architecture](#️-architecture)
- [Installation / quick start](#-installation--quick-start)
- [Documentation](#-documentation)
- [Security](#-security)
- [Testing](#-testing)
- [License](#-license)

---

## 🎯 What it is

HORIZON GRID is a self-hosted threat-intelligence workbench. A single IOC
lookup (IP, domain, URL, file hash, CVE, or MITRE ATT&CK technique) fans out
in parallel to every configured intelligence provider, the results are
deduplicated and correlated into a relationship graph, an AI backend
summarizes each provider's findings, and a deterministic scoring engine
produces a final risk verdict — all streamed live to a SOC-style dashboard.

## 🧩 What problem it solves

Investigating an indicator by hand normally means opening a dozen browser
tabs (VirusTotal, AbuseIPDB, OTX, crt.sh, NVD, ...), manually reconciling
conflicting verdicts, and writing up a judgment call under time pressure.
HORIZON GRID collapses that into one search: it queries every provider you've
configured at once, correlates what comes back, and hands you a scored,
evidence-cited assessment instead of a pile of raw JSON to reconcile
yourself.

## 👥 Who it's for

Security operations teams, threat-intel analysts, and incident responders who
want a self-hosted (on-prem or lab) console for indicator triage — including
teams that need to run entirely offline/air-gapped using a local Ollama model
instead of a cloud AI API.

## ⚙️ How it works, at a high level

1. An analyst submits an indicator through the frontend or the API.
2. The backend detects the IOC type and queries every registered provider
   that supports that type, concurrently, with Redis-backed caching and
   retry/timeout handling.
3. A deterministic correlation engine links the returned data (shared
   infrastructure, related hashes/URLs, malware families, threat actors,
   MITRE techniques, CVEs) into a relationship graph.
4. The configured AI backend summarizes each provider's raw result and, once
   all providers have responded, produces a final narrative assessment.
5. A separate deterministic scoring engine (not the AI) computes the
   authoritative risk score, confidence score, and severity band from the
   provider verdicts and correlation edges — the AI's narrative is displayed
   alongside this score but never overrides it.
6. Results stream to the dashboard over Server-Sent Events as each provider
   and the correlation/scoring/AI steps complete.

> [!NOTE]
> The AI never computes the risk score — it narrates a number the
> deterministic scoring engine already produced. The backend mechanically
> overwrites any risk figures the AI emits before persisting the final
> assessment.

## ✨ Features

### IOC investigation and threat scoring

- One-search pipeline covering IPv4/IPv6, domains, URLs, file hashes,
  hostnames, CVEs, ASNs, TLS certificates, and MITRE ATT&CK technique IDs,
  routed to whichever providers support each type.
- A deterministic scoring engine (`backend/app/scoring/engine.py`) computes
  `overall_risk_score`, `confidence_score`, and `malicious_probability` from
  provider-verdict consensus (weighted toward graduated multi-engine ratios
  such as VirusTotal's detection ratio, with a corroboration multiplier so a
  single provider can't swing the score alone) plus qualifying correlation
  edges (`associated_with`, `attributed_to`, `part_of_campaign`, `exploits`,
  `uses_technique`), each requiring corroboration from 2+ distinct providers
  to count at full weight. `severity` is banded from `overall_risk_score` at
  fixed thresholds (10/30/55/80 → none/low/medium/high/critical).
- This scoring engine is wired into both the live investigation stream and
  the reanalyze/rebuild path in `backend/app/api/routes/lookup.py`, and into
  the Security Assessment Toolkit's refresh flow — the AI is given the score
  as a fact in its prompt, and the backend mechanically overwrites the AI's
  own risk numbers with the scoring engine's output before persisting, so the
  score displayed is always the deterministic one.
- Covered by a 22-test unit suite (`backend/app/tests/unit/test_scoring_engine.py`)
  exercising corroboration weighting, conflicting-verdict confidence collapse,
  and severity banding.

### 🔌 Provider intelligence

Seventeen threat-intelligence providers are registered and queried through a
single plugin interface, plus one OSINT crawler-as-provider:

| Provider | Indicator types | API key required | What it queries |
|---|---|---|---|
| VirusTotal | IPv4, IPv6, Domain, URL, MD5/SHA1/SHA256/SHA512 | ✅ Yes | Reputation/detection stats per IOC type |
| AbuseIPDB | IPv4, IPv6 | ✅ Yes | Abuse confidence score, report count, ISP/usage-type |
| AlienVault OTX | IPv4, IPv6, Domain, Hostname, URL, hashes | ✅ Yes | Pulses, malware families, threat actors |
| URLhaus | URL, Domain, IPv4 | ✅ Yes (abuse.ch Auth-Key) | Known malware-distribution URLs/hosts |
| ThreatFox | IPv4, IPv6, Domain, URL, MD5, SHA256 | ✅ Yes (abuse.ch Auth-Key) | IOC-to-malware-family associations |
| MalwareBazaar | MD5/SHA1/SHA256/SHA512 | ✅ Yes (abuse.ch Auth-Key) | Malware sample metadata by hash |
| crt.sh | Domain, TLS certificate | 🆓 No | Certificate transparency log entries + related subdomains |
| NVD | CVE | 🆓 No *(optional key raises rate limit)* | CVSS score/severity, CWEs, description |
| CISA KEV | CVE | 🆓 No | Known Exploited Vulnerabilities catalog — exploitation status, due date, ransomware use |
| MITRE ATT&CK | MITRE technique ID | 🆓 No | Technique name, tactics, platforms |
| WHOIS/RDAP | Domain, IPv4, IPv6, ASN | 🆓 No | Domain WHOIS and IP/ASN registration data |
| urlscan.io | URL, Domain | ✅ Yes | Sandbox scan verdict, screenshots, resolved infrastructure |
| Google Safe Browsing | URL, Domain | ✅ Yes | Malware/phishing/unwanted-software matches |
| Hybrid Analysis | SHA256 only | ✅ Yes | Threat score, AV detection percentage |
| Spamhaus | IPv4, Domain | 🆓 No | ZEN/DBL blocklist status |
| PhishTank | URL | 🆓 No *(optional key raises rate limit)* | Community-verified phishing URL status |
| Censys | IPv4, IPv6 | ✅ Yes (PAT + org ID) | Open services, ASN, geo (Censys Platform API) |
| Internet Intelligence Collector | Domain, IPv4, malware family, threat actor, campaign, CVE, file name | 🆓 No | Free-text OSINT hits from GitHub, Reddit, RSS security news, and paste-dump search |

> [!TIP]
> Providers without a configured key or credential report `not_configured`
> rather than failing the lookup, so a fresh install still works with
> whatever keys you've added — add the rest later, at your own pace.

### 🤖 AI analysis

The AI layer is backend-agnostic — eleven backends implement the same
interface so the platform can switch between them without any branching in
the calling code, including a fully local/self-hosted option with no API
key and no cloud cost:

| Backend | Requires API key | Notes |
|---|---|---|
| 🏠 Ollama (local/self-hosted) | 🆓 No — needs a reachable Ollama server | Live model discovery from your locally-pulled models |
| Anthropic (Claude direct API) | ✅ Yes | Static fallback model list |
| AWS Bedrock | ✅ Yes (bearer token or AWS access key+secret) | Static fallback model list |
| Google Gemini | ✅ Yes | Static fallback model list |
| Groq | ✅ Yes | Live model discovery via Groq's models API; default `llama-3.3-70b-versatile` |
| OpenAI | ✅ Yes | Live model discovery via OpenAI's models API; default `gpt-4o-mini` |
| Kimi (Moonshot AI) | ✅ Yes | Live model discovery; default `kimi-k2.5` (deliberately not one of Moonshot's "thinking" models, which reject forced tool calls) |
| DeepSeek | ✅ Yes | Live model discovery; default `deepseek-v4-flash` |
| Grok (xAI) | ✅ Yes | Live model discovery; default `grok-4.6` |
| Mistral AI | ✅ Yes | Live model discovery; default `mistral-small-2506` |
| OpenRouter | ✅ Yes | Meta-router giving access to hundreds of underlying models from many providers through one API; live model discovery filtered to models that support forced tool calls; default `openai/gpt-4o` |

Every backend supports a live connection test with candidate (unpersisted)
credentials before you save them, and the active backend can be switched
platform-wide at runtime without a restart.

### 📊 Executive dashboard

The dashboard renders real, live-queried data — no hardcoded or mocked
figures:

- Seven KPI tiles backed by real SQL aggregations against the lookup, case,
  provider-result, and final-assessment tables (active investigations,
  critical/high-risk IOC count, open cases, open critical cases, average
  threat score, provider health percentage, AI success rate).
- An AI-written executive summary layered on the same KPI numbers, with a
  template fallback (clearly badged) if AI generation is unavailable.
- A provider-health widget showing per-provider status, success rate,
  latency, and consecutive-failure counts over 1h/24h/7d/30d windows.

### 🔐 Admin and RBAC

Three roles — Admin, Analyst, Viewer — enforced server-side via a FastAPI
dependency on every gated route (not just declared in the UI):

| Role | Access |
|---|---|
| 🔴 **Admin** | Everything Analyst has, plus provider management and user management |
| 🟡 **Analyst** | Create/write access — lookups, cases, security assessments, and more |
| 🟢 **Viewer** | Read-only access to lookups, evidence, cases, security assessments, and the dashboard |

User-management routes (create user, update user, roles, stats) require the
`user:manage` permission, which only Admin holds; launching a Security
Assessment scan requires `security_assessment:create`, which Admin and
Analyst hold but Viewer does not.

### 🛡️ Security Assessment Toolkit

An active-scanning module (`backend/app/security_assessment/`) that runs
real technical checks against a target — port/service scanning, DNS, TLS,
HTTP-header inspection, and hash lookups — gated by a mandatory explicit
authorization/scope confirmation per run. Findings feed through the same
evidence/correlation/AI pipeline used by ordinary provider lookups, and a
refresh re-runs the deterministic scoring engine using the new finding
severities as a floor on the risk score.

### ⚔️ Pentest Suite

A standalone, scope-enforced assessment lifecycle (`backend/app/pentest/`) —
DISCOVER → ENUMERATE → ASSESS → CORRELATE → PRIORITIZE → REPORT — distinct
from the Security Assessment Toolkit above, which stays tightly bound to a
single investigation's own IOC. Declare a scope (CIDR ranges/domains — an
empty scope authorizes nothing), add targets inside it, and run an automated
scan pipeline with full pause/resume/cancel/emergency-stop control plus a
global, admin-only kill switch. Findings carry a confidence rating
(`Confirmed`/`Likely`/`Potential`/`Informational`) alongside severity, and an
AI Security Analyst can explain any finding or summarize a whole assessment,
grounded strictly in real data.

For administrators only: **Exploit Validation**, a real, self-hosted
Metasploit Framework connection baked into the backend's own Docker image.

> [!WARNING]
> This is genuine exploit-module execution, not a simulation. Reachable only
> for a finding with a matched CVE, only after manually selecting one
> specific module, and real execution requires an explicit confirmation on
> every single request — the target host is always locked to the finding's
> own real target regardless of what's entered in the options form. Only
> ever point it at systems you own or are explicitly authorized to test. See
> [docs/PENTEST_SUITE.md](docs/PENTEST_SUITE.md) for the full safety model,
> including the five independent gates between "an assessment exists" and "a
> real exploit ran."

### 🔁 Reliability and mission-critical deployment

Hardened for a one-time install at a remote site with no developer access
afterward (full detail in the Mission-Critical Operations Manual):

- All 8 Docker Compose services restart automatically on a crash
  (`restart: unless-stopped`), including Redis's persistent volume so a
  routine container recreation no longer resets the cache/rate-limiter state.
- Boot-time auto-start on both platforms (Windows Scheduled Task; Linux
  `systemctl enable`) and a 5-minute health watchdog that checks a real
  dependency-aware endpoint (`GET /health/detailed`, which genuinely pings
  Postgres/Redis) and restarts the stack if it's unhealthy.
- Scheduled nightly database backups on both platforms, plus a real,
  tested restore procedure (`Restore-Database.ps1` / `horizon-grid restore`)
  requiring an explicit typed confirmation.
- An SSRF guard on the Ollama AI backend's outbound URL, login brute-force
  rate limiting, a 10 MB request-body-size limit, and Swagger/OpenAPI docs
  disabled in production.

## 💻 Platform support

| | 🪟 Windows | 🐧 Linux |
|---|---|---|
| Package format | Inno Setup installer (`.exe`) | `.deb` (Debian/Ubuntu) |
| Distros/versions | Windows, 64-bit only | Debian 12, Ubuntu 22.04, Ubuntu 24.04 |
| Setup flow | GUI wizard (admin account, AI backend, providers, ports, live connection tests) | Terminal wizard, same flow; supports `--non-interactive --answers-file` and `--dry-run` |
| Runtime | Docker Compose (built on first `docker compose up --build`) | Docker Compose, managed via a systemd unit wrapping the `horizon-grid` CLI |
| Code/package signing | Not code-signed — SmartScreen will warn; click "Run anyway" | Not signed (standard for `.deb` packages) |
| Uninstall (keep data) | "Remove Application" — stops containers, no volume deletion | `apt remove horizon-grid` — stops containers, no volume deletion |
| Uninstall (delete everything) | "Remove Everything" — requires typing `DELETE`; deletes volumes and all config/data | `apt purge horizon-grid` — force-removes containers/volumes and deletes all config/data |
| Current version | `0.3.8` | `0.3.8` |

## 🏗️ Architecture

- **Backend**: FastAPI (Python), served under the `/api/v1` prefix.
- **Frontend**: Next.js.
- **Datastores**: PostgreSQL (primary store, including the correlation
  graph), Redis (caching, background job queue), Neo4j and OpenSearch
  (provisioned in `docker-compose.yml` for future graph/search use).
- **Background processing**: Celery worker + Celery beat for scheduled OSINT
  refresh jobs.
- **Orchestration**: Docker Compose (`docker-compose.yml` for development,
  `docker-compose.prod.yml` for production).

## 🚀 Installation / quick start

### Docker Compose (development)

```bash
cp .env.example .env
# edit .env:
#  - REQUIRED: replace JWT_SECRET_KEY with a real random value, e.g.
#    `openssl rand -hex 32` -- the app will boot and log a warning if you
#    skip this, but every token it issues is forgeable until you don't.
#  - add whichever provider/AI API keys you have
docker compose up --build
```

> [!IMPORTANT]
> Always replace `JWT_SECRET_KEY` before exposing this beyond your own
> laptop. The app boots fine without it, but every auth token it issues is
> forgeable until you do.

Frontend: http://localhost:3000
Backend API docs: http://localhost:8000/docs

### 🪟 Windows installer

Built from `windows/installer.iss` (Inno Setup). The compiled installer
copies the application (backend, frontend, Docker Compose files) under
Program Files, then launches `windows/wizard/Setup-Wizard.ps1` to configure
the admin account, AI backend, providers, and network ports, testing each
credential against the running backend before it's saved. Requires
administrator privileges; 64-bit Windows only.

### 🐧 Linux package

Built via `linux/build-deb.sh` (requires a Debian/Ubuntu host; produces
`horizon-grid_<version>_amd64.deb`, e.g. `release/horizon-grid_0.3.8_amd64.deb`).
Install with `sudo dpkg -i horizon-grid_0.3.8_amd64.deb`, then run the
terminal setup wizard as root to configure the admin account, AI backend,
providers, and ports; the platform is then managed via the `horizon-grid`
systemd-backed CLI (`start` / `stop` / `restart`).

## 📚 Documentation

Full documentation source lives under
[`documentation/DOCUMENTATION_SOURCE/`](documentation/DOCUMENTATION_SOURCE/)
as individual Markdown files (architecture, backend reference, provider and
AI integration detail, runtime configuration, security architecture,
background processing, deployment/troubleshooting, the Security Assessment
Toolkit, and standalone per-platform guides for Windows and Linux). Built,
distributable copies (PDF and DOCX) of the same material are under
[`documentation/`](documentation/) — see `documentation/DOCUMENTATION_INDEX.md`
for the full index.

## 🔒 Security

See [`SECURITY.md`](SECURITY.md) for how to report a vulnerability and known
security-relevant limitations, and
[`documentation/DOCUMENTATION_SOURCE/standalone-security.md`](documentation/DOCUMENTATION_SOURCE/standalone-security.md)
for the auth/JWT model, RBAC enforcement, and secrets handling in more detail.

## 🧪 Testing

Backend (335 unit tests pass standalone, no infra required; the full suite —
380 passed, 39 skipped — additionally requires either a running Docker
Compose stack or the host-published Postgres/Redis ports, and a subset is
designed to run inside the backend container; the 39 skips are intentional
host-only/environment-gated tests, not failures):

```bash
cd backend
pip install -r requirements.txt
python -m pytest app/tests/unit -v      # 335 passed, no infra required
python -m pytest app/tests -v           # full suite: 380 passed, 39 skipped, requires DB/Redis
```

Frontend:

```bash
cd frontend
npm ci
npm run lint
npm run build
```

> [!NOTE]
> `npm test` (vitest) is wired up in `frontend/package.json`, but no test
> files exist yet under `frontend/app`, `frontend/components`, or
> `frontend/lib` — this is a placeholder, not a passing suite.

## 📄 License

Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See
[LICENSE](LICENSE) for the full text.
