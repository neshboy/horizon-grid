# HORIZON GRID — Hackathon Demo Guide

**Every Signal. One Operational Picture.**

A suggested 7–10 minute live-demo sequence, built around what the product actually does today (v0.2.4). Every step below drives a real feature — nothing here is scripted around a mockup or a canned response.

## 0. Before You Start

- The stack should already be running (`docker compose ... up -d` against the installed copy, or via the Windows/Linux installer). Confirm the Executive Dashboard loads real numbers (not zeros-because-nothing-ran) by having at least one completed investigation in the database beforehand.
- Have one AI backend configured and live-tested (Ollama if you want a fully offline demo with no API key, or any of the ten cloud backends if you want faster responses).
- Have at least one IOC provider credential configured beyond the no-key providers, so the demo shows real provider diversity rather than only the six providers that need no key at all (crt.sh, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Spamhaus, Internet Intelligence Collector).

## 1. The Problem, in One Sentence (30 seconds)

"No single threat-intel source sees everything, so analysts manually cross-reference five or six of them per indicator — and that manual cross-referencing is the first thing that gets skipped when the queue is long."

## 2. Executive Dashboard First, Not the Search Box (1 minute)

Open the dashboard before running anything new. Point at the seven live KPI tiles (active investigations, critical/high-risk IOC count, open case counts, average threat score, provider health percentage, 30-day AI success rate) and the Provider Health summary widget. Say explicitly: **every number on this screen is a real query result, not a hardcoded demo value** — that's a deliberate design constraint, not an accident, and it's worth saying out loud because judges have seen dashboards that fake this.

## 3. Run a Live Investigation (2–3 minutes)

Submit a real IOC from the global search bar — a known-benign IP (e.g. `8.8.8.8`) for a clean demo, or a known-malicious sample hash if you want the more dramatic result. Narrate what's happening as it streams in:

- Results arrive per-provider over Server-Sent Events, not all at once — the page doesn't block waiting for the slowest provider.
- Each provider result gets its own short AI summary as it lands, grounded only in that provider's data.
- Once every provider has reported, point out the two things that happen *before* the AI's final verdict: correlation (shared infrastructure, related hashes, MITRE ATT&CK techniques) and the deterministic scoring engine computing `overall_risk_score` / `confidence_score` / `malicious_probability` / severity from that evidence.
- Only then does the AI's consolidated Final Assessment appear — narrating the score it was handed, not inventing one.

## 4. Prove the AI Isn't the Source of Truth (1–2 minutes)

This is the single most differentiating moment in the demo. Open the Evidence Ledger and one of the verdict-interrogation tools ("Why?", "Challenge This Verdict", "Score Explanation", or "Intelligence Conflicts") and show that every AI claim traces back to a concrete, non-AI-generated fact. Then switch the active AI backend (AI Quickswitch, top of the home page) to a different provider and re-run the same investigation's assessment — the threat score stays identical because it was never computed by the AI in the first place; only the narration changes.

## 5. Provider Health (1 minute)

Navigate to the full Provider Health page. Show the four rolling windows (1h/24h/7d/30d) and point out the honesty rule that matters most here: a provider with zero real attempts in a window shows **Unknown**, never a false "Healthy" — and a provider correctly returning "nothing found" counts as a healthy outcome, not a failure. This is the page that would catch a Safe-Browsing failure being silently misread as "safe," which is exactly the kind of dashboard lie this design is built to prevent.

## 6. Security Assessment Toolkit (1–2 minutes, optional but strong)

From a completed investigation, trigger the Security Assessment Toolkit against a target you're explicitly authorized to scan (your own demo host is safest). Show the two required confirmations (retype the target, confirm authorization) before anything runs — call out that this is the one feature in the product that sends real active traffic, unlike every passive provider lookup, and that it's gated accordingly. Show a finding feeding back into the investigation's risk/confidence floor without inflating `malicious_probability` on its own.

## 7. Administration and RBAC (1 minute)

Open the Admin console. Show the three fixed roles (Admin/Analyst/Viewer) and that permission checks are enforced server-side on every route, not just hidden in the UI — a Viewer can see the dashboard and provider health but cannot run a scan or export. If more than one admin account exists, mention that multi-admin support is real, not a single hardcoded superuser.

## 8. Export and Close (30 seconds)

Export the investigation you ran (PDF or Markdown) and point out the HORIZON GRID branding, generation timestamp, and Investigation ID baked into the export — every report carries provenance, so a downstream reader can trace it back to a specific run.

## Closing Line

"Every number you saw today — the dashboard KPIs, the threat score, the provider health page — was computed live from real evidence, and every AI statement was checkable against that evidence. That auditability, not the AI itself, is the actual product."

## If Something Goes Wrong Live

- **A provider is down/rate-limited mid-demo:** that's fine — say so, and point at Provider Health showing the same thing honestly. It's a better demo moment than a fake all-green dashboard would be.
- **The configured AI backend fails:** the platform is designed to distinguish a real AI failure from a correct "no evidence to reason over" skip, with a disclosed fallback either way — narrate that distinction live if it happens rather than treating it as a demo failure.
