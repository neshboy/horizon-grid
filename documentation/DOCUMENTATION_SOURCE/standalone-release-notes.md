# 📰 HORIZON GRID — Release Notes

## 📋 Table of contents

- [v0.3.8 — DeepSeek backend fix](#v038---deepseek-backend-fix)
- [v0.3.1 – v0.3.7 — Windows Setup Wizard reliability fixes](#v031--v037---windows-setup-wizard-reliability-fixes)
- [v0.3.0 — Pentest Suite: scope-enforced assessments and gated real-exploit validation](#v030---pentest-suite-scope-enforced-assessments-and-gated-real-exploit-validation)
- [v0.2.5 — Security Assessment panel visibility and friction fixes](#v025---security-assessment-panel-visibility-and-friction-fixes)
- [v0.2.4 — Original visual identity and branding pass](#v024---original-visual-identity-and-branding-pass)
- [v0.2.3 — Mission-critical deployment hardening](#v023---mission-critical-deployment-hardening)
- [v0.2.2 — Independent re-verification: 7 real bugs found and fixed](#v022---independent-re-verification-7-real-bugs-found-and-fixed)
- [v0.2.1 — Port scanning: cancellation added](#v021---port-scanning-cancellation-added)
- [What's new in v0.2.0](#-whats-new-in-v020)
- [Upgrading from a previous install](#-upgrading-from-a-previous-install)
- [Known limitations](#-known-limitations-current-as-of-v038----unchanged-since-v023-through-every-later-release-in-this-document-including-the-pentest-suite-and-the-v031v038-wizardbackend-fixes-none-of-which-touched-anything-this-list-covers)
- [Verdict](#-verdict)

## v0.3.8 — 🤖 DeepSeek backend fix

Every AI call against the DeepSeek backend (per-provider summaries and the final assessment alike) failed outright with an HTTP 400 ("Thinking mode does not support this tool_choice"), live-confirmed investigating a real IP and a file hash. DeepSeek's current v4 models default their own "thinking" mode on, and DeepSeek's API rejects that combined with the forced tool-call this platform relies on for structured output — every other AI backend in this codebase uses the same forced-tool-call approach, so this was specific to how DeepSeek's own API validates that combination. Fixed by explicitly disabling thinking mode on this one call path, since this client only ever wanted the forced tool call's structured arguments, never a reasoning trace. Verified live: the same call path used for a real investigation now returns a normal result instead of failing.

No manual upgrade step is required; re-running the installer/package on an existing install preserves your configuration and data as always. Shared backend code — affects both platforms equally.

## v0.3.1 – v0.3.7 — 🪟 Windows Setup Wizard reliability fixes

Seven small, targeted releases fixed a cluster of real bugs in the Windows Setup Wizard, all rooted in the same underlying PowerShell scripting pitfall: a `.GetNewClosure()` scriptblock nested inside a wizard page's own invoked `Build` block cannot reliably see a bare `$script:`-scoped or top-level variable, which silently resolved to `$null`/an empty value instead of throwing an obvious error at the point of the mistake. Each release found and fixed the next site this pattern was hit live, working through the AI Configuration, Provider Configuration, and Summary/Install pages one at a time until a full deliberate sweep in v0.3.5 closed out every remaining instance:

- **v0.3.1** fixed an Ollama connection check crashing on a literal `null` response field (some Ollama versions/proxies return this when nothing is pulled yet), a Watchdog scheduled task that failed to register because `[TimeSpan]::MaxValue` doesn't serialize to a value Windows Task Scheduler accepts, and a misleading "Sign-in required" message shown on every AI/Provider "Test Connection" click during a fresh install — before the backend has even started, so there was nothing to sign in to yet.
- **v0.3.2 – v0.3.5** fixed the closure-scoping bug itself everywhere it was found: the post-install AI validation step, the "Start Installation" button, the per-provider "Test" button, the AI Configuration page's own "Test Connection" button, and finally a full sweep of every remaining `$script:`-scoped variable in the wizard to close out any instance not yet hit live.
- **v0.3.4** additionally closed a real chicken-and-egg gap: the AI Configuration page's "Test Connection" button always required an authenticated admin session, even on a fresh install where the backend was reachable but no admin account existed yet to sign in with. The backend now allows one unauthenticated test call, but only during the same bootstrap window already used for creating the very first admin account — a window that closes permanently the moment any account exists.
- **v0.3.6** fixed a regression introduced by v0.3.4's own fix — the new bootstrap check itself hit the identical closure-scoping bug, so a not-yet-started backend showed a raw "Unable to connect to the remote server" instead of the intended, clearer message.

None of these releases touched backend business logic, the database schema, or any IOC/AI-analysis behavior — every fix is confined to the Windows Setup Wizard's own PowerShell scripts. No manual upgrade step is required for any of them.

## v0.3.0 — ⚔ Pentest Suite: scope-enforced assessments and gated real-exploit validation

A new, standalone assessment subsystem for authorized security testing: declare a scope, add targets inside it, and run an automated discovery/enumeration/vulnerability-assessment pipeline against them, completely separate from the existing per-investigation Security Assessment Toolkit (which is untouched). Findings carry a confidence rating alongside severity, an AI Security Analyst can explain any finding or summarize a whole assessment in plain language, and administrators get a new, heavily gated capability: running a real Metasploit exploit module against a finding that has a matched CVE.

That last piece is real, not a simulation, and is gated accordingly: only administrators can reach it, only for a finding with a real CVE match, only after manually searching and picking one specific module, and real execution (as opposed to a safe, non-exploiting "check") requires an explicit confirmation on every single request. The target host is always locked to the finding's own real target regardless of what's entered in the options form. A dedicated adversarial security review ran before release specifically to try to break these guarantees — it found and closed one real confidentiality gap (exploit-attempt transcripts were briefly readable by non-admin roles) and hardened several other defense-in-depth points; every fix is covered by a new automated test. Two further real bugs were found and fixed during live testing against an actual running Metasploit instance (a message-encoding mismatch that silently made Metasploit look unreachable, and a UI dialog that could hide its own action buttons for a long option list) — see `CHANGELOG.md`'s `[0.3.0]` entry and `docs/PENTEST_SUITE.md` for full detail.

Explicitly verified, not just claimed: the backend test suite grew from 404 to 432 passing tests with zero regressions, and the feature was verified live end-to-end against a real, running Metasploit installation — a real module search by CVE, real module metadata, and a real non-exploiting check run against an authorized test target, honestly reporting what it actually found rather than a fabricated result either way. This subsystem currently requires the backend's Docker image to include Metasploit Framework at build time; a fresh install that hasn't finished that build degrades gracefully (the feature reports itself unavailable) rather than failing.

## v0.2.5 — 🛡 Security Assessment panel visibility and friction fixes

Two real bugs found and fixed while live-testing the Security Assessment Toolkit (the port scanner UI) against a fresh install. Both frontend-only: no backend logic, database schema, or API contract changed, confirmed by a full backend regression run (383 passed, 39 skipped, zero regressions) before and after.

The Security Assessment panel -- including its "Run" trigger form -- was silently disappearing with no explanation whenever an investigation's overall status ended up `FAILED`, even when every provider had succeeded, because it was incorrectly gated alongside panels that genuinely need a successful AI final assessment. It now renders whenever the investigation reached either terminal state. Separately, the target-confirmation field required retyping the exact IOC value with zero feedback on a mismatch, silently disabling the Run button on a single stray space -- replaced with a plain read-only target display, keeping the one authorization checkbox as the sole confirmation gate.

Both bugs were reproduced live against a real investigation and a real Nmap scan, not just caught by unit tests. No manual upgrade step is required; re-running the installer/package on an existing install preserves your configuration and data as always.

## v0.2.4 — 🎨 Original visual identity and branding pass

A professional branding + UI/UX pass across the entire application -- previously the product name and tagline ("Every Signal. One Operational Picture.") were barely visible anywhere in the running app. This release is presentation-only: no backend logic, database schema, authentication, IOC processing, AI/provider logic, port scanner logic, or admin permissions were modified, confirmed by a full backend regression run (383 passed, 39 skipped, zero regressions) and a clean frontend typecheck before and after.

New: an original visual identity (a CRT-phosphor teal-cyan primary color against a near-black anodized-steel shell), an original geometric logo mark that depicts the tagline itself (a horizon line with two signal nodes converging on one detection node), a six-state accessible operational-status language used consistently everywhere a status appears, a new `/about` page, and HORIZON GRID branding plus page numbering and Investigation IDs on every exported report (PDF/CSV/Markdown).

One real bug was self-discovered and fixed during this release's own screenshot QA pass: a React hydration mismatch on the new `/about` page, caused by reading client-only session state directly in the render body instead of after mount.

No manual upgrade step is required; re-running the installer/package on an existing install preserves your configuration and data as always.

## v0.2.3 — 🔁 Mission-critical deployment hardening

A dedicated reliability and security review for a one-time install at a remote, physically-inaccessible site with no developer access afterward. 18 real gaps were found and fixed — 2 of them self-discovered during the review itself. Every service now restarts automatically on a crash (previously only 2 of 8 did), a real dependency-aware health check (`/health/detailed`) backs a new 5-minute watchdog on both platforms, both platforms now auto-start at boot (a self-discovered bug meant Linux's systemd unit was never actually enabled, despite the unit file itself being correct), and both platforms got a real, tested database restore procedure plus scheduled nightly backups — previously only manual/pre-upgrade backups existed, with no restore procedure at all beyond a self-contradictory manual instruction.

On the security side: the SSRF guard on the local AI backend's outbound URL now covers the actual investigation call path (not just the connection-test button), login attempts are now rate-limited, the API's interactive documentation is disabled in production, and a request-body-size limit closes an unbounded-input gap. A page-crashing bug in the Relationship Graph's "View as list" toggle was found and fixed, along with a dead-code bug that meant provider network-error retries had no real effect for most providers.

Full backend suite: 380 passed, 39 skipped. A 3-hour soak test against the live stack completed cleanly — flat memory, zero spontaneous restarts. See the Mission-Critical Operations Manual and Mission-Critical Certification Report for complete detail, including honestly disclosed limitations (no off-site backup option, no disk-space alerting, a live elevated Windows install not performed this release).

No manual upgrade step is required; re-running the installer/package on an existing install preserves your configuration and data as always.

## v0.2.2 — 🔎 Independent re-verification: 7 real bugs found and fixed

The v0.2.1 cancellation fix was independently re-verified rather than taken on faith: nine separate reviewers, each reading the real code fresh, re-proved the original before/after claim directly from git history, then tried hard to break the result — live browser automation of the full UI flow, every real scan profile and target type, every documented failure condition, a dedicated adversarial security pass, real concurrency races, and full regression of the rest of the application. That pass found four real defects in the scanner itself and three unrelated ones elsewhere. All seven are fixed, tested, and live-verified in this release; nothing here was assumed correct because a test suite stayed green.

**Port scanner:** an IPv6 scan previously never actually probed the target (missing a required nmap flag) yet reported a normal "clean" result — now fixed, and a real IPv6 scan correctly reports the target as up with its actual port states. A mistyped or unknown scan profile was silently accepted and also reported as a clean scan with no error anywhere — now rejected up front with a clear message. A malformed scan target could crash the request with a generic server error — now rejected cleanly like every other invalid request. A rare race during heavy concurrent use could let a scan's own completion silently overwrite a status something else had already recorded for it — now guarded, matching the same protection cancellation already had.

**Also fixed, found while regression-testing the rest of the app:** the Spamhaus threat-intelligence provider could misread a "your DNS resolver isn't allowed to query us" rejection as a positive malicious finding, which could flag a genuinely clean domain as malicious depending on your deployment's DNS setup. An admin losing a rare simultaneous "disable this account" race against another admin got a confusing generic session error instead of a clear explanation. An AI-generated assessment could occasionally cite specific evidence in its written summary while leaving the structured evidence list empty; it's now held to the same evidence-traceability standard the rest of the platform already enforces.

No manual upgrade step is required; re-running the installer on an existing install preserves your configuration and data as always.

## v0.2.1 — 🛡 Port scanning: cancellation added

This is a small, targeted release. A forensic audit was requested of the Security Assessment Toolkit's Nmap port scanner after a report that it wasn't working correctly. The audit traced the entire pipeline — frontend, API, validation, scanner, subprocess execution, result parsing, UI — and found every stage already working correctly against real local targets. The one real, confirmed gap: **there was no way to cancel a scan once started.** That's now fixed — a "Cancel Scan" button genuinely stops the underlying scan process (not just its displayed status), survives a backend restart without getting stuck, and is covered by 5 new tests including a live in-flight cancellation. See the Backend Documentation's Security Assessment Toolkit chapter for the full technical detail, and the User Manual's Security Assessment section for what you'll actually see on screen.

No other behavior changed in this release; nothing about upgrading from v0.2.0 requires any extra step.

## 🤖 What's new in v0.2.0

HORIZON GRID is the renamed, significantly extended release of this platform (previously "IOC Intelligence Platform"). If you're deciding whether this release matters to you, here's the short version:

**Five new AI backends (v0.2.0).** Kimi (Moonshot AI), DeepSeek, xAI (Grok), Mistral AI, and OpenRouter join the existing six (Ollama, Anthropic, Bedrock, Gemini, Groq, OpenAI), bringing the total to eleven — each with a real live model-discovery endpoint and a real live connection test, not a static placeholder. OpenRouter in particular gives access to hundreds of underlying models from many different companies through a single API. A real Windows installer packaging bug was also found and fixed in this release: every prior installer build silently bundled the local development Python environment, making it roughly 8x larger than it needed to be with zero functional benefit.

**A real operational picture, not just a search box.** A new Executive Dashboard gives you seven live metrics — active investigations, high-risk indicator counts, case load, average threat score, provider fleet health, and AI reliability — the moment you open the platform, backed by a real AI-generated (or plainly-labeled fallback) narrative explaining what the numbers mean. A new Provider Health page shows exactly which of your 18 configured intelligence sources are working right now, with real success rates and latency, not just "configured/not configured."

**A threat score you can actually audit.** Risk scoring is no longer 100% AI-generated. A new deterministic scoring engine computes the number from real provider evidence and correlation data, with documented weights and a version stamp on every assessment — the AI narrates the score, it cannot invent or override it. See the dedicated Threat Scoring guide for the exact formula.

**Two new intelligence sources.** urlscan.io and Google Safe Browsing are now built-in, with the same failure-safety guarantee every other provider follows: an unreachable or misconfigured source is always reported as unknown or an error, never mistaken for a "safe" result.

**Real fixes from real testing, not assumptions.** This release went through a genuine adversarial testing pass — including live load testing (a real concurrency bug in the Provider Health page was found and fixed, taking it from complete failure under load to a sub-2-second response), a real security review that found and closed a scoring-manipulation gap, and a real installer failure that was reported, root-caused, and fixed rather than worked around. The full findings are in the Final Release QA Report.

## 📦 Upgrading from a previous install

Re-running the installer on an existing install preserves your configuration, credentials, and all investigation/case/watchlist data — nothing about this release requires starting over. Internal identifiers (data folder location, database name) are unchanged from before the rename specifically so an upgrade is safe.

## ⚠ Known limitations (current, as of v0.3.8 -- unchanged since v0.2.3 through every later release in this document, including the Pentest Suite and the v0.3.1–v0.3.8 wizard/backend fixes, none of which touched anything this list covers)

- No automated host-disk-space alerting, and no retention/cleanup job for ever-growing investigation tables.
- No off-host/off-site backup copy option — backups are local-disk-only, which does not protect a genuinely remote site against the host/disk itself failing.
- A narrow DNS-rebinding TOCTOU window remains on the SSRF check (validates a resolution snapshot; the real outbound call re-resolves independently afterward).
- Neo4j and OpenSearch remain fully provisioned (~1.5–2 GB RAM) with zero actual application traffic — a real resource cost with no current benefit, flagged as an open product question rather than resolved unilaterally.
- No frontend test infrastructure exists (`vitest` is wired into `package.json`, but zero test files exist anywhere in the tree).
- A live, elevated, end-to-end Windows installer run was not performed for v0.2.3 (requires an interactive UAC prompt); the installer's packaged contents were verified directly instead.
- If you configure a local AI model (Ollama) as your active backend, the AI-generated executive summary can be slower under heavy *concurrent* load, since a single local model processes generation requests one at a time. This does not affect the accuracy of any number shown, and does not affect the Dashboard's KPI tiles or the Provider Health page, both plain database reads independent of AI backend choice.
- A minor, disclosed hardening item remains in the scoring engine's handling of a malformed numeric provider value (NaN/Infinity) — not exploitable by any currently-integrated provider, tracked as a future improvement.

## 🏁 Verdict

**MISSION-CRITICAL READY WITH DOCUMENTED LIMITATIONS** (established as of v0.2.3, unchanged through every release since, up to and including the current v0.3.8). See `MISSION_CRITICAL_CERTIFICATION_REPORT.md` for the full evidence behind this verdict; none of the v0.2.4 branding pass, the v0.2.5 UI fixes, the v0.3.0 Pentest Suite addition, or the v0.3.1–v0.3.8 wizard/backend fixes touched anything this verdict covers.
