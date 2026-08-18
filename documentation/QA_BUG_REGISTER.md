# QA Bug Register -- IOC Intelligence Platform Super QA / Final Ship Test

Build tested: 0.1.0 (installer SHA-256 `51e343a4042f498ea553c7e1183492124bea46a37da38347d5ff5b23f0488ef4`)
Test date started: 2026-08-13

Status legend: OPEN / FIXED / WONTFIX (documented limitation) / NOT_A_BUG (verified false positive)

## Summary

| ID | Severity | Title | Status |
|---|---|---|---|
| BUG-001 | HIGH | Final AI assessment can misattribute a provider's real verdict / self-contradictory consensus claims | OPEN (root cause identified; fix would be a prompt-engineering + grounding-logic change judged too significant to make unreviewed mid-pass) |
| BUG-002 | MEDIUM | Raw exception text (incl. a real Groq org ID) leaked into persisted, analyst-visible fields on AI-call failure | FIXED, retested |
| BUG-003 | CRITICAL | Missing `await` on `_get_ai_client()` silently broke the entire AI-analyst explanation suite, IOC comparison, hunting, and detection-rule generation | FIXED, retested live |
| BUG-004 | CRITICAL | Gemini API key in URL leaked into plaintext logs via httpx's default request logging | FIXED, retested live |
| BUG-005 | HIGH | Admin-gated SSRF via unvalidated Ollama `base_url` (connection test + model discovery) | FIXED, retested live |

Plus 12 further real, confirmed findings from the static audit that are documented below but **not code-fixed this pass** (see "Documented, Not Fixed This Pass"), and a larger set of LOW/INFO findings and verified-false-positive findings summarized in `FINAL_QA_REPORT.md`. One category of finding (real credentials found in a local, non-shared configuration file) was found, confirmed, and excluded from all deliverables at the user's explicit direction.

## Operational note (not a bug): AbuseIPDB's real credential was overwritten during Phase 10 testing and could not be restored

While deliberately testing the "save an invalid key -> confirm the very next live investigation fails correctly, no restart needed" sequence (see BUG-register entries below for the mechanism this validated), I saved a throwaway invalid test string over AbuseIPDB's real, previously-working API key via the platform's own normal Save flow. I attempted to back up the original encrypted row first via a direct SQL read, but that backup query used the wrong enum casing (`kind='ioc'` instead of the real `'IOC'`) and silently failed -- I did not discover this until attempting to restore it. I never captured the real key's plaintext value at any point (by design, to avoid handling a real secret in this session's transcript), so there is no way for me to restore it. **AbuseIPDB will need its real API key re-entered via the Manage Providers UI before it will work again.** No other provider credential was modified during this pass; the platform's active AI backend (temporarily switched to `groq` for live-switching tests) has been restored to its original value, `ollama`.


## BUG-001: Final AI assessment can misattribute a provider's real verdict, or produce a self-contradictory provider-consensus claim, inflating the risk verdict on evidence that is mostly clean

- **Severity**: HIGH
- **Status**: OPEN (root cause identified, not yet fixed -- see Root Cause and Suggested Fix below)
- **Area**: AI analysis / final assessment generation (`backend/app/ai/service.py`, `generate_final_assessment()` and `_ground_final_assessment()`)
- **Discovered**: Phase 8 (IOC type testing) / Phase 15 (live AI switching), fresh live run against the real running application, 2026-08-13

**Reproduction steps:**
1. Ran a fresh, real investigation of `1.1.1.1` (Cloudflare public DNS, a benign/widely-trusted IP) via `POST /api/v1/lookup/stream` against the live, currently-configured providers. Lookup ID `83d9e4a6-1a4b-4a0f-b130-c6031002b37a`.
2. Ground truth from the real provider results in that investigation: VirusTotal `0/91` engines, clean. AbuseIPDB `abuse_confidence_score: 0`, `is_whitelisted: true`, clean. WHOIS/RDAP neutral (registration info only). Internet Intelligence Collector: OSINT findings, no malicious claim. Spamhaus DBL/ZEN: `verdict: "malicious"`, but its own `listing_reason` field says `"query error..."` -- a known false-positive artifact (already documented in the User Manual's Security & Data Handling chapter for a different IOC). ThreatFox/URLhaus not configured, Censys rate-limited, OTX no data. **Net: exactly 1 of 9 responding providers said malicious, and that provider's own data flags the listing as a query error, not a real detection.**
3. The primary final assessment (backend `ollama`/`llama3.2:3b`, the platform's currently active AI backend) produced: `final_verdict: "malicious"`, `risk_score: 87`, `malicious_probability: 90%`, with `agreeing_providers: []` (empty) but a `technical_summary` claiming *"the majority of providers (8/9) agree that it has malicious reputation, with Spamhaus DBL/ZEN being the sole provider to concur"* -- a sentence that contradicts itself (majority agree, but only one is "the sole provider to concur") and contradicts its own structured `agreeing_providers`/`disagreeing_providers` fields, and does not match the real 1-malicious-out-of-9 ground truth.
4. Re-ran the identical, already-persisted evidence through `POST /api/v1/lookup/{id}/reanalyze` with `ai_backend: "groq"` (`llama-3.3-70b-versatile`, a materially stronger model). This second analysis was internally consistent (`agreeing_providers: ["spamhaus","abuseipdb"]` matched its own prose) but factually wrong on the evidence itself: it states *"AbuseIPDB reports 1.1.1.1 as malicious"* and lists `abuseipdb` in `agreeing_providers`, when AbuseIPDB's real, persisted verdict for this lookup was `clean` with `is_whitelisted: true`. Verdict came out as `"suspicious"` (60% probability) -- lower than Ollama's, but still built on a misattributed piece of evidence.

**Expected result**: A final verdict for an indicator where 8-of-9 real signals are clean/neutral and only one flagged provider's own data admits a query-error artifact should not reach "malicious" (Ollama's output), and no AI-generated sentence should attribute a stance to a named provider that contradicts that provider's own persisted verdict (Groq's output).

**Actual result**: Both of the platform's two most-used AI backends produced a verdict skewed toward "malicious"/"suspicious" that overstates the real evidence, and each did so through a different failure mode -- Ollama through an internally self-contradictory, numerically wrong consensus claim; Groq through a plausible-sounding but factually incorrect attribution of a specific provider's stance.

**Root cause**: `_ground_final_assessment()` (`backend/app/ai/service.py:211-264`, documented in the Backend Documentation's Runtime Configuration chapter and independently in the Source Code Documentation) only checks whether a provider *named* in `agreeing_providers`/`disagreeing_providers` corresponds to a provider that actually ran (rejecting hallucinated provider names not backed by any real correlation edge, `provider_agreement` entry, or summary). It does not check whether the *stance* attributed to a real, correctly-named provider matches that provider's own persisted verdict. A real provider can therefore be correctly named but have its actual finding inverted or fabricated, and the grounding pass will not catch it, because grounding only verifies provider *existence*, not verdict-vs-attribution *consistency*. Separately, nothing in the prompt or a post-processing check verifies that a claimed count ("8/9 agree") matches `len(agreeing_providers)` / the number of providers that actually returned a comparable verdict, which is how Ollama's self-contradiction reached the client unfiltered.

**Suggested fix** (not yet implemented -- this is a prompt-engineering + grounding-logic change to core AI output validation, judged too significant to make unreviewed mid-QA-pass): extend `_ground_final_assessment()` with a second pass that (a) recomputes any explicit provider-count claim against the real number of providers in `agreeing_providers`/`disagreeing_providers` and flags/strips a mismatched count claim the same way a hallucinated MITRE mapping is flagged today, and (b) cross-checks each named provider in `agreeing_providers`/`disagreeing_providers` against that provider's own persisted `ProviderResult`/`ProviderSummary` verdict field, stripping or flagging (mirroring the existing `grounded: False` pattern used for MITRE mappings) any provider whose attributed stance contradicts its own recorded verdict.

**Mitigating factors**: the platform's own documentation already states AI output is "analytical assistance, not unquestionable truth" and that every claim should be checked against the Evidence Ledger, which does show the real per-provider verdicts correctly (the bug is in the AI's narrative/aggregation layer, not in the underlying evidence storage -- `EvidenceItem` rows and `ProviderResult` records for this lookup are all correct). An analyst who opens the Evidence Ledger rather than trusting the executive summary would see the discrepancy. This is why the finding is graded HIGH rather than CRITICAL.

---

## BUG-002: Raw exception text (including a real third-party account identifier) leaks into persisted, analyst-visible investigation data when an AI call fails

- **Severity**: MEDIUM
- **Status**: FIXED (this pass)
- **Area**: AI analysis error handling (`backend/app/ai/service.py`, `summarize_provider()` and `generate_final_assessment()`)
- **Discovered**: Phase 12/13/16 (provider/AI failure handling), triggered organically by a real Groq TPM rate limit hit during live AI-switching tests, 2026-08-13

**Reproduction steps:**
1. With `groq` set as the active AI backend, ran two real investigations in quick succession (`1.1.1.1` reanalyze, then a fresh `9.9.9.9` lookup) -- genuinely exhausted Groq's real per-minute token budget for the configured account (this was not simulated; it is the account's actual live rate limit).
2. Every per-provider AI summary call that failed during the `9.9.9.9` investigation returned a `caveats` field containing the full, raw Python exception `repr()` -- `RuntimeError('Groq invocation failed: HTTP 429: {"error":{"message":"Rate limit reached for model \`llama-3.3-70b-versatile\` in organization \`<redacted-25-char-org-id>\` service tier ...")` -- including Groq's real organization ID for the account currently configured on this platform (redacted here), verbatim inside a field the frontend renders and that is persisted to `ai_summaries`/`final_assessment_records`.
3. The final assessment's `technical_summary` and `verdict_rationale` fields contained the identical raw `repr(exc)` text for the same reason.

**Expected result**: An AI-call failure should degrade to a clean, generic, analyst-readable message (the platform already does this correctly for the *rest* of each fallback object -- `what_it_knows: "AI summarization unavailable for this provider (generation error)."` is exactly right). The full raw exception belongs in the server-side structured log only.

**Actual result**: The raw exception `repr()` -- implementation details plus a real, account-identifying Groq organization ID -- is embedded in the same fallback objects and therefore persisted into the database and surfaced to any analyst viewing the investigation, and would be included in any future export/report of that investigation.

**Root cause**: `backend/app/ai/service.py:314` (`caveats=repr(exc)`) and `:436`/`:448` (`technical_summary=f"...: {exc!r}"`, `verdict_rationale=f"...({exc!r})."`) each already log the exception correctly one line earlier via `logger.warning(..., exc)` (`service.py:305`, `:430`) -- the bug is that the *same* raw exception text is then duplicated into the user-facing/persisted dataclass fields instead of a clean static message.

**Fix applied**: Replaced all three occurrences of `repr(exc)`/`{exc!r}` in the user-facing fallback fields with clean, generic, non-identifying messages. The full exception remains available server-side via the existing `logger.warning` calls, unchanged. See `backend/app/ai/service.py` diff.

**Retest**: Copied the fixed `service.py` into the live running `app-backend-1` container (bind-mounted dev compose, confirmed byte-identical via `diff` after copy) and, inside that same container, forced both fallback paths with a mocked AI client raising `RuntimeError("org_SECRETORGID123 leaked-detail")`: `summarize_provider()`'s `caveats` came back as `"The AI backend failed to generate a summary for this provider's data (see server logs for details)."` and `generate_final_assessment()`'s `technical_summary`/`verdict_rationale` came back as clean static strings -- the injected marker string was absent from all three fields (asserted programmatically), while `logger.warning(...)` still printed the full original exception to the container's stdout, confirming operator troubleshooting capability is unaffected. PASS.

---

## BUG-003: Missing `await` on `_get_ai_client()` silently breaks the entire AI-analyst explanation suite, IOC comparison, hunting-package generation, and detection-rule generation

- **Severity**: CRITICAL -- the worst bug found in this pass
- **Status**: FIXED (this pass), live-retested against the running application
- **Area**: `backend/app/ai/analysis_service.py` (`_call_and_ground()` line 126, `compare_iocs()` line 402), `backend/app/ai/hunting_service.py` (`generate_hunting_package()` line 61, `generate_detection_rule()` line 93)
- **Discovered**: parallel static-QA workflow (source-code audit agent), adversarially verified against the real files, then independently reproduced live against the running container, 2026-08-13

**Reproduction steps (as found, before fix):**
1. `_get_ai_client()` (`app/ai/service.py:102`) is `async def ... -> tuple[_AIClient, str, Optional[str]]`. Four call sites called it as a plain `client = _get_ai_client()` -- no `await`, no tuple-unpacking -- binding `client` to a bare, un-awaited coroutine object instead of an AI client.
2. The very next line in each function, `await client.call_claude_json(...)`, raised `AttributeError: 'coroutine' object has no attribute 'call_claude_json'` every single time, with Python additionally emitting `RuntimeWarning: coroutine '_get_ai_client' was never awaited`.
3. Every one of these functions wraps its AI call in `except Exception: logger.warning(...); return <fallback>`, so the failure was completely invisible to the caller: every route returned `HTTP 200` with a canned placeholder, unconditionally, regardless of whether any AI backend was configured, healthy, or reachable.
4. **Live-confirmed against the real running application** (not just static reading): `POST /api/v1/lookup/{id}/analysis/why` returned `{"reasons":[],"caveat":"AI explanation unavailable (generation error)."}` and the backend log showed the exact predicted `AttributeError`/`RuntimeWarning` pair.
5. **Affected, real, routed endpoints**: all nine `/lookup/{id}/analysis/*` endpoints (why, what-is-this, disagreement, false-positive, challenge, next-actions, gaps, score-explanation, copilot) sharing `_call_and_ground()`; `POST /basket/compare` (`compare_iocs()`); `POST /lookup/{id}/hunt` (`generate_hunting_package()`); `POST /lookup/{id}/detection` (`generate_detection_rule()`). That is essentially the entire "AI Analyst" feature set advertised in the User Manual beyond the primary final assessment.
6. No existing automated test caught this: unit tests for these modules only exercise the pure grounding/stripping helper functions with pre-built objects, never the `_get_ai_client()` call path itself.

**Root cause**: a straightforward omission -- these four call sites did not follow the correct pattern already used correctly elsewhere in the same codebase (`app/ai/service.py:296`, `:407`: `client, _backend, _model = await _get_ai_client(...)`).

**Fix applied**: changed all four call sites to `client, _backend, _model = await _get_ai_client()`, matching the established pattern exactly.

**Retest (live, against the running application, after `docker restart app-backend-1`** -- the dev container's `--reload` file-watcher did not pick up a `docker cp`-delivered change on this Windows/Docker-Desktop bind mount, a known inotify-over-bind-mount limitation, not a product defect; a plain restart resolved it):
- `POST /lookup/{id}/analysis/why` -- now returns a real, evidence-grounded explanation (`evidence_ids` pointing at real `EvidenceItem` rows) instead of the placeholder. PASS.
- `POST /lookup/{id}/hunt` -- now returns a full, real hunting package (8 query-language formats, plus a correctly-grounded expansion target matching the investigation's real correlation edge to ASN 13335). PASS.
- `POST /lookup/{id}/detection` -- now returns a real, complete detection-rule draft. PASS.
- The remaining six `_call_and_ground()`-based endpoints and `/basket/compare` were not each individually re-invoked (to conserve the live Groq account's real per-minute rate limit, already exhausted twice during this pass), but they execute the identical, now-fixed code path proven working by the `/why` retest above -- verified by re-reading the fixed source, not merely inferred.

**Note -- this bug also explains part of BUG-001's pattern**: with this bug fixed, `/analysis/why`'s real output for the `1.1.1.1` investigation attributed a "malicious, high threat level" finding to AbuseIPDB -- but AbuseIPDB's real, persisted verdict for this lookup was `clean` (`abuse_confidence_score: 0`, `is_whitelisted: true`). This is the same root-cause class as BUG-001 (a real, correctly-named provider's stance gets inverted in AI prose) reproducing in a second, independent call site, which strengthens BUG-001 from "possibly IOC-specific" to "a systemic gap in how grounding checks evidence IDs but not verdict directionality," across at least two different generation functions and two different AI backends.

---

## BUG-004: Gemini API key embedded in the request URL leaks into plaintext application logs via httpx's default INFO-level request logging

- **Severity**: CRITICAL
- **Status**: FIXED (this pass), empirically retested live
- **Area**: `backend/app/ai/gemini_client.py` (`call_claude_json()`), `backend/app/ai/connection_test.py` (`_check_gemini()`)
- **Discovered**: parallel static-QA workflow (`backend-secrets` finder agent). This specific finding's adversarial-verification agent hit an internal tool-schema failure ("StructuredOutput retry cap exceeded") and produced no verdict, so it silently fell out of both the confirmed and refuted result buckets during automatic synthesis -- caught only because I read the raw workflow journal rather than trusting the synthesized summary, and independently re-verified it myself from scratch.

**Reproduction steps:**
1. Both `GeminiClient.call_claude_json()` and `_check_gemini()` (the live "Test Connection" handler for Gemini) built the outbound request as `f"{_API_BASE}/models/{model}:generateContent?key={api_key}"` -- the real API key directly embedded in the URL query string. This matches one of Google's two documented Gemini REST auth methods, but is the wrong one to use here.
2. `httpx.AsyncClient` logs every request at INFO level via the standard-library `httpx` logger, in the form `HTTP Request: <method> <full URL> "<status line>"` -- confirmed empirically live, inside the real running container, using a throwaway fake key: `INFO:httpx:HTTP Request: POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=FAKE_TEST_KEY_ABC123XYZ "HTTP/1.1 400 Bad Request"` -- the full key value appeared in plaintext in the log line.
3. This app does not suppress the `httpx` logger, and I had already independently observed real, unrelated `INFO:httpx:HTTP Request: ...` lines in this container's actual logs during earlier live testing (the Groq rate-limit investigation) -- confirming this isn't a hypothetical, it's this deployment's real, active logging behavior.
4. Gemini currently shows `configured: false` in this platform's live runtime config (no real key saved yet), so no real key has actually leaked into today's logs -- but the vulnerability would trigger immediately and unconditionally on the very first real AI call or Test Connection click once any admin configures a real Gemini key, with no special conditions required (not an edge case -- the happy path itself leaks).

**Expected result**: No credential should ever appear in a request URL that a standard HTTP client logs by default.

**Actual result**: Every Gemini API call (both the production `call_claude_json()` path and the `/ai/test` Test-Connection path) placed the live API key directly into a URL that this application's own logging configuration makes visible in plaintext.

**Root cause**: Google's Gemini REST API supports two authentication mechanisms -- a `?key=` query parameter and an `x-goog-api-key` header -- and this codebase used the query-string form in both places it calls Gemini directly, without accounting for httpx's default request-logging behavior.

**Fix applied**: switched both call sites to send the key via the `x-goog-api-key` header instead, removing `?key=...` from the URL entirely.

**Retest (live, empirical, against the real Gemini API after `docker restart app-backend-1`)**:
- `GeminiClient.call_claude_json()` with a fake key: log line is now `INFO:httpx:HTTP Request: POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent "HTTP/1.1 400 Bad Request"` -- no key in the URL -- and Google's real API responded with its standard `"API_KEY_INVALID"` / "API key not valid" error body, proving the header is genuinely being read and processed by Google's endpoint (not silently ignored in a way that would mask a different failure mode).
- `_check_gemini()` with the same fake key: same clean log line, and the function's own candidate-key-testing behavior is unaffected (`ok: False, message: "Authentication failed -- check your Gemini API key."`).
- Both PASS.

---

## BUG-005: Admin-gated SSRF via unvalidated Ollama `base_url` in the AI connection-test and model-discovery endpoints

- **Severity**: HIGH
- **Status**: FIXED (this pass), empirically retested live
- **Area**: `backend/app/ai/connection_test.py` (`_check_ollama()`), `backend/app/api/routes/ai_config.py` (`POST /ai/{backend}/models`, `backend == "ollama"` branch)
- **Discovered**: parallel static-QA workflow (`backend-injection-authz` finder), adversarially verified against the real files, then independently reproduced live against the running container, 2026-08-13

**Reproduction steps (before fix):** `POST /api/v1/ai/test` (`backend=ollama`) and `POST /api/v1/ai/ollama/models` both took `credentials.base_url` as a completely free-form string and issued a server-side request to `f"{base_url}/api/chat"` / `f"{base_url}/api/tags"` with no host validation. Both routes require `provider:manage` (admin-only), so this is an authenticated rather than anonymous SSRF, but it still let an admin session (or a hijacked/CSRF'd admin token) direct the backend to make an outbound request to any host of the caller's choosing, with the response body/error text echoed back -- including cloud instance-metadata services (`169.254.169.254`), a well-known credential-theft target on any cloud-hosted deployment.

**Constraint that shaped the fix**: this deployment's own real, currently-working Ollama configuration legitimately points at `host.docker.internal` (Docker's own loopback-adjacent bridge), and Ollama's whole use case is a local-or-LAN server -- so a naive fix that blocks all loopback/private (RFC1918) ranges would break real, intended functionality, not just theoretical attacks.

**Fix applied**: added `backend/app/core/url_safety.py` (`assert_safe_outbound_url()`), which validates the URL scheme is `http`/`https` and resolves the hostname via DNS, refusing only link-local addresses (`169.254.0.0/16` / `fe80::/10` -- the range with no legitimate Ollama use and where every major cloud provider's metadata service lives). RFC1918 private ranges and loopback are deliberately left reachable. Applied at both call sites.

**Retest (live, against the real running application, after `docker restart app-backend-1`)**:
- `POST /api/v1/ai/test` with `base_url: "http://169.254.169.254"` -- now returns `{"ok": false, "message": "Refusing to connect to http://169.254.169.254: Host '169.254.169.254' resolves to a link-local address ... refusing to connect."}`, no outbound request made. PASS.
- `POST /api/v1/ai/test` with `base_url: "http://host.docker.internal:11434"` (the platform's real, currently-configured Ollama address) -- still returns `{"ok": true, "message": "Connected. Model replied: 'pong'", "model": "llama3.2:3b", "latency_ms": 7212}`, a genuine live round-trip. Confirms the fix does not break the legitimate use case. PASS.
- `POST /api/v1/ai/ollama/models` with the same metadata address -- refused with a logged warning, falls back to the static model list rather than erroring. PASS.

---

## Documented, Not Fixed This Pass

Real, verified findings from the static-QA workflow (each independently adversarially re-verified against the actual source, not taken on the finder agent's word alone) that were judged lower-urgency, higher-risk-to-fix-unreviewed, or requiring test infrastructure (a real install/uninstall cycle) not exercised this pass. Grouped by area; severity shown is the post-adversarial-review severity, which in three cases was downgraded from the finder's initial call.

**Backend/dependency hygiene**
- **HIGH** -- `backend/requirements.txt` ships `pytest`/`pytest-asyncio`/`pytest-cov`/`respx` directly in the production image (no `requirements-dev.txt` split; `Dockerfile` installs the whole file unconditionally). Image bloat/attack-surface, not a direct vulnerability.
- **MEDIUM** -- `passlib==1.7.4` (last released 2020) backs password hashing; the codebase's own `docs/TESTING.md`/`docs/TROUBLESHOOTING.md` already document a real compatibility break against `bcrypt>=4.1` caused by this staleness, currently worked around by pinning `bcrypt==4.0.1`. The actual hashing work is delegated to the separately-maintained `bcrypt` library, so downgraded from the finder's initial HIGH.
- **MEDIUM** -- No lockfile for backend transitive dependencies (only top-level `==` pins in `requirements.txt`); reproducible-build risk.
- **LOW/INFO** -- Several dependency-freshness items with no known live vulnerability: `cryptography==43.0.1`, `boto3==1.35.24`, `python-jose==3.3.0` (verified NOT abandoned -- 3.4.0/3.5.0 exist with an active CVE fix; downgraded from the finder's initial HIGH after checking PyPI/GitHub directly), `python-whois==0.9.6` (naming-collision risk on PyPI worth double-checking), Next.js 14.2.15, React 18.3.1. Frontend `dependencies`/`devDependencies` classification itself was checked and found correctly split, no action needed there.

**Frontend**
- **MEDIUM x3** -- `ProviderCard.tsx` (two locations: OSINT-finding links, `source_url` links) and `EvidencePanel.tsx` (`source_url` links) render attacker-influenceable URLs (from OSINT/provider data about the very infrastructure being investigated) directly into `<a href>` with no scheme check -- a `javascript:`/`data:` URI could execute in-origin on click. Fix would be one shared `isSafeHttpUrl()` guard applied at all three sites.
- **MEDIUM** -- Access/refresh JWTs stored in `localStorage` rather than `httpOnly` cookies (`frontend/lib/api.ts`) -- a design-level tradeoff, not a typo, so left for a deliberate follow-up decision rather than an unreviewed change mid-pass.
- **LOW** -- `ExportMenu.tsx` collapses every PDF/CSV export failure mode (network error, auth failure, 500) into the same "Export format not yet available" message, masking a real backend error as "not implemented."
- **LOW** -- Path segments (lookupId, caseId, etc.) interpolated into `fetch()` URLs without `encodeURIComponent` in `lib/api.ts`, inconsistent with the same file's own query-string encoding elsewhere.
- **LOW** -- `AskAiPanel.tsx`'s `window.open()` to Gemini deliberately omits `noopener` (documented, intentional, for focus/reuse logic) -- a known tabnabbing anti-pattern against a fixed, trusted Google domain; low real risk.
- **INFO** -- Two stale file-header comments (`app/lookup/new/page.tsx`, `app/lookup/[id]/page.tsx`) describe a "placeholder" architecture that no longer matches the code (every section already renders real components).

**Windows installer / wizard scripts** (not exercised via a real install/uninstall cycle this pass, per user direction -- documented from source review only)
- **HIGH** -- `windows/installer.iss`'s uninstaller strips the `.env` secrets file's restrictive ACL (`icacls /reset`) *before* deleting it, with the delete's return value unchecked -- a failed delete (locked handle from AV/Docker) leaves a now-world-readable secrets file behind while uninstall silently reports success.
- **HIGH** -- `windows/scripts/Common.ps1`'s `$script:InstallDir` is taken unvalidated from the user-writable `IOC_INSTALL_DIR` environment variable; combined with UAC elevation on split-token admin accounts, this is a real Medium-to-High-integrity local-privilege-escalation primitive (an attacker-controlled `docker-compose.yml` executed at full Administrator integrity).
- **HIGH** -- `windows/scripts/Diagnostics.ps1`'s secret-redaction pass filters `Get-ChildItem -Filter "*.txt"`, which structurally never matches `setup.log` (copied with a literal `.log` extension) -- that file receives zero redaction before being zipped into a bundle explicitly built to hand to third-party support.
- **MEDIUM** -- The same redaction pass has no shape pattern for most first-party provider keys (VirusTotal/AbuseIPDB/OTX/NVD/abuse.ch/Hybrid Analysis/Censys/PhishTank/Groq) -- only Anthropic/AWS/Google/JWT shapes are covered.
- **MEDIUM** -- `Common.ps1`'s `Sync-ComposeEnvFile` briefly leaves the copied secrets file inheriting Program Files' world-readable default ACL between `Copy-Item` and the following `icacls` lockdown (TOCTOU), recurring on every Start/Stop/Restart/Diagnostics invocation.
- **MEDIUM** -- `installer.iss`'s uninstall `docker compose ... down -v` command is built by string-concatenating the install path between manually-inserted quotes inside a `-Command` string; an install path containing an apostrophe breaks the intended quoting.
- **LOW** -- `Write-SetupLog`'s own directory-creation fallback applies no ACL (unlike `Initialize-DataDirectories`), latent but not currently triggered given today's call ordering.
- **LOW** -- `Backup-Database.ps1` parses `POSTGRES_USER`/`POSTGRES_DB` from `.env` with only `.Trim()` before passing them as `pg_dump` arguments; reaching this requires prior write access to an Administrators-only file.

**Backend hygiene (LOW, code-smell/latent-fragility -- not reproducible failures under this app's current single-process deployment model)**
- Provider fan-out tasks (`orchestrator.py`) are never explicitly cancelled if the generator closes early (client disconnect) -- wasted background work, not a correctness bug given per-step commits already make partial results safe.
- `debug=True` and the literal default JWT secret `"change-me-in-production"` are the out-of-the-box `Settings` defaults, with no startup check that warns/refuses to boot if still active in what looks like a production deployment.
- `seed_from_env_if_empty()`'s check-then-insert has a TOCTOU race across multiple worker processes/replicas (masked by a blanket `try/except` at the call site, so the app still boots -- just logs a spurious failure).
- `get_redis()`'s lazy-singleton init is unsynchronized (a benign, low-impact race given `Redis.from_url` doesn't eagerly open a socket).
- `whois_rdap.py`/`virustotal.py` and `crawler/sources/pastebin_search.py` interpolate the IOC value into fixed-host URL paths without `urllib.parse.quote()` (inconsistent with `otx.py`'s correct encoding) -- confirmed as *not* full SSRF (the host is always a hardcoded literal; empirically tested that embedding a full alternate-host string stays a path segment on the original host), but does allow path-traversal to a different endpoint on the same already-trusted third-party API.
- `LookupCreateRequest.value` has no length/pattern constraint and `ioc_type_hint` lets a caller force a shape-mismatched type onto an arbitrary string, within a de facto ~2048-char ceiling enforced by the `ioc_lookups` column (crudely, via an unhandled DB exception rather than a clean 422). Requires an already-privileged ADMIN/ANALYST account.
- `basket.py`'s `/basket/compare` and `cases.py`'s IOC-add both call `uuid.UUID()` on unvalidated input, raising an unhandled `ValueError` -> generic 500 instead of a clean 422 on a malformed ID.
- `CaseIOCAddRequest.ioc_value`/`ioc_type` accept unbounded free-text (not independently exploitable -- SQLAlchemy parameterizes the insert -- but a data-integrity gap on team-visible case data).
- `docker-compose.yml` falls back to weak default Postgres/Neo4j passwords (`ioc` / `changeme-neo4j`) when the corresponding env var is unset; mitigated by the loopback-only port binding but worth requiring explicit values instead.
- OpenSearch runs with `DISABLE_SECURITY_PLUGIN: "true"` (deliberate, commented, loopback-mitigated tradeoff, not a leaked secret).

---

