# HORIZON GRID — Release Notes

## v0.2.2 — Independent re-verification: 7 real bugs found and fixed

The v0.2.1 cancellation fix was independently re-verified rather than taken on faith: nine separate reviewers, each reading the real code fresh, re-proved the original before/after claim directly from git history, then tried hard to break the result — live browser automation of the full UI flow, every real scan profile and target type, every documented failure condition, a dedicated adversarial security pass, real concurrency races, and full regression of the rest of the application. That pass found four real defects in the scanner itself and three unrelated ones elsewhere. All seven are fixed, tested, and live-verified in this release; nothing here was assumed correct because a test suite stayed green.

**Port scanner:** an IPv6 scan previously never actually probed the target (missing a required nmap flag) yet reported a normal "clean" result — now fixed, and a real IPv6 scan correctly reports the target as up with its actual port states. A mistyped or unknown scan profile was silently accepted and also reported as a clean scan with no error anywhere — now rejected up front with a clear message. A malformed scan target could crash the request with a generic server error — now rejected cleanly like every other invalid request. A rare race during heavy concurrent use could let a scan's own completion silently overwrite a status something else had already recorded for it — now guarded, matching the same protection cancellation already had.

**Also fixed, found while regression-testing the rest of the app:** the Spamhaus threat-intelligence provider could misread a "your DNS resolver isn't allowed to query us" rejection as a positive malicious finding, which could flag a genuinely clean domain as malicious depending on your deployment's DNS setup. An admin losing a rare simultaneous "disable this account" race against another admin got a confusing generic session error instead of a clear explanation. An AI-generated assessment could occasionally cite specific evidence in its written summary while leaving the structured evidence list empty; it's now held to the same evidence-traceability standard the rest of the platform already enforces.

No manual upgrade step is required; re-running the installer on an existing install preserves your configuration and data as always.

## v0.2.1 — Port scanning: cancellation added

This is a small, targeted release. A forensic audit was requested of the Security Assessment Toolkit's Nmap port scanner after a report that it wasn't working correctly. The audit traced the entire pipeline — frontend, API, validation, scanner, subprocess execution, result parsing, UI — and found every stage already working correctly against real local targets. The one real, confirmed gap: **there was no way to cancel a scan once started.** That's now fixed — a "Cancel Scan" button genuinely stops the underlying scan process (not just its displayed status), survives a backend restart without getting stuck, and is covered by 5 new tests including a live in-flight cancellation. See the Backend Documentation's Security Assessment Toolkit chapter for the full technical detail, and the User Manual's Security Assessment section for what you'll actually see on screen.

No other behavior changed in this release; nothing about upgrading from v0.2.0 requires any extra step.

## What's new in v0.2.0

HORIZON GRID is the renamed, significantly extended release of this platform (previously "IOC Intelligence Platform"). If you're deciding whether this release matters to you, here's the short version:

**Five new AI backends (v0.2.0).** Kimi (Moonshot AI), DeepSeek, xAI (Grok), Mistral AI, and OpenRouter join the existing six (Ollama, Anthropic, Bedrock, Gemini, Groq, OpenAI), bringing the total to eleven — each with a real live model-discovery endpoint and a real live connection test, not a static placeholder. OpenRouter in particular gives access to hundreds of underlying models from many different companies through a single API. A real Windows installer packaging bug was also found and fixed in this release: every prior installer build silently bundled the local development Python environment, making it roughly 8x larger than it needed to be with zero functional benefit.

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
