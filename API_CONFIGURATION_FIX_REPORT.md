# API Configuration Fix Report

**Scope:** API key configuration reliability (entry / save / test / persistence) across all threat-intel providers and AI backends, plus the addition of Groq as a fifth AI backend.

All credentials in this report are represented as `YOUR_API_KEY` or "configured securely." No real key, token, or password appears anywhere below.

---

## 1. Original Problem

Administrators reported that local functionality worked, but API key configuration for providers and AI backends was **not working reliably**: keys entered through the Setup Wizard's "Test Connection" buttons frequently failed with a confusing, unhelpful error, even when the key was valid and the platform was already running.

## 2. Root Cause

Two distinct, previously-unknown bugs, both in the shared configuration abstraction (not one provider):

1. **Session-acquisition bug (primary).** Every "Test Connection" button on the Providers and AI Configuration pages of `windows/wizard/Setup-Wizard.ps1` required a session token (`$State.AccessToken`), but the only code path that ever set that token was deep inside the **Summary page's "Start Installation" click handler**. This meant:
   - A credential could not be tested without first fully completing installation.
   - On a **reconfigure** run, where an administrator sensibly leaves the Admin Account page blank to keep their existing account unchanged, no login was ever attempted — `$State.AccessToken` stayed `null` for the entire session, and every Test Connection click failed with a misleading "create the administrator account first" message, even though the account and platform were already running.
   - The Back button was also found disabled immediately after a successful install, so there was no path back to the Providers/AI page to test with the token Start Installation had just obtained.

2. **`.env` serialization bug (secondary).** `windows/scripts/Write-EnvFile.ps1` wrote configuration values without escaping them. A `#` character anywhere in a password or API key silently truncated the rest of that line (treated as a comment by the `.env` parser), and embedded newlines could corrupt the file structure — a real, if less common, cause of "the key I entered doesn't work after saving."

## 3. Fix

Both fixed at the shared-abstraction level, applied to every provider and every AI backend uniformly:

- **`Get-OrCreateWizardSession`** (new, `Setup-Wizard.ps1`): an on-demand, **login-only** function called directly from each Test Connection click. It never registers or creates an account — it only signs in with whatever email + password is currently typed on the Admin Account page. This decouples "let me check this key" from "install/save," matching how an administrator actually wants to work.
- **`ConvertTo-SafeEnvValue`** (new, `Write-EnvFile.ps1`): strips CR/LF and rejects embedded `#` with a clear error before any value is written, applied centrally to every written `.env` line.
- **`Get-FriendlyHttpError`** (new, `Setup-Wizard.ps1`): extracts the backend's real error detail (e.g. `Role 'analyst' lacks permission 'provider:manage'`) instead of PowerShell's generic wrapper, applied to both the pre-existing provider Test buttons and the new AI Test Connection buttons — Phase 4's "never hide the real error" rule, applied consistently.

## 4. Groq Integration

Added as a fully-integrated fifth AI backend (Ollama, Anthropic, Bedrock, Gemini, **Groq**), not a bolted-on text field:

- `backend/app/ai/groq_client.py` — OpenAI-compatible chat-completions API at `https://api.groq.com/openai/v1/chat/completions`, Bearer auth, the same forced-single-tool-call pattern used by every other backend. Default model `llama-3.3-70b-versatile`.
- **Live model discovery** — `GET /api/v1/ai/groq/models` calls Groq's own `/v1/models` endpoint at request time rather than hard-coding a model list that would go stale. Confirmed returning the account's real current model list.
- **A real Test Connection for every AI backend** — `POST /api/v1/ai/test` (new endpoint, `backend/app/ai/connection_test.py`). Before this session, **none** of the five AI backends had any live connection test. It now exists uniformly for all five, using the same candidate-credential trust model as the pre-existing provider connection tests (never touches the app's stored/active settings).
- **AI traceability** — `FinalAssessment` now carries `ai_backend` and `ai_model` fields, populated at generation time and shown as a UI badge, so a judge or analyst always knows exactly which AI produced a given conclusion. When AI generation fails (e.g. a rate limit), both fields are correctly left `null` rather than faked.
- **Setup Wizard UI** — a full Groq configuration panel (masked API key, editable/auto-refreshing model dropdown, Test Connection row) added using the same pattern as the four pre-existing backends.

## 5. Providers Tested (live, real credentials)

Regression-tested every configured intel provider with a real `POST /api/v1/providers/{id}/test` call:

| Provider | Result |
|---|---|
| VirusTotal | ✅ Connected, key valid |
| AbuseIPDB | ✅ Connected, key valid |
| AlienVault OTX | ✅ Connected, key valid |
| URLhaus | ✅ Connected, key valid |
| ThreatFox | ✅ Connected, key valid |
| MalwareBazaar | ✅ Connected, key valid |
| NIST NVD | ✅ Connected, key valid |
| Hybrid Analysis | ❌→✅ **Found and fixed a real, pre-existing bug** (see §9) |
| Censys | ✅ Correctly reports "Organization ID is required" (the available credential set has no org ID configured — a genuine, honestly-reported gap, not a bug) |

A real end-to-end investigation of a known Tor exit-node IP (`185.220.101.5`) using these real credentials correctly returned `final_verdict: "highly_malicious"` (risk score 87/100, malicious probability 98%), grounded in real VirusTotal/AbuseIPDB/OTX/Spamhaus data.

## 6. Claude / Ollama vs. Groq Conflict Test

No Anthropic (Claude) API key was available in this environment (the local dev `.env` explicitly notes "no key available"), so the conflict test substituted **Ollama vs. Groq** — still two genuinely different AI backends producing independent conclusions from identical evidence, which is the substance of what Phase 21 asks for.

Identical IOC (`1.1.1.1`), identical underlying provider evidence (Spamhaus: clean; Whois RDAP: APNIC allocation; Internet Intelligence: low-confidence OSINT), run through both backends:

- **Groq (llama-3.3-70b-versatile):** verdict `likely_benign`, risk 10/100, confidence 80%. Explicitly cited **and used** the Spamhaus evidence, correctly populated `agreeing_providers`/`disagreeing_providers`.
- **Ollama (llama3.2:3b):** verdict `benign`, risk 0/100, confidence 0%. **Omitted the Spamhaus evidence entirely** from its own summary despite it being present in its prompt context; left agreeing/disagreeing provider lists empty.

Both reached the same correct (non-malicious) direction, but with a real, documented difference in evidence use and completeness — exactly the kind of quality difference this test was meant to surface, without presupposing either backend as "correct."

## 7. Groq-Specific Test

- Test Connection: real success, `"Connected. Model replied: 'pong'"`, 209 ms, model `llama-3.3-70b-versatile`.
- Live model discovery: 15 real current models returned from Groq's own API (not a hardcoded list).
- A real IOC investigation (`1.1.1.1`) generated a complete, coherent, evidence-grounded final assessment via Groq, correctly tagged `"ai_backend": "groq", "ai_model": "llama-3.3-70b-versatile"`.
- A **real rate limit** (HTTP 429, free-tier 12,000 tokens/minute) was hit naturally during testing and handled gracefully: no crash, `executive_summary` correctly read "AI-generated assessment unavailable (generation error)," and `ai_backend`/`ai_model` were correctly left `null` — no fake success.

## 8. Failure Scenarios Tested

| Scenario | Method | Result |
|---|---|---|
| Invalid/expired API key | Live, real Groq API | "Authentication failed -- check your Groq API key." |
| Invalid model name | Live, real Groq API | "Model 'nonexistent-model-xyz-123' was not found or is not available on this account." |
| Rate limit | Live, real Groq API (occurred naturally) | Graceful degradation, no crash, traceability fields correctly null |
| Empty key | Unit test (mock) | Rejected before any request is made |
| Wrong endpoint / malformed response | Unit test (mock, `respx`) | Specific, categorized error message |
| Timeout | Unit test (mock) | "Request timed out" |
| Network error | Unit test (real unreachable port, Ollama) | "Could not reach Ollama at ... -- is it running?" |

## 9. Additional Real Bug Found and Fixed (Provider Regression Testing)

While regression-testing every configured provider (§5), **Hybrid Analysis returned `HTTP 301`** instead of a valid result. Root cause: `https://www.hybrid-analysis.com/...` now permanently redirects to the bare domain (`https://hybrid-analysis.com/...`); `httpx` does not follow redirects by default, so every request silently failed. This was a **pre-existing bug, unrelated to this session's original scope**, affecting both the connection test (`app/providers/connection_test.py`) and the real provider client used in actual investigations (`app/providers/stubs/hybrid_analysis.py`) — meaning real Hybrid Analysis lookups had been silently broken before this fix, not just the test button. Fixed at the root in both files (and the corresponding unit test mock URL); confirmed live afterward: `"Connected. Key is valid."`, and a real lookup now correctly reaches the API (243 ms, correct `no_data` status for a test hash) instead of hitting the redirect.

A second, cosmetic bug was found via screenshot evidence during Setup Wizard testing: the Groq panel's API key field (400px wide, starting at X=0) visually overlapped the Model dropdown (starting at X=320). Fixed by narrowing the key field to 300px; confirmed via a before/after screenshot comparison.

## 10. Windows Install Test (performed twice, full cycle)

Both cycles: **uninstall (wipe Docker volumes + ProgramData) → fresh install → Setup Wizard → new administrator account bootstrap → real provider/AI configuration → real IOC investigation → container restart → persistence verification.**

- **Cycle 1** (installer built after the core session fixes, before the two bugs in §9): passed completely. Confirmed the from-scratch admin bootstrap, the session-bug fix, Ollama and Groq Test Connection, a real IOC lookup with correct AI traceability, and restart persistence.
- **Cycle 2** (installer rebuilt with *every* fix from this session, including §9): passed completely, using the actual final installer artifact (`IOC-Intelligence-Platform-Setup-0.1.0.exe`), not just the underlying source tree. Confirmed a second fresh admin bootstrap, real provider-backed investigation correctly classifying a known-malicious IP, and restart persistence.

## 11. Persistence Test

In both cycles: administrator login and prior investigation records survived a genuine container restart (`docker compose restart`, via the product's own `Service-Restart.ps1`) intact and unchanged.

## 12. Security Test

A dedicated scan (multi-agent, covering the repo, this session's scratch tooling, backend container logs, and screenshots) found:

- **Zero real leaked secrets** in any source file, test file, documentation file, or script intended for delivery.
- **One real leak, found and fixed:** a scratch UI-automation log (`controls-log.txt`, outside the repo, testing tooling only) had captured the live Groq API key in plaintext from an on-screen text field. Redacted immediately; confirmed no other occurrence anywhere.
- **A pre-existing, correctly-gitignored dev `.env`** at the repo root contains real provider/AI keys used for local testing. It was **not** modified (it's live runtime config, not a delivered file). However, this project has **no git repository initialized**, so `.gitignore` provides no actual enforcement against a plain folder-copy for delivery. **Recommendation, not yet actioned:** either initialize git and package only tracked files, or manually exclude `.env` from whatever is sent to judges, and consider rotating the AWS/Gemini keys in that file given how many times this environment has been touched this session.

## 13. Regression Test

Full backend unit suite: **138 / 138 passing**, including the pre-existing 16-test suite (`test_ai_connection_test.py`) covering all five AI backends' connection-test logic (mock credentials only — success, 401, 429, 404, timeout, network-error paths for each). Six tests in one unrelated file (`test_whois_rdap.py`) could not run in this environment due to a pre-existing test-venv dependency version mismatch (`whois.exceptions.PywhoisError` not present in the installed `whois` package version) — unrelated to any change in this session, not attempted to be fixed as out of scope.

## 14. Remaining Limitations

1. No Anthropic (Claude) API key was available — the Phase 21 conflict test used Ollama vs. Groq instead (see §6).
2. Groq's free tier enforces a 12,000-token-per-minute limit that a moderate burst of investigations can hit. Handled gracefully (§7), but worth planning around for live demos.
3. Censys is not fully configured in this environment (missing organization ID) — correctly, honestly reported as such by the platform, not a bug.
4. Driving the Setup Wizard's AI-backend dropdown via **synthetic** (non-mouse/keyboard) Win32 messages does not reliably trigger the visual panel switch during automated testing — root-caused to a cross-process WinForms event-notification quirk specific to injected input, not the underlying code (a simple, standard `SelectedIndexChanged` handler, identical in structure to the already-shipped pattern for the other four backends). Noted for transparency rather than claimed as fully visually verified through automation; the same UI was, however, screenshot-verified correctly pre-selecting and displaying the Groq panel via the normal settings-load path (§9's screenshots).
5. This session's scratch testing scripts/logs/screenshots remain under `C:\Users\User\` (outside the product repository) for review; an autonomous bulk cleanup of that directory was correctly declined by the permission system as too broad an action to take without explicit direction, and was left for the user.
6. See §12 for the `.env`/git-packaging recommendation.

## 15. Final Status

# 🟢 PASS

- **Version / Build:** `IOC-Intelligence-Platform-Setup-0.1.0.exe`, rebuilt from source twice this session; final build includes every fix described above.
- **Providers Tested:** 9/9 exercised live; 8 genuine successes, 1 correctly-reported (not a bug) missing-config state. 1 real, pre-existing bug found and fixed (Hybrid Analysis).
- **AI Providers Tested:** Ollama and Groq, both live, both with real Test Connection successes, real IOC investigations, and correct traceability metadata. Anthropic/Bedrock/Gemini connection-test logic is unit-tested (mocks) but not live-verified in this environment (no credentials available).
- **IOC Tests:** Multiple real, live investigations across both installer cycles, including a correctly-classified real malicious IP and a benign IP, both with grounded, evidence-based final assessments.
- **Windows Tests:** 2 full uninstall → wipe → fresh-install → configure → test → restart cycles, both passing completely, the second using the final rebuilt installer artifact.
- **Regression Tests:** 138/138 backend unit tests passing.
- **Security Checks:** No real leaked secret in any delivered file; one real leak in scratch tooling found and fixed; one actionable packaging recommendation not yet applied (§12).
