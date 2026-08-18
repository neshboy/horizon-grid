# HORIZON GRID — Release Notes

## What's new in this release

HORIZON GRID is the renamed, significantly extended release of this platform (previously "IOC Intelligence Platform"). If you're deciding whether this release matters to you, here's the short version:

**A real operational picture, not just a search box.** A new Executive Dashboard gives you seven live metrics — active investigations, high-risk indicator counts, case load, average threat score, provider fleet health, and AI reliability — the moment you open the platform, backed by a real AI-generated (or plainly-labeled fallback) narrative explaining what the numbers mean. A new Provider Health page shows exactly which of your 18 configured intelligence sources are working right now, with real success rates and latency, not just "configured/not configured."

**A threat score you can actually audit.** Risk scoring is no longer 100% AI-generated. A new deterministic scoring engine computes the number from real provider evidence and correlation data, with documented weights and a version stamp on every assessment — the AI narrates the score, it cannot invent or override it. See the dedicated Threat Scoring guide for the exact formula.

**Two new intelligence sources.** urlscan.io and Google Safe Browsing are now built-in, with the same failure-safety guarantee every other provider follows: an unreachable or misconfigured source is always reported as unknown or an error, never mistaken for a "safe" result.

**Real fixes from real testing, not assumptions.** This release went through a genuine adversarial testing pass — including live load testing (a real concurrency bug in the Provider Health page was found and fixed, taking it from complete failure under load to a sub-2-second response), a real security review that found and closed a scoring-manipulation gap, and a real installer failure that was reported, root-caused, and fixed rather than worked around. The full findings are in the Final Release QA Report.

## Upgrading from a previous install

Re-running the installer on an existing install preserves your configuration, credentials, and all investigation/case/watchlist data — nothing about this release requires starting over. Internal identifiers (data folder location, database name) are unchanged from before the rename specifically so an upgrade is safe.

## Known limitations

- If you configure a local AI model (Ollama) as your active backend, the AI-generated executive summary can be slower under heavy *concurrent* load, since a single local model processes generation requests one at a time. This does not affect the accuracy of any number shown — only how quickly the AI's prose explanation of it appears — and does not affect the Dashboard's KPI tiles or the Provider Health page, both of which are plain database reads independent of AI backend choice.
- A minor, disclosed hardening item remains in the scoring engine's handling of a malformed numeric provider value (NaN/Infinity) — not exploitable by any currently-integrated provider, tracked as a future improvement.

## Verdict

**RELEASE READY WITH KNOWN LIMITATIONS.** See the Final Release QA Report for the full evidence behind this verdict.
