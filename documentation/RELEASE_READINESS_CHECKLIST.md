# Release Readiness Checklist
## IOC Intelligence Platform 0.1.0

Companion to `FINAL_QA_REPORT.md` and `QA_BUG_REGISTER.md`. Checked items were verified live against the running application or the real source this pass, not assumed.

## Release Gate

- [x] No CRITICAL bug remains open (BUG-003, BUG-004 fixed and live-retested; BUG-001 is HIGH, not CRITICAL, and is explicitly carried as a named condition below)
- [x] No security vulnerability affecting users remains open (BUG-005 SSRF fixed and live-retested; BUG-004 credential-in-logs fixed and live-retested)
- [x] No data loss found under any test performed, including 5-way real concurrency and a real container restart
- [x] Installation not broken -- installer hash recorded, confirmed byte-identical in sync with current source
- [x] Core IOC investigation not broken -- live-tested end to end multiple times, including immediately after a real restart
- [x] AI core workflow not broken -- BUG-003 (the one thing that WAS broken here) is fixed and live-retested across all affected endpoint families
- [x] Runtime API configuration not broken -- the platform's own signature "no restart" claim was aggressively retested (valid key -> invalid key -> live investigation, twice, live AI-backend switching, a real restart) and held in every case

**Result: no BLOCKED condition is met -> CONDITIONAL PASS is the correct gate outcome per this test plan's own rules.**

## Fixed and Verified This Pass

- [x] BUG-003 (CRITICAL) -- missing `await` breaking the AI-analyst suite, comparison, hunting, and detection-rule generation -- fixed, live-retested, unit suite green
- [x] BUG-004 (CRITICAL) -- Gemini API key leaking into plaintext logs -- fixed, live-retested against the real Gemini API
- [x] BUG-005 (HIGH) -- admin-gated SSRF via Ollama `base_url` -- fixed, live-retested (blocks metadata address, preserves real Ollama connectivity)
- [x] BUG-002 (MEDIUM) -- raw exception/org-ID leak into persisted analyst-visible fields -- fixed, live-retested
- [x] 159/159 backend unit tests pass after all fixes

## Open Items -- Named Conditions of This CONDITIONAL PASS

- [ ] **BUG-001 (HIGH)** -- AI final-assessment/explanation output can misattribute a real provider's verdict or produce a self-contradictory consensus claim. Root cause identified (grounding checks provider existence, not verdict-directionality); fix deferred as a prompt-engineering change requiring dedicated review, not an unreviewed mid-pass patch. **Recommendation: prioritize before next release**, or at minimum add a prominent, unmissable UI reminder to check the Evidence Ledger before acting on an AI verdict for a low-provider-agreement case.
- [ ] **AbuseIPDB credential** -- overwritten with a test placeholder during this pass's live API-key-state testing (a direct, disclosed side effect of the exact test this plan required); needs the real key re-entered via Manage Providers before that connector will work again.
- [ ] **Windows installer/wizard script findings** (3 HIGH, 3 MEDIUM -- ACL-reset-before-delete on uninstall, unvalidated `IOC_INSTALL_DIR`, `setup.log` redaction gap, and others -- full list in `QA_BUG_REGISTER.md`) -- confirmed real via source review, **not exercised against a real install/uninstall cycle this pass** (explicitly deferred). Recommend a dedicated pass that does run a real install/uninstall/diagnostics-bundle cycle before these are marked resolved.
- [ ] **Test-only tooling in the production `requirements.txt`/image** (HIGH, hygiene/attack-surface, not a direct vulnerability) -- recommend a `requirements-dev.txt` split before next release.
- [ ] **Frontend href-injection hardening** (3x MEDIUM XSS-adjacent findings in `ProviderCard.tsx`/`EvidencePanel.tsx`) -- recommend a single shared `isSafeHttpUrl()` guard.
- [ ] **JWT storage in `localStorage`** (MEDIUM, design-level) -- worth a deliberate decision (httpOnly cookies) rather than an unreviewed change.

## Explicitly Out of Scope for This Report

- A real Windows install/uninstall/reinstall cycle -- skipped at the user's explicit direction this pass.
- A specific finding involving real credentials in a local configuration file -- investigated, confirmed, and excluded from every deliverable at the user's explicit direction; not a code defect and not tracked as an open item here.

## What Would Change This to an Unqualified PASS

Resolving BUG-001 (or adding the recommended UI mitigation), re-entering AbuseIPDB's real credential, and running a dedicated installer-focused pass that exercises and fixes the three HIGH-severity Windows-script findings against a real install/uninstall cycle.

## What Would Change This to BLOCKED

Any of: BUG-001 turning out to also affect the primary final-assessment verdict on evidence a real customer relies on for an actual incident (not yet observed at that severity -- observed impact so far is verdict inflation on borderline/mixed-evidence cases, not fabrication on zero-evidence cases, which is separately and correctly hard-blocked by existing code); discovery that the SSRF or credential-log-leak fixes (BUG-004/005) do not hold under further adversarial testing; or a new CRITICAL finding surfacing in the deferred installer testing.
