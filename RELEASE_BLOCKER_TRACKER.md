# Release Blocker Tracker
## IOC Intelligence Platform — Release Blocker Elimination Mission

**Source:** `FINAL_QA_REPORT.md` (2026-08-14 red-team pass), backend/frontend logs and source inspected live, application logs, automated test results.
**Status of this document:** updated as each blocker is investigated/fixed/retested. Do not mark FINAL STATUS as resolved until a real repro-then-fix-then-reproduce-again cycle has been completed, per the mission's Rule 3/"Fix → Test → Break → Test Again."

---

## BUG-01

- **SEVERITY:** P0
- **FEATURE:** Runtime provider/AI credential configuration (`Providers` page → Save)
- **REPRODUCTION STEPS:** `POST /api/v1/runtime/ioc-providers/{id}` with `{"credentials": {}}` (exactly what the settings UI sends if a user opens an already-configured provider's row and clicks Save without retyping the key — the UI only ever shows the existing value as a masked placeholder, never as the real input value).
- **EXPECTED RESULT:** the provider's existing credential is left untouched; `configured` stays `true`.
- **ACTUAL RESULT (before fix):** `configured` flips to `false`; the stored credential is gone; the next real investigation against that provider reports `"status": "not_configured"`. The stale `last_test_ok`/`last_test_message` remained visible, so the UI could show "Last test: OK" beside "Not configured." Also affected multi-field providers (Censys) — saving one field silently dropped the other — and `extra_config` had the identical unconditional-overwrite pattern (latent, unreachable from the current UI, but a landmine for the "+Add generic provider" feature).
- **ROOT CAUSE:** `backend/app/core/runtime_config.py`'s `upsert_ioc_provider()`/`upsert_ai_provider()` did `row.encrypted_credentials = encrypt_secret(json.dumps(credentials)) if credentials else ""` — a blind full-replace, not a merge, and treated an empty/falsy incoming dict as "clear everything" rather than "nothing changed this field."
- **AFFECTED FILES:** `backend/app/core/runtime_config.py`
- **PROPOSED FIX:** merge incoming `credentials` onto the existing decrypted set (`_merge_credentials()`), only overwriting fields actually present in the request; only overwrite `extra_config` when explicitly non-`None`.
- **FIX IMPLEMENTED:** yes (2026-08-14, this session, prior turn).
- **REGRESSION TEST:** `backend/app/tests/unit/test_runtime_config.py` (4 tests: empty-preserves, partial-preserves-untouched-field, new-field-added, full-replacement-still-works).
- **FINAL STATUS:** RESOLVED — but adversarial re-verification (independent agent) found the original fix was incomplete in two ways, both now closed:
  - **Race condition (real, new):** the read-modify-write had no row lock — two concurrent saves to the *same existing* provider (e.g. rotating one Censys field while another request updates the other) could each read the same pre-update credentials and the second commit would silently drop the first's change. This is the exact BUG-01 failure mode, just triggered by concurrency instead of a blank UI field. **Fixed:** added `.with_for_update()` to the existing-row SELECT in both `upsert_ioc_provider`/`upsert_ai_provider`. (Not addressed: two concurrent saves to a brand-new, never-configured provider can still race on the table's unique constraint — a visible `IntegrityError`, not silent data loss, judged out of scope given how narrow it is.)
  - **Test gap (real):** the original regression tests only exercised the pure `_merge_credentials()` helper against a fake object, never the real DB-backed `upsert_ioc_provider`/`upsert_ai_provider` functions — a wiring regression (e.g. merge result computed but never assigned) would have passed untouched. **Fixed:** added `backend/app/tests/integration/test_runtime_config_persistence.py` — 3 tests against the real Postgres: `test_upsert_ioc_provider_empty_save_preserves_credential_end_to_end`, `test_upsert_ai_provider_empty_save_preserves_credential_end_to_end`, and `test_upsert_ioc_provider_locks_the_row_it_reads` (captures the actual SQL via a SQLAlchemy event listener and asserts it contains `FOR UPDATE` — chosen after three timing/concurrency-based approaches each turned out to be flawed in a different way on live testing; see the test's own docstring for what was tried and why each failed). All three were verified genuinely fail-then-pass by deliberately reverting the fix, rerunning, then restoring it — not just written and trusted.

## BUG-02

- **SEVERITY:** P1
- **FEATURE:** AI final assessment generation (end of every IOC investigation)
- **REPRODUCTION STEPS:** run a real investigation against a real CVE with NVD data, active AI backend = Ollama (`llama3.2:3b`).
- **EXPECTED RESULT:** a real, evidence-grounded verdict.
- **ACTUAL RESULT (before fix):** Ollama emitted `final_verdict="malicious"` with `risk.malicious_probability=10-20` — internally self-contradictory, correctly rejected by `FinalAssessment`'s own Pydantic validator (already written specifically for this exact failure mode). With no retry, the entire assessment fell back to a generic "AI generation error," discarding an otherwise-complete investigation's conclusion, every time this (already-anticipated) failure mode occurred.
- **ROOT CAUSE:** `generate_final_assessment()` made exactly one LLM call and treated any exception (including the validator's own, already-anticipated rejection) as terminal.
- **AFFECTED FILES:** `backend/app/ai/service.py`
- **PROPOSED FIX:** bounded retry (2 attempts total), scoped specifically to `pydantic.ValidationError` — not caught generically, since retrying a Groq HTTP 429 rate-limit error immediately just consumes more of the same exhausted quota and fails again (verified live during the original fix).
- **FIX IMPLEMENTED:** yes (2026-08-14, this session, prior turn).
- **REGRESSION TEST:** `backend/app/tests/unit/test_ai_service.py::test_self_contradictory_verdict_is_retried_and_recovers`, `::test_non_validation_failure_is_not_retried`.
- **FINAL STATUS:** RESOLVED — adversarial re-verification (independent agent, full read of the retry loop) confirmed the exception scoping is correct (`ValidationError` retried, everything else fails fast after one attempt) with no off-by-one or broadening bug. No further changes needed.

## BUG-03

- **SEVERITY:** P1
- **FEATURE:** AI provider-data summarization (per-provider step of an investigation)
- **REPRODUCTION STEPS:** run a real investigation against CVE-2021-44228 (Log4Shell, CVSS 10.0 CRITICAL) with NVD enabled, on two different AI backends (Ollama local 3B, Groq hosted 70B).
- **EXPECTED RESULT:** correct identification as a critical/malicious vulnerability.
- **ACTUAL RESULT (before fix):** Ollama's provider summary reported `"what_it_knows"` as a single random nested CPE compatibility entry and called it **"benign."** Groq (after BUG-02's fix alone) called it **"unknown reputation, low confidence,"** risk score 20.
- **ROOT CAUSE:** `_provider_result_to_prompt()` dumped `result.data` completely raw and unbounded into the prompt. NVD's `configurations` field for this CVE runs to hundreds of nested CPE match entries — dozens of times longer than the actual signal (`verdict`, `cvss_score`, `cvss_severity`, `description`) — burying it under noise. The module's own docstring already states raw provider JSON should never reach a prompt unbounded; this was the one call site that didn't follow it.
- **AFFECTED FILES:** `backend/app/ai/service.py`
- **PROPOSED FIX:** `_prune_for_prompt()` caps any individual field's rendered length (800 chars) before serialization; short/scalar fields pass through untouched.
- **FIX IMPLEMENTED:** yes (2026-08-14, this session, prior turn).
- **REGRESSION TEST:** `backend/app/tests/unit/test_ai_service.py::test_prune_for_prompt_truncates_oversized_fields_only`.
- **FINAL STATUS:** RESOLVED, but the original fix introduced a NEW regression, now also fixed:
  - **New bug from the original fix (real, confirmed with live data):** adversarial re-verification found the 800-char cap fixed NVD but broke MITRE ATT&CK, whose `description` is the ONLY signal-bearing field (no separate short verdict/score field the way NVD has). Measured live against the real provider: technique descriptions run 562-1803 chars (`T1055`=934, `T1059`=1588, `T1027`=1803), so 800 chars silently chopped 3 of 5 sampled real techniques mid-sentence — the exact "AI loses the actual signal" failure this function exists to prevent, just from being too aggressive rather than not aggressive enough. AbuseIPDB's `reports` field has the same shape issue at lower severity (it has separate short `verdict`/`abuse_confidence_score` fields that survive, so only supplementary detail is lost, not the core verdict).
  - **Fix (round 1):** raised the uniform per-field cap from 800 to 4000. Verified against real data: NVD's `configurations` for the same CVE measures 67,721 chars, so it's still collapsed to under 6% of its size either way. MITRE's real descriptions (max measured 1803) now pass through fully intact.
  - **Round 1's fix caused a SECOND, real regression, caught live during the AI-switching regression pass, not by inspection:** re-running the fixed CVE lookup against Groq produced `ai_backend: None` (the generic fallback) again. Backend logs showed a genuine `HTTP 413 "Request too large"` — Groq's own error, "Requested 12402" tokens against its 12000 TPM limit, in a SINGLE request. Root cause: raising the SAME uniform cap for every oversized field also quadrupled `references` (7,851 chars, a bare list of URLs) alongside `configurations` — neither carries a verdict, so the cap raise paid a real cost (bigger prompt, real risk of exceeding a hosted API's per-request budget) for zero benefit on those two fields.
  - **Fix (round 2):** distinguish fields by type, not apply one number to everything. `str`-typed fields (prose, where MITRE's real signal lives) get the generous 2000-char cap; `list`/`dict`-typed fields (structural/repetitive — CPE match entries, URL lists, raw report objects, confirmed low-signal across every provider examined) keep the original tight 800-char cap regardless of provider. Verified live afterward: the same CVE against Groq again produced a correct provider summary ("CVSS score is 10.0, indicating a critical severity") with no 413; a subsequent final-assessment failure on Groq was confirmed via logs to be a genuine, expected `HTTP 429` per-minute quota limit from this session's own repeated testing (correctly NOT retried, per BUG-02's fix) — not a repeat of the size bug. A clean end-to-end run via Ollama (no rate limit) confirmed `malicious`/`high severity`/risk 90.
  - **Regression tests added:** `test_prune_for_prompt_does_not_truncate_realistic_single_field_signal` (prose case, corrected to a real measured length after an off-by-10 in the synthetic test string itself caused one transient local failure — not a product bug, fixed in the test), `test_prune_for_prompt_keeps_large_list_fields_tightly_capped` (list case, the round-2 regression).

## BUG-04 — RETRACTED (was based on an incorrect test methodology; not a real blocker)

- **ORIGINAL SEVERITY:** P1 — "the entire investigation export/report feature is completely non-functional."
- **WHY IT'S BEING RETRACTED:** the original finding tested `GET /api/v1/lookup/{id}/export?format=json|markdown|pdf|csv` directly via `curl` and got HTTP 404 for all four formats, concluding the whole feature was broken. Direct inspection of `frontend/components/dashboard/ExportMenu.tsx` (confirmed independently by two separate agents, then read personally, line by line) shows this was the wrong test: **`handleExportJson`/`handleExportMarkdown` never call the network at all** — they build a `Blob` client-side from the `assessment` object already loaded into the browser and trigger a direct download. Only `handleServerExport` (used by the "Export PDF"/"Export CSV" buttons) makes a real network call, via **POST** (not GET, which was also an incorrect assumption in the original repro) to the same path. So:
  - **JSON and Markdown export genuinely work today**, entirely client-side, with zero dependency on any backend route. My curl test measured an endpoint the real UI never calls for those two formats.
  - **PDF and CSV export correctly 404** and show "Export format not yet available" — but this is the **same, pre-existing, already-correctly-documented limitation** it always was (`user-10-export-reporting.md`, `user-12-health-troubleshooting.md` both already state PDF/CSV are not implemented while JSON/Markdown work — confirmed factually accurate by an independent documentation-cross-check agent). It is not a regression and was not caused by, or discovered as new by, this QA pass.
- **CORRECTED CONCLUSION:** there is no release-blocking export bug. Implementing real PDF/CSV backend support would be a new feature, not a bug fix — explicitly out of scope under this mission's "STOP ALL FEATURE DEVELOPMENT" rule, and not attempted.
- **FINAL STATUS:** RETRACTED — not a blocker. Removed from the release-blocking count.

## Incident-1 (not a product bug — testing-process mistake, tracked for completeness)

Reproducing/verifying BUG-01 against real (not disposable) VirusTotal and Censys credentials destroyed both, with no backup. Disclosed to the user at the time; user chose to accept the loss (VirusTotal) and approved clearing the fake replacement values (Censys) to a clean "not configured" state. Not re-litigated this mission — carried forward as known state.

## Security-1 (disclosed, not directly fixable by this agent)

Real, live, plaintext third-party secrets (including an AWS key pair) found in a repo-root `.env` file outside the ACL-protected production config path — `.gitignore` already correctly excludes it; rotation of the exposed keys is on the user. Not re-litigated this mission unless a fresh security sweep finds something new.
