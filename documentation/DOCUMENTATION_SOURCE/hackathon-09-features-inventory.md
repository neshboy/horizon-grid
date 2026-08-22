# Feature Inventory

Every item below is implemented and verified against current source code (`backend/app/providers/registry.py`, `backend/app/core/runtime_config.py`, `backend/app/scoring/engine.py`, `backend/app/models/user.py`, `backend/app/security_assessment/`) — nothing here is planned or aspirational. Deep-dive detail on each area lives in the companion technical documentation set (Provider Guide, AI Guide, Threat Scoring guide, Admin Guide, Security guide) referenced at the end of this submission.

## IOC Investigation

The core workflow: submit one indicator (IP, domain, URL, file hash, CVE, and 27 other recognized `IOCType` values — 32 in total), and the platform validates, classifies, and fans the value out to every registered provider that supports that type. Results stream in over Server-Sent Events rather than blocking on the slowest provider.

## Provider Ecosystem — 18 Providers

`VirusTotal`, `AbuseIPDB`, `AlienVault OTX`, `URLhaus`, `ThreatFox`, `MalwareBazaar`, `crt.sh`, `NIST NVD`, `CISA KEV`, `MITRE ATT&CK`, `WHOIS/RDAP`, `urlscan.io`, `Google Safe Browsing`, `Hybrid Analysis`, `Spamhaus`, `PhishTank`, `Censys`, and the platform's own **Internet Intelligence Collector** (a live OSINT crawler) — spanning multi-engine reputation scanning, community abuse/malware databases, certificate-transparency search, government vulnerability catalogs, sandbox behavior, DNS blocklists, phishing databases, and internet-wide host scanning. Several (`crtsh`, `cisa_kev`, `mitre_attack`, `whois_rdap`, and the stub-implemented `spamhaus`/`phishtank`) need no API key at all and are active from first boot.

## AI System — 11 Interchangeable Backends

`Ollama` (local, free, no key), `Anthropic`, `AWS Bedrock`, `Google Gemini`, `Groq`, `OpenAI`, `Kimi` (Moonshot AI), `DeepSeek`, `xAI` (Grok), `Mistral AI`, and `OpenRouter` — all exposed through one identical `call_claude_json()` interface, switchable at runtime with no restart. Two distinct AI passes run per investigation: a grounded per-provider summary as each result arrives, and one consolidated Final Assessment once every provider has reported, conditioned on the deterministic threat score (see below). Every AI generation is tracked as one of three honest outcomes — real success, correct no-evidence skip, or disclosed failure — never a fabricated result.

## Deterministic Threat Scoring

A fixed, versioned (`SCORING_ENGINE_VERSION = "1.0"`) scoring engine computes `overall_risk_score`, `confidence_score`, `malicious_probability`, and a severity band from provider-verdict consensus and correlation-graph evidence — **before** the AI's final assessment runs, not after. The AI receives the score as a fixed input and is validated against it, so it narrates rather than decides. A dedicated corroboration-scaling mechanism prevents one account listing several tags across free-text fields from single-handedly flooding the score.

## Correlation and Evidence

A pure, deterministic correlation engine extracts typed relationship edges (shared infrastructure, related hashes, malware families, MITRE ATT&CK techniques, exploited CVEs) from normalized provider fields and boosts confidence when independent providers corroborate the same fact. A non-AI-generated Evidence Ledger, built directly from provider results and correlation edges, backs a set of verdict-interrogation tools (WHY malicious, What Is This, Provider Disagreement, False-Positive Assessment, Challenge/red-team, Smart Next Actions, Intelligence Gaps, Score Explanation) plus Copilot Q&A, IOC comparison, and hunting-query/detection-rule generation.

## Executive Dashboard

Live KPI tiles — active investigations, critical/high-risk IOC count, open case counts, average threat score, provider health percentage, AI success rate — computed from real database aggregates, never hardcoded, plus an AI-generated narrative that is honestly labeled as AI-generated or template-fallback.

[FIGURE: threat-scoring-ai-assessment.png | The Final Assessment panel's Risk & Verdict tab — overall risk score, confidence score, severity, and malicious probability, all computed before the AI narrates them.]

## Provider Health

A dedicated page tracking every registered provider's real status (Healthy/Degraded/Down/Unknown) across four rolling windows (1h/24h/7d/30d), built from the same `ProviderResultRecord` data every real investigation already writes. A provider with zero attempts in a window shows Unknown, never a false Healthy.

## Security Assessment Toolkit (Active Port Scanner)

A genuinely active check — Nmap port/service scan, DNS record lookup, TLS certificate inspection, HTTP security-header check — against a target the analyst explicitly confirms authorization for (target retype + authorization checkbox), with real cancellation support (a live task can be stopped mid-scan, not just flagged in the database). Findings feed the investigation's risk/confidence floor without inflating `malicious_probability` on their own.

[FIGURE: security-assessment-port-scanner.png | A completed Nmap "quick" scan against an authorized target, showing the required target-confirmation/authorization controls and a real finding.]

## Case Management and IOC Basket

Group indicators into a case with analyst notes as an incident develops, or keep a running personal watchlist of indicators worth revisiting.

## Administration and RBAC

Three fixed roles — Admin, Analyst, Viewer — enforced server-side on every route via a `require_permission()` dependency, not just hidden in the UI. Genuine multi-administrator support (any admin can create further admin accounts from the console; the platform does not hardcode a single superuser). A full audit log records configuration and security-relevant changes.

## Exporting Findings

JSON, Markdown, CSV, and PDF export, gated behind an export-specific permission distinct from ordinary read access. CSV and PDF paths carry tested defenses against formula-injection and markup-injection abuse. Every export carries the platform's branding, a generation timestamp, and an Investigation ID.

[FIGURE: reports-export-menu.png | The export panel on a completed investigation — JSON, Markdown, CSV, and PDF, each carrying platform branding and an Investigation ID.]

## Deployment

A Windows Inno Setup installer with a guided WinForms Setup Wizard (administrator account, AI backend, provider credentials with live "Test" buttons, network ports, install), and a Linux `.deb` package with an equivalent setup flow — both running the actual application as Docker Compose, plus a parallel Kubernetes/Kustomize deployment alternative for either platform.
