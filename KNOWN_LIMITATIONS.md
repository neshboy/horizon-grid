# Known Limitations — IOC Intelligence Platform 0.1.0

This document distinguishes what is implemented, what is intentionally not implemented, what is a known limitation of what *is* implemented, and what requires action from a user or operator before/after deployment. It exists so that nothing in this list is mistaken for an open bug.

---

## IMPLEMENTED

- Runtime (no-restart) configuration of all 5 AI backends (Ollama, Anthropic, Amazon Bedrock, Google Gemini, Groq) and all 16 IOC providers, including live credential save/change/test, enable/disable, and live AI-backend switching.
- Credential-save semantics that merge into existing stored credentials rather than replacing them — a partial or empty save can no longer silently clear an already-configured field.
- Concurrent-save protection via database row locking on provider/AI configuration writes, for both an already-configured provider (row-level lock) and a brand-new, never-before-configured provider (retry-on-conflict — see the note removed from Known Limitations below).
- AI final-assessment generation with a bounded, validation-scoped retry, and provider-data prompt construction that keeps a per-field size bound to prevent one oversized structural field (e.g. a CVE's CPE-match list) from burying its own short verdict/severity fields.
- IOC investigation export to **JSON** and **Markdown** (built client-side in the browser) **and now also PDF and CSV** (server-rendered — added after this release's ship audit specifically flagged the "Export PDF"/"Export CSV" buttons as UI-exposed and broken, not merely undocumented). All four formats produce a real file from the same underlying investigation data.
- Case management (create, add IOC/notes, list, close/reopen) and the audit log (every configuration change, never a credential value).
- LAN accessibility: the app auto-detects the host's real LAN-facing IP, binds only the app's own ports (not the database/cache/graph services), and creates a Windows Firewall rule scoped to the Private network profile only.
- 180 automated tests (backend unit + integration), including 17 new regression tests added during this release's QA cycle and its immediate follow-up fix pass, one per confirmed-and-fixed bug.

## NOT IMPLEMENTED

*(Nothing currently tracked here — PDF/CSV export, the only item previously listed, was implemented in a follow-up fix pass; see IMPLEMENTED above.)*

## KNOWN LIMITATION

- **Groq's free/shared-tier rate limit (12,000 tokens/minute) is a real, external constraint**, not a platform defect. Rapid, repeated AI analysis calls against Groq in a short window can hit this limit; the platform handles it correctly (a single clean failure, not a retry storm, not a crash), but the underlying capacity is Groq's, not this platform's, to increase.
- **AI-generated verdicts are model-dependent in quality**, most visibly for smaller local models (e.g. Ollama's default `llama3.2:3b`). The prompt-construction and retry fixes in this release ensure the model reliably *receives* the correct evidence and that a malformed response is retried once rather than silently discarded — they cannot make a smaller model's judgment as reliable as a larger hosted one's. This is a model-capability property, not a code defect.
- **No literal GUI-driven installer click-through was performed for this release's build.** The installer's payload was verified byte-for-byte against the current fixed source (see `RELEASE_MANIFEST.md`), and the underlying install/configure/uninstall mechanics were verified by direct invocation of the real production functions in an earlier QA pass this engagement. Driving the installer's own wizard UI via scripted input was attempted and found to be blocked by the test environment itself (not the product) — see `FINAL_RELEASE_QA_REPORT.md` §7 for detail. This is a limitation of the test environment used to verify this release, not of the shipped product.

- **Amazon Bedrock accepts any string in its `model_id` field with no format validation.** Newer Claude models (e.g. Claude Sonnet 4.5) are only invocable on Bedrock through an inference-profile-qualified ID (e.g. a `global.` or region-prefixed ID), not the raw model ID. If an operator enters the raw ID via Admin → AI Providers, every AI call against that provider fails at request time with a Bedrock `ValidationException` ("on-demand throughput isn't supported") rather than being caught at save time. This is an input-validation gap, not a crash or data-loss risk.

## USER ACTION REQUIRED

- The disposable QA test account and test case created during this release's QA cycle (`final-rtp-admin@example.com` credential resets, and a case titled "Final Ship Audit Smoke Test Case") should be reviewed and removed or reset before handing this environment to an actual end user, if this exact database is what ships. A fresh install starts with none of this. The same applies to several `stream-persistence-test-*@example.test` analyst accounts left over from integration-test runs against this specific database.
- **This environment's active AI provider (Bedrock) is currently misconfigured and every AI summary/final-assessment call is failing.** `provider_runtime_configs.model_id` for `bedrock` is set to `anthropic.claude-sonnet-4-5-20250929-v1:0`, missing the required inference-profile prefix — confirmed in the running backend's logs as the cause of repeated `ValidationException` failures (provider summaries for spamhaus, whois_rdap, internet_intelligence, and the final assessment for 8.8.8.8 all failed the same way). Fix via Admin → AI Providers by setting the model ID to `global.anthropic.claude-sonnet-4-5-20250929-v1:0`.
- **This environment's `.env` sets `AWS_REGION=us-east-1`, which does not match the AWS region (`ap-southeast-1` / Singapore) the operator reports their actual Bedrock access is in.** If AI calls still fail after the `model_id` fix above, verify this value and correct it to the region where this account's Bedrock model access is actually enabled, then restart the backend container (env vars are read at container start).

## SECURITY ACTION REQUIRED

> **SECURITY ACTION REQUIRED BEFORE REAL PRODUCTION DEPLOYMENT: ROTATE ALL EXPOSED API CREDENTIALS.**
>
> A prior QA pass found real, live, plaintext third-party API credentials (including an AWS access key/secret pair, and several threat-intelligence provider keys) in a development-environment `.env` file. This is **not** a defect introduced by this release — it is a pre-existing operational exposure in this environment's dev configuration, outside the application's own credential-handling code (which correctly encrypts and masks every credential it manages at rest and in every API response, per this release's security re-verification). It is disclosed here again, without repeating the exposed values, because it must be resolved before any of the affected credentials are trusted in a real production context. This QA process did not rotate, expose, or further propagate these credentials.
