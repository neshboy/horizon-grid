# Testing and Quality Assurance

This appendix covers two distinct, non-overlapping bodies of evidence about the quality of HORIZON GRID (a self-hosted tool that looks up an **IOC** — Indicator of Compromise, e.g. an IP address, domain, URL, or file hash — against many third-party threat-intelligence sources at once, then uses a local or cloud AI model to summarize and correlate the results):

1. **Automated test suites** that exist in the source code today (backend unit + integration tests, frontend tooling), confirmed by direct source-code inspection.
2. **Manual/QA end-to-end validation history** — a full install-to-uninstall exercise of the actual compiled Windows installer, with a bug list, fixes, and a final release verdict.

These two bodies of evidence come from different inspection passes and are reported separately below. Where a number (test count, line count, bug count) is stated, it is attributed to its source and not blended with the other source to make the two agree.

## 1. Automated Test Suites

### 1.1 Backend

The backend (FastAPI/Python) test suite lives under `backend/app/tests/` and uses **pytest**, **pytest-asyncio**, **pytest-cov**, and **respx** (an HTTP-mocking library), all declared in `requirements.txt`.

| Layer | Location | File count | Approx. line count |
|---|---|---|---|
| Unit tests | `backend/app/tests/unit/` | 13 files | ~1,486 lines |
| Integration tests | `backend/app/tests/integration/` | 3 files | ~1,009 lines |

**Unit tests** cover: abuse.ch status mapping, AI schemas/validators, the AI service (including its no-evidence short-circuit guard, described below), `analysis_service` grounding logic, connection-test handlers, the correlation engine, the OSINT crawler's collector/rate-limit logic, the evidence builder, the IOC-type detector, pivot logic, the provider base class, and WHOIS/RDAP handling.

**Integration tests** are three named files: `test_lookup_flow.py`, `test_lookup_stream_persistence.py`, and `test_api_health.py`. They exercise the real lookup **orchestrator** (the component that fans a lookup out to every applicable data-source connector, called a "provider," concurrently) end-to-end, but against:

- **Fake `BaseProvider` subclasses** standing in for real providers — the real, network-hitting connectors (VirusTotal, AbuseIPDB, etc.) are never called in these tests;
- **respx-mocked HTTP** for any HTTP calls that do occur;
- a **real Redis** instance reached via docker-compose (these tests auto-skip if Redis is not reachable, rather than failing).

With that harness, the integration tests verify: concurrent (parallel, not sequential) fan-out across providers, isolation of a single provider's failure from the rest of the investigation, cache hit/miss behavior, and correct short-circuiting for providers that are unsupported for a given IOC type or not configured (missing API key).

[FIGURE: tech-08-testing-qa-diagram-1.png | Diagram: 1.1 Backend]

**Coverage percentage: Not measured.** `pytest-cov` is present as a declared dependency, but no coverage percentage, threshold, or report is asserted anywhere in the source. Only file counts, line counts, and which behaviors the tests exercise are confirmed above.

### 1.2 Frontend

The frontend (Next.js/React/TypeScript) declares a `"test": "vitest run"` script in `package.json` and lists Vitest as a devDependency — the test *runner* is configured.

**However, a repo-wide search for `*.test.*` / `*.spec.*` files under `frontend/` (excluding `node_modules` and `.next`) found zero test files.** Stated plainly: the frontend has test tooling wired up but no automated tests actually exist. This is a real, reportable gap in the current build — running `npm test` in the frontend would execute Vitest against an empty test set.

### 1.3 Summary

| Area | Framework(s) configured | Test files that actually exist | Coverage % |
|---|---|---|---|
| Backend unit | pytest, pytest-asyncio, pytest-cov | 13 | Not measured |
| Backend integration | pytest, respx, real Redis | 3 | Not measured |
| Frontend | Vitest (declared) | 0 | Not measured (no tests to measure) |

### 1.4 Regression Tests for the API-Key / AI-Backend Configuration Fix

A follow-on engineering pass fixed a bug where entering, saving, and testing provider and AI-backend API-key credentials in the Windows setup wizard was unreliable — every "Test Connection" button required a session token that had previously only ever been set deep inside the final "Start Installation" step, so a credential could never be tested before a full install completed, and never at all on a reconfigure run where the admin-account fields were left blank to preserve an existing account. The same pass added Groq as a fifth AI backend alongside Ollama, Anthropic, Bedrock, and Gemini, and introduced a live connection-test endpoint shared by all five backends.

That fix shipped with a new regression-test file, `backend/app/tests/unit/test_ai_connection_test.py`, adding **16 automated tests** that exercise the connection-test logic for all five AI backends using **mock/fake credentials only** — no real API key ever appears in the test suite — with **respx**-mocked HTTP responses standing in for the real provider APIs. The 16 tests cover, across the five backends: a successful ping, an invalid-key/401 response, a rate-limit/429 response, a model-not-found/404 response, a request timeout, and a network error, each expected to be reported as its own specific, honest failure category rather than a generic error. With this file added, the full backend automated suite was reported as **144 tests total, passing with no regressions** — a count reported by this follow-on pass itself, distinct from (and not necessarily contemporaneous with) the 13-file/~1,486-line source-inspection figures in Section 1.1 above.

## 2. Manual / QA End-to-End Validation History

Separately from the automated suites above, a full manual QA pass was performed against the actual compiled Windows installer (`IOC-Intelligence-Platform-Setup-0.1.0.exe`, version 0.1.0, ~62.6 MB final build, SHA256 `b32b1cc02205a0a53dda200d6bc336943a71df6b930cecd2dff45b28d84e81e8`), dated 2026-08-11, and documented in `FINAL_END_TO_END_TEST_REPORT.md`. This pass treated the build as never-before-tested and covered install, configuration, normal use, deliberate failure injection, a real Windows reboot, uninstall, reinstall, and a final independent clean install — exercised against the real installer and running containers, not source/dev-server shortcuts.

[FIGURE: tech-08-testing-qa-diagram-2.png | Diagram: 2. Manual / QA End-to-End Validation History]

### 2.1 Final Verdict

**READY FOR RELEASE.** The report's stated justification: every defect found — including the single most severe one (AI evidence-free fabrication, below) — was root-caused, fixed, covered by a regression test, and re-verified against the real running product. The three highest-severity findings (AI fabrication, LAN-exposed unauthenticated datastores, and silent data loss on client disconnect) were all closed with direct, live re-confirmation. Remaining open items are explicitly scoped-out unbuilt features (Report generation, PDF/CSV export, Timeline) and small-model AI-quality limitations, not incorrect or unsafe behavior.

### 2.2 Specific Bugs Found and Fixed

| # | Severity | Area | Description |
|---|---|---|---|
| 1 | High | AI safety | Fabricated `final_verdict: "highly_malicious"`, `malicious_probability: 92`, and invented "association with ransomware and trojans" for the EICAR test hash (`44d88612fea8a8f36de82e1278abb02f`) queried against zero real provider evidence — the small local model answered from its own pretrained knowledge instead of refusing. |
| 2 | High | Security | Postgres, Redis, Neo4j, and OpenSearch were all published on `0.0.0.0` (every network interface), reachable unauthenticated from another device on the same LAN — confirmed live via the machine's real LAN IP. OpenSearch had no authentication at all. |
| 3 | High | Data integrity | A client disconnect mid-investigation (simulated via `curl --max-time 3`) silently discarded all already-fetched provider results from the database, even though six providers (including a live Spamhaus hit) had already completed and been streamed to the client. |
| 4 | High | Recovery UX | The "Open Platform" shortcut was a bare `.url` file with no check for whether Docker/containers were running, no auto-start, no health wait — directly failing the requirement that the shortcut verify services, start if needed, and open the browser automatically. Caught by the real post-reboot test. |
| 4b | Medium | Regression in fix #4 | The launcher's own fix checked whether the platform was configured (via `Test-Path` on an ACL-locked `.env` file) *before* elevating privileges, which threw an access-denied error that read as "not configured" for an already-fully-configured install. |
| 5 | Medium | AI correctness | `evidence_ids`, `agreeing_providers`, and `disagreeing_providers` structured fields came back empty even when the AI's own prose cited a specific evidence ID or named a specific provider — because some schema fields lacked field descriptions, and the grounding filter only recognized providers that produced a correlation-graph edge (excluding the OSINT crawler provider, `internet_intelligence`, which does neither). |
| 6 | Medium | AI correctness | A provider's raw `"listed": false` boolean field was misread by the AI summarization step as "the IOC **is** listed," inverting a clean result into a false "has been blocked" claim. |
| 7 | Medium | Configuration | `docker-compose.yml` hardcoded `OLLAMA_BASE_URL` in the `environment:` block, which always overrides `env_file:`, so the setup wizard's AI Configuration page could write the correct value to `.env` but the platform would never actually use it. |
| 8 | Medium | Data/feature gap | `GET /api/v1/lookup/{id}` never returned the persisted relationship-graph data, so revisiting a completed investigation always showed an empty graph even though `CorrelationEdgeRecord` rows existed in Postgres. |
| 9 | Low | Installer UX | Five WinForms label-overlap/text-clipping bugs across the Administrator Account, AI Configuration, Threat Intelligence Providers, and Network Ports wizard pages. |
| 10 | Low | Installer UX | The account-creation failure path dumped a raw FastAPI/Pydantic validation-error JSON blob into the user-facing log and unconditionally printed "Setup complete." even when the admin account was never created. |
| 11 | Low | Cosmetic | Routine `docker compose` stderr progress output was rendered as a fake red "NativeCommandError" on every Start/Stop/Restart, even on full success. |
| 12 | Low | Branding accuracy | The landing page hardcoded "Claude" as the AI backend name regardless of which backend was actually configured. |

Bugs #1–12 (including 4b) were all root-caused, fixed, covered by a regression test where the fix was in backend Python code, rebuilt into a real running instance, and re-verified live against the actual product. Per the QA report, the regression tests added for these fixes brought the backend unit-test suite to **128/128 passing** at the time of that pass, plus the targeted stream-persistence integration tests — a count reported by the QA pass itself, distinct from (and not necessarily contemporaneous with) the 13-file/3-file source-inspection counts in Section 1 above. One named regression test is called out specifically: `test_completed_lookup_returns_rebuilt_correlation_graph`, added for bug #8.

### 2.3 Findings Documented but Not Fixed (Not Blocking Release)

| # | Severity | Area | Description |
|---|---|---|---|
| 13 | Info | AI quality | A detection-rule-generation call mapped MITRE ATT&CK technique `T1053` to "Create a Backdoor"; the real T1053 is "Scheduled Task/Job." Documented as a limitation of the bundled small local model (`llama3.2:3b`), not fixed. |
| 14 | Info | AI quality | The OSINT crawler provider occasionally surfaces keyword-matched but semantically unrelated content, and the AI summarization step sometimes repeated it as if it were a specific finding. Confidence/verdict fields stayed appropriately cautious in every case observed; judged a data-quality/polish issue rather than a safety-relevant fabrication. |
| 15 | Info | Feature scope | Report generation does not exist (backend field is permanently empty, no frontend UI). PDF and CSV export are wired to a backend export endpoint that returns a genuine 404; the frontend shows a graceful "not yet available" message rather than crashing (JSON and Markdown export do work end-to-end). Timeline does not exist anywhere in the codebase. All three are unbuilt features, not defects. |

### 2.4 Failure-Recovery Testing

Beyond the bug list, the QA pass deliberately injected failures and confirmed recovery:

- **AI backend down**: Ollama made genuinely unreachable (bad `OLLAMA_BASE_URL`, confirmed via `docker exec ... printenv`). Provider data stayed intact; AI-dependent fields honestly reported the failure (`final_verdict: "unknown"`, risk scores zeroed) rather than pretending to succeed. Reverting restored full functionality with no other intervention.
- **Database down**: stopping the Postgres container mid-request produced a real, fully logged HTTP 500 (not a silent failure or corruption); restarting Postgres restored functionality with prior data intact.
- **Bulk workflow**: eight IOCs processed sequentially (mixed types, one duplicate, one malformed value). The malformed entry was cleanly rejected with HTTP 422; the duplicate correctly created an independent investigation record (investigations are not deduplicated by design) while still benefiting from provider-level caching.
- **Real Windows reboot**: a genuine `Restart-Computer` was executed (with user approval) on the tester's own workstation; post-reboot, login, prior case/watchlist data, and a brand-new investigation all worked without any manual component restarts — this is the scenario that surfaced bugs #4 and #4b above.
- **Uninstall/reinstall**: both the keep-data and "Remove Everything" (`docker compose down -v`) uninstall paths, plus a reinstall and a fully independent final clean install, were each verified against real data (existing cases, watchlist entries, admin login all confirmed intact where expected).

### 2.5 Performance Observations (as measured in that pass)

Idle-baseline container memory was recorded as: backend ~96 MB, frontend ~39 MB, celery_worker ~695 MB, postgres ~38 MB, redis ~5 MB, neo4j ~553 MB, opensearch ~1.07 GB, all containers under 1% CPU at rest. After an eight-IOC bulk run, backend memory grew to ~104 MB (attributed to normal request handling, not a leak) and settled; no other container changed. A typical single-IOC investigation completed in 5–15 seconds end-to-end, with the OSINT crawler's multi-source fan-out consistently the slowest single component (~6 seconds). These are the specific figures reported by that one QA pass on that one machine, not a benchmark suite, and are not restated as general performance guarantees.

### 2.6 Live End-to-End Verification of the API-Key / AI-Backend Fix

Beyond the automated regression tests in Section 1.4, the same fix was also verified live against the real running product, start to finish: a full uninstall, a wipe of the database and Docker volumes, a fresh install, a complete run through the setup wizard, a fresh administrator-account bootstrap, and a live IOC investigation all passed. A genuine container-restart persistence test was performed separately: after a real container restart, admin login and all prior investigation records were confirmed to have survived intact. Finally, a live side-by-side comparison ran one identical IOC through both the Ollama and Groq AI backends to compare the quality of each backend's AI-generated output against identical underlying provider evidence. As with the rest of Section 2, these are the results observed in that specific verification pass, not a repeatable benchmark.

## 3. What This Means Together

The two bodies of evidence answer different questions and should not be conflated: Section 1 shows that the codebase has a real, if partial, automated regression safety net on the backend (13 unit-test files, 3 integration-test files exercising the orchestrator against fake providers plus real Redis) and none yet on the frontend. Section 2 shows that, independent of those automated tests, a full manual lifecycle pass against the actual shipped installer found and fixed 12 real defects — including one severe AI-safety issue (evidence-free fabrication of a malicious verdict) and one severe security issue (unauthenticated datastores reachable from the LAN) — and reached a "ready for release" verdict with two remaining categories of known, documented, non-blocking gaps: small-model AI-quality quirks, and three genuinely unbuilt features (Report generation, PDF/CSV export, Timeline).
