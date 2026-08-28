# 🛰️ HORIZON GRID

**Every Signal. One Operational Picture.**

![Version](https://img.shields.io/badge/version-0.3.8-brightgreen)
![Windows](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)
![Linux](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)
![AI](https://img.shields.io/badge/AI-11%20backends%20incl.%20local%20Ollama-6E56CF)

**Application Version:** 0.3.8
**Status:** Release Ready with Known Limitations — see the Final Release QA Report for the full evidence behind that verdict.

## 📋 Table of contents

- [🎯 What Is HORIZON GRID?](#-what-is-horizon-grid)
- [🧩 The Problem It Solves](#-the-problem-it-solves)
- [⚙️ How It Works](#️-how-it-works)
- [✨ Key Features](#-key-features)
- [🔌 Supported Intelligence Providers](#-supported-intelligence-providers)
- [🤖 AI Capabilities](#-ai-capabilities)
- [🧮 Threat Scoring](#-threat-scoring)
- [🚀 Getting Started](#-getting-started)
- [📚 Documentation Map](#-documentation-map)

---

## 🎯 What Is HORIZON GRID?

HORIZON GRID is a self-hosted, open-web intelligence and threat-analysis platform. You give it one **IOC** (Indicator of Compromise — a piece of evidence such as an IP address, domain, URL, file hash, or CVE ID that a security analyst wants to investigate), and it queries every relevant third-party threat-intelligence source it knows about, in parallel, correlates what those sources say about each other, computes a deterministic threat score from that evidence, and asks an AI model to explain the result in plain language — with every claim traceable back to the real data it came from.

It runs entirely on infrastructure you control. There is no vendor cloud in the loop, no per-lookup fee to a hosted SaaS platform, and no requirement to send your indicators anywhere except the outbound calls to whichever third-party providers you personally choose to configure. A solo analyst can run it on a single Windows machine; a small security team can point several browsers at the same install and share cases, a watchlist, and an operational dashboard.

[FIGURE: dashboard-executive-overview.png | The Executive Dashboard — real KPI tiles, an AI-generated (or clearly-labeled template-fallback) narrative, and a provider-health summary, all sourced live from the same platform that ran the investigation below it.]

## 🧩 The Problem It Solves

No single threat-intelligence source sees everything. A file hash might be flagged by one antivirus engine and ignored by another. An IP address might be a known Tor exit node on one blocklist and unremarkable on the next. Getting a trustworthy read on an indicator means checking it against several independent sources and weighing what they collectively say — and, just as importantly, noticing when two sources are quietly describing the *same* underlying fact from different angles (an IP tied to a malware family, which is tied to a MITRE ATT&CK technique, which matches a hash already flagged elsewhere).

In practice, that usually means an analyst opens a reputation lookup site, then a malware sandbox or sample database, then a certificate-transparency search, then a vulnerability database, then a DNS blocklist — pasting the same indicator into each one, reading each result in its own format, and holding all of it in their head well enough to catch a correlation or a disagreement between sources. That manual cross-referencing is the real cost, and it's the cost that quietly gets skipped when the queue of indicators needing triage is long.

HORIZON GRID exists to collapse that workflow into a single search box: one submission, every applicable provider queried at once, the results correlated automatically, and a threat score and an AI-written explanation produced from the combined evidence — along with a concrete way to check every one of the AI's claims against the real, underlying data before you act on it.

## ⚙️ How It Works

HORIZON GRID is a FastAPI (Python) backend with an async SQLAlchemy ORM over Postgres 16, a Next.js 14 / TypeScript frontend, Redis for provider-result caching and rate limiting, and a Celery worker/beat pair that runs exactly one scheduled job (an hourly OSINT re-crawl of recently-looked-up indicators) — the live investigation pipeline itself runs synchronously inside the backend process and streams results to the browser over Server-Sent Events, not through Celery or a WebSocket. Neo4j and OpenSearch containers are also provisioned in the stack for a future graph store and search index respectively, but today the correlation graph the product actually shows you lives entirely in Postgres; that distinction matters if you're reading the Technical Architecture document and wondering why those two containers appear alongside everything else. On Windows, all of this is packaged behind a single Inno Setup installer and a guided Setup Wizard that stands the whole stack up as Docker containers — see the Windows Installation guide for the full mechanics.

## ✨ Key Features

- **Multi-provider parallel IOC lookup** — submit one indicator and query every configured, applicable provider at once; results stream into the page live as each provider responds, rather than making you wait for the slowest one.
- **Automatic correlation** — a correlation engine extracts relationships between what different providers reported (shared infrastructure, related hashes, malware families, MITRE ATT&CK techniques, exploited CVEs) and boosts confidence when multiple independent providers corroborate the same fact.
- **Deterministic, auditable threat scoring** — `overall_risk_score`, `confidence_score`, `malicious_probability`, and a severity band are computed by a fixed, versioned scoring engine *before* any AI call, from provider-verdict consensus and correlation evidence. The AI is handed that number as a given fact and can only narrate it — it cannot invent or override it, and the platform re-validates its output against the real number before saving anything. See the Threat Scoring guide for the exact formula.
- **AI-assisted analysis, twice per investigation** — a short summary per provider as each one reports in, then one consolidated Final Assessment once every provider has finished, on your choice of eleven interchangeable AI backends. See "AI Capabilities" below.
- **Evidence Ledger and verdict-interrogation tools** — every investigation carries a deterministic, non-AI-generated list of the concrete facts behind it, plus dedicated tools ("Why?", "Challenge This Verdict", "False Positive Check", "Score Explanation", "Intelligence Conflicts") for checking any AI claim against that evidence rather than taking it on faith.
- **Security Assessment Toolkit** — a genuinely different, *active* check against a target (Nmap port/service scan, DNS record lookup, TLS certificate inspection, HTTP security-header check), gated behind two explicit confirmations (retype the target, confirm authorization) since — unlike every passive provider — it sends real traffic. Findings feed back into the same investigation's threat score as a floor, never silently inflating `malicious_probability`.
- **Case management and IOC Basket** — group indicators into a case with analyst notes as an incident develops, or keep a running personal watchlist of IOCs worth revisiting.
- **Executive Dashboard** — seven live KPI tiles (active investigations, critical/high-risk IOC count, open case counts, average threat score, provider health percentage, 30-day AI success rate) plus an AI-generated narrative that is honestly labeled as either "AI-generated" or "Template fallback" — never silently fabricated, never hardcoded.
- **Provider Health** — a database-backed page showing every registered provider's real status (Healthy / Degraded / Down / Unknown) across four rolling windows (1h/24h/7d/30d). A provider with zero real attempts in a window is always "Unknown," never "Healthy," and a provider correctly reporting "nothing found" counts as a healthy outcome, not a failure.
- **Role-based access control** — three fixed roles (Admin, Analyst, Viewer) enforced server-side on every route, not just hidden in the UI; Viewer is deliberately broad on read access (including the dashboard) but cannot create investigations, run active security assessments, or export.
- **Exporting findings** — download a completed investigation as JSON, Markdown, CSV, or PDF, gated behind an export-specific permission (Admin/Analyst only). The CSV and PDF paths carry real, tested defenses against formula-injection and markup-injection abuse.
- **Windows installer with a guided Setup Wizard** — a standard installer followed by a step-by-step wizard that creates the administrator account, configures the AI backend and threat-intelligence providers (with live "Test" buttons), reviews network ports, and brings the whole stack up end to end. (One deliberate exception: the installer's own on-disk data folder and a few internal identifiers keep the product's previous name for upgrade safety — everything you actually see in the product is branded HORIZON GRID.)

## 🔌 Supported Intelligence Providers

HORIZON GRID ships with **18 built-in providers** spanning multi-engine reputation scanning, community abuse/malware databases, certificate-transparency search, government vulnerability catalogs, sandbox behavior, DNS blocklists, phishing databases, internet-wide host scanning, and the platform's own live OSINT crawler — including VirusTotal, AbuseIPDB, AlienVault OTX, URLhaus, ThreatFox, MalwareBazaar, crt.sh, NIST NVD, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, urlscan.io, Google Safe Browsing, Hybrid Analysis, Spamhaus, PhishTank, Censys, and the Internet Intelligence Collector. Most work with a free API key; several (crt.sh, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Spamhaus, and the Internet Intelligence Collector) need no credential at all and are active from the moment the platform starts. Every provider that's relevant to the IOC type you submitted is queried — a file hash is never sent to a domain-registration lookup. See the Provider Guide for the full breakdown of each one, including exactly what it checks and what it returns.

## 🤖 AI Capabilities

Every investigation gets two distinct AI passes: a short summary of each provider's own result as it arrives, grounded only in that provider's own data, and one consolidated Final Assessment once every provider has finished, grounded in all the per-provider summaries plus the correlation engine's output. The platform supports eleven interchangeable AI backends — Ollama (local, free, no API key), Anthropic, AWS Bedrock, Google Gemini, Groq, OpenAI, Kimi (Moonshot AI), DeepSeek, xAI (Grok), Mistral AI, and OpenRouter (a meta-router giving access to hundreds of underlying models through one API) — switchable at any time from the app itself with no restart. Every AI generation is tracked as one of exactly three honest outcomes: a real success, a correct decision to skip the AI entirely because there was no evidence to reason over, or a genuine failure with a deterministic-score-based fallback — never a fabricated result. The AI is deliberately never the source of the threat score itself; see "Threat Scoring" below and the dedicated AI Guide for the full architecture, including the grounding mechanisms that strip any citation the AI invents.

## 🧮 Threat Scoring

Underneath every investigation's score is a deterministic, non-AI scoring engine (currently version `1.0`) that computes `overall_risk_score`, `confidence_score`, `malicious_probability`, and a severity band (none/low/medium/high/critical) from two additive, weighted components — provider-verdict consensus (65 points, with a corroboration multiplier that keeps one uncorroborated flag from scoring like five independent providers agreeing) and correlation-graph evidence (35 points, given the same anti-flood corroboration treatment). A Security Assessment Toolkit finding can raise the floor on risk and confidence, but never on `malicious_probability` — a vulnerability finding and a confirmed malicious verdict are deliberately kept as separate claims. The AI receives this number as a fixed input and narrates it; it cannot change it. The full formula, the corroboration math, and a real worked example live in the dedicated Threat Scoring guide.

## 🚀 Getting Started

If you're installing HORIZON GRID for the first time and want the fastest path from a blank Windows machine to your first completed investigation, start with the **Quick Start** guide — it assumes no prior technical knowledge and walks through installation, launch, your first provider and AI configuration, your first IOC lookup, and reading the result, end to end. For the full installer mechanics (system requirements, every Setup Wizard page, upgrading, uninstalling), see the **Windows Installation** guide.

## 📚 Documentation Map

This README is one document in a larger package. Every document below is generated from source material reviewed against the real running application and real source code — nothing in this package is speculative.

| Document | Purpose |
|---|---|
| **README** (this document) | What HORIZON GRID is, why it exists, and a map of the rest of this package. |
| **Quick Start** | Zero-to-first-investigation walkthrough for a complete beginner — no assumed technical knowledge. |
| **User Manual** | The full page-by-page guide to investigating IOCs, reading results, cases, and exports. |
| **Function Reference** | An exhaustive, per-page catalog of every major control in the application. |
| **Admin Guide** | User/role management, provider and AI configuration, backups, and uninstall. |
| **Technical Architecture** | System architecture, ports, data flow, request lifecycle, and diagrams. |
| **Backend Documentation** | A module-by-module reference to the backend codebase. |
| **Source Code Guide** | Setting up a development environment and running/building/testing the codebase. |
| **API Documentation** | Every real API endpoint — method, authentication, request/response shape, and errors. |
| **Security** | Authentication, RBAC, credential handling, injection defenses, and known risks. |
| **Operations Guide** | Day-to-day running: health checks, caching, backups, and connection pooling. |
| **Troubleshooting** | Real, tested symptom-to-cause-to-fix entries. |
| **Testing & QA** | Test categories and real pass/fail statistics from the project's own test suites. |
| **Final Release QA Report** | The complete, honest release-readiness verdict and the evidence behind it. |
| **Windows Installation** | The full installer and Setup Wizard walkthrough, upgrade/uninstall, and real fixed issues. |
| **Provider Guide** | Every one of the 18 integrated intelligence providers, covered in detail. |
| **AI Guide** | The AI backends, how switching works, prompt architecture, and why the AI can't override the score. |
| **Threat Scoring** | The exact deterministic scoring formula, with a real worked example. |
| **Documentation Index** | A single-page index of this entire package, tagged by intended audience. |
| **Changelog** | Every notable change in this release, grouped by area. |
| **Release Notes** | A short, plain-language summary of what's new and the release verdict. |

For the same list with intended audience tagged against each document, see the **Documentation Index**.
