# FINAL QA REPORT — Red-Team Regression Pass
## IOC Intelligence Platform

**Test date:** 2026-08-14
**Tester:** Automated QA/red-team pass (Claude Code), treating the current build as potentially buggy despite prior QA passes
**Scope:** Aggressive, systematic bug hunt against the live, already-installed application — credential lifecycle, provider/AI runtime switching, the investigation engine, security, persistence, documentation accuracy, and automated test coverage. Explicitly did **not** wipe the environment at the start, per instruction.
**Related:** `documentation/FINAL_QA_REPORT.md` (an earlier, separate "Super QA" pass, 2026-08-12 — untouched by this pass); `LAN_DEPLOYMENT_QA_REPORT.md` and `LAN_REGRESSION_TEST_REPORT.md` (this session's earlier LAN-deployment work).

---

## Executive Summary

Three real, previously-unknown, reproducible bugs were found and **fixed live**, each verified with a before/after empirical retest against the running application — not a code read, an actual repro:

1. **P0 — Saving a provider/AI credential without retyping every field silently destroyed the existing, working credential.** Reproduced against real, previously-configured providers (with real-world consequences — see Incidents below), root-caused to a blind-overwrite bug in `runtime_config.py`, fixed with merge-not-replace semantics, verified with disposable test credentials afterward.
2. **P1 — The final AI assessment could fail completely and silently** whenever the model emitted an internally self-contradictory verdict (a real, reproducing failure mode the schema's own validator was already built to catch, but nothing ever retried after catching it). Fixed with a scoped retry.
3. **P1 — Provider data fed to the AI was not size-bounded**, so a large nested field (confirmed with NVD's `configurations` array for a real CVE) buried the actual severity signal under noise — reproduced on **two different AI backends** (a local 3B model and a hosted 70B model), both calling a CVSS 10.0 CRITICAL remote-code-execution vulnerability "benign" or "unknown risk." Fixed by bounding individual field length before prompt construction.

A fourth, more severe finding was **not code-fixed** this pass because it is a missing feature, not a small bug: **the entire investigation export/report-download feature is completely non-functional** — confirmed via the live OpenAPI schema that no `/export` route exists anywhere in the backend, for any format (JSON, Markdown, PDF, CSV alike). This is worse than previously documented (which claimed JSON/Markdown worked). See Bug List, BUG-04.

Two real incidents happened during this pass, both disclosed to the user as they occurred: this agent's own reproduction/verification steps destroyed two real, previously-working third-party API credentials (VirusTotal, Censys) with no way to recover them, and a parallel security sweep found a repo-root `.env` file with real, live secrets (including an AWS key pair) sitting in plaintext outside the ACL-protected production config location. Both are detailed below.

All 166 backend unit tests pass (159 pre-existing + 7 new regression tests added this pass, one per confirmed bug). Documentation was cross-checked against the current code by an independent agent pass and two real inaccuracies were found and corrected at the source.

## Verdict

# NOT RELEASE READY

The credential-wipe bug (BUG-01) is exactly the failure class this mission was written to hunt — "Test Connection: SUCCESS, but real investigation: API KEY NOT PROVIDED" — except worse, since it destroys an *already-working* configuration via an ordinary UI interaction with no confirmation step. It is now fixed and verified, but its mere existence, plus the completely non-functional export feature (a documented, UI-exposed capability with zero working backend route), plus the plaintext-secrets exposure, are each independently disqualifying per this mission's own severity rules ("a credential/security leak means NOT RELEASE READY"). Fix BUG-04 (or explicitly descope it) and rotate the exposed third-party credentials before shipping.

---

## 1. Build Tested

Live, already-installed application at `C:\Program Files\IOC Intelligence Platform`, backend/frontend/celery containers rebuilt three times during this pass to pick up fixes (final rebuild: backend `app-backend-1` image built from the source tree with all three fixes applied). Not a fresh install — this pass deliberately tested the environment as it already existed.

## 2. Environment

- Docker Compose stack: `postgres`, `redis`, `neo4j`, `opensearch`, `backend`, `celery_worker`, `celery_beat`, `frontend` — all healthy throughout, restarted once mid-pass to verify persistence (see §8).
- AI backends with real, working credentials at test start: `ollama` (local, `llama3.2:3b`) and `groq` (hosted, `llama-3.3-70b-versatile`). `anthropic`, `bedrock`, `gemini` had no usable credential.
- IOC providers with real, working credentials confirmed at test start: `otx`, `nvd`, `censys` (destroyed during this pass, see Incidents), `abuseipdb` (already broken — see §6), `virustotal` (destroyed during this pass), `groq`.

## 3. Feature Inventory (Phase 0)

- **AI backends (5):** Ollama, Anthropic (Claude), Amazon Bedrock, Google Gemini, Groq — confirmed against `AI_BACKENDS` in `runtime_config.py`.
- **IOC providers (16):** VirusTotal, AbuseIPDB, OTX, URLhaus, ThreatFox, MalwareBazaar, CrtSh, NVD, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Hybrid Analysis, Spamhaus, PhishTank, Censys, and the Internet Intelligence Collector — confirmed against the live provider registry.
- **Runtime architecture:** every credential/enabled-state change persists to Postgres (`provider_runtime_configs`) and takes effect on the *next* investigation via a per-investigation `ContextVar` snapshot — no process restart required, by design, and confirmed working (see §5).

## 4. Bug List

### BUG-01 — P0 — Saving a provider/AI credential with an empty or partial field silently destroys the existing credential

**Component:** `backend/app/core/runtime_config.py`, `upsert_ioc_provider()` / `upsert_ai_provider()`
**Reproduction:** `POST /api/v1/runtime/ioc-providers/{id}` with `{"credentials": {}}` (exactly what the settings UI sends if a user opens an already-configured provider's row and clicks Save without retyping the key — the masked existing value is shown only as a placeholder hint, never as the real input value). `configured` flips from `true` to `false`; the credential is gone.
**Compounding factor:** the stale `last_test_ok`/`last_test_message` ("Connected. Key is valid.") remains visible even after the wipe, so the UI can show "Last test: OK" directly beside "Not configured."
**Also affected:** partial multi-field providers (Censys needs both `personal_access_token` and `organization_id`) — saving only one silently dropped the other, and `extra_config` had the identical unconditional-overwrite pattern (latent, since the frontend never currently sends it, but a landmine for the "+Add generic provider" feature).
**Downstream effect (confirmed live):** the next real investigation reports the provider as `"status": "not_configured"` — this is the exact "Test Connection: SUCCESS → real investigation: API KEY NOT PROVIDED" class this mission was written to find, except triggered by an ordinary Save on an *already-working* provider rather than a fresh setup.
**Fix:** `_merge_credentials()` merges incoming fields onto the already-stored, decrypted set rather than replacing it wholesale; only fields actually present in a request change. `extra_config` now only overwrites when explicitly provided (`is not None`).
**Verified:** reproduced and fixed on disposable test credentials (not real ones, after the incident below) — empty-save preserves a single-field credential; partial multi-field save preserves the untouched field. Regression tests added: `test_runtime_config.py` (4 tests).

### BUG-02 — P1 — Final AI assessment fails completely and silently on a known, already-anticipated model failure mode

**Component:** `backend/app/ai/service.py`, `generate_final_assessment()`
**Reproduction:** ran a real investigation against a real CVE with NVD data; Ollama (`llama3.2:3b`) emitted `final_verdict="malicious"` with `risk.malicious_probability=10-20` — a self-contradictory pair that `FinalAssessment`'s own Pydantic validator (already written specifically for this exact failure mode, per its own docstring) correctly rejects. With no retry, the *entire* assessment fell back to a generic "AI generation error," discarding an otherwise-complete investigation's conclusion.
**Fix:** added a bounded retry (2 attempts total), scoped specifically to `pydantic.ValidationError` — not caught generically, since a live retest showed that retrying a Groq HTTP 429 rate-limit error immediately just consumes more of the same exhausted quota and fails again (see Phase 20's "no runaway requests on rate limit" requirement). Non-validation failures now fail fast after one attempt, as before.
**Verified:** 3 consecutive runs against the same CVE after the fix all produced a real verdict, no fallback. A rate-limited Groq call correctly fails after exactly one attempt, not two. Regression tests added: `test_ai_service.py` (2 tests).

### BUG-03 — P1 — Unbounded raw provider data in the AI prompt buries the actual severity signal, causing wrong verdicts on two different AI backends

**Component:** `backend/app/ai/service.py`, `_provider_result_to_prompt()` (feeds `summarize_provider()`)
**Reproduction:** NVD's real data for CVE-2021-44228 (Log4Shell, CVSS 10.0 CRITICAL) includes a `configurations` field with hundreds of nested CPE compatibility entries — dozens of times longer than the actual signal (`verdict`, `cvss_score`, `cvss_severity`, `description`). Dumped raw into the prompt, this buried the severity so completely that:
  - Ollama's provider summary reported `"what_it_knows"` as a single random nested CPE match entry, and the final assessment called it **"benign."**
  - After fixing BUG-02, Groq's final assessment called it **"unknown reputation and low confidence"** with a risk score of 20 — for the same CRITICAL RCE.
This module's own docstring already states raw provider JSON should never reach a prompt unbounded — this was the one call site (`summarize_provider()`, not `generate_final_assessment()`) that didn't follow it.
**Fix:** `_prune_for_prompt()` caps any individual field's rendered length (800 chars) before serialization; short/scalar fields (the ones actually carrying a verdict) pass through untouched, only oversized nested structures collapse to a truncation note.
**Verified:** after the fix, the same CVE's provider summary correctly states "CVSS score is 10.0, indicating a critical severity," `threat_level: critical`, and both Ollama and Groq's final assessments correctly call it `malicious`/`critical` with risk scores 87-97. Regression test added: `test_ai_service.py::test_prune_for_prompt_truncates_oversized_fields_only`.

### BUG-04 — P1 (feature-level, not code-fixed this pass) — The entire investigation export/report feature is completely non-functional

**Component:** frontend `ExportMenu.tsx` calls `GET /api/v1/lookup/{id}/export?format=...`; **this route does not exist anywhere in the backend**, confirmed via the live OpenAPI schema (`/api/v1/openapi.json` lists no `/export` path at all, in any router).
**Impact:** every export format — JSON, Markdown, PDF, CSV — returns HTTP 404. This contradicts prior documentation, which claimed JSON/Markdown "genuinely work" (PDF/CSV were already correctly documented as unimplemented). The feature is advertised in the UI and in the user manual and does nothing.
**Why not fixed this pass:** implementing this is a real feature build (serialization format, template design, an actual new endpoint), not a small root-cause correction, and deserves the user's input on scope/format rather than a unilateral implementation under time pressure. Flagged here per Phase 39's "if it cannot safely be fixed, clearly report it as a known limitation" — reported prominently rather than fixed or hidden.

### Minor findings (not fixed, low severity)

- **P3 — Wording imprecision in the "no usable data" fallback assessment.** When all providers in an investigation are disabled/erroring (not literally "not configured"), the deterministic fallback message still says "not configured" for all cases. Cosmetic; the verdict itself is still correct.
- **P4 (documentation, fixed) — Gemini's auth mechanism was documented backwards** in two chapters (`backend-04-provider-and-ai-integrations.md`, `dev-04-provider-and-ai-architecture.md`): claimed the API key is sent as a `?key=...` query parameter, when the code deliberately sends it via the `x-goog-api-key` header specifically *to avoid* that (httpx logs full URLs at INFO level). Corrected at the source.
- **P4 (documentation, fixed) — Providers page tab count.** `user-06-providers.md` said "three tabs"; the page has four (the LAN-deployment work added a "Network Access" tab that was never documented). Corrected at the source.
- **P4 (test-coverage gap, addressed) — Zero unit tests existed for `runtime_config.py`** before this pass despite it being the security-relevant module owning credential encryption/merge logic. Added `test_runtime_config.py`.

## 5. Provider Runtime Switching (Phase 8-9)

Confirmed live: disabling a provider mid-session makes it correctly report `status: "disabled"`; a provider with a broken credential correctly reports `status: "error"` with the real upstream error; re-enabling works immediately, no restart. These three states (`disabled` / `error` / `not_configured`) are correctly distinguished from each other in the actual data, matching Phase 9's explicit requirement that "provider unavailable" must never be presented as "provider found nothing."

## 6. AI Provider Switching (Phase 10-13)

Live-switched the active AI backend `ollama → groq → ollama` mid-session, running a real analysis after each switch — confirmed correct backend/model attribution every time, zero restart, zero credential leakage between backends (each stored independently in `provider_runtime_configs`). See BUG-02/BUG-03 for the correctness issues found and fixed along the way.

## 7. Security (Phase 24-27)

A dedicated pass (independent agent + direct verification) found:

- **P0 — Real, live, plaintext third-party secrets** (including an AWS access key/secret pair) in a repo-root `.env` file outside the ACL-protected production config path. Disclosed to the user; `.gitignore` already correctly excludes it from any future commit (no `.git` exists yet); rotation of the exposed keys is outside this agent's ability and is on the user.
- **P3 — Weak hardcoded default DB/graph credentials** (`POSTGRES_PASSWORD=ioc`, `NEO4J_PASSWORD=changeme-neo4j`) used as-is in the live `.env`.
- **P4 — `JWT_SECRET_KEY` still the literal `.env.example` placeholder** in that same file — notable because it also derives the Fernet key encrypting every stored provider credential.
- **Clean:** no hardcoded secrets in source, no `.git` history to leak from, no credential leakage in Docker logs, no raw stack traces or connection strings in API error responses, no secrets in the served frontend JS bundle, correct RBAC-permission gating on all runtime-config/audit endpoints, and the CORS/auth boundary from the LAN-deployment pass (see `LAN_DEPLOYMENT_QA_REPORT.md`) remains intact and unaffected by this pass's changes.

## 8. Persistence (Phase 21)

Snapshotted row counts, restarted `postgres`, `backend`, `redis`, and `frontend` containers, and confirmed an exact match afterward (1 user, 2 cases, 41 lookups, 21 provider configs), plus confirmed login and `/health` both work immediately post-restart with no reconfiguration needed.

## 9. Automated Tests (Phase 36)

```
166 passed in 1.42s
```
159 pre-existing + 7 new regression tests (one dimension per confirmed bug): `test_runtime_config.py` (credential-merge, 4 tests), `test_ai_service.py` (retry scoping, 2 tests; prompt pruning, 1 test).

## 10. Documentation (Phase 35)

Independent agent cross-check against current code (all user-manual chapters, source-code docs, backend docs) found the codebase's documentation "unusually rigorous and self-verifying" overall, with two genuine, now-corrected mismatches (Gemini auth mechanism, provider-page tab count — see Bug List). All 38 referenced screenshots confirmed to exist; AI/IOC provider lists, live-switching claims, and Test Connection semantics all confirmed accurate against the real code.

## 11. Incidents During This Pass (both disclosed as they happened)

1. **Reproducing BUG-01 against the real VirusTotal provider** (rather than a disposable test credential) destroyed its actual, working, previously-configured API key. No backup existed. Disclosed immediately; user chose to accept the loss and re-enter it later.
2. **Verifying BUG-01's fix against the real Censys provider** made the same mistake a second time, overwriting a real credential with fake test values before a safety check blocked the cleanup attempt and flagged the real loss had already happened one step earlier. Disclosed immediately; user approved clearing the fake values to a clean "not configured" state.

Both are recorded here in the interest of the mission's own "I want to know what did NOT survive" instruction — these were testing-process mistakes (using real credentials for destructive-style reproduction instead of disposable ones), not defects in the product.

## 12. Not Covered This Pass

- **Genuine second-device/browser UI testing.** All functional testing was via direct API calls (more precise for root-causing the bugs found) rather than a driven browser session; no Puppeteer/Playwright pass was run this time. UI/UX phases (31-32) and the literal click-through of Phase 41's journey are therefore unverified at the UI layer, though every step's underlying API behavior was verified directly.
- **Concurrent-investigation isolation (Phase 17)** and **runtime-config-change-mid-investigation (Phase 18)** were not explicitly tested this pass — the `ContextVar`-per-investigation-snapshot architecture (see `runtime_context.py`) is designed specifically for this, and was already reviewed as part of BUG-01's root-cause trace, but no live concurrent-request test was run.
- **Windows installer / clean-install cycle** — not re-run this pass; see `LAN_DEPLOYMENT_QA_REPORT.md` for this session's earlier, separate installer verification.
