# Executive Summary

HORIZON GRID is a self-hosted threat-intelligence platform. An analyst gives it one indicator of compromise — an IP address, domain, URL, file hash, or CVE ID — and it queries 18 independent intelligence sources at once, correlates what they say about each other, computes a deterministic threat score from that evidence, and has an AI model explain the result in plain language, with every claim traceable back to the real data behind it. The product's own tagline states the design goal directly: **Every Signal. One Operational Picture.**

[FIGURE: dashboard-executive-overview.png | The Executive Dashboard — every KPI tile is a real query result against the live database, never a hardcoded display value.]

## What Problem Does It Solve?

No single threat-intelligence source sees everything. A file hash flagged by one antivirus engine might be ignored by another; an IP address on one blocklist might look unremarkable on the next. Getting a trustworthy read on an indicator normally means an analyst manually checking it against several independent sources, one browser tab at a time, and holding all of it in their head well enough to notice when two sources are describing the same underlying fact from different angles. That manual cross-referencing is the real cost of threat triage — and it is exactly the cost that gets skipped when the queue of indicators is long.

## What Does HORIZON GRID Do About It?

It collapses that workflow into a single search box. One submission fans out to every applicable provider in parallel; results correlate automatically; a fixed, versioned, non-AI scoring engine turns the combined evidence into a threat score before any AI is involved; and an AI model is then handed that score as a given fact to narrate, not a number it's free to invent. The platform tracks its own AI outcomes honestly — a real success, a correct decision to skip the AI when there's no evidence to reason over, or a disclosed failure with a deterministic fallback — never a fabricated result.

## Who Uses It?

A solo analyst can run the whole stack on one Windows or Linux machine behind a guided installer; a small security team can point several browsers at the same install and share cases, a shared watchlist ("the Basket"), and one live operational dashboard. Three fixed roles — Admin, Analyst, Viewer — are enforced on every backend route, not just hidden in the UI, so a broader audience (including a Viewer who should see the operational picture but not run scans or export data) can be given access safely.

## What Makes It Different?

Two things a typical dashboard tool doesn't do:

1. **The threat score is computed before the AI ever sees it, not by the AI.** A deterministic scoring engine (versioned, currently `1.0`) turns provider-verdict consensus and correlation-graph evidence into `overall_risk_score`, `confidence_score`, `malicious_probability`, and a severity band using a fixed, documented formula. The AI is handed that number as an input and narrates it — the platform re-validates the AI's own stated verdict against that number before saving anything, so the AI cannot quietly override the math.
2. **Every AI claim is checkable against real evidence, not just plausible.** An Evidence Ledger and a set of verdict-interrogation tools ("Why?", "Challenge This Verdict", "False Positive Check", "Score Explanation", "Intelligence Conflicts") let an analyst check any AI statement against the concrete, non-AI-generated facts the platform actually collected — rather than trusting a well-written paragraph on faith.

## Why It Matters

Analysts don't need another tool that produces a confident-sounding paragraph about an indicator — they need one that shows its work. HORIZON GRID's central design bet is that a security tool earns trust by being *auditable*: a fixed score computed the same way every time, an AI that narrates rather than decides, and a health/operational picture (Provider Health, Executive Dashboard) that is never allowed to show a hardcoded or invented number. That bet shaped every architectural decision documented in the rest of this submission.
