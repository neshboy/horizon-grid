# IOC Intelligence Platform — Bug Triage (Enterprise Release Certification)

This document compiles every distinct finding with a real severity (P0-P4) from `ENTERPRISE_QA_PHASE1_FINDINGS.md` (the full Phase 1 QA pass: regression baseline, 21 test-dimension findings, adversarial verification) plus the findings and fixes reported directly and separately (not yet written to any file) on 2026-08-16. Pure `info` / no-defect-found / `not_tested` entries are intentionally excluded — those belong in the certification report's "Known Limitations" / "Confirmed Working" sections, not bug triage.

Three items in the source findings document (`#31`, `#32` in the "Low-Stakes Findings" section, and `#75`) are template/placeholder artifacts (title `"t"`, description `"d"`/`"t"`, dimension `"test"`) with no substantive content and were excluded as document noise, not genuine QA findings.

Several bugs below (BUG-006, BUG-039, BUG-040, BUG-041, BUG-045, BUG-046, BUG-047) were originally discovered and disclosed as open findings during Phase 1 testing, and were subsequently fixed, regression-tested where noted, and deployed to the live app on 2026-08-16 — this is reflected by merging the Phase 1 finding's reproduction/root-cause detail with the fix information reported separately. BUG-051, BUG-052, BUG-053, and BUG-054 do not appear in the Phase 1 findings document at all — they were found during separate network/load/large-data and Windows-installer testing on 2026-08-16 and are transcribed here for the first time.

BUG-055 through BUG-060 come from a final, unscripted adversarial red-team round run later on 2026-08-16, specifically scoped to hunt for NEW interaction effects between the same-day fixes (BUG-006/BUG-039/BUG-041/BUG-051's request-correlation-ID middleware, orphaned-lookup recovery sweep, and the Security Assessment Toolkit) rather than re-covering ground already in BUG-001 through BUG-054. Six lenses each reported findings; the five rated P0-P2 were independently re-verified by a second agent before being included here. One P2 finding from that round ("Aborted/cancelled SSE lookup requests still run to full completion server-side") was independently re-tested and refuted — live re-reproduction showed the opposite: Starlette's `StreamingResponse` does cancel the SSE generator on a real client disconnect in the general case — so it is excluded from this document as not a genuine defect. That same refutation pass surfaced a real, narrower, opposite-failure-mode bug as a byproduct (an early-disconnect race that leaves a lookup stuck RUNNING), which is included below as BUG-060 with a caveat on its single-source provenance. Two of the six lenses independently discovered the same underlying defect (no orphaned-run recovery for `SecurityAssessmentRun`); those are merged into a single entry, BUG-056, rather than duplicated.

## Table of Contents

| ID | Severity | Title | Status |
|---|---|---|---|
| [BUG-001](#bug-001-login-response-time-leaks-account-existence-via-a-26x-timing-side-channel) | P2 | Login response time leaks account existence via a ~26x timing side-channel | OPEN (disclosed, not fixed) |
| [BUG-002](#bug-002-no-rate-limiting-backoff-or-account-lockout-on-authlogin) | P2 | No rate limiting, backoff, or account lockout on /auth/login | OPEN (disclosed, not fixed) |
| [BUG-003](#bug-003-set_user_active-overcounts-audit-log-entries-on-no-op-calls) | P2 | set_user_active() overcounts audit log entries on no-op calls | OPEN (disclosed, not fixed) |
| [BUG-004](#bug-004-last-admin-protection-lock-serializes-all-admin-console-mutations-platform-wide) | P2 | Last-admin-protection lock serializes all admin-console mutations platform-wide | OPEN (disclosed, not fixed) |
| [BUG-005](#bug-005-concurrent-ioc-investigations-degrade-sharply-in-latency-confounded-run) | P3 | Concurrent IOC investigations degrade sharply in latency (confounded run) | OPEN (disclosed, not fixed) |
| [BUG-006](#bug-006-oversized-ioc-value-crashes-lookupstream-generator-lookup-stuck-running-forever) | P1 | Oversized IOC value crashes /lookup/stream generator, lookup stuck RUNNING forever | FIXED (deployed + regression tested) |
| [BUG-007](#bug-007-final-assessment-generation-exhausts-its-one-retry-and-falls-back-to-unavailable-on-a-healthy-backend) | P2 | Final-assessment generation exhausts its one retry and falls back to "unavailable" on a healthy backend | OPEN (disclosed, not fixed) |
| [BUG-008](#bug-008-stale-last-test-failed-status-persists-on-the-ai-providers-panel-for-a-healthy-backend) | P3 | Stale "last test: failed" status persists on the AI Providers panel for a healthy backend | OPEN (disclosed, not fixed) |
| [BUG-009](#bug-009-get-apiv1providershealths-configured-field-is-stale-vs-runtime-db-state) | P3 | GET /api/v1/providers/health's `configured` field is stale vs. runtime DB state | OPEN (disclosed, not fixed) |
| [BUG-010](#bug-010-gemma22b-asserts-100-malicious_probability-far-beyond-cited-evidences-confidence) | P2 | gemma2:2b asserts 100% malicious_probability far beyond cited evidence's confidence | OPEN (disclosed, not fixed) |
| [BUG-011](#bug-011-single-ai-generated-provider_summary-is-internally-self-contradictory) | P2 | Single AI-generated provider_summary is internally self-contradictory | OPEN (disclosed, not fixed) |
| [BUG-012](#bug-012-agreeing_providersdisagreeing_providers-never-populated-despite-naming-providers-in-prose) | P2 | agreeing_providers/disagreeing_providers never populated despite naming providers in prose | OPEN (disclosed, not fixed) |
| [BUG-013](#bug-013-incoherent-overall_risk_score50-alongside-cleanbenignlow-probability-fields) | P3 | Incoherent overall_risk_score=50 alongside clean/benign/low-probability fields | OPEN (disclosed, not fixed) |
| [BUG-014](#bug-014-misleading-narrative-conflation-of-unrelated-osint-noise-with-a-malicious-verdict) | P3 | Misleading narrative conflation of unrelated OSINT noise with a malicious verdict | OPEN (disclosed, not fixed) |
| [BUG-015](#bug-015-log4shells-cisa-kev-ransomwaredeadline-evidence-silently-dropped-from-the-final-assessment) | P2 | Log4Shell's CISA KEV ransomware/deadline evidence silently dropped from the final assessment | OPEN (disclosed, not fixed) |
| [BUG-016](#bug-016-8888-lands-on-benign-with-an-incoherent-elevated-risk-score-driven-by-coincidental-osint-noise) | P3 | 8.8.8.8 lands on 'benign' with an incoherent, elevated risk score driven by coincidental OSINT noise | OPEN (disclosed, not fixed) |
| [BUG-017](#bug-017-2030113777-test-net-3-gets-a-confident-benign-verdict-despite-zero-evidence-plus-a-corrupted-json-artifact) | P3 | 203.0.113.77 (TEST-NET-3) gets a confident 'benign' verdict despite zero evidence, plus a corrupted JSON artifact | OPEN (disclosed, not fixed) |
| [BUG-018](#bug-018-mitre_mappings-is-empty-in-every-final_assessment-including-textbook-cve-cases) | P4 | mitre_mappings is empty in every final_assessment, including textbook CVE cases | OPEN (disclosed, not fixed) |
| [BUG-019](#bug-019-long-legitimate-target-string-causes-an-unhandled-500-and-a-permanently-orphaned-pending-run) | P2 | Long (legitimate) target string causes an unhandled 500 and a permanently orphaned PENDING run | OPEN (disclosed, not fixed) |
| [BUG-020](#bug-020-single-argv-slot-argument-injection-into-nmaps-own-flag-parser-is-possible-but-not-currently-exploitable) | P4 | Single-argv-slot argument injection into nmap's own flag parser is possible but not currently exploitable | OPEN (disclosed, not fixed) |
| [BUG-021](#bug-021-ioc_type_hint-lets-a-caller-assign-an-arbitrary-ioctype-label-bypassing-scan-target-validation) | P3 | ioc_type_hint lets a caller assign an arbitrary IOCType label, bypassing scan-target validation | OPEN (disclosed, not fixed) |
| [BUG-022](#bug-022-csv-export-writes-raw-unescaped-ioc-values-into-cells----csvformula-injection) | P2 | CSV export writes raw, unescaped IOC values into cells -- CSV/formula injection (CWE-1236) | OPEN (disclosed, not fixed) |
| [BUG-023](#bug-023-pdf-export-interpolates-raw-text-into-a-reportlab-paragraph----markup-injectioncrash) | P2 | PDF export interpolates raw text into a ReportLab Paragraph -- markup injection/crash | OPEN (disclosed, not fixed) |
| [BUG-024](#bug-024-export-endpoint-is-gated-on-lookupread-instead-of-the-dedicated-lookupexport-permission) | P2 | Export endpoint is gated on lookup:read instead of the dedicated lookup:export permission | OPEN (disclosed, not fixed) |
| [BUG-025](#bug-025-refreshing-mid-investigation-does-not-resume-it----it-silently-starts-a-duplicate-investigation) | P2 | Refreshing mid-investigation does not resume it -- it silently starts a duplicate investigation | OPEN (disclosed, not fixed) |
| [BUG-026](#bug-026-concurrent-add-to-basket-for-the-same-new-ioc-throws-an-unhandled-integrityerror----raw-500) | P2 | Concurrent 'Add to Basket' for the same new IOC throws an unhandled IntegrityError -> raw 500 | OPEN (disclosed, not fixed) |
| [BUG-027](#bug-027-add-to-case-has-zero-duplicate-protection----concurrent-requests-silently-create-duplicate-ioc-rows) | P2 | 'Add to Case' has zero duplicate protection -- concurrent requests silently create duplicate IOC rows | OPEN (disclosed, not fixed) |
| [BUG-028](#bug-028-logging-out-in-one-tab-leaves-a-second-tab-looking-fully-signed-in-with-no-warning) | P3 | Logging out in one tab leaves a second tab looking fully signed-in, with no warning | OPEN (disclosed, not fixed) |
| [BUG-029](#bug-029-qatest-disposable-email-domain-is-rejected-by-authlogin-and-authregister-with-http-422) | P4 | @qa.test disposable email domain is rejected by /auth/login and /auth/register with HTTP 422 | OPEN (disclosed, not fixed) |
| [BUG-030](#bug-030-weak-hardcoded-default-datastore-credentials-are-actually-in-effect-on-the-live-postgres-container) | P2 | Weak, hardcoded default datastore credentials are actually in effect on the live Postgres container | OPEN (disclosed, not fixed) |
| [BUG-031](#bug-031-insecure-hardcoded-fallback-jwt-signing-secret-ships-in-source-secret-scan-finding) | P3 | Insecure hardcoded fallback JWT signing secret ships in source (secret-scan finding) | OPEN (disclosed, not fixed) |
| [BUG-032](#bug-032-hardcoded-plaintext-adminanalyst-passwords-committed-in-documentation-walkthrough-scripts) | P3 | Hardcoded plaintext admin/analyst passwords committed in documentation walkthrough scripts | OPEN (disclosed, not fixed) |
| [BUG-033](#bug-033-frontend-pins-next14215-which-has-30-confirmed-advisories-including-a-critical-middleware-auth-bypass) | P2 | Frontend pins next==14.2.15, which has 30 confirmed advisories including a critical middleware auth-bypass | OPEN (disclosed, not fixed) |
| [BUG-034](#bug-034-backend-pins-cryptography4301-which-has-11-advisories-in-certificate-validation-logic) | P2 | Backend pins cryptography==43.0.1, which has 11 advisories in certificate-validation logic | OPEN (disclosed, not fixed) |
| [BUG-035](#bug-035-fastapi-pulls-in-starlette-0386-unpinned-transitive-which-has-14-advisories) | P3 | fastapi pulls in starlette 0.38.6 (unpinned, transitive), which has 14 advisories | OPEN (disclosed, not fixed) |
| [BUG-036](#bug-036-python-jose330-carries-a-critical-algorithm-confusion-cve-and-a-jwtjwe-bomb-dos-cve) | P3 | python-jose==3.3.0 carries a critical algorithm-confusion CVE and a JWT/JWE-bomb DoS CVE | OPEN (disclosed, not fixed) |
| [BUG-037](#bug-037-python-multipart009-has-a-confirmed-dos-cve-fixed-0018) | P4 | python-multipart==0.0.9 has a confirmed DoS CVE (fixed 0.0.18) | OPEN (disclosed, not fixed) |
| [BUG-038](#bug-038-lxml530-has-a-confirmed-xxe-cve-in-its-default-iterparseetcompatxmlparser-config) | P4 | lxml==5.3.0 has a confirmed XXE CVE in its default iterparse()/ETCompatXMLParser() config | OPEN (disclosed, not fixed) |
| [BUG-039](#bug-039-no-request-correlation-id-anywhere-in-backend-logs) | P1 | No request-correlation ID anywhere in backend logs | FIXED (deployed, no dedicated test) |
| [BUG-040](#bug-040-failed-login-attempts-are-invisible-in-application-logs-beyond-a-bare-401) | P1 | Failed login attempts are invisible in application logs beyond a bare 401 | FIXED (deployed, no dedicated test) |
| [BUG-041](#bug-041-security-assessment-toolkit-runs-produce-zero-application-log-output-on-success) | P1 | Security Assessment Toolkit runs produce zero application log output on success | FIXED (deployed, no dedicated test) |
| [BUG-042](#bug-042-structlog-is-configured-but-never-used----all-real-log-output-is-unstructured-plaintext) | P2 | structlog is configured but never used -- all real log output is unstructured plaintext | OPEN (disclosed, not fixed) |
| [BUG-043](#bug-043-high-volume-routine-polling-floods-the-log-stream-burying-security-relevant-events-in-noise) | P2 | High-volume routine polling floods the log stream, burying security-relevant events in noise | OPEN (disclosed, not fixed) |
| [BUG-044](#bug-044-prometheus-metrics-provide-no-per-incident-detail-no-correlation-with-logs-no-per-userioc-labels) | P3 | Prometheus metrics provide no per-incident detail (no correlation with logs, no per-user/IOC labels) | OPEN (disclosed, not fixed) |
| [BUG-045](#bug-045-adminguidemd-self-contradicts-on-whether-provider-management-ui-and-the-audit-log-exist) | P1 | ADMIN_GUIDE.md self-contradicts on whether provider-management UI and the audit log exist | FIXED (deployed, no dedicated test) |
| [BUG-046](#bug-046-userguidemds-claim-exactly-eight-routesnothing-else-exists-is-false) | P1 | USER_GUIDE.md's claim "exactly eight routes...nothing else exists" is false | FIXED (deployed, no dedicated test) |
| [BUG-047](#bug-047-userguidemd-omits-the-entire-security-assessment-panel-and-ai-comparison-section) | P1 | USER_GUIDE.md omits the entire Security Assessment panel and AI Comparison section | FIXED (deployed, no dedicated test) |
| [BUG-048](#bug-048-providers-renders-blank-content-for-a-non-admin-role-with-no-access-denied-message) | P2 | /providers renders blank content for a non-admin role with no access-denied message | OPEN (disclosed, not fixed) |
| [BUG-049](#bug-049-userguidemds-sse-sequence-notation-reads-as-batched-but-the-real-stream-interleaves-per-provider) | P3 | USER_GUIDE.md's SSE-sequence notation reads as batched but the real stream interleaves per-provider | OPEN (disclosed, not fixed) |
| [BUG-050](#bug-050-jwt_secret_key-hardcoded-fallback-default-has-no-startup-guard-security-posture-review-finding) | P2 | jwt_secret_key hardcoded fallback default has no startup guard (security-posture-review finding) | OPEN (disclosed, not fixed) |
| [BUG-051](#bug-051-hard-process-kill-leaves-a-lookup-permanently-stuck-running-no-python-cleanup-can-run) | P1 | Hard process kill leaves a lookup permanently stuck RUNNING (no Python cleanup can run) | FIXED (deployed + regression tested) |
| [BUG-052](#bug-052-get-apiv1runtimeaudit-log-has-no-upper-bound-on-limit-and-no-real-pagination) | P2 | GET /api/v1/runtime/audit-log has no upper bound on `limit` and no real pagination | OPEN (disclosed, not fixed) |
| [BUG-053](#bug-053-concurrent-post-lookupstream-throughput-does-not-scale-with-concurrency) | P2 | Concurrent POST /lookup/stream throughput does not scale with concurrency | OPEN (disclosed, not fixed) |
| [BUG-054](#bug-054-robocopy-propagated-files-survive-a-keep-data-uninstall-as-orphaned-untracked-files) | P2 | robocopy-propagated files survive a "keep data" uninstall as orphaned, untracked files | OPEN (disclosed, not fixed) |
| [BUG-055](#bug-055-debugqa-harness-scripts-that-bypass-auth-and-audit-trails-are-baked-into-the-shipping-installer-and-live-inside-the-running-production-containers) | P1 | Debug/QA harness scripts that bypass auth and audit trails are baked into the shipping installer and live inside the running production containers | FIXED (deployed, no dedicated test) |
| [BUG-056](#bug-056-securityassessmentrun-rows-get-permanently-stuck-in-running-after-a-backend-crash----the-orphaned-lookup-recovery-sweep-doesnt-cover-this-sibling-subsystem) | P1 | SecurityAssessmentRun rows get permanently stuck in RUNNING after a backend crash -- the orphaned-lookup recovery sweep doesn't cover this sibling subsystem | FIXED (deployed + regression tested) |
| [BUG-057](#bug-057-background-security-assessment-runs-are-never-re-authorized-after-the-initial-http-request-and-there-is-no-way-to-cancel-an-in-flight-run) | P2 | Background security-assessment runs are never re-authorized after the initial HTTP request, and there is no way to cancel an in-flight run | OPEN (disclosed, not fixed) |
| [BUG-058](#bug-058-orphaned-lookup-recovery-sweep-has-no-instanceleader-scoping----would-misfire-the-moment-more-than-one-backend-process-is-ever-live-against-the-same-db) | P2 | Orphaned-lookup recovery sweep has no instance/leader scoping -- would misfire the moment more than one backend process is ever live against the same DB | OPEN (disclosed, not fixed) |
| [BUG-059](#bug-059-backend-container-crashed-exit-137-during-rate-limit-load-testing-and-self-recovered-root-cause-not-cleanly-attributable) | P3 | Backend container crashed (exit 137) during rate-limit load testing and self-recovered; root cause not cleanly attributable | OPEN (disclosed, not fixed) |
| [BUG-060](#bug-060-very-early-sse-client-disconnect-can-leave-a-lookup-permanently-stuck-in-running-until-the-next-backend-restart) | P2 | Very-early SSE client disconnect can leave a lookup permanently stuck in RUNNING until the next backend restart | OPEN (disclosed, not fixed) |

---

## Full Entries

### BUG-001: Login response time leaks account existence via a ~26x timing side-channel

- **Severity:** P2
- **Component:** `backend/app/api/routes/auth.py` (`login()`)
- **Reproduction:** POST /api/v1/auth/login with `{"email": "<real-user-email>", "password": "wrong"}` vs. `{"email": "<never-registered-email>", "password": "wrong"}`, timing each response.
- **Expected:** Login response time should not differ measurably between an existing account and a non-existent one, so timing cannot be used to enumerate valid accounts.
- **Actual:** Requests against an existing email with a wrong password consistently take ~200-300ms longer than requests against a nonexistent email, even though both return the identical 401 body `{"detail": "Invalid email or password"}`.
- **Root Cause:** `login()`'s check `if not user or not verify_password(payload.password, user.hashed_password):` short-circuits on Python's `or` — `verify_password()` (bcrypt) is only ever invoked when the email matches a real user; for a nonexistent email the function returns almost immediately.
- **Evidence:** Empirical measurement, N=40 requests/arm against a real disposable user and a nonexistent email, interleaved: existing-email+wrong-password median=231.4ms (mean=264.1ms, min=222.3ms, max=468.1ms) vs. nonexistent-email median=8.8ms (mean=10.5ms, min=7.6ms, max=22.0ms). Median ratio = 26.35x.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-002: No rate limiting, backoff, or account lockout on /auth/login

- **Severity:** P2
- **Component:** `backend/app/api/routes/auth.py`; `backend/app/core/users.py` (`record_login_failure`)
- **Reproduction:** POST /api/v1/auth/login repeatedly with wrong passwords for the same email; observe all responses are 401 with no rate-limit signal, then confirm the correct password still logs in immediately after.
- **Expected:** Repeated failed logins against the same account should eventually be throttled, rate-limited, or trigger a lockout, consistent with the rate-limiting pattern already used elsewhere in the codebase (e.g. `backend/app/api/routes/lookup.py`).
- **Actual:** 15 rapid sequential failed-login attempts against one disposable user all returned 401 (elapsed 3.86s for the batch); no 429 or 423 was ever observed, and the correct password succeeded with 200 immediately afterward — confirming no lockout side-effect either.
- **Root Cause:** The login endpoint has no per-IP or per-account `RateLimiter` wrapper (unlike `lookup.py`), no exponential backoff, no CAPTCHA, and no account lockout after repeated failures. Every failed attempt is recorded to the audit log via `record_login_failure` -> `record_audit('auth.login_failed', ...)`, but that log is never consulted to block or slow further attempts. bcrypt's own cost provides only a mild, non-adaptive throttle (~230ms/attempt) that does not scale down as attack parallelism scales up.
- **Evidence:** 15 rapid sequential failed logins: `statuses=[401]*15`, elapsed=3.86s; immediately-following correct-password login returned 200.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-003: set_user_active() overcounts audit log entries on no-op calls

- **Severity:** P2
- **Component:** `backend/app/core/users.py` (`set_user_active()`, contrast with `update_user()`)
- **Reproduction:** 1) Create a disposable ANALYST user X (active=true). 2) Fire two concurrent `POST /api/v1/admin/users/{X}/active {"is_active": false}` from two different admin tokens via `asyncio.gather`. 3) Query `config_audit_log` for X's email: two 'user.disable' rows appear even though only one real active->inactive transition occurred. 4) For contrast, repeat with two concurrent `PATCH /api/v1/admin/users/{X} {"role": "<same value>"}` — only one 'user.update' row appears.
- **Expected:** The audit log should record one entry per real state transition, matching `update_user()`'s behavior (`if changes: ... await record_audit(...)`), not one entry per API call regardless of whether anything changed.
- **Actual:** Across a live concurrency test, 3 'user.disable' audit rows were written for effectively 1 real disable transition — two of the three rows were no-op re-assertions of the already-current state, indistinguishable in the log from a genuine transition.
- **Root Cause:** `set_user_active()` unconditionally calls `record_audit()` after every successful call, with no "did this actually change anything" guard — unlike its sibling `update_user()`, which only commits/logs when the computed `changes` list is non-empty.
- **Evidence:** Live test on disposable target `qa-ent-multiadmin-x@example.com`: overlapping concurrent disable calls (B 10:35:53.880597, C 10:35:53.909752) both wrote 'user.disable' rows for one true transition; a later race added a third phantom 'user.disable' (10:35:53.941848) followed by a real 'user.enable' (10:35:53.946322). Verified via `SELECT timestamp, action, actor_email, detail FROM config_audit_log WHERE detail ILIKE '%qa-ent-multiadmin-x%' ORDER BY timestamp` — 8 rows total, 3 of which are phantom/no-op 'user.disable' entries.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-004: Last-admin-protection lock serializes all admin-console mutations platform-wide

- **Severity:** P2
- **Component:** `backend/app/core/users.py` (`_lock_all_admin_rows()`, `update_user()`, `set_user_active()`)
- **Reproduction:** 1) Create a disposable VIEWER user Z. 2) From a raw DB connection, run `BEGIN; SELECT id FROM users WHERE role='ADMIN' FOR UPDATE;` and hold the transaction open (e.g. `SELECT pg_sleep(2.5)`) without committing. 3) While held, issue `PATCH /api/v1/admin/users/{Z} {"full_name": "x"}` as any admin — it blocks for ~the remaining hold duration even though Z is a VIEWER and the payload never touches role or is_active. 4) Repeat with `GET /api/v1/admin/users` during the same hold — returns immediately.
- **Expected:** A full_name-only edit on an unrelated non-admin user should not contend for a lock scoped to admin-role rows; the module's own docstring states the lock is taken "before counting how many active admins would remain" only for role-demotion/disable paths.
- **Actual:** `update_user()` and `set_user_active()` both call `_lock_all_admin_rows(db)` (`SELECT * FROM users WHERE role='ADMIN' FOR UPDATE`) unconditionally at the very start of every transaction, even for a plain full_name edit on a non-admin VIEWER and even when `role`/`is_active` isn't changing at all — serializing any two concurrent admin-console mutations anywhere in the system against each other, contradicting the docstring's stated scope.
- **Root Cause:** `update_user()` takes the lock before even checking whether `role` was supplied in the request.
- **Evidence:** Baseline PATCH full_name on unrelated VIEWER Z completed in 0.020s. With a separate connection holding the ADMIN-rows FOR UPDATE lock for 2.5s, the same PATCH took 2.519s. A control `GET /api/v1/admin/users` (no lock) during the same window returned in 0.009s, isolating the block to the FOR-UPDATE-taking write path.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-005: Concurrent IOC investigations degrade sharply in latency (confounded run)

- **Severity:** P3
- **Component:** `backend/app/ai/service.py`; `backend/app/providers/orchestrator.py`; single uvicorn process (no `--workers`)
- **Reproduction:** Mint 5 JWTs (2 ANALYST, 3 ADMIN); `asyncio.gather` 5 `POST /api/v1/lookup/stream` calls each with a distinct benign public IP; time each to completion; cross-check `ioc_lookups.ioc_value`/`requested_by` against the submitting persona per lookup_id.
- **Expected:** Concurrent investigations should complete without cross-user data bleed and within a latency range reasonably close to the documented single-run baseline (~20-40s).
- **Actual:** Correctness held perfectly (all 5 reached COMPLETED, correct ioc_value/requested_by per lookup, no duplicate lookup_ids), but completion latency was 100.1s, 87.0s, 89.4s, 125.6s, and 160.6s — 3-8x the ~20-40s single-run baseline. An initial run with a 120s client timeout cut off 3 of 5 requests (server correctly marked them FAILED via the GeneratorExit path).
- **Root Cause:** The backend runs as a single uvicorn process; the active AI backend was 'ollama' (a local model), a plausible single-instance-inference bottleneck for the per-provider `summarize_provider` + `generate_final_assessment` AI calls every concurrent investigation funnels through. No application-level lock/semaphore gates this. **Confound disclosed by the original tester:** a separate, unrelated QA process was simultaneously flipping the active AI backend ~387 times over roughly the same 2-minute window on the shared instance, so the exact multiplier could not be cleanly attributed to the 5-way load alone. See BUG-053 for a cleaner, unconfounded re-measurement of this same underlying bottleneck.
- **Evidence:** `ioc_lookups` rows: 1.1.1.1/qa-ent-analyst-a 100.1s COMPLETED, 9.9.9.9/qa-ent-analyst-b 87.0s COMPLETED, 8.8.8.8/qa-ent-admin-a 89.4s COMPLETED, 8.8.4.4/qa-ent-admin-b 125.6s COMPLETED, 208.67.222.222/qa-ent-admin-c 160.6s COMPLETED. `config_audit_log` showed 387 `ai_provider.activate` rows from a sibling QA persona interleaved throughout the same window at ~270ms intervals.
- **Fix:** Not fixed — disclosed limitation; the tester explicitly recommended re-running this measurement in an isolated window before treating the exact multiplier as authoritative.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-006: Oversized IOC value crashes /lookup/stream generator, lookup stuck RUNNING forever

- **Severity:** P1
- **Component:** `backend/app/providers/base.py` (`ProviderResult`); `backend/app/providers/otx.py`, `virustotal.py`, `abuseipdb.py`, `malwarebazaar.py`, `nvd.py` (source-URL construction); `backend/app/api/routes/lookup.py` (`stream_lookup()` generator's `except`/`finally` blocks)
- **Reproduction:** 1) Auth as any user with `lookup:create`. 2) POST /api/v1/lookup/stream with `value = 'https://example.com/' + 'A'*1990` (or any URL whose length pushes a provider's built source URL past 2048 chars, with that provider enabled/configured). 3) Observe the SSE stream die abruptly after the failing provider's `provider_result` event (no `error`/`done` event ever arrives). 4) Query the lookup's row in `ioc_lookups` by its id — status remains `running` indefinitely.
- **Expected:** An oversized IOC value should either be rejected cleanly or, if a downstream write fails, the lookup should be marked FAILED and the SSE stream should terminate with a clean `error` event.
- **Actual:** The lookup was left permanently stuck at `status=running`, unreachable by completion or failure, and the client saw a raw dropped connection rather than a clean error.
- **Root Cause:** Every affected provider's client builds its source URL by interpolating the IOC value with no length cap (e.g. `otx.py` lines 61/79/93: `source_url=f"https://otx.alienvault.com/indicator/{section}/{ioc_value}"`), which is written verbatim into `provider_results.source_url`, a `VARCHAR(2048)` column. An oversized value causes Postgres to raise `StringDataRightTruncationError` during the per-provider `await stream_db.commit()` in `stream_lookup()`'s generator (`lookup.py` ~line 150). That first exception is caught by the generator's `except Exception` block, which sets `.status = FAILED` in memory and calls `await stream_db.commit()` a **second time on the same, already-broken session** (~line 264) — but the prior flush failure had already rolled the session back internally, so this second commit raises an uncaught `PendingRollbackError` that escapes the generator entirely. The `finally` block's own safety net (mark FAILED via a fresh session if still RUNNING) is a no-op because the in-memory `.status` attribute had already been (uncommitted) set to FAILED one step earlier, so the safety net believes recovery already happened when nothing was ever persisted.
- **Evidence:** Repro against `'https://example.com/' + 'A'*1990` (2010-char URL): client-side `httpx.RemoteProtocolError: peer closed connection without sending complete message body`. Server logs: `StringDataRightTruncationError: value too long for type character varying(2048)` on the `provider_results` INSERT for `provider_id='otx'`, immediately followed by an unhandled `PendingRollbackError`. DB confirmation: the lookup row remained `status='running'` well after the stream had terminated.
- **Fix:** Added `ProviderResult.__post_init__()` truncating `source_url` to 2048 chars — a single choke point protecting every provider. Rewrote the `stream_lookup()` `except` block to use a brand-new session for the FAILED-status write, matching the pattern already used in the generator's `finally` block for the `GeneratorExit` case.
- **Regression Test:** `test_oversized_source_url_does_not_crash_and_lookup_completes` and `test_provider_pipeline_exception_marks_lookup_failed_not_stuck_running`, both in `backend/app/tests/integration/test_lookup_stream_persistence.py` — passing.
- **Status:** FIXED (deployed + regression tested)

### BUG-007: Final-assessment generation exhausts its one retry and falls back to "unavailable" on a healthy backend

- **Severity:** P2
- **Component:** `backend/app/ai/service.py` (`generate_final_assessment()`)
- **Reproduction:** 1) With ollama/gemma2:2b active and healthy, POST /api/v1/lookup/stream `{"value": "1.0.0.1"}` (or any IOC likely to produce genuinely conflicting provider signals). 2) Inspect server logs for 'Final assessment attempt 1 failed' / 'Final assessment generation failed' pydantic `ValidationError` messages, and confirm the SSE `final_assessment` event's `executive_summary` is the generic "unavailable" fallback even though no AI backend was ever actually down.
- **Expected:** A fully healthy AI backend with real, successfully-generated per-provider summaries should not fall back to the same generic "unavailable" text used for genuine infrastructure outages.
- **Actual:** Against IOC `1.0.0.1` with a fully healthy, correctly-restored ollama/gemma2:2b backend and real mixed-signal evidence, gemma2:2b produced two different self-contradictory outputs across its two attempts (attempt 1: verdict='benign' + malicious_probability=90.0; attempt 2: verdict='malicious' + malicious_probability=1.0), both rejected by the model's own consistency validator, and the pipeline fell back to "AI-generated assessment unavailable (generation error)" — even though all 4 per-provider AI summaries for the same lookup had generated successfully moments earlier. From the API/UI's perspective this renders identically to a total AI-backend outage, though root cause and remediation are completely different.
- **Root Cause:** `generate_final_assessment()` retries exactly once, and only for pydantic `ValidationError` (self-contradictory verdict/risk pairs). On a small model like gemma2:2b, stochastic sampling flakiness on mixed-signal evidence can exhaust both attempts even when the backend itself is fully healthy.
- **Evidence:** docker logs (~10:5x UTC 2026-08-15): "Final assessment attempt 1 failed for 1.0.0.1: ... final_verdict=\"benign\" contradicts risk.malicious_probability=90.0 ... -- retrying once" followed by "Final assessment generation failed for 1.0.0.1: ... final_verdict=\"malicious\" contradicts risk.malicious_probability=1.0". SSE `final_assessment` event: `ai_backend=None`, `final_verdict='unknown'`, generic fallback `executive_summary`. A second, immediate reproduction on a low-signal domain succeeded on the first try, confirming stochastic flakiness rather than a deterministic bug.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-008: Stale "last test: failed" status persists on the AI Providers panel for a healthy backend

- **Severity:** P3
- **Component:** `backend/app/core/runtime_config.py` (`upsert_ai_provider()`; missing call to `record_ai_test_result()`)
- **Reproduction:** `GET /api/v1/runtime/ai-providers` as a `provider:manage` user and inspect the 'ollama' entry's `last_test_ok`/`last_test_message`/`last_test_at` fields vs. `updated_at`/`configured`/`is_active` for this staleness pattern.
- **Expected:** After credentials are reconfigured/restored to a working value following an outage-and-recovery cycle, the "last tested" status shown on the Manage AI Providers panel should reflect current health, or at minimum not display a stale failure for a backend confirmed to be actively serving investigations.
- **Actual:** At session start, the 'ollama' row already showed `last_test_ok=false` / `last_test_message='Ollama base URL and model are both required.'` (timestamped 2026-08-12, 3 days stale) even though ollama/gemma2:2b was independently confirmed fully functional during the session (real per-provider AI summaries were generated correctly).
- **Root Cause:** `upsert_ai_provider()` (used both to break and to restore the base_url) never calls `record_ai_test_result()`, so reconfiguring credentials back to a working value does not clear or refresh the previously recorded test-failure status. An admin viewing the panel after a transient outage-and-recovery cycle would see a persistent "last tested: failed" badge on the currently-active, currently-working backend until someone manually clicks "Test connection" again.
- **Evidence:** `GET /api/v1/runtime/ai-providers` at session start for `provider_id='ollama'`: `is_active=true`, `configured=true`, `model_id='gemma2:2b'`, `last_test_ok=false`, `last_test_message='Ollama base URL and model are both required.'`, `last_test_at='2026-08-12T14:29:39'` while `updated_at='2026-08-15T04:53:03'` (same-day, from a configure call) — credentials touched/restored same-day but test result never refreshed. `config_audit_log` shows the actor at that earlier timestamp as `'claude-code-test'`, suggesting a prior automated session already exercised this exact scenario and restored credentials without re-testing.
- **Fix:** Not fixed — pre-existing state, predates this QA session; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-009: GET /api/v1/providers/health's `configured` field is stale vs. runtime DB state

- **Severity:** P3
- **Component:** `backend/app/providers/registry.py` (`get_provider_health()`); contrast with `backend/app/core/runtime_config.py` / `backend/app/core/runtime_context.py`
- **Reproduction:** As any authenticated user with `lookup:read`, `GET /api/v1/providers/health` and compare its `configured` field for virustotal/abuseipdb/otx against `GET /api/v1/runtime/ioc-providers`'s `configured` field (admin-only) for the same provider_ids — the two endpoints disagree.
- **Expected:** `GET /api/v1/providers/health`'s `configured` field should reflect whether a provider is actually dispatched by live investigations.
- **Actual:** `GET /providers/health` reported `configured=false` for virustotal, abuseipdb, and otx, yet a live investigation actually dispatched real outbound calls to all three (virustotal/abuseipdb got real 401s from the live third-party APIs; otx succeeded with `no_data`) — proving the effective runtime configuration was true for those three at request time.
- **Root Cause:** `get_provider_health()` reports `configured` straight from each provider singleton's class-level `.configured` attribute, set once at process import time from `Settings` (env-var-derived). The DB-backed `provider_runtime_configs` table (editable at runtime) is what the orchestrator actually consults, and these two notions of "configured" have diverged live. Impact is currently limited: the only frontend consumer of `/providers/health` reads `supported_types`, never `.configured`; the admin Providers page is fed by the separate, correct `/runtime/ioc-providers` endpoint.
- **Evidence:** Live `GET /api/v1/providers/health` returned `configured=false` for virustotal, abuseipdb, otx, urlhaus, threatfox, malwarebazaar, hybrid_analysis, censys, while the same investigation's stream showed virustotal/abuseipdb/otx were actually attempted. Read-only query of `provider_runtime_configs` (kind='IOC') showed `last_test_ok=true` for virustotal, otx, hybrid_analysis, independent of the stale process-level `Settings` flag.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-010: gemma2:2b asserts 100% malicious_probability far beyond cited evidence's confidence

- **Severity:** P2
- **Component:** `backend/app/ai/service.py` (`generate_final_assessment()`); `backend/app/ai/schemas.py` (`FinalAssessment`)
- **Reproduction:** POST /api/v1/lookup/stream `{"value":"199.212.57.95"}` with an analyst Bearer token; inspect the correlation event's edge confidence values (0.5) vs. the `final_assessment` event's `risk.malicious_probability` (100.0) and `risk.analyst_confidence` ('high') in the same SSE stream.
- **Expected:** The model's stated confidence/probability should not exceed the confidence of the underlying evidence it cites as its basis.
- **Actual:** `final_assessment.risk = {overall_risk_score: 80.0, confidence_score: 90.0, malicious_probability: 100.0, analyst_confidence: 'high'}`, with the stated basis being correlation edges to `threat_actor:silverfox` and 3 campaigns — but every one of those edges carries `confidence: 0.5` (source=otx), and the upstream otx `provider_summary` itself reported `confidence: 'medium'`. The model discards both underlying confidence signals and reports absolute certainty.
- **Root Cause:** No validator in `app/ai/schemas.py` cross-checks `FinalAssessment.risk.malicious_probability`/`analyst_confidence` against the confidence of the correlation edges or provider summaries it cites; the LLM is free to overclaim certainty relative to its own evidence.
- **Evidence:** Correlation edges: `{"source": "ipv4:199.212.57.95", "target": "threat_actor:silverfox", "relationship": "attributed_to", "confidence": 0.5, "provenance": "otx"}` (plus 3x `part_of_campaign` edges also confidence 0.5). otx `provider_summary`: `"confidence": "medium"`. `final_assessment`: `{"malicious_probability": 100.0, "analyst_confidence": "high"}`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-011: Single AI-generated provider_summary is internally self-contradictory

- **Severity:** P2
- **Component:** `backend/app/ai/service.py` (`summarize_provider()`); `backend/app/ai/schemas.py` (`ProviderSummary`)
- **Reproduction:** POST /api/v1/lookup/stream `{"value":"2201104c6a6b96a0c44738a7c6b6c4d1e0a6c1b5a6c5849d7dc6fc1131d46c1f"}`; read the otx `provider_result` event's `data.verdict` field and compare it to the very next otx `provider_summary` event's `reputation` field in the same stream.
- **Expected:** A single AI-generated summary object should be internally consistent — its `reputation` field should not contradict its own `what_it_knows` prose and `threat_level`.
- **Actual:** For the hash IOC's otx `provider_summary`, the model wrote `what_it_knows='This IOC, a sha256 hash, is classified as malicious by AlienVault OTX.'` with `threat_level:'high'`, `confidence:'high'`, but `reputation:'unknown'` in the same JSON object — directly contradicting its own prose and the raw `provider_result.data.verdict` which was explicitly `'malicious'`.
- **Root Cause:** `summarize_provider()` (`app/ai/service.py` lines 336-364) generates the entire `ProviderSummary` object via one LLM call — `reputation` is model output, not deterministic — and there is no cross-field validator in `app/ai/schemas.py`'s `ProviderSummary` class checking `reputation` against `what_it_knows`/`threat_level` (only `FinalAssessment` has a `model_validator`, and it only checks `final_verdict` vs. `malicious_probability`).
- **Evidence:** otx `provider_summary`: `{"what_it_knows": "This IOC, a sha256 hash, is classified as malicious by AlienVault OTX.", "reputation": "unknown", "detection_status": "ok", "threat_level": "high", "confidence": "high"}`. Raw `provider_result.data`: `{"verdict": "malicious", "pulse_count": 1, "campaigns": ["whack.sh — cloaked malware — 2026-08-14"]}`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-012: agreeing_providers/disagreeing_providers never populated despite naming providers in prose

- **Severity:** P2
- **Component:** `backend/app/ai/schemas.py` (`FinalAssessment.agreeing_providers`/`disagreeing_providers`); `backend/app/ai/service.py`
- **Reproduction:** Run any of three lookups (8.8.8.8, a hash, 199.212.57.95) and grep the `final_assessment` event's `agreeing_providers`/`disagreeing_providers` fields; compare against the same event's `threat_assessment` prose which names a specific provider_id/display name.
- **Expected:** Per the schema's own documented contract — "Every provider named as agreeing in the prose MUST also be listed here: this array, not the prose, is what the UI renders as clickable provider citations" — these arrays should be populated whenever prose names a specific provider.
- **Actual:** In all three freshly-run `final_assessment` objects, both arrays were empty (`[]`) even though each `threat_assessment`/`technical_summary` explicitly named and relied on a specific provider (Spamhaus for 8.8.8.8, OTX for the hash and for 199.212.57.95) — meaning the running UI would show zero clickable evidence citations for all three real assessments.
- **Root Cause:** The LLM does not reliably populate these mandatory citation fields even when its own prose names a provider by name; no code-level derivation or validator backstops this.
- **Evidence:** `benign_8888.sse` final_assessment: `"threat_assessment": "...associated with Google LLC..."`, `"agreeing_providers": []`. `hash_notconfigured.sse`: `"threat_assessment": "The IOC is classified as malicious by OTX..."`, `"agreeing_providers": []`. `otx_attrib_ip.sse`: `"...classified as malicious by AlienVault OTX..."`, `"agreeing_providers": []`. Schema requirement at `app/ai/schemas.py` lines 152-169.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-013: Incoherent overall_risk_score=50 alongside clean/benign/low-probability fields

- **Severity:** P3
- **Component:** `backend/app/ai/schemas.py` (`FinalAssessment._verdict_must_agree_with_risk`)
- **Reproduction:** POST /api/v1/lookup/stream `{"value":"8.8.8.8"}`; read the `final_assessment` event's `risk` object and note `overall_risk_score=50` next to `reputation='clean'`/`severity='none'`/`malicious_probability=10`.
- **Expected:** A mid-scale risk score should not coexist with four other fields all indicating a clearly clean, low-risk IOC; the platform's own validator should catch this class of internal inconsistency.
- **Actual:** For 8.8.8.8, gemma2:2b returned `final_verdict='benign'`, `reputation='clean'`, `severity='none'`, `malicious_probability=10.0`, `confidence_score=80.0`, but `overall_risk_score=50.0` — a mid-scale, ambiguous-reading score sitting beside four other fields all indicating a clean IOC. This passed validation and reached the stream.
- **Root Cause:** `FinalAssessment._verdict_must_agree_with_risk` (lines 199-220) only checks `risk.malicious_probability` against `final_verdict` thresholds (<30 for malicious, >50 for benign) — `overall_risk_score` is not referenced anywhere in that validator.
- **Evidence:** `benign_8888.sse` final_assessment: `{"overall_risk_score": 50.0, "confidence_score": 80.0, "severity": "none", "reputation": "clean", "malicious_probability": 10.0}`, `"final_verdict": "benign"`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-014: Misleading narrative conflation of unrelated OSINT noise with a malicious verdict

- **Severity:** P3
- **Component:** `backend/app/ai/service.py` (final-assessment narrative generation)
- **Reproduction:** POST /api/v1/lookup/stream `{"value": "199.212.57.95"}`; read the `internet_intelligence` `provider_summary` event (reputation:unknown, threat_level:low) and compare its narrative role in `final_assessment.executive_summary` to the otx `provider_summary` (reputation:malicious).
- **Expected:** Unrelated, low-confidence OSINT chatter should not be given equal narrative weight to a well-evidenced malicious classification, implying a connection the underlying data does not support.
- **Actual:** The `executive_summary`/`technical_summary` for 199.212.57.95 open by foregrounding an unrelated GitHub repository (an essay about Chinese politics incidentally mentioning the IP) in the same sentence/paragraph as the OTX malicious classification and SilverFox threat-actor attribution, giving both equal narrative weight and implying a thematic/causal connection the evidence doesn't support.
- **Root Cause:** No synthesis-level guard prevents the model from narratively conflating low-relevance OSINT hits with high-confidence threat-intel findings in the same sentence.
- **Evidence:** `otx_attrib_ip.sse` `final_assessment.executive_summary`: "The IOC, 199.212.57.95, is associated with the GitHub repository 'cirosantilli/cirosantilli', which contains content related to China's political and social landscape... This IP address has been classified as malicious by AlienVault OTX. A correlation analysis reveals a connection to the SilverFox threat actor." Compare `internet_intelligence` provider_summary: `{"reputation": "unknown", "threat_level": "low"}`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-015: Log4Shell's CISA KEV ransomware/deadline evidence silently dropped from the final assessment

- **Severity:** P2
- **Component:** `backend/app/ai/service.py` (`summarize_provider()` exception fallback, lines 365-375); `backend/app/api/routes/lookup.py` (`generate_final_assessment` input)
- **Reproduction:** POST /api/v1/lookup/stream `{"value": "CVE-2021-44228"}` as an analyst-role JWT; read the SSE stream's `provider_summary` event for `provider_id=cisa_kev`, then compare against the `final_assessment` event's `supporting_evidence`/`verdict_rationale` fields — the KEV ransomware/deadline facts are present in `provider_result` but absent from every AI-narrative field.
- **Expected:** The single most authoritative fact available for a KEV-listed CVE — active ransomware exploitation and a legally mandated, years-overdue remediation deadline — should reach the analyst-facing narrative when the raw provider data contains it.
- **Actual:** `cisa_kev` returned real, correct structured data (`known_ransomware_campaign_use: "Known"`, `due_date: "2021-12-24"`), but its AI-generated `provider_summary` came back as a generic failure placeholder (`what_it_knows: "AI summarization unavailable for this provider (generation error)."`). Because `generate_final_assessment` only receives `provider_summaries` (not raw `provider_results`), this placeholder is all the final-assessment step ever sees for `cisa_kev` — the final narrative cites only NVD and unrelated GitHub OSINT hits, never mentioning the CVSS score, CVSS vector, or CISA KEV ransomware/deadline facts, even though those exact facts sit untouched in `provider_result.data`.
- **Root Cause:** docker logs confirm the root cause: `ERROR:app.ai.ollama_client:Ollama response was not valid JSON (model=gemma2:2b): ..."relationships": [\n "CVE-2021-44228 is a known exploited vulnerability.", "], }'` followed by `WARNING:app.ai.service:Provider summary generation failed for cisa_kev`. The fallback code (`app/ai/service.py:365-375`, `except Exception` -> generic 'AI summarization unavailable' `ProviderSummary`) has no path that reconstructs a deterministic summary from the still-valid raw provider fields when the LLM's JSON is malformed.
- **Evidence:** Full CISA KEV `provider_summary` event: `{"provider_id": "cisa_kev", "what_it_knows": "AI summarization unavailable for this provider (generation error).", "reputation": "unknown", ...}`. The numeric risk fields (severity=critical, risk=90) happened to land correctly this run because NVD's CVSS still came through, but the analyst-facing rationale is missing the single most operationally important fact.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-016: 8.8.8.8 lands on 'benign' with an incoherent, elevated risk score driven by coincidental OSINT noise

- **Severity:** P3
- **Component:** `backend/app/ai/service.py` (final-assessment narrative generation); `internet_intelligence` OSINT provider
- **Reproduction:** POST /api/v1/lookup/stream `{"value": "8.8.8.8"}`; inspect the `internet_intelligence` provider_result (irrelevant coincidental hits) versus `final_assessment.risk.overall_risk_score`/`malicious_probability`, which are elevated relative to what whois_rdap+spamhaus+otx alone would justify.
- **Expected:** A universally-known benign public DNS resolver with Google-LLC WHOIS ownership, a clean Spamhaus result, and OTX no_data should not receive an elevated, "coin-flip"-reading risk score.
- **Actual:** The `internet_intelligence` OSINT provider returned five GitHub repositories whose only connection to '8.8.8.8' is an incidental numeric-substring match with empty/irrelevant snippets. The final assessment's `threat_assessment` text reasons directly from this noise ("The IP address 8.8.8.8 is associated with five Github repositories. This suggests a potential for malicious activity..."), and `overall_risk_score` came back 60.0 with `malicious_probability` 50.0 — framed as a coin-flip for one of the internet's best-known, permanently-benign IPs. `final_verdict` did still resolve to 'benign', so this is not an outright misclassification.
- **Root Cause:** The model weights coincidental OSINT hits (numeric-substring matches with no real relevance) as if they were meaningful threat signal, with nothing checking relevance before folding them into the risk score.
- **Evidence:** `internet_intelligence` provider_result: `{"osint_findings": [{"title": "skilldevlopit-star/82585", "snippet": ""}, ...]}`. `final_assessment.risk`: `{"overall_risk_score": 60.0, "confidence_score": 90.0, "severity": "low", "reputation": "unknown", "malicious_probability": 50.0}`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-017: 203.0.113.77 (TEST-NET-3) gets a confident 'benign' verdict despite zero evidence, plus a corrupted JSON artifact

- **Severity:** P3
- **Component:** `backend/app/ai/service.py` (final-assessment generation / JSON-repair path)
- **Reproduction:** POST /api/v1/lookup/stream `{"value": "203.0.113.77"}`; observe that 6 of 7 applicable provider_result events are `not_configured`/`no_data`, yet `final_assessment` still reports a high-confidence 'benign' verdict rather than 'unknown'; also inspect `final_assessment.recommended_actions[1]` for a literal corrupted string.
- **Expected:** An IOC with near-total absence of real provider data (only spamhaus returned real 'clean'; the rest `not_configured`/`no_data`; independently re-verified via direct RDAP query returning a real 404) should surface as 'unknown / insufficient data' with a correspondingly low confidence, not a confident clean verdict.
- **Actual:** `final_assessment` asserted `final_verdict='benign'` with `confidence_score=80.0` (`risk.overall_risk_score=50.0`, `malicious_probability=10.0`) despite essentially no genuine security signal. Separately, the same `final_assessment` JSON's `recommended_actions` array contained a corrupted entry: the second list item was literally the raw text `"], \""` — a JSON-syntax artifact leaking into structured, analyst-facing output.
- **Root Cause:** No code-level short-circuit routes near-zero-evidence IPv4/domain cases (as exists for the fully-empty-evidence hash case documented elsewhere, see BUG-level context in dimension 10's historical note) to an honest 'unknown' outcome for this specific case; the model instead produced a confident verdict, and a JSON-repair artifact leaked through unsanitized.
- **Evidence:** `final_assessment.risk`: `{"overall_risk_score": 50.0, "confidence_score": 80.0, "severity": "none", "reputation": "clean", "malicious_probability": 10.0}`. `recommended_actions`: `["Further investigation into the IOC's full context...", "], \""]`. Independent RDAP re-check from inside `app-backend-1`: `GET https://rdap.org/ip/203.0.113.77` -> HTTP 404 (confirming whois_rdap's `no_data` was itself correct real-world behavior).
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-018: mitre_mappings is empty in every final_assessment, including textbook CVE cases

- **Severity:** P4
- **Component:** `backend/app/ai/schemas.py` / `backend/app/ai/service.py` (`FinalAssessment.mitre_mappings`)
- **Reproduction:** Run POST /api/v1/lookup/stream for CVE-2021-44228 (or any of the five critical-classification-test IOCs) and inspect `final_assessment.mitre_mappings` in the SSE stream — it is consistently `[]`.
- **Expected:** For a CVE that is one of the most commonly MITRE-mapped in the industry (Log4Shell, typically T1190 Exploit Public-Facing Application), the optional `mitre_mappings` field should be populated when the model is otherwise capable of synthesizing structured content from the same evidence.
- **Actual:** Across all five lookups tested (two malicious IPs/hashes with real threat-actor/campaign attribution, one CVE with a 10.0 CVSS RCE, one benign IP, one no-data IP), `final_assessment.mitre_mappings` came back as an empty list every single time, including for CVE-2021-44228.
- **Root Cause:** Not independently isolated by the QA tester beyond noting the field is optional; the "MITRE ATT&CK Mappings" section of every exported report/PDF is silently omitted for CVEs where it is most expected.
- **Evidence:** `final_assessment.mitre_mappings == []` for all five IOCs, including CVE-2021-44228 alongside `"risk": {"overall_risk_score": 90.0, "severity": "critical"}`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-019: Long (legitimate) target string causes an unhandled 500 and a permanently orphaned PENDING run

- **Severity:** P2
- **Component:** `backend/app/core/security_assessment.py` (`start_run()`); `backend/app/core/audit.py` (`record_audit()`); `backend/app/models/runtime_config.py` (`ConfigAuditLog.detail`, `String(1000)`)
- **Reproduction:** 1) Create an `IOCLookup` with `ioc_type='domain'`/`'url'` and `ioc_value` of length ~1000-2048 chars (e.g. `'a'*1900+'.example.test'`). 2) POST /api/v1/security-assessment/{lookup_id}/run with `{tool_ids:['nmap'], profile:'quick', target_confirmation:<same string>, authorization_confirmed:true}` as any ANALYST/ADMIN. 3) Observe a non-200 response with an empty/unparseable body, and a `SecurityAssessmentRun` row stuck in PENDING indefinitely.
- **Expected:** A fully legitimate, schema-valid target string (well under the `IOCLookup.ioc_value` `String(2048)` cap) should either succeed or fail cleanly with a 4xx and no orphaned DB state, consistent with the toolkit's stated design principle of "no silent failure."
- **Actual:** The client got a broken/empty non-200 response, and the `SecurityAssessmentRun` row that was already committed as PENDING is left there forever — it will never run, complete, fail, or surface any error.
- **Root Cause:** `start_run()` commits the `SecurityAssessmentRun` row (status=PENDING) FIRST, then calls `record_audit()` with an f-string that embeds `target_confirmation` verbatim with no length cap. `record_audit()` does no truncation either, and `ConfigAuditLog.detail` is `String(1000)`. Any target longer than ~933 characters (67-char fixed prefix + 1000-char column) makes this INSERT raise `StringDataRightTruncationError`, which happens BEFORE `_spawn_background(_execute_run(...))` is ever reached.
- **Evidence:** Reproduced live: `IOCLookup ioc_value='a'*1900+'.example.test'` (1913 chars), `target_confirmation=<same string>`, `tool_ids=['nmap']`. docker logs: `StringDataRightTruncationError: value too long for type character varying(1000)` at 2026-08-15T10:39:37Z. Client response non-200 with empty body (`JSONDecodeError: 'Expecting value: line 1 column 1'`). The resulting `SecurityAssessmentRun` row was confirmed still present, in PENDING, blocking even test-user hard-delete via FK, until manually cleaned up.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-020: Single-argv-slot argument injection into nmap's own flag parser is possible but not currently exploitable

- **Severity:** P4
- **Component:** `backend/app/security_assessment/nmap_tool.py`
- **Reproduction:** `docker exec app-backend-1 python3 -c` with `argv=['nmap','-oX','-','-T4','-F','--top-ports','100','--script=vuln']`; observe nmap accepts the flag but reports no targets scanned. Not independently reachable as a full exploit because the tool's argv construction leaves exactly one attacker-controlled slot, always in the terminal target position.
- **Expected:** The target argv slot should only ever be interpreted by nmap as a target, consistent with the module's own docstring claim that "no profile ever includes `--script`" and the target is "one argv element."
- **Actual:** With `target_confirmation = '--script=vuln 127.0.0.1'` (one of the required injection payloads), nmap's NSE engine parsed this as the flag `--script` with value `vuln 127.0.0.1` and failed to match a category (rc=1, no scan). Separately, `target='--script=vuln'` alone WAS accepted by nmap's parser as a legitimate flag with no error, but because it consumed the tool's single attacker-controlled argv slot, no target argv element remained, so nmap reported "No targets were specified" (rc=0) and never loaded/ran any script against any host.
- **Root Cause:** `nmap_tool.py`'s argv always places the attacker-controlled value as the single LAST list element (`[..., *_PROFILE_ARGS[profile_id], target]`); nmap does its own argv parsing independent of any shell and does not know "this argv slot is supposed to be a target only," so a string starting with `-`/`--` can be interpreted as a flag rather than a hostname. Because a single Python string can only occupy one OS-level argv slot, this class of bug cannot currently be leveraged to both inject a flag AND supply a real target in the same request.
- **Evidence:** Direct argv-shape test: `argv=[...,'--script=vuln 127.0.0.1']` -> stderr "NSE: failed to initialize the script engine: ... 'vuln 127.0.0.1' did not match a category...", rc=1. Follow-up `argv=[...,'--script=vuln']` (no trailing target) -> "WARNING: No targets were specified, so 0 hosts scanned.", rc=0. Same behavior reproduced through the live API (HTTP 200, run completed, 0 findings).
- **Fix:** Not fixed — disclosed as a real, non-urgent gap; recommended hardening (not applied): reject/normalize target values starting with `-` before building argv, or insert a literal `--` end-of-options separator immediately before the target element.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-021: ioc_type_hint lets a caller assign an arbitrary IOCType label, bypassing scan-target validation

- **Severity:** P3
- **Component:** `backend/app/api/routes/lookup.py` line 81 (`ioc_type = payload.ioc_type_hint or detect_ioc_type(ioc_value)`); `backend/app/schemas/lookup.py` line 11 (`ioc_type_hint: Optional[IOCType]`); `backend/app/core/security_assessment.py` lines 113-130 (`_validate_scope()`)
- **Reproduction:** POST /api/v1/lookup/stream with `json={"value": "<arbitrary string>", "ioc_type_hint": "ipv4"}` as any `lookup:create`-permitted user; inspect the resulting `IOCLookup` row's `ioc_type`/`ioc_value`. Not independently executed against the live provider fan-out in the source QA pass to avoid triggering real external threat-intel provider calls for garbage strings — the equivalent DB state was instead created directly.
- **Expected:** The Security Assessment Toolkit's scan-target validation should confirm that a lookup's `ioc_value` is actually shaped like the claimed `ioc_type` (IP/hostname) before treating it as a valid nmap/tls/dns/http-headers target.
- **Actual:** A caller supplying `ioc_type_hint` skips `detect_ioc_type()` (and all its format regexes/`ipaddress.ip_address()` parsing) entirely — the raw string is stored as `IOCLookup.ioc_value` with whatever `ioc_type` the caller asked for. `_validate_scope()` then only checks `lookup.ioc_type in SCANNABLE_TYPES` and (for CIDR only) parses `ioc_value` with `ipaddress.ip_network` — for IPV4/IPV6/DOMAIN/HOSTNAME it never re-validates that `ioc_value` is actually shaped like an IP/hostname.
- **Root Cause:** This is not a command-injection bug (nmap_tool.py's argv-exec handling is safe, see BUG-020's context) — it is the realistic path by which an attacker-controlled, non-IP-shaped string ends up seeded as `target` for the Nmap/TLS/DNS/HTTP-header tools in the first place. A caller with only `lookup:create` (any ANALYST/ADMIN) can create a lookup with `ioc_value='anything they want'` and `ioc_type_hint='ipv4'`, then (separately, with `security_assessment:create`) request a scan against it with `target_confirmation` equal to that same arbitrary string.
- **Evidence:** `app/api/routes/lookup.py:81`; `app/schemas/lookup.py:11` (any enum value, unconstrained relative to `value`); `app/core/security_assessment.py:113-130` (`_validate_scope()` never calls IP/hostname-format validation for IPV4/IPV6/DOMAIN/HOSTNAME types).
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-022: CSV export writes raw, unescaped IOC values into cells -- CSV/formula injection (CWE-1236)

- **Severity:** P2
- **Component:** `backend/app/api/routes/lookup.py` (`_render_csv()`, lines 476-496); `backend/app/schemas/lookup.py` (`LookupCreateRequest.value`)
- **Reproduction:** 1) POST /api/v1/lookup/stream `{value:'=1+1+cmd|calc!A1', ioc_type_hint:'malware_family'}` as any analyst -> get lookup_id. 2) POST /api/v1/lookup/{lookup_id}/export?format=csv -> response body's second line is `ioc_value,=1+1+cmd|calc!A1` unescaped.
- **Expected:** IOC values beginning with `=`, `+`, `-`, or `@` should be neutralized (e.g. leading-apostrophe prefix or quoting) before being written into a CSV cell, to prevent formula interpretation by spreadsheet applications.
- **Actual:** `_render_csv()` writes `lookup.ioc_value` and other fields verbatim into CSV cells via `csv.writer` with no neutralization. Any analyst/admin can create a lookup whose `ioc_value` is a formula payload (free-text IOC types like `malware_family`/`threat_actor`/`campaign` accept arbitrary strings via `ioc_type_hint`), and when another analyst exports that lookup to CSV and opens it in Excel/LibreOffice, the leading `=` is interpreted as a formula (classic DDE/formula-injection vector).
- **Root Cause:** No output-sanitization step exists between the raw `ioc_value` and the CSV cell write.
- **Evidence:** Created a disposable lookup (id `45545891-1ada-4839-9faf-f1f6d916db3a`) via `POST /api/v1/lookup/stream` with `{"value": "=1+1+cmd|calc!A1", "ioc_type_hint": "malware_family"}`; exported CSV (200 OK) contained verbatim `ioc_value,=1+1+cmd|calc!A1` with no quoting/escaping/leading-apostrophe neutralization.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-023: PDF export interpolates raw text into a ReportLab Paragraph -- markup injection/crash

- **Severity:** P2
- **Component:** `backend/app/api/routes/lookup.py` (`_render_pdf()`, lines 499-571)
- **Reproduction:** 1) POST /api/v1/lookup/stream `{value:'<b>INJECTED</b> title & unclosed <tag AAAA', ioc_type_hint:'malware_family'}` -> lookup_id. 2) POST /api/v1/lookup/{lookup_id}/export?format=pdf -> HTTP 500, confirmed via container logs to be the reportlab paraparser `ValueError`.
- **Expected:** IOC/assessment text embedded in a PDF export should be treated as literal text, not parsed as markup, and malformed input should not crash the export endpoint.
- **Actual:** (a) A value containing an unclosed/malformed tag makes `reportlab.platypus.paraparser` raise `ValueError`, uncaught -> unhandled 500 on every future export attempt of that specific lookup (denial of service for that record's PDF export). (b) A value containing a well-formed tag (e.g. `<font color="red" size="40">...`) is accepted by reportlab as real markup and renders successfully (200), meaning free-text IOC values can inject arbitrary formatting/spoofed content into an otherwise "official-looking" exported SOC report.
- **Root Cause:** `_render_pdf()` builds `Paragraph(f"IOC Assessment: {lookup.ioc_value}", ...)` and several other Paragraph/`_section` calls directly from `lookup.ioc_value` and AI-generated `FinalAssessment` text, with zero XML-escaping. ReportLab's `Paragraph` parses its input as a small XML/HTML-like markup dialect.
- **Evidence:** Case (a): lookup id `4a61fa8c-c4c4-45af-83f7-1169896fe12a`, value `'<b>INJECTED</b> title & unclosed <tag AAAA'` -> HTTP 500; traceback: `reportlab/platypus/paraparser.py ... ValueError: paraparser: syntax error: parse ended with 1 unclosed tags / para`. Case (b): lookup id `8fddb9cb-6b69-48ec-8799-60ded65f0a34`, value `'<font color="red" size="40">FAKE-VERDICT-INJECTED</font>'` -> HTTP 200, valid PDF returned.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-024: Export endpoint is gated on lookup:read instead of the dedicated lookup:export permission

- **Severity:** P2
- **Component:** `backend/app/api/routes/lookup.py` (`export_lookup()`, lines 574-579); `backend/app/models/user.py` (`ROLE_PERMISSIONS`)
- **Reproduction:** Mint an access token with `role='viewer'` for a pre-existing disposable account (role VIEWER, is_active=true) via `create_access_token`. Call `POST /api/v1/lookup/{any_lookup_id}/export?format=csv` (or pdf) with that token -> 200 with real file content, despite VIEWER lacking `lookup:export` in `ROLE_PERMISSIONS`.
- **Expected:** Per `ROLE_PERMISSIONS`, `lookup:export` is granted to ADMIN and ANALYST but NOT to VIEWER — the export endpoint should be gated behind `lookup:export`, per the platform's own documentation (`docs/API_DOCUMENTATION.md` line 57, and lines 423-425 explicitly instructing that a real export endpoint "should be gated behind the already-reserved `lookup:export` permission").
- **Actual:** `export_lookup()` uses `Depends(require_permission("lookup:read"))`, not `lookup:export`. Since VIEWER already has `lookup:read`, a VIEWER-role user can successfully call the export endpoint and download real PDF/CSV files. `lookup:export` is dead code — defined in the permission matrix but never referenced by `require_permission` anywhere in the codebase.
- **Root Cause:** Endpoint dependency wired to the wrong permission string.
- **Evidence:** Viewer token for `qa-ent-viewer-a@qa.test` (role VIEWER, is_active=true): `GET /api/v1/lookup/{id}` -> 200 (expected). `POST /api/v1/lookup/{id}/export?format=csv` as the same viewer token -> 200, 334 bytes of real CSV content. `POST .../export?format=pdf` as viewer -> 200, 2185 bytes starting with `b'%PDF'`. Unauthenticated request to the same endpoint -> 401 (auth works; the role-permission check is wrong).
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-025: Refreshing mid-investigation does not resume it -- it silently starts a duplicate investigation

- **Severity:** P2
- **Component:** `frontend/app/lookup/new/page.tsx`
- **Reproduction:** 1) Log in as an analyst. 2) Go to /lookup/new?value=<any new domain>. 3) Wait ~3s so some `provider_result` events land but the investigation is not done. 4) Press F5 (full reload). Query `ioc_lookups` for that value afterward: two rows appear instead of one, and the first is FAILED.
- **Expected:** A full-page refresh mid-investigation should either resume the in-progress investigation or clearly warn the user that a new one will be started.
- **Actual:** A full-page reload re-mounts the page and fires an entirely new POST, creating a second, independent `IOCLookup` row for the same value while the first is abandoned server-side (its client connection drops, so it never reaches `final_assessment`/`completed`). The UI shows no warning, and the post-refresh screen looks visually identical to the pre-refresh screen (same '2/8 providers responded, PENDING' layout), completely masking that a new investigation was just started from zero.
- **Root Cause:** `/lookup/new?value=X` always POSTs a fresh `/api/v1/lookup/stream` on mount and never navigates to a persistent `/lookup/{id}` URL after completion, so there is nothing to "resume" from.
- **Evidence:** Reproduced twice. DB ground truth: for one test value, two `ioc_lookups` rows exist 4 seconds apart, both `status=FAILED`. Same pattern repeated for a second test value. Screenshots `chaos-01-1-before-refresh-mid-lookup.png` and `chaos-02-1-immediately-after-refresh.png` (`documentation/build/raw-screenshots/`) are pixel-identical in layout despite being two different lookup_ids under the hood.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-026: Concurrent 'Add to Basket' for the same new IOC throws an unhandled IntegrityError -> raw 500

- **Severity:** P2
- **Component:** `backend/app/api/routes/basket.py` (`add_to_basket()`, line 84)
- **Reproduction:** From two browser tabs logged in as the same account, both viewing a fresh (never-basketed) IOC's investigation page, click 'Add to Basket' in both tabs within the same ~100ms window. One tab gets 201, the other gets a raw 500 (backend log shows the IntegrityError traceback at `basket.py:84`).
- **Expected:** A duplicate/racing basket-add for the same IOC should be handled gracefully (e.g. caught and treated as already-added), not surfaced as a raw server error.
- **Actual:** `add_to_basket` does a check-then-insert (SELECT existing, then INSERT if none) that is not atomic. When two requests for the same not-yet-basketed `ioc_value` race within the same transaction window, both pass the SELECT, then the second INSERT hits the `uq_basket_owner_ioc` unique constraint and raises `IntegrityError`, which is never caught in this route (contrast with the equivalent upsert pattern in `app/core/runtime_config.py` and `app/core/users.py`, which both explicitly catch `IntegrityError`). This surfaces to the client as a bare "Internal Server Error," turned into a vague "Failed to add to basket." toast by the frontend's generic catch.
- **Root Cause:** Non-atomic check-then-insert with no exception handling for the resulting unique-constraint violation.
- **Evidence:** Reproduced 3 times independently: (1) isolated concurrent httpx POSTs — first request 201 Created, second 500 with traceback `duplicate key value violates unique constraint "uq_basket_owner_ioc"`; (2) live two-tab simultaneous click (backend log: one 201, one 500); (3) clean isolated follow-up — backend log shows `500 Internal Server Error` with traceback at `basket.py:84` immediately followed by a 201 from the other tab. DB confirms no data corruption either time (exactly 1 basket_items row per value, thanks to the DB constraint).
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-027: 'Add to Case' has zero duplicate protection -- concurrent requests silently create duplicate IOC rows

- **Severity:** P2
- **Component:** `backend/app/api/routes/cases.py` (`add_case_ioc()`); `CaseIOC` model (no unique constraint on `(case_id, ioc_value)`)
- **Reproduction:** POST /api/v1/cases/{case_id}/iocs twice, near-simultaneously, with identical `{ioc_value, ioc_type}` body. Both succeed (201); GET the case afterward and count matching `ioc_value` entries -- 2 instead of 1.
- **Expected:** Adding the same IOC to a case twice (via double-click or two tabs) should not silently create two identical rows in the case with no error or warning to the analyst.
- **Actual:** Two concurrent (or rapidly double-clicked) 'Add to Case' requests for the identical `ioc_value` both return 201 and both persist, leaving the case permanently showing the same IOC listed twice.
- **Root Cause:** Unlike `basket.py`, `add_case_ioc` performs no existing-row check at all, and there is no unique constraint on `CaseIOC (case_id, ioc_value)`.
- **Evidence:** Verified via a direct backend test: 2 concurrent `POST /api/v1/cases/{id}/iocs` for the same `ioc_value` both returned 201, and `GET /api/v1/cases/{id}` afterward showed 2 matching IOC rows for that exact value. (Test case id `ba9c7920-3701-495e-8fbf-4e9bf3e28f44` and both duplicate rows were deleted afterward.)
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-028: Logging out in one tab leaves a second tab looking fully signed-in, with no warning

- **Severity:** P3
- **Component:** `frontend/lib/api.ts` (`authedFetch()`); `frontend/app/lookup/new/page.tsx` (`onAuthExpired`, SSE-only)
- **Reproduction:** Tab A and Tab B both logged in as the same account (shared localStorage). Start an investigation in tab B. In tab A, click 'Sign out'. Wait for tab B's investigation to finish, then click 'Add to Basket' in tab B: no redirect to /login occurs; a generic failure message appears instead.
- **Expected:** When another tab of the same account signs out, other tabs should detect the auth-state change and redirect to /login on the next authenticated action, rather than presenting a misleading generic error.
- **Actual:** After tab A signs out (clearing both tokens), tab B keeps rendering the completed investigation UI indefinitely (basket badge count, action buttons all still shown as if logged in). The first subsequent authenticated action in tab B does not redirect to /login — the user just sees the same generic "Failed to add to basket." message used for any other transient error, with no indication they need to sign in again.
- **Root Cause:** Auth state lives in `localStorage` (`access_token`/`refresh_token`), shared synchronously across tabs, but there is no `storage` event listener anywhere in the frontend to detect a cross-tab logout. `authedFetch()`'s 401-then-failed-refresh path (`lib/api.ts`) has no `onAuthExpired`-style hook — that redirect behavior exists only for the dedicated SSE lookup-stream path (`app/lookup/new/page.tsx`'s `onAuthExpired`).
- **Evidence:** Screenshot `chaos-21-5-tabB-add-to-basket-after-session-died.png` shows tab B still fully rendered (Basket badge '3', all panels populated, verdict shown) with "Failed to add to basket." printed under Investigation Actions — no login prompt, no banner, URL unchanged.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-029: @qa.test disposable email domain is rejected by /auth/login and /auth/register with HTTP 422

- **Severity:** P4
- **Component:** `backend/app` `LoginRequest`/`RegisterRequest` pydantic schemas (`EmailStr`/email-validator library)
- **Reproduction:** `docker exec app-backend-1` httpx `POST /api/v1/auth/login {"email":"nonexistent@qa.test",...}` -> 422 "value is not a valid email address: The part after the @-sign is a special-use or reserved name..."; same call with `@example.com` -> 401 for a nonexistent user.
- **Expected:** The stated QA convention of using `@qa.test` disposable email addresses should be usable through the real HTTP login/register API, not just via direct service-layer/DB calls.
- **Actual:** `LoginRequest`/`RegisterRequest` use `EmailStr` (via the `email-validator` library), which rejects the `.test` TLD as a "special-use or reserved name" with a 422 before the request ever reaches application logic or the database — personas following the `@qa.test` convention cannot authenticate through the real HTTP API at all.
- **Root Cause:** `email-validator`'s reserved-TLD rejection is stricter than the project's own documented QA data convention; not a functional application bug, but a real gotcha — this silently breaks any tester's login/failed-login audit test if they pick the `.test` suffix, since no `auth.login`/`auth.login_failed` audit entry is produced (the request never reaches the login handler).
- **Evidence:** `POST /api/v1/auth/login {"email":"nonexistent@qa.test",...}` -> 422 `{"detail":[{"type":"value_error","loc":["body","email"],"msg":"value is not a valid email address: The part after the @-sign is a special-use or reserved name..."}]}`; same call with `@example.com` -> 401 `{"detail":"Invalid email or password"}`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation (workaround: use `@example.com`-style addresses for any test persona that needs to authenticate through the real HTTP login path).
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-030: Weak, hardcoded default datastore credentials are actually in effect on the live Postgres container

- **Severity:** P2
- **Component:** `backend/app/core/config.py` line 39 (`database_url`); `docker-compose.yml` lines 6, 76, 115; dev-tree `.env`
- **Reproduction:** 1) Inspect `backend/app/core/config.py` line 39 and `docker-compose.yml` lines 6/41/76/115. 2) `grep -c '^POSTGRES_PASSWORD=' .env` in the dev tree returns 0, confirming no override. 3) Run `docker exec app-backend-1 python -c "from app.core.config import Settings; print('ioc:ioc@' in Settings().database_url)"` to confirm the default is the value actually in effect.
- **Expected:** A production-facing deployment should not be reachable with a well-known default database password baked into committed source/compose files, unless a deployment path explicitly generates a strong secret.
- **Actual:** `config.py:39` hardcodes `database_url: str = "postgresql+asyncpg://ioc:ioc@postgres:5432/ioc_intel"` and `:43` hardcodes `neo4j_password: str = "changeme-neo4j"`; `docker-compose.yml` mirrors this with `${POSTGRES_PASSWORD:-ioc}` and `NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:-changeme-neo4j}`. The dev-tree `.env` does not set `POSTGRES_PASSWORD`/`NEO4J_PASSWORD`/`POSTGRES_USER`/`POSTGRES_DB` at all. Verified live: the running `app-backend-1` container's actual `Settings()` object shows `database_url` still equals the literal default containing `ioc:ioc@` — the live Postgres instance backing this threat-intel platform is currently reachable with the well-known default password. (Neo4j's live password was separately confirmed NOT to be the default, so this specific weakness is Postgres-only in the current running instance.)
- **Root Cause:** Any deployment that skips the Windows setup wizard's random-secret generation (`windows/scripts/Write-EnvFile.ps1`'s `New-RandomSecret -Bytes 24` for PostgresPassword/Neo4jPassword) and just runs `docker compose up` silently falls back to these guessable defaults, with no startup check refusing to run with them.
- **Evidence:** `docker exec app-backend-1 python -c "from app.core.config import Settings; print('ioc:ioc@' in Settings().database_url)"` returned `True`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-031: Insecure hardcoded fallback JWT signing secret ships in source (secret-scan finding)

- **Severity:** P3
- **Component:** `backend/app/core/config.py` line 29 (`jwt_secret_key`)
- **Reproduction:** Inspect `backend/app/core/config.py` line 29. To reproduce impact: unset `JWT_SECRET_KEY` in the environment and start the backend — it will boot without error and accept the hardcoded default as its signing key instead of refusing to start.
- **Expected:** A missing `JWT_SECRET_KEY` in the environment should cause the application to fail to start (or at minimum log a loud warning), rather than silently signing/verifying all auth JWTs with a publicly-committed default string.
- **Actual:** `config.py:29` hardcodes `jwt_secret_key: str = Field(default="change-me-in-production")`. If `JWT_SECRET_KEY` is ever absent from the environment, the app starts successfully anyway and silently uses this exact string — letting anyone who has read this source file forge a valid access token for any user/role, with no startup warning or crash. Currently NOT the active value on either the dev-tree `.env` or the live container (both confirmed non-default, non-empty), so this is a latent/defense-in-depth gap rather than an active compromise today. (See BUG-050 for the same underlying issue re-identified independently by a separate security-posture-review pass, with a different severity rating and additional impact analysis.)
- **Root Cause:** No startup guard checks `jwt_secret_key` against the literal default.
- **Evidence:** `docker exec app-backend-1 python -c "from app.core.config import Settings; print(Settings().jwt_secret_key == 'change-me-in-production')"` returned `False` (not currently exploited).
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-032: Hardcoded plaintext admin/analyst passwords committed in documentation walkthrough scripts

- **Severity:** P3
- **Component:** `documentation/build/walkthrough.js` lines 16-17; `documentation/build/walkthrough-admin.js` lines 14-15; `documentation/build/walkthrough-secassess.js` lines 13-14
- **Reproduction:** Read the three files at the line numbers above. Cross-check current DB state with `docker exec app-postgres-1 psql -U ioc -d ioc_intel -c "SELECT email FROM users;"` to confirm no matching live account exists today.
- **Expected:** Documentation/automation scripts should not commit real plaintext passwords for accounts that were ever created against the live application.
- **Actual:** `walkthrough.js` hardcodes `ADMIN_EMAIL = 'final-admin@example.com'` / `ADMIN_PASSWORD = 'FinalTestPass123!'`; `walkthrough-admin.js` hardcodes `ADMIN_EMAIL = 'docs-walkthrough-admin@example.com'` / `ADMIN_PASSWORD = 'WalkthroughQA-2026!'`; `walkthrough-secassess.js` hardcodes `ANALYST_EMAIL = 'secassess-walkthrough@example.com'` / `ANALYST_PASSWORD = 'WalkthroughQA-2026!'`. These scripts only type credentials into the live login form (no self-registration), meaning the accounts were manually created against the real running app at some point with these exact plaintext passwords.
- **Root Cause:** None of the three emails currently exist in the users table (18 total users, none matching), so there is no immediately exploitable live account right now, but the plaintext passwords remain permanently readable in the dev tree and would become live credentials again the moment any of these accounts is recreated with a matching password.
- **Evidence:** `walkthrough.js:17`: `const ADMIN_PASSWORD = 'FinalTestPass123!';`. `walkthrough-admin.js:15` / `walkthrough-secassess.js:14`: `const ...PASSWORD = 'WalkthroughQA-2026!';`. `SELECT email,role FROM users;` lists 18 users, none matching the three emails above.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-033: Frontend pins next==14.2.15, which has 30 confirmed advisories including a critical middleware auth-bypass

- **Severity:** P2
- **Component:** `frontend/package.json` (`next` dependency)
- **Reproduction:** `docker exec app-frontend-1` (or host) `npm audit --omit=dev` inside `frontend/`; or POST `{"package":{"name":"next","ecosystem":"npm"},"version":"14.2.15"}` to `https://api.osv.dev/v1/query`.
- **Expected:** The internet/LAN-facing web tier should be kept reasonably current against known Next.js CVEs, especially patch-only fixes.
- **Actual:** Direct OSV.dev query for `next` 14.2.15 returned 30 vulns, including GHSA-f82v-jwr5-mffw/CVE-2025-29927 "Authorization Bypass in Next.js Middleware" (CVSS 9.1, fixed in 14.2.25) and clusters of SSRF, HTTP request smuggling, XSS, and cache-poisoning advisories. `npm audit --omit=dev` independently flagged the same `next` range as critical.
- **Root Cause:** Version has not been bumped since pinning; most attack-surface clusters (middleware, rewrites/i18n, Server Actions, Image Optimization) were checked and ruled out for this specific deployment (no app-owned `middleware.ts`, no rewrites/i18n config, no `"use server"`/`next/image`/`remotePatterns` usage), but a residual cluster of React-Server-Component cache-poisoning/confusion advisories inherent to App Router's RSC machinery is NOT ruled out regardless of app-code usage. 14.2.15 is nearly a year of patch releases behind 14.2.x HEAD.
- **Evidence:** OSV query from `app-backend-1`: 30 vulns incl. GHSA-f82v-jwr5-mffw. `find frontend -iname 'middleware.*'` returns only `node_modules/.next` paths. grep for `'"use server"|next/image|remotePatterns'` under `frontend/app`/`frontend/components`: no matches.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation (recommended: patch-level bump, lowest-risk highest-value item in the whole dependency inventory).
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-034: Backend pins cryptography==43.0.1, which has 11 advisories in certificate-validation logic

- **Severity:** P2
- **Component:** `backend/requirements.txt` (`cryptography`); `backend/app/core/crypto.py` (Fernet, credential encryption-at-rest); `backend/app/security_assessment/tls_tool.py` (X.509 cert parsing)
- **Reproduction:** `docker exec app-backend-1 python -c "import urllib.request,json; print(urllib.request.urlopen(urllib.request.Request('https://api.osv.dev/v1/query', data=json.dumps({'package':{'name':'cryptography','ecosystem':'PyPI'},'version':'43.0.1'}).encode(), headers={'Content-Type':'application/json'})).read())"`.
- **Expected:** A library used both to protect at-rest secrets and to parse/validate X.509 certificates from scan targets should not be sitting on a pin with known certificate-validation CVEs.
- **Actual:** Direct OSV query for `cryptography` 43.0.1 returned 11 vulns: two "vulnerable OpenSSL bundled in cryptography wheels" advisories, plus four 2026-dated cert/crypto-validation issues — CVE-2026-69248 (wildcard-DNS-name verifier escape), CVE-2026-34073 (incomplete DNS name constraint enforcement), CVE-2026-69249 (duplicate self-signed intermediates -> exponential path-building DoS), CVE-2026-26007 (missing subgroup validation for SECT curves, signature-forgery-class).
- **Root Cause:** Pin not bumped past 43.0.1 despite this library being used in exactly the two places these CVEs affect (secrets-at-rest and TLS certificate parsing). No PoC built exploiting these specific CVEs against `tls_tool.py` — treated as a verified version-currency/exposure finding, not a demonstrated exploit.
- **Evidence:** OSV query for `cryptography==43.0.1` returned 11 vulns incl. GHSA-m2h6-j472-rp4c/CVE-2026-69248, GHSA-m959-cc7f-wv43/CVE-2026-34073, GHSA-jwv3-5hgf-82ww/CVE-2026-69249, GHSA-r6ph-v2qm-q3c2/CVE-2026-26007. grep confirms usage in `backend/app/core/crypto.py`, `backend/app/models/runtime_config.py`, `backend/app/security_assessment/tls_tool.py`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-035: fastapi pulls in starlette 0.38.6 (unpinned, transitive), which has 14 advisories

- **Severity:** P3
- **Component:** `backend/requirements.txt` (`fastapi==0.115.0`, transitively resolves `starlette` 0.38.6, not directly pinned)
- **Reproduction:** `docker exec app-backend-1 pip show starlette`; then query `https://api.osv.dev/v1/query` with `{package:{name:'starlette',ecosystem:'PyPI'},version:'0.38.6'}`.
- **Expected:** A transitive dependency this central to the request-handling stack should ideally be pinned directly so a routine `fastapi` upgrade doesn't silently change it, and known-vulnerable code paths should be checked for actual reachability.
- **Actual:** Direct OSV query for starlette 0.38.6 returned 14 vulns spanning 2024-2026: multipart/form-data DoS, urlencoded-form DoS, Host-header/path poisoning, StaticFiles SSRF/NTLM-credential-theft via UNC paths on Windows, arbitrary HTTP-method dispatch via `HTTPEndpoint` `getattr`.
- **Root Cause:** `starlette` is not listed directly in `requirements.txt` — resolves transitively via `fastapi==0.115.0`. grep confirmed zero app-owned use of `UploadFile`/`Form(`/multipart, `StaticFiles`/`HTTPEndpoint`/Host-header trust anywhere in `backend/app` (only inside vendored `.venv`), and the app runs Linux containers in production (the Windows-only UNC-path CVE is moot). Real exploitability today looks low because the vulnerable code paths aren't exercised, but the unpinned transitive dependency means a routine `pip install -U fastapi` later will silently change it.
- **Evidence:** `docker exec app-backend-1 pip list` shows `starlette 0.38.6` though it's absent from `requirements.txt`. OSV query returned 14 vulns incl. GHSA-86qp-5c8j-p5mr/CVE-2026-48710, GHSA-wqp7-x3pw-xc5r/CVE-2026-48818, GHSA-x746-7m8f-x49c/CVE-2026-48817.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation (recommended: pin starlette explicitly, or upgrade fastapi to pull a patched version, as routine hygiene).
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-036: python-jose==3.3.0 carries a critical algorithm-confusion CVE and a JWT/JWE-bomb DoS CVE

- **Severity:** P3
- **Component:** `backend/requirements.txt` (`python-jose==3.3.0`); `backend/app/auth/security.py`; `backend/app/core/config.py` (`jwt_algorithm = "HS256"`)
- **Reproduction:** Read `backend/app/auth/security.py` and `backend/app/core/config.py`; query `https://api.osv.dev/v1/query` with `{package:{name:'python-jose',ecosystem:'PyPI'},version:'3.3.0'}`.
- **Expected:** The library sitting on the authentication trust boundary should not be pinned to a version with an unpatched critical CVE for roughly three years.
- **Actual:** OSV confirms `python-jose` 3.3.0 is listed for GHSA-6c5p-j8vq-pqhj/CVE-2024-33663 ("algorithm confusion with OpenSSH ECDSA keys and other key formats", CVSS 9.3, fixed in 3.4.0) and a "JWT bomb" JWE decompression DoS (also fixed 3.4.0). Upstream had no releases between 3.3.0 (2021) and 3.4.0.
- **Root Cause:** This app's actual usage (`jwt.encode`/`jwt.decode` with a single, server-controlled `algorithms=[settings.jwt_algorithm]` allowlist, `HS256` only, no JWE anywhere) is not the vulnerable path either advisory describes (alg-confusion requires the verifier to accept multiple/asymmetric algorithms; the JWE-bomb requires decoding a JWE) — so not exploitable today via these two CVEs, but any future change (adding RS/ES256 support, or JWE) would need to happen only after upgrading past 3.4.0.
- **Evidence:** OSV query for `python-jose==3.3.0` returned GHSA-6c5p-j8vq-pqhj/CVE-2024-33663 and GHSA-cjwg-qfpm-7377, both "fixed in 3.4.0". `backend/app/auth/security.py` line 34: `jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)`; line 54: `jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])`. `backend/app/core/config.py` line 30: `jwt_algorithm: str = "HS256"`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-037: python-multipart==0.0.9 has a confirmed DoS CVE (fixed 0.0.18)

- **Severity:** P4
- **Component:** `backend/requirements.txt` (`python-multipart==0.0.9`)
- **Reproduction:** `grep -rln 'UploadFile' C:\Users\User\ioc-intel-platform\backend` (excluding `.venv`, `.venv_test`); query OSV for `python-multipart==0.0.9`.
- **Expected:** A pinned dependency should not sit 9 releases behind a known-DoS-fixed version, and `pip-audit`'s default run should surface this if relied upon as a signal (see BUG context: it does not — the false-negative behavior is noted informationally in the source, not triaged here as its own bug since it carries `info` severity).
- **Actual:** OSV confirms `python-multipart` 0.0.9 matches GHSA-59g5-xgcq-4qw3/CVE-2024-53981 (DoS via inefficient byte-at-a-time boundary skipping in malformed multipart/form-data, fixed in 0.0.18).
- **Root Cause:** grep across `backend/app` (excluding vendored `.venv`/`.venv_test`) for `UploadFile` and `Form(`/`OAuth2PasswordRequestForm` found zero matches in app-owned route code, and the login endpoint takes a JSON body, not a form — so the vulnerable multipart-parsing code path does not appear reachable through any endpoint this app currently defines. Low priority today; a future feature like bulk IOC CSV upload would silently inherit the flaw if added without first bumping this pin.
- **Evidence:** OSV query for `python-multipart==0.0.9` returned GHSA-59g5-xgcq-4qw3/CVE-2024-53981, "fixed 0.0.18". grep found no `UploadFile`/`Form(`/`OAuth2PasswordRequestForm` usage outside vendored site-packages.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-038: lxml==5.3.0 has a confirmed XXE CVE in its default iterparse()/ETCompatXMLParser() config

- **Severity:** P4
- **Component:** `backend/requirements.txt` (`lxml==5.3.0`); `backend/app/crawler/sources/rss_news.py` (`feedparser` untrusted RSS/Atom ingestion)
- **Reproduction:** Query OSV for `lxml==5.3.0`; `grep -rn 'iterparse|ETCompatXMLParser' C:\Users\User\ioc-intel-platform\backend\app`.
- **Expected:** A library used (via `feedparser`) to parse untrusted, externally-sourced RSS/Atom threat-news feeds should not carry a known XXE CVE in its default parser configuration without at least confirming the vulnerable code path is unreachable.
- **Actual:** OSV confirms `lxml` 5.3.0 matches GHSA-vfmq-68hx-4jfw/CVE-2026-41066: "Default configuration of iterparse() and ETCompatXMLParser() allows XXE to local files." `backend/app/crawler/sources/rss_news.py` uses `feedparser` to ingest external, untrusted RSS/Atom feeds, and `lxml` is present as an accelerator `feedparser` can use internally.
- **Root Cause:** grep across `backend/app` for direct calls to `lxml.etree`, `iterparse(`, `ETCompatXMLParser(`, or `BeautifulSoup(` found zero matches — the app never calls the specific vulnerable APIs itself. The tester did not audit `feedparser`'s or `BeautifulSoup`'s internal use of `lxml`, so internals hitting the vulnerable path cannot be ruled out; flagged as a verified-version/low-confirmed-exposure item.
- **Evidence:** OSV query for `lxml==5.3.0` returned GHSA-vfmq-68hx-4jfw/CVE-2026-41066. grep for `'iterparse|ETCompatXMLParser|lxml\.etree|BeautifulSoup\('` across `backend/app`: no matches. `feedparser` used only in `backend/app/crawler/sources/rss_news.py`.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation (recommended: cheap patch-level bump given the untrusted-feed-ingestion role).
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-039: No request-correlation ID anywhere in backend logs

- **Severity:** P1
- **Component:** `backend/app/main.py`
- **Reproduction:** 1. Have two or more concurrent callers each run `POST /api/v1/lookup/stream` for different IOC values at roughly the same time. 2. Run `docker logs -t app-backend-1 --tail 200` immediately after. 3. Attempt to determine, using log content alone (no DB access), which `httpx: HTTP Request` lines belong to which of the concurrent lookups — there was no field that let you group them.
- **Expected:** Every log line produced in service of a given request should carry a stable, shared identifier so an operator can reconstruct which log lines belong to which request, especially under concurrent load.
- **Actual:** A repo-wide search (`grep -rn 'request_id|correlation_id|X-Request-Id|X-Correlation'` over `app/`) returned zero matches outside throwaway QA scripts. `app/main.py` registered only `CORSMiddleware` and the Prometheus `Instrumentator` — no request-ID middleware, no `contextvars`-based logging context, no OpenTelemetry/Sentry/Jaeger integration. During a single lookup, concurrent `POST /api/v1/lookup/stream` 200s and their httpx provider-fanout lines were all logged identically with nothing but an ephemeral source `ip:port` in common — the only way to distinguish one's own httpx lines from a concurrent run's was recognizing the literal `ioc_value` string in the URL.
- **Root Cause:** No middleware ever generated or propagated a per-request identifier into the logging context.
- **Evidence:** During one lookup (lookup_id `28943dda-20ee-44fb-848a-d6b978bb1559`), `docker logs -t app-backend-1` in the same window showed interleaved `POST /api/v1/lookup/stream` 200s at ~12 different timestamps, each logged identically as `INFO: 127.0.0.1:PORT - "POST /api/v1/lookup/stream HTTP/1.1" 200 OK` with no lookup_id, ioc_value, user, or shared token.
- **Fix:** `backend/app/main.py` now has a `contextvars.ContextVar` set by a new `request_id_middleware`, read by a `logging.Filter` attached to the root logger's handler, rendered via an updated `logging.basicConfig` format string. Deliberately does NOT reset the contextvar in a `finally` — doing so would fire before a `StreamingResponse`'s body (e.g. `/lookup/stream`'s SSE generator) actually runs, since Starlette's `BaseHTTPMiddleware.call_next()` returns as soon as headers are ready, well before a streaming body is drained.
- **Regression Test:** None added — logging-format change, verified via live manual testing of concurrent requests plus the retry red-team pass.
- **Status:** FIXED (deployed, no dedicated test)

### BUG-040: Failed login attempts are invisible in application logs beyond a bare 401

- **Severity:** P1
- **Component:** `backend/app/api/routes/auth.py` (`login()`); `backend/app/core/users.py` (`record_login_failure()`/`record_login_success()`)
- **Reproduction:** 1. `POST /api/v1/auth/login` with a wrong password for any email. 2. `docker logs -t app-backend-1 --tail 60` immediately after — confirm the only line is the bare uvicorn access-log entry with status 401 and no email. 3. Compare against `SELECT * FROM config_audit_log WHERE action='auth.login_failed' ORDER BY timestamp DESC LIMIT 1` in Postgres, which does contain the targeted email (in free text).
- **Expected:** An incident responder tailing `docker logs` during a live credential-stuffing attack should be able to see which account is being targeted by a failed login.
- **Actual:** The only trace of a failed login in `docker logs` was uvicorn's generic access-log line, carrying no identity information at all. The targeted email was only recoverable via a direct Postgres query against `config_audit_log`, and even there `actor_email` itself was left NULL (the email is only present inside the free-text `detail` string).
- **Root Cause:** `login()` in `app/api/routes/auth.py` has zero `logger.*` calls. On failure it calls `record_login_failure(payload.email)`, which only writes a row to Postgres via `record_audit()` — it never touches Python's `logging` module.
- **Evidence:** After POSTing a wrong password for `qa-ent-obs-nope@example.com` (got back 401 as expected), the only corresponding line in `docker logs` was `INFO: 127.0.0.1:42430 - "POST /api/v1/auth/login HTTP/1.1" 401 Unauthorized`. The Postgres audit row read `detail = "Failed login attempt for email 'qa-ent-obs-nope@example.com'."` with `actor_email` NULL.
- **Fix:** `backend/app/core/users.py`'s `record_login_failure()`/`record_login_success()` now call `logger.warning`/`logger.info` respectively before writing the audit row.
- **Regression Test:** None added — pure logging addition; deployed live.
- **Status:** FIXED (deployed, no dedicated test)

### BUG-041: Security Assessment Toolkit runs produce zero application log output on success

- **Severity:** P1
- **Component:** `backend/app/security_assessment/*.py`; `backend/app/core/security_assessment.py` (`start_run()`/`_execute_run()`)
- **Reproduction:** 1. As an analyst-role user, POST `/api/v1/security-assessment/{lookup_id}/run` with `tool_ids: ["nmap"], profile: "quick", target_confirmation: "<the lookup's ioc_value>", authorization_confirmed: true` against a lookup seeded with `ioc_value` 127.0.0.1. 2. Poll `GET /api/v1/security-assessment/{lookup_id}/runs` until status is terminal. 3. `docker logs -t app-backend-1` — confirm no completion/finding-count line exists anywhere, only the initial request line, and the run_id is never printed in logs at all.
- **Expected:** An incident responder watching `docker logs` in real time should be able to tell that an active-scanning run (including real nmap scans) started, and see when/whether it completed and what it found.
- **Actual:** A real nmap 'quick' scan against 127.0.0.1 completed successfully with 1 finding, but the only related log line was the initial HTTP request (`POST .../run HTTP/1.1" 200 OK`), which revealed the lookup_id only because it's in the URL path — nothing else: not the run_id, tool, profile, completion, or finding count. `SELECT ... FROM config_audit_log` showed the full picture existed, just never reached stdout.
- **Root Cause:** None of the toolkit's tool adapters under `app/security_assessment/*.py` contain a single `logger.*` call. `app/core/security_assessment.py` only calls `logger.exception(...)` twice, both exclusively on the failure path — there is no `logger.info` for run start, tool invocation, or successful completion.
- **Evidence:** `docker logs -t app-backend-1` for run_id `aea6503a-fe73-439d-915a-b04f97b98c7f` (lookup `28943dda-...`) showed only the initial request line. `config_audit_log` showed `security_assessment.run_requested` and `security_assessment.run_completed` rows with full detail, never surfaced to stdout.
- **Fix:** `backend/app/core/security_assessment.py`'s `start_run()`/`_execute_run()` now call `logger.info()` on run request and completion respectively, mirroring the existing `logger.exception()` calls already present on the failure paths.
- **Regression Test:** None added — logging addition; deployed live.
- **Status:** FIXED (deployed, no dedicated test)

### BUG-042: structlog is configured but never used -- all real log output is unstructured plaintext

- **Severity:** P2
- **Component:** `backend/app/main.py` (lines 26-27: `logging.basicConfig` + `structlog.configure`)
- **Reproduction:** 1. `docker exec app-backend-1 grep -rln structlog /app/app` -> only `app/main.py`. 2. `docker logs -t app-backend-1 --tail 50` -> confirm every line is stdlib plaintext, not JSON.
- **Expected:** If `structlog.configure(processors=[structlog.processors.JSONRenderer()])` is present, structured JSON logs should actually be emitted for use by a log-aggregation pipeline.
- **Actual:** `structlog` is imported/configured only in `main.py` itself — no other file in the codebase (21 files use `logger = logging.getLogger` directly) ever calls `structlog.get_logger()`. Every observed log line was plaintext via `logging.basicConfig(level=logging.INFO)`, which also uses Python's default bare format with no app-emitted timestamp (only Docker's own capture-time timestamp via `docker logs -t`).
- **Root Cause:** The `structlog` configuration is dead code.
- **Evidence:** `app/main.py` line 26: `logging.basicConfig(level=logging.INFO)` followed by line 27: `structlog.configure(...)`. Every observed log line across three test operations was plaintext, e.g. `INFO:httpx:HTTP Request: GET https://api.abuseipdb.com/... "HTTP/1.1 401 Unauthorized"` and `WARNING:app.ai.service:Provider summary generation failed for spamhaus: RuntimeError(...)` — never JSON, never containing an app-emitted timestamp or structured key/value.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-043: High-volume routine polling floods the log stream, burying security-relevant events in noise

- **Severity:** P2
- **Component:** `frontend` polling of `POST /api/v1/runtime/ai-active`; backend uvicorn access logging (no severity/category distinction)
- **Reproduction:** 1. Load/leave the frontend open against the live backend for ~15 seconds. 2. `docker logs -t app-backend-1 --tail 60` — count the `runtime/ai-active` lines vs. any single security-relevant event in the same window.
- **Expected:** Routine, high-frequency polling traffic should be distinguishable from (or filterable separately from) security-relevant single-line events like a failed login, so an operator scanning logs doesn't have to visually pick one line out of dozens of near-identical ones.
- **Actual:** The frontend appears to poll `POST /api/v1/runtime/ai-active` roughly every 250-300ms, and each poll produces its own uvicorn access-log line indistinguishable in format/verbosity from a security-relevant event. `docker logs --tail 60` captured 40+ `runtime/ai-active` 200 OK lines in a ~15-second window, with the single failed-login 401 line sandwiched in the middle, visually indistinguishable in format/color/level from the noise around it.
- **Root Cause:** No severity/category distinction beyond URL path, and no correlation ID (see BUG-039) to filter by.
- **Evidence:** `docker logs -t app-backend-1 --tail 60` immediately after the failed-login test: 40+ lines of `INFO: 127.0.0.1:38070 - "POST /api/v1/runtime/ai-active HTTP/1.1" 200 OK` across ~15 seconds (roughly one every 275ms), with the single `"POST /api/v1/auth/login HTTP/1.1" 401 Unauthorized` line sandwiched in the middle.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-044: Prometheus metrics provide no per-incident detail (no correlation with logs, no per-user/IOC labels)

- **Severity:** P3
- **Component:** `prometheus_fastapi_instrumentator` `/metrics` endpoint
- **Reproduction:** `curl http://localhost:8000/metrics | grep http_requests_total` — observe labels are limited to handler/method/status, nothing more granular.
- **Expected:** Aggregate metrics are a useful trend signal, but an incident investigation needs the ability to tie an anomaly back to specific requests/users/IOCs.
- **Actual:** `/metrics` is live and tracks `http_requests_total{handler=...,method=...,status=...}` counters, which would let an operator notice e.g. an elevated 4xx rate on `/auth/login` or `/lookup/stream` on a dashboard — but these are pure aggregate counters with no exemplar linking a specific metric increment back to a specific log line, trace, user, or request, and no latency histogram was observed being scraped either.
- **Root Cause:** No exemplar/trace-linking or per-actor labeling is configured on the Prometheus instrumentation.
- **Evidence:** `curl http://localhost:8000/metrics` returned real counters, e.g. `http_requests_total{handler="/api/v1/lookup/stream",method="POST",status="4xx"} 8.0` and `http_requests_total{handler="/api/v1/auth/login",method="POST",status="2xx"} 5.0` — confirming metrics infrastructure is present and functioning, but with no per-request or per-actor granularity.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation. This is noted as a partial mitigant to BUG-039/BUG-040/BUG-041/BUG-043, not a standalone defect requiring urgent action.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-045: ADMIN_GUIDE.md self-contradicts on whether provider-management UI and the audit log exist

- **Severity:** P1
- **Component:** `docs/ADMIN_GUIDE.md` §5 (summary table) vs. §1/§2
- **Reproduction:** 1) Log in as an admin. 2) GET/navigate to http://localhost:3000/providers -> 200, full tab UI renders, `GET /api/v1/runtime/ai-providers` returns real provider list (anthropic/gemini/groq/ollama/bedrock) with `is_active`/`configured` flags. 3) Compare against ADMIN_GUIDE.md §5's table, which claims this is NOT IMPLEMENTED, and against its own §1/§2 sections which say it IS implemented.
- **Expected:** A single document should not contradict itself about whether a feature exists.
- **Actual:** ADMIN_GUIDE.md's own intro said "Provider/AI configuration also has its own UI at /providers," but its §5 summary table said "Manage providers via UI | NOT IMPLEMENTED -- provider:manage permission exists, no route uses it" and "View an audit log | NOT IMPLEMENTED -- audit:read permission exists, no route uses it." Live testing showed both are fully implemented: `/providers` renders a real "Manage Providers" page with AI Providers / IOC Providers / Audit Log / Network Access tabs, backed by working endpoints (200 for admin JWT, 403 for analyst JWT, confirming server-side RBAC is correctly enforced even though the doc claimed the feature didn't exist at all). The live active AI backend was actually flipped from ollama to groq and back via this UI, confirming it persists across reload.
- **Root Cause:** §5's summary table was not updated when the provider-management UI and audit log were implemented, leaving it out of sync with §1/§2 of the same document and with the live application.
- **Evidence:** ADMIN_GUIDE.md §5: "View an audit log | NOT IMPLEMENTED" and "Manage providers via UI | NOT IMPLEMENTED". Live: 200 `GET http://localhost:3000/providers`; 200 `GET /api/v1/runtime/ai-providers` (admin) vs. 403 (analyst); groq `is_active` flipped true->false->true across a real click+reload+revert cycle.
- **Fix:** Corrected the §5 summary table in `docs/ADMIN_GUIDE.md`.
- **Regression Test:** None added — documentation correction, not code.
- **Status:** FIXED (deployed, no dedicated test)

### BUG-046: USER_GUIDE.md's claim "exactly eight routes...nothing else exists" is false

- **Severity:** P1
- **Component:** `docs/USER_GUIDE.md` (route table; "Not implemented / planned" section)
- **Reproduction:** Log in as an admin persona and observe the persistent top nav renders 'Providers' and 'Administration' links for every session; navigate directly to `/providers` -- 200, full UI. Compare against USER_GUIDE.md's route table and 'Not implemented' section.
- **Expected:** The documented route inventory and "Not implemented" claims should match the real, live application.
- **Actual:** USER_GUIDE.md stated unconditionally: "There are exactly eight routes in the app. Nothing else exists," listing only /, /login, /register, /lookup/new, /lookup/[id], /basket, /cases, /cases/[id]. It also stated in "Not implemented / planned": "No admin/user-management UI... there is no in-app way to manage users or view an audit log." Both claims were contradicted live: `/providers` (a real, functioning Manage Providers page) and `/admin` ("Administration" nav item, visible only to an admin-role session) both exist and are reachable, and neither appeared in the eight-route table.
- **Root Cause:** The route table and "Not implemented" section were not updated when `/admin` and `/providers` were implemented.
- **Evidence:** Live page text dump for an admin session: "Investigate\nBasket\nCases\nProviders\nAdministration" in the nav bar, none of which appear in USER_GUIDE's eight-route table.
- **Fix:** Added the missing `/admin` and `/providers` routes to `docs/USER_GUIDE.md`; removed the false "no in-app way to manage users or view an audit log" claim.
- **Regression Test:** None added — documentation correction, not code.
- **Status:** FIXED (deployed, no dedicated test)

### BUG-047: USER_GUIDE.md omits the entire Security Assessment panel and AI Comparison section

- **Severity:** P1
- **Component:** `docs/USER_GUIDE.md` (panel-by-panel breakdown of `/lookup/new`)
- **Reproduction:** 1) Log in, run a lookup for 127.0.0.1 (or any IOC), let the SSE stream finish. 2) Scroll to the bottom of the page -- a 'Security Assessment' card is present with tool checkboxes, a target-confirmation box, an authorization checkbox, and a 'Run Security Assessment' button. 3) Select 'Nmap Port/Service Scan', type '127.0.0.1', check the authorization box, click Run -- a real scan executes and returns a finding row. 4) Grep QUICKSTART.md/USER_GUIDE.md/ADMIN_GUIDE.md for 'Security Assessment' -- zero matches in any of the three.
- **Expected:** An exhaustive, panel-by-panel documentation breakdown of a page should include every real panel present on that page.
- **Actual:** USER_GUIDE.md listed every main-column and post-done panel on `/lookup/new` in detail (ThreatScoreGauge, ProviderCardGrid, FinalAssessmentPanel, RelationshipGraph, MitreMatrix, DetectionRulesPanel, RecommendedActionsPanel, VerdictAnalysisPanel, EvidencePanel, PivotPanel, HuntingCenterPanel, InvestigationCopilot) but never mentioned a "Security Assessment" panel, even though it is present on that exact page and is a real, active-scanning feature (Nmap Port/Service Scan, TLS Certificate Inspection, HTTP Security Headers, gated behind a retype-the-target confirmation box and an authorization checkbox). A user relying solely on the three named docs would have no way to discover this feature exists at all. The same page also has an "AI Comparison" section ("Analyze with..." picker showing Original/Ollama/Gemini) likewise absent from USER_GUIDE's FinalAssessmentPanel description.
- **Root Cause:** The panel-by-panel breakdown was not updated when the Security Assessment feature and AI Comparison section were added to the `/lookup/new` page.
- **Evidence:** Live run result captured in the UI: "nmap (quick) completed / Severity: info / Finding: Open port tcp/8000". grep -i 'security assessment' across docs/QUICKSTART.md, docs/USER_GUIDE.md, docs/ADMIN_GUIDE.md: no files found.
- **Fix:** Added the "Security Assessment" panel and "AI Comparison" section to `docs/USER_GUIDE.md`'s panel breakdown.
- **Regression Test:** None added — documentation correction, not code.
- **Status:** FIXED (deployed, no dedicated test)

### BUG-048: /providers renders blank content for a non-admin role with no access-denied message

- **Severity:** P2
- **Component:** `frontend` `/providers` page
- **Reproduction:** Log in as an analyst-role user. Navigate to /providers. Observe page chrome renders normally but the content area under any tab is blank. Open the network tab: 403 GET http://localhost:8000/api/v1/runtime/ai-providers / /runtime/ioc-providers / /runtime/audit-log.
- **Expected:** When the backing APIs correctly 403 a non-admin user, the page should show an access-denied message or otherwise explain the empty state, rather than presenting silently blank content.
- **Actual:** An analyst-role session can load `/providers` and see the page header, description text, and all four tab buttons ('AI Providers', 'IOC Providers', 'Audit Log', 'Network Access'); clicking any tab produces a completely empty content area with zero error text, toast, or 'access denied' messaging.
- **Root Cause:** The backend correctly returns 403 for `GET /api/v1/runtime/ai-providers`, `/runtime/ioc-providers`, and `/runtime/audit-log` for an analyst JWT (this is not an RBAC/security bug), but the frontend gives no feedback at all when those calls fail with 403.
- **Evidence:** Captured browser console/network log: '403 GET http://localhost:8000/api/v1/runtime/ai-providers', '403 GET http://localhost:8000/api/v1/runtime/audit-log?limit=50', '403 GET http://localhost:8000/api/v1/runtime/ioc-providers' for a JWT with role:'analyst'; page innerText for the tab area was empty.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-049: USER_GUIDE.md's SSE-sequence notation reads as batched but the real stream interleaves per-provider

- **Severity:** P3
- **Component:** `docs/USER_GUIDE.md` (SSE event-sequence description) vs. `docs/QUICKSTART.md` (mermaid diagram)
- **Reproduction:** Run any lookup and capture the debug 'Event log' panel or raw SSE stream.
- **Expected:** Documentation describing the SSE event order should match the actual event order, and be internally consistent between the platform's own guides.
- **Actual:** USER_GUIDE.md states the order as 'detected -> N x provider_result -> N x provider_summary -> correlation -> final_assessment -> done', which read literally implies all provider_result events arrive before any provider_summary events. The actual captured event log interleaves them per provider (a provider's provider_result is immediately followed by that same provider's provider_summary, before the next provider's result appears), consistent with QUICKSTART.md's own mermaid loop diagram but not with USER_GUIDE's flatter notation.
- **Root Cause:** Documentation-clarity inconsistency between the two guides' descriptions of the same event stream; not a functional defect.
- **Evidence:** Captured live event log for a 127.0.0.1 lookup: 'provider_result: spamhaus (ok)' -> 'provider_summary: spamhaus' -> 'provider_result: internet_intelligence (ok)' -> 'provider_summary: internet_intelligence' -> ... -> 'correlation' -> 'final_assessment' -> 'done' -- i.e. per-provider pairing, not two separate batched phases.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-050: jwt_secret_key hardcoded fallback default has no startup guard (security-posture-review finding)

- **Severity:** P2
- **Component:** `backend/app/core/config.py` line 29 (`jwt_secret_key`); `backend/app/auth/security.py` lines 34/54; `backend/app/core/crypto.py` lines 14-45 (HKDF-derived at-rest encryption key)
- **Reproduction:** Not independently re-executed in this pass (evidence/reproduction fields marked "—" in source); see BUG-031 for the equivalent live verification steps against this same code path (`config.py` line 29 inspection; live check of whether the default is currently in effect).
- **Expected:** A default JWT secret should not be usable in a way that compromises both auth-token forgery AND stored-credential decryption with no startup-time detection.
- **Actual:** `backend/app/core/config.py:29` declares `jwt_secret_key: str = Field(default="change-me-in-production")`. This value is used directly to sign/verify every access/refresh token, and `backend/app/core/crypto.py:14-45` also derives the at-rest encryption key for stored provider/AI credentials from this same value via HKDF when `encryption_master_key` is unset — so a default JWT secret compromises both auth-token forgery AND stored-credential decryption. No code anywhere fails loudly, logs a warning, or refuses to start if this default is left in place. The disclosed real-world failure scenario: an operator deploying via `docker compose up` directly (bypassing the Windows Setup Wizard — e.g. a Linux/staging deployment, or someone who runs `cp .env.example .env` and forgets to fill in `JWT_SECRET_KEY`) ends up running with the literal default secret with zero warning; the exact default string is publicly visible in `.env.example` (`JWT_SECRET_KEY=replace-with-a-long-random-string`) and in `config.py`'s own default, letting anyone who finds it mint a valid admin JWT offline with no password or DB access needed. This specific live install was confirmed NOT using the default (a real 61-char generated secret, `is_default_jwt_secret: False`) because the Windows wizard's `New-RandomSecret` generates a real random 48-byte secret before ever writing `.env` — but that protection lives entirely in the installer script, not in the backend itself. Also observed in the same check: `environment: development` and `debug: True` are still the running values even in this installed/production-facing deployment, because `Write-PlatformEnvFile` never sets `ENVIRONMENT` or `DEBUG`, so `config.py`'s dev-oriented defaults silently carry into what's presented to the operator as a finished install.
- **Root Cause:** No startup guard checks `jwt_secret_key` (or `ENVIRONMENT`/`DEBUG`) against insecure defaults; the only protection against the default JWT secret being live is external to the backend (the Windows installer's secret-generation script), so any deployment path that skips the wizard has no safety net at all. (Same underlying gap as BUG-031, re-identified independently by the security-posture-review dimension with a different severity rating and the additional crypto.py/HKDF and environment/debug-default impact detail.)
- **Evidence:** Live check confirmed this specific instance's `database_url`/JWT secret are NOT the defaults (see BUG-031's evidence for the equivalent JWT-secret boolean check). `environment`/`debug` confirmed still `"development"`/`True` on this installed/production-facing deployment.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-051: Hard process kill leaves a lookup permanently stuck RUNNING (no Python cleanup can run)

- **Severity:** P1
- **Component:** `backend/app/main.py` (new `_recover_orphaned_running_lookups()` startup hook); `backend/app/api/routes/lookup.py` (`stream_lookup()`'s `except`/`finally` recovery paths, which cannot execute in this scenario)
- **Reproduction:** Start a real investigation; kill the backend container with `docker kill` (no grace period) mid-flight, simulating an OOM-kill or power loss; restart the container cleanly; query the lookup's status afterward.
- **Expected:** A lookup should not remain permanently stuck at `status=RUNNING` after the process that was running it is gone, even across a full container restart.
- **Actual:** Found via live chaos testing (not a synthetic test): a hard `docker kill` gives the backend process zero chance to run any Python cleanup. Confirmed live: started a real investigation, killed the container mid-flight, and the lookup was left at `status=RUNNING` forever even after the container restarted cleanly. (By contrast, `docker restart`'s SIGTERM+grace-period was also tested and found to gracefully finish the in-flight request — that scenario is not broken.)
- **Root Cause:** Neither the route's `except` block nor its `finally` block's `GeneratorExit`-based recovery (see BUG-006's Root Cause for how that path normally works) can run in a hard-kill scenario, since the process is gone before any of that code executes.
- **Evidence:** Live end-to-end: after deploying the fix and restarting, the specific lookup that had been stuck RUNNING since the earlier hard-kill test was automatically recovered to FAILED.
- **Fix:** Added a new FastAPI startup hook, `_recover_orphaned_running_lookups()`, in `backend/app/main.py` — since a freshly-started process cannot yet be handling any request, any `IOCLookup` row already `status=RUNNING` at startup is necessarily orphaned from a previous, no-longer-running process instance, so it is unconditionally marked `FAILED`.
- **Regression Test:** `test_startup_recovers_lookups_orphaned_by_a_hard_kill` in `backend/app/tests/integration/test_lookup_stream_persistence.py` — passing.
- **Status:** FIXED (deployed + regression tested)

### BUG-052: GET /api/v1/runtime/audit-log has no upper bound on `limit` and no real pagination

- **Severity:** P2
- **Component:** `backend/app/api/routes/runtime.py` (audit-log endpoint); contrast with `GET /api/v1/lookup` (clamped to max 200)
- **Reproduction:** `GET /api/v1/runtime/audit-log?limit=5000` against the live append-only `config_audit_log` table.
- **Expected:** An append-only audit-log endpoint that will keep growing indefinitely should enforce a reasonable upper bound on `limit` and support real page-based pagination.
- **Actual:** `limit=5000` returned the entire 1142-row table in one 36ms response — no upper bound on `limit` and no real pagination. `GET /api/v1/lookup` is at least clamped to max 200, but neither endpoint implements real page-based pagination (no `page`/`total`/`has_more` in the response shape; `page`/`offset` params are silently ignored).
- **Root Cause:** No server-side clamp on the `limit` query parameter for the audit-log endpoint, and no page-based pagination contract implemented for either endpoint.
- **Evidence:** Confirmed live: `limit=5000` returned the entire 1142-row table in one 36ms response.
- **Fix:** Not fixed — disclosed; will not scale as the append-only audit table grows.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-053: Concurrent POST /lookup/stream throughput does not scale with concurrency

- **Severity:** P2
- **Component:** `backend/app/ai/service.py` / local Ollama process (single-instance-inference bottleneck); single uvicorn process (no `--workers`)
- **Reproduction:** Fire N concurrent `POST /lookup/stream` requests (N = 1, 5, 10) against the live deployment and measure completion time for each batch.
- **Expected:** Throughput should degrade gracefully, and ideally sub-linearly, as concurrency increases, without correctness or stability failures.
- **Actual:** 1 concurrent -> 32.6s, 5 concurrent -> 79.0s, 10 concurrent -> 189.7s (all 100% success, zero failures — this is a latency/queueing issue, not a correctness or stability bug). This is a cleaner, unconfounded re-measurement of the same underlying bottleneck disclosed in BUG-005 (which was confounded by a concurrent sibling QA process's AI-backend churn during that earlier run).
- **Root Cause:** Every investigation's AI calls funnel through a single local Ollama process that can only run one inference at a time, so concurrent investigations serialize against that one shared resource.
- **Evidence:** Measured completion times: 1 concurrent = 32.6s, 5 concurrent = 79.0s, 10 concurrent = 189.7s, all with 100% success and zero failures.
- **Fix:** Not fixed — disclosed as an inherent limitation of this deployment (single local Ollama process); not tested beyond 10 concurrent (explicit environment limitation — single dev machine, would only stack more queued inference calls without exercising new code).
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed)

### BUG-054: robocopy-propagated files survive a "keep data" uninstall as orphaned, untracked files

- **Severity:** P2
- **Component:** Windows installer (Inno Setup `[Files]`/uninstall log); `C:\Program Files\IOC Intelligence Platform\app` (installed copy)
- **Reproduction:** Propagate a file into the installed copy via `robocopy` from the dev tree (not via Setup.exe); run a real silent, keep-data uninstall; check whether the file survives; then run a real reinstall via a freshly-recompiled installer and check whether its content is refreshed.
- **Expected:** Files present in the installed copy should either be tracked by the installer's own uninstall log (and removed on uninstall) or not be present via any mechanism other than the installer.
- **Actual:** Files added to the installed copy via any out-of-band mechanism other than running the official Setup.exe (this entire QA session's own method of deploying every fix today: direct `robocopy` propagation from the dev tree, used because there's no way to safely automate the GUI reinstall wizard) are not tracked by Inno Setup's own uninstall log and therefore survive a "keep data" uninstall as orphaned files. Confirmed live: after a real uninstall (silent, keep-data mode) followed by a real reinstall via a freshly-recompiled installer, real application source files (`admin.py`, `security_assessment.py`, `SecurityAssessmentPanel.tsx`, and several test files) that had only ever been propagated via robocopy (never via any Setup.exe run) were still present after uninstall — though the subsequent reinstall's own `[Files]` copy step did correctly refresh their content to match the current dev tree. The uninstall->reinstall cycle itself was otherwise a full, clean pass: zero data loss (94 historical lookups + both real admin accounts survived), Alembic migrations correctly stayed at head (`6d2f4b8e1a7c`), and a real end-to-end investigation completed successfully immediately after reinstall.
- **Root Cause:** Inno Setup's uninstall log only tracks files it itself copied via the `[Files]` section during a Setup.exe run; any file placed in the installed directory tree by an external tool (robocopy) has no corresponding uninstall-log entry, so the uninstaller has no record telling it to remove that file.
- **Evidence:** Files present and unchanged in content immediately after a "keep data" uninstall: `admin.py`, `security_assessment.py`, `SecurityAssessmentPanel.tsx`, and several test files, all previously propagated only via robocopy. Post-reinstall, the same files' content was correctly refreshed to match the dev tree by the reinstall's own `[Files]` copy step. 94 historical lookups and both real admin accounts confirmed to survive the cycle; Alembic head confirmed at `6d2f4b8e1a7c`; a real end-to-end investigation completed successfully post-reinstall.
- **Fix:** Not fixed — disclosed as an inherent limitation: there is no way to safely automate the GUI reinstall wizard, so robocopy propagation was used for every fix deployed in this QA cycle, and Inno Setup has no mechanism to track files it did not itself place.
- **Regression Test:** None added — this is a packaging/installer-process limitation, not application code.
- **Status:** OPEN (disclosed, not fixed)

### BUG-055: Debug/QA harness scripts that bypass auth and audit trails are baked into the shipping installer and live inside the running production containers

- **Severity:** P1
- **Component:** `windows/installer.iss` (`[Files]` section, Excludes list); installed copy `C:\Program Files\IOC Intelligence Platform\app\backend\_qa_break_ollama.py`, `_qa_rate_limit_test.py`, `_qa_stream_lookup.py`, `cleanup_qa_users.py`; `docker-compose.yml` (`./backend:/app` bind mount shared by the backend, celery_worker, and celery_beat services)
- **Reproduction:** On the live install: `diff -rq "C:\Users\User\ioc-intel-platform\backend" "C:\Program Files\IOC Intelligence Platform\app\backend" -x __pycache__ -x *.pyc -x .pytest_cache -x celerybeat-schedule -x nul` shows four extra files present only in the installed copy; `docker exec app-backend-1 sh -c "ls -la /app/cleanup_qa_users.py"` shows it live inside the running backend container.
- **Expected:** Only files present in the dev tree (and covered by the installer's own Excludes list) should ever ship in a compiled installer or end up inside the running production containers; ad-hoc scratch/debug scripts that bypass authentication and audit trails should never reach a shipping build.
- **Actual:** Four scratch QA scripts (`_qa_break_ollama.py`, `_qa_rate_limit_test.py`, `_qa_stream_lookup.py`, `cleanup_qa_users.py`) exist in the installed copy but not anywhere in the current dev tree, and are not matched by `installer.iss`'s Excludes list (`__pycache__,*.pyc,.pytest_cache,celerybeat-schedule,nul` — no pattern for scratch scripts). They were captured into the already-compiled `release\IOC-Intelligence-Platform-Setup-0.1.0.exe` while transiently present in the dev tree during today's QA session, then deleted from the dev tree without the installer ever being rebuilt; tonight's real "keep data" uninstall+reinstall cycle (which necessarily used that stale, already-compiled binary) reintroduced all four into the fresh install. Because `backend`, `celery_worker`, and `celery_beat` all bind-mount `./backend:/app`, the files are not inert — they are live, executable (`-rwxr-xr-x`, root-owned), and reachable at `/app/*.py` inside the currently-running production containers right now.
- **Root Cause:** Inno Setup's `[Files]` Source line for the backend tree uses a wildcard with an Excludes list that only covers build/cache artifacts, with no pattern excluding ad-hoc scratch/debug scripts — anything present in the dev tree at build time, sanctioned or not, gets baked into the compiled installer permanently. Once a script is captured into a compiled build and then deleted from the dev tree, there is no "propagate + rebuild" path that fixes an already-installed copy: rebuilding the installer only stops *new* installs from getting the file; the existing install has no record telling it to remove something Inno Setup itself never tracked as having installed it in the first place.
- **Evidence:** NTFS timestamp forensics: all four files share an identical `CreationTime` of `2026-08-16 00:24:00` (tonight's reinstall moment) while each preserves its own distinct, original `LastWriteTime` from Aug 14-15 — the exact signature Inno Setup's file-copy leaves (destination ctime = copy time, mtime preserved from source), and the fact that all four share one common CreationTime (rather than staggered times) further confirms they arrived via a single bulk `[Files]` copy, not piecemeal manual propagation. `release\IOC-Intelligence-Platform-Setup-0.1.0.exe`'s own `LastWriteTime` (2026-08-15 22:00:29) postdates all four files' last-write times, confirming they existed in the dev tree at build time. `docker exec app-backend-1 sh -c "ls -la /app/_qa_break_ollama.py /app/_qa_rate_limit_test.py /app/_qa_stream_lookup.py /app/cleanup_qa_users.py"` returned all four as `-rwxr-xr-x root root`, live inside the running container via the bind mount. Content review confirmed the danger is not theoretical: `cleanup_qa_users.py` performs raw, unauthenticated SQLAlchemy deletion of `User`/`ConfigAuditLog` rows with no RBAC check and no audit trail beyond a `print()`; `_qa_break_ollama.py` calls the exact same `app.core.runtime_config.upsert_ai_provider()` the real authenticated admin route uses, but with `actor_user_id=None`, silently repointing the live AI provider's base_url outside any HTTP auth and leaving a `config_audit_log` row attributed to no real actor; `_qa_rate_limit_test.py`/`_qa_stream_lookup.py` mint arbitrary-role JWTs in-process and fire real investigations, bypassing auth entirely. Independently re-verified live by a second agent, who reproduced every element of this finding end-to-end (directory diff, timestamps, live container contents, and the four files' actual contents) and found nothing to refute.
- **Fix:** FIXED. Deleted all four stray files from the installed copy's on-disk source (`C:\Program Files\IOC Intelligence Platform\app\backend\`), added an Excludes pattern (`_qa_*.py,cleanup_qa_*.py`) to `windows/installer.iss`'s `[Files]` section to prevent recurrence, then rebuilt and redeployed the backend image. Live-confirmed post-rebuild: `docker exec app-backend-1 sh -c "ls /app/_qa_break_ollama.py /app/_qa_rate_limit_test.py /app/_qa_stream_lookup.py /app/cleanup_qa_users.py"` returns "No such file or directory" for all four.
- **Regression Test:** None added (file-hygiene/packaging fix, not application logic).
- **Status:** FIXED (deployed, no dedicated test) — independently verified prior to fix; fix confirmed live post-deployment.

### BUG-056: SecurityAssessmentRun rows get permanently stuck in RUNNING after a backend crash -- the orphaned-lookup recovery sweep doesn't cover this sibling subsystem

- **Severity:** P1
- **Component:** `backend/app/main.py` (`_recover_orphaned_running_lookups()`, added for BUG-051, scoped only to `ioc_lookups`); `backend/app/core/security_assessment.py` (`start_run()`, `_execute_run()`, `_spawn_background()`); `backend/app/models/security_assessment.py` (`SecurityAssessmentRun`); `backend/app/api/routes/security_assessment.py` (no cancel/retry/delete route); `backend/app/workers/celery_app.py` (beat_schedule has no equivalent sweep, only the hourly OSINT crawl)
- **Reproduction:** 1) Create/authenticate as an ANALYST-role user. 2) Create an `IOCLookup` for a scannable IOC type. 3) POST /api/v1/security-assessment/{lookup_id}/run with `tool_ids:["nmap"], profile:"standard"`, a slow-to-respond non-routable target (e.g. `192.0.2.0/24`), and `authorization_confirmed:true`. 4) Within ~1-5s (before the run reaches 'completed'), SIGKILL the backend process/container. 5) Restart the backend. 6) GET /api/v1/security-assessment/runs/{run_id} -- status remains 'running' forever with `completed_at=null`, and no request, cron, or startup hook will ever change it.
- **Expected:** A `SecurityAssessmentRun` uses the exact same "detached asyncio background task mutates `.status` outside any request lifecycle" pattern that `IOCLookup` used before BUG-051 was fixed, and should be equally protected by a startup recovery sweep (or an equivalent mechanism) after an abrupt backend crash/restart.
- **Actual:** `_recover_orphaned_running_lookups()` (added specifically to fix this exact failure mode for `IOCLookup`, per BUG-051) only issues `UPDATE ioc_lookups SET status='failed' WHERE status='running'` -- it has no equivalent statement for `security_assessment_runs`. Live-reproduced twice, independently, by two separate red-team lenses that had been given unrelated assignments: a genuine SIGKILL mid-scan (`docker kill --signal=SIGKILL app-backend-1` followed by `docker start`) leaves the run's row permanently `status='running'`, `completed_at=null`; a subsequent authenticated `GET /api/v1/security-assessment/runs/{run_id}` call confirms this is exactly what a real user/frontend would see forever, with no cancel/retry/delete endpoint anywhere on the router to recover it short of a manual DB UPDATE.
- **Root Cause:** `_execute_run()` (spawned via a detached `asyncio.create_task` in `_spawn_background()`, mirroring the IOCLookup investigation flow) sets `status=RUNNING` in one DB transaction, and only reaches the COMPLETED or FAILED transition via in-process Python control flow later; a SIGKILL between those two points leaves the row permanently RUNNING, with nothing else in the codebase -- no startup sweep, no Celery Beat task, no cancel/retry endpoint -- able to ever flip it. The tool's own internal timeout (`nmap_tool.py`'s `_TIMEOUT_SECONDS=120` subprocess kill) is irrelevant here since the whole async task, including the timeout-enforcing `wait_for`, dies with the process, not just the subprocess.
- **Evidence:** Two independent live reproductions: (1) run `ffaacee7-d324-48cf-9691-9e8a891f52d6` (target 192.0.2.77), observed `status='running'`, `completed_at=NULL` moments after a restart where `_recover_orphaned_running_lookups()` had run and found 0 `IOCLookup` rows to recover but touched nothing in `security_assessment_runs`; (2) a second, fully controlled repro against `45.33.32.156` (scanme.nmap.org): `docker kill` mid-scan (exit 137, confirmed true SIGKILL), `docker start`, then re-queried the same `run_id` both immediately and 30+ seconds later -- `status` remained `running`, `completed_at` remained `NULL` both times, and a real authenticated `GET /api/v1/security-assessment/runs/{run_id}` call confirmed the API itself reports this indefinitely. `backend/app/tests/integration/test_lookup_stream_persistence.py`'s `test_startup_recovers_lookups_orphaned_by_a_hard_kill` only asserts against `ioc_lookups`; no analogous test exists anywhere for `security_assessment_runs`. Independently confirmed twice more by two separate verification passes (one per original discovery), both concluding the finding stands; the second verifier's live repro was, in its own words, more conclusive than the original report's evidence since it held the same `run_id` through the entire kill-restart-recheck cycle without losing it to concurrent cleanup in this shared test environment.
- **Fix:** FIXED. Extended `backend/app/main.py`'s startup hook with a second sweep that marks every `SecurityAssessmentRun` row in `PENDING` or `RUNNING` status as `FAILED` (with an explanatory `error_message`) at every backend startup — mirroring the existing `IOCLookup` sweep. `PENDING` is swept too, not just `RUNNING`, closing the narrow window between `start_run()`'s initial commit and `_execute_run()`'s first status write. Deployed and regression tested.
- **Regression Test:** `test_startup_recovers_orphaned_security_assessment_runs` in `backend/app/tests/integration/test_lookup_stream_persistence.py` (seeds one PENDING and one RUNNING orphaned run, asserts both are recovered to FAILED) — passing. Full regression suite re-run after deployment: 229 passed / 14 skipped / 0 failed (container), 7 passed / 1 deselected (host-side file) — notably, the two previously-documented pre-existing `test_security_assessment_api.py` failures (an unrelated FK-cleanup race, tracked separately) did not reproduce on this run or a repeated isolated re-run, plausibly because this fix's sweep cleaned up orphaned rows left over from earlier chaos testing that were quietly interfering with that file's own assertions.
- **Status:** FIXED (deployed + regression tested) — independently verified prior to fix (found independently by two separate red-team lenses in the same round and confirmed by two separate verification passes; merged here into one entry rather than duplicated); fix confirmed live post-deployment.

### BUG-057: Background security-assessment runs are never re-authorized after the initial HTTP request, and there is no way to cancel an in-flight run

- **Severity:** P2
- **Component:** `backend/app/core/security_assessment.py` (`start_run()`, `_execute_run()`, `_refresh_lookup_assessment()`, `_spawn_background()`); `backend/app/auth/rbac.py` (`get_current_user()`/`require_permission()`, evaluated once per HTTP request only); `backend/app/api/routes/security_assessment.py` (router exposes only GET /profiles, GET /tool-health, POST /{lookup_id}/run, GET /{lookup_id}/runs, GET /runs/{run_id} -- no cancel/abort route)
- **Reproduction:** 1) Mint a JWT for an analyst. 2) POST /api/v1/security-assessment/{lookup_id}/run with `authorization_confirmed:true` against an IOC the analyst owns. 3) Immediately `UPDATE users SET is_active=false` (and/or `role='viewer'`) WHERE id=<that analyst>. 4) Poll GET /api/v1/security-assessment/runs/{run_id} and the lookup's final assessment -- observe the run completes and the lookup's primary assessment is refreshed despite the account no longer having any permission or even being able to log in.
- **Expected:** A subsystem that performs real active-scanning side effects (a real subprocess sending real network traffic), gated by a one-time authorization confirmation, should either re-check the requesting user's permission/account status before each side-effecting step, or provide an admin-facing way to abort an in-flight run -- especially since disabling an account or revoking a permission is exactly the kind of action an operator would take in response to a suspected compromise or scoping mistake.
- **Actual:** Live-tested: started a real nmap scan as a disposable analyst, then 67ms after the POST returned, set `is_active=False` on that user directly in the DB -- a subsequent request with their still-valid JWT was correctly rejected with 401 (confirming the per-request auth checks work as designed), and the same user's role was also demoted to viewer (removing `security_assessment:create`) before the run finished. The background task nonetheless ran to full completion ~15s later, then over the next ~2 minutes made two further AI calls under the same originating request_id and wrote a new primary `FinalAssessmentRecord` (final_verdict=MALICIOUS) plus correlation edges and evidence items onto the shared `IOCLookup` -- all attributed to the now-disabled, now-demoted user's `actor_user_id`.
- **Root Cause:** Permission and account-status checks happen exactly once, in the `require_permission` FastAPI dependency at the moment the initiating HTTP request is received. `start_run()` then spawns `_execute_run()` as a detached `asyncio.Task`; nothing inside `_execute_run()` or `_refresh_lookup_assessment()` ever re-checks the requesting user's permission, active flag, or role, and there is no cancel/abort endpoint anywhere on the router -- once a scan is authorized, it cannot be stopped short of restarting the backend process.
- **Evidence:** Code review of `app/core/security_assessment.py` (no permission re-check anywhere in the background path) and `app/api/routes/security_assessment.py` (no cancel/abort route). Live: POST /run -> 200 at t=0; `is_active=False` committed at t=0.067s; GET /profiles with the same token -> 401 at t=0.07s; role demoted to viewer before completion; run status still transitioned pending->running->completed at t=15.2s with 1 finding; `final_assessment_records`/`ai_summaries`/`correlation_edges`/`evidence_items` all populated minutes later using the disabled/demoted user's id. Independently reproduced by a second agent using a faster (`dns`) tool against a disposable domain lookup, confirming the identical sequence: POST -> 200 at t=0.026s, `is_active=false`+role demotion at t=0.064s, 401 on the same token at t=0.070s, run completed at t=1.119s with results persisted and attributed to the disabled/demoted user throughout.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation. May be an accepted design tradeoff (already-started work isn't revoked mid-flight, common in many systems, and each tool run is wall-clock capped at 120s), but per the verifying agent's own assessment it should be an explicit, documented decision rather than an undocumented gap, given the subsystem's real-world active-scanning side effects.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed) — independently verified.

### BUG-058: Orphaned-lookup recovery sweep has no instance/leader scoping -- would misfire the moment more than one backend process is ever live against the same DB

- **Severity:** P2
- **Component:** `backend/app/main.py` (`_recover_orphaned_running_lookups()`, lines ~145-176)
- **Reproduction:** Could not be fully reproduced against the live single-replica deployment (starting a second backend container against the shared production Postgres/Redis/Neo4j was correctly blocked by the permission system as a live-production-data risk). Verified instead via code review plus a safe live proxy test: insert one synthetic RUNNING row directly into `ioc_lookups`, unrelated to any real request or process history, then do a normal single-container `docker restart app-backend-1` -- the startup log emits "Recovered 1 lookup(s) orphaned..." and the synthetic row flips RUNNING->FAILED, proving the sweep cannot distinguish "orphaned by my own prior crash" from "any RUNNING row that happens to exist at boot."
- **Expected:** A recovery sweep whose safety argument is "since this process just started, no such request could exist yet" is only actually safe if no *other*, currently-live process could have a genuinely in-progress row at the same time -- i.e. it needs some form of instance/leader scoping (an instance ID, an advisory lock, a staleness/age filter) before it is safe under any deployment topology other than the exact one running today.
- **Actual:** The sweep performs an unconditional, unscoped `UPDATE ioc_lookups SET status='FAILED' WHERE status='RUNNING'` across the entire table -- no instance ID, no advisory lock, no leader election, and no staleness threshold. This is currently safe only because today's deployment happens to run a single named service, never scaled (confirmed via `docker inspect`: one `app-backend-1` container, no `--workers`, no `deploy.replicas`) -- an operational fact, not a code invariant. The moment an operator runs `docker-compose up -d --scale backend=2` for a blue-green rollout or capacity test, or this service is deployed to any real orchestrator (Kubernetes, Docker Swarm) where rolling updates deliberately keep old and new instances alive simultaneously, the new instance's startup sweep would immediately FAIL every genuinely in-progress investigation running on every other currently-healthy replica.
- **Root Cause:** The safety comment backing this code ("since this process just started, no such request could exist yet") is an argument about this process's own history only; the code does nothing to defend against a RUNNING row that belongs to a different, concurrently-live process.
- **Evidence:** `uvicorn`'s installed `Server.startup()` source confirms the sweep runs to completion before the process ever binds/listens, proving the single-replica case is provably safe today. `docker-compose.prod.yml`/`Dockerfile` confirmed to run a single uvicorn process with no scale directive. Grep across the backend tree for `advisory_lock|leader|singleton|instance_id` found nothing resembling cross-process coordination. The live proxy test (see Reproduction) confirmed the sweep blindly claims every RUNNING row in the table regardless of which process "owns" it. Independently re-verified by a second agent via the same code review plus an equivalent safe live test, reaching the same conclusion and noting that today's own concurrency/Ollama-serialization findings (BUG-005/BUG-053) make horizontal scaling a realistic near-term motivation for this platform, which would make this bug fire on essentially every rolling deploy rather than as a rare edge case.
- **Fix:** Not fixed — no remediation performed in this QA cycle; disclosed for remediation. Recommended: tag each row with an instance/process identifier at RUNNING-time, or add an age/staleness filter (e.g. only sweep rows older than N minutes) before this service is ever scaled beyond one replica.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed) — independently verified.

### BUG-059: Backend container crashed (exit 137) during rate-limit load testing and self-recovered; root cause not cleanly attributable

- **Severity:** P3
- **Component:** `app-backend-1` container (docker); `backend/app/main.py` (`_recover_orphaned_running_lookups()` -- confirmed to generalize correctly to this organic crash)
- **Reproduction:** Not independently reproduced in isolation (confounded by concurrent unrelated activity on the shared test environment). While firing real POST /lookup/stream requests to exhaust a test user's rate limit, `app-backend-1` exited with code 137.
- **Expected:** The backend should not crash under a single test user's rate-limit-exhausting load; if it does, the cause should be attributable and investigated.
- **Actual:** `app-backend-1` exited with code 137 (`docker inspect` reported `OOMKilled: false`, so not a conventional cgroup memory-limit kill); the restart policy brought the container back up within ~20 seconds, Alembic ran cleanly on restart, and the health endpoint returned 200 immediately after. `docker logs` in the ~90 seconds preceding the crash showed both the test's own traffic and unrelated concurrent activity from a different disposable user running Security Assessment Toolkit scans against non-routable targets, so the crash cannot be cleanly attributed to either process alone. After the auto-restart, `SELECT status, count(*) FROM ioc_lookups GROUP BY status` showed 21 FAILED / 77 COMPLETED / 0 RUNNING -- i.e. the BUG-051 orphaned-lookup recovery sweep correctly cleaned up whatever was in-flight at crash time, generalizing beyond the original manual SIGKILL test case to this second, organic crash.
- **Root Cause:** Not isolated -- reported as an observation, not a repeat of the already-completed intentional hard-SIGKILL chaos test (BUG-051), since the crash was not deliberately triggered and cannot be ruled out as caused by concurrent, unrelated activity in the shared test environment.
- **Evidence:** `docker inspect app-backend-1` showed `OOMKilled=false`, `exit=137` at the time of the crash. Post-restart lookup-status counts (21 FAILED / 77 COMPLETED / 0 RUNNING) confirm the recovery sweep worked correctly on this organic crash, not just the original synthetic one.
- **Fix:** Not fixed — disclosed as an unattributed observation, not a repeat of BUG-051. Recommended: re-run as a controlled experiment (a single session's sustained, non-cancelled load while monitoring `docker stats` memory growth for `app-backend-1`/`app-celery_worker-1`) to determine whether uncancellable lookup work (see BUG-060) alone is sufficient to reproduce this without concurrent unrelated activity.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed) — not independently verified (this round's verification pass only covered P0-P2 findings; this P3 observation was not selected for it).

### BUG-060: Very-early SSE client disconnect can leave a lookup permanently stuck in RUNNING until the next backend restart

- **Severity:** P2
- **Component:** `backend/app/api/routes/lookup.py` (`stream_lookup()`'s `event_stream()` generator -- specifically the disconnect window before the generator resumes past its first `yield`, which sits before the `async with new_session()`/try-finally block added for BUG-006/BUG-051)
- **Reproduction:** Mint a JWT for any real user, POST /api/v1/lookup/stream, and disconnect extremely early -- e.g. read only the first `detected` SSE frame (or just the response status line) and close the connection within roughly the first 50ms, before the generator has resumed execution past its initial `yield` and entered the try/finally-protected body. Repeated 5-7 times in the source testing; the lookup was left permanently in `status=RUNNING` with 0 `provider_results`, confirmed unchanged 5+ minutes later.
- **Expected:** A client disconnect, at any point in the SSE lifecycle, should leave the lookup in a terminal, non-RUNNING state (or otherwise be cleanly recoverable), consistent with the fixes already made for BUG-006 (mid-pipeline crash) and BUG-051 (hard process kill).
- **Actual:** This is the opposite failure mode from a related, ultimately-refuted finding from this same round (that disconnects don't stop backend work at all -- see note below). In fact, Starlette's `StreamingResponse` framework-level disconnect handling (an anyio task group racing `listen_for_disconnect(receive)` against `stream_response(send)`) does correctly cancel the SSE generator on a real client disconnect in the general case -- confirmed in the same testing: a disconnect ~12s into a real, in-progress pipeline (after 7 provider_result events had already streamed) correctly stopped further provider/AI work and flipped the lookup to FAILED within ~12 seconds. But for disconnects landing in the narrow window *before* the generator has resumed past its first `yield` (i.e. before it ever reaches the try/finally block that performs status-write cleanup), the cancellation lands somewhere that never executes any cleanup code at all, leaving the lookup permanently stuck in `status=RUNNING` with 0 provider_results.
- **Root Cause:** `event_stream()`'s cleanup logic (the except/finally blocks that mark a lookup FAILED on error, added/hardened for BUG-006 and BUG-051) only runs once the generator has entered its try block; a cancellation delivered while the generator is still suspended at its very first `yield` (before that block is entered) skips the block entirely, so no code path ever marks the row FAILED. Unlike a hard process kill (BUG-051, recovered by the startup sweep on the *next* restart), this leaves the row stuck for the remaining uptime of the current process, however long that is.
- **Evidence:** Reported directly by the agent independently verifying (and ultimately refuting) a different finding in this same round, "Aborted/cancelled SSE lookup requests still run to full completion server-side": across 7 real disconnected requests against the live `app-backend-1`, the earliest-disconnect variants (5 replicating that finding's own repro exactly, plus 1 even-faster ~49ms variant) left the lookup permanently in RUNNING with 0 provider_results and zero further backend activity logged, confirmed unchanged after 60+ seconds (and, for the fastest variant, after 5+ minutes) -- described by the reporting agent verbatim as "a real, different bug... a resource/visibility-leak bug, but it is the opposite failure mode of what's being reported" in the finding it was verifying.
- **Fix:** Not fixed — this bug was surfaced as a byproduct of an independent verification pass in this round (while disproving a different, now-excluded finding), not itself put through this round's formal red-team/verification pipeline. No remediation performed; disclosed for remediation. Recommended: move (or duplicate) the RUNNING-status write earlier, before the first `yield`, or wrap the entire generator body (including its first frame) in the try/finally cleanup so a cancellation at any point reaches cleanup code.
- **Regression Test:** None added.
- **Status:** OPEN (disclosed, not fixed) — single-source (one verification agent's live testing, reported in detail with reproducible steps); not independently re-verified by a separate third pass, since this exact scenario was not itself sent through this round's formal verification stage. Included here on its merits (concrete, reproducible, opposite-failure-mode evidence) rather than discarded along with the finding it was found while refuting.

**Note on an excluded finding from this same red-team round:** "Aborted/cancelled SSE lookup requests still run to full completion server-side -- client disconnect provides zero cost savings" (P2, from the rate-limit-key-reuse lens) is deliberately *not* included as a BUG-NNN entry. An independent verification agent re-tested it live (7 real disconnected requests, including an exact replication of the original repro) and found the opposite of its central claim: disconnected SSE requests do stop backend work (either immediately, before any provider fan-out, or within seconds of a mid-pipeline disconnect), rather than running to completion as originally reported. Given a direct, repeated, live contradiction of the specific claims in both the finding's title and its evidence section, this is treated as a refuted non-defect rather than a genuine bug. See BUG-060 above for the real, narrower, opposite-failure-mode defect the same verification pass discovered as a byproduct.
