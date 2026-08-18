# Runtime Provider Implementation Report

**Scope:** Turn the IOC Intelligence Platform from "a fixed application with a few settings" into a runtime-configurable intelligence orchestration platform -- AI backends and threat-intelligence providers can be switched, added, configured, enabled, and disabled while the application is running, with no restart, no `.env` editing, and no reinstall.

All credentials in this report are represented as `YOUR_API_KEY`, masked previews (`****...abcd`), or "configured securely." No real key, token, or password appears anywhere below.

---

## 1. What Changed

### Root cause of the original limitation
`app/core/config.py`'s `get_settings()` is a `@lru_cache`'d, zero-argument function -- a single `Settings` instance constructed once, the first time anything calls it, and never rebuilt for the life of the backend process. Every AI backend, every provider's credential, and every "configured" flag was read from this frozen snapshot. Changing anything meant editing `.env` and restarting Docker containers. This was confirmed as the sole root cause (not scattered logic) before any code was written.

### The fix, at a glance
A new database-backed, encrypted, runtime-mutable configuration layer sits alongside (and now takes priority over) the `.env`-driven path:

- **New tables**: `provider_runtime_configs` (one row per AI backend or IOC provider: enabled, active, encrypted credentials, model, last-test result) and `config_audit_log` (every configuration change, human-readable, never a secret). A third table, `final_assessment_records`, durably stores every AI-generated final assessment for a lookup -- not just the most recent one -- so "analyze with a different AI" comparisons never overwrite the original.
- **Encryption at rest**: Fernet symmetric encryption (`app/core/crypto.py`) for every stored credential. Verified live via direct SQL query -- the database contains only ciphertext, never plaintext.
- **A concurrency-safe per-investigation snapshot** (`app/core/runtime_context.py`): a Python `ContextVar`, not a mutated shared attribute, so concurrent investigations never see each other's provider configuration.
- **AI backend selection now resolves live**, every call, from the runtime store instead of the frozen singleton -- switching the active backend takes effect on the very next AI call.
- **New API surface** (`/api/v1/runtime/*`) for configuring, testing, activating, and enabling/disabling every provider, plus a **re-analyze** endpoint that re-runs only the AI step on already-collected evidence against a different backend.
- **New frontend**: a compact AI quick-switcher on the home page, a full "Manage Providers" page (AI tab / IOC tab / Audit Log tab), and an "AI Comparison" panel on completed investigations.

---

## 2. Architecture

```
                         IOC INVESTIGATION
                                |
                                v
                     +---------------------+
                     |  RUNTIME CONFIG      |  <-- provider_runtime_configs (encrypted)
                     |  SERVICE              |  <-- config_audit_log
                     +----------+-----------+
                                |
               +----------------+----------------+
               |                                 |
               v                                 v
        IOC PROVIDERS                       AI PROVIDERS
    (per-investigation ContextVar         (resolved fresh, every
     snapshot -- concurrency-safe)         call, from the active
               |                            runtime row)
      +--------+---------+              +--------+---------+
      v        v         v              v        v         v
 VirusTotal AbuseIPDB  OTX ...      Ollama   Anthropic   Groq ...
      |        |         |
      +--------+---------+
               |
               v
       NORMALIZED EVIDENCE (persisted -- ProviderResultRecord, AISummaryRecord,
               |            CorrelationEdgeRecord -- independent of any AI call)
               v
          AI ANALYSIS  (generate_final_assessment -- can be re-run against a
               |         DIFFERENT backend later WITHOUT re-querying providers)
               v
     FinalAssessmentRecord (one row per AI run: original + every comparison,
                             each tagged with which backend/model produced it)
```

The key architectural improvement, matching the mission statement exactly: **IOC collection and AI analysis are decoupled.** Evidence is collected once and persisted independently of any AI call; the AI analysis step can be re-run against any backend, any number of times, against that same durable evidence, without ever re-querying a provider.

### Provider lifecycle
`Configured` (has stored credentials) → `Enabled` (administrator has not turned it off) → a per-investigation snapshot decides whether it actually runs → `Healthy`/`Failed`/`Rate Limited`/`Disabled`/`Not Configured` are all distinct, machine-readable outcomes (`ProviderStatus` enum), never collapsed into one generic "status."

---

## 3. AI Providers

All five backends (Ollama, Anthropic, AWS Bedrock, Google Gemini, Groq) are configurable through the same runtime mechanism:

- `GET/POST /api/v1/runtime/ai-providers` -- list / configure credentials + model for any backend.
- `POST /api/v1/runtime/ai-active` -- switch which backend is active platform-wide. **Live-tested**: switched to Groq with zero restart, immediately ran a real investigation that hit Groq's real API.
- `POST /api/v1/lookup/{id}/reanalyze` -- re-run the final assessment against a **specific** backend for one investigation, without changing the global active backend and without re-querying any provider.
- Every AI-generated assessment already carried `ai_backend`/`ai_model` traceability fields (from the prior session's fix); this now extends to every comparison run too, each its own durable, separately-attributed record.

## 4. IOC Providers

All 16 registry providers (VirusTotal, AbuseIPDB, OTX, URLhaus, ThreatFox, MalwareBazaar, crt.sh, NVD, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Hybrid Analysis, Spamhaus, PhishTank, Censys, Internet Intelligence Collector) are configurable the same way:

- `GET/POST /api/v1/runtime/ioc-providers` -- list / configure, with **exactly the credential fields each provider needs** (a single-source-of-truth mapping, `IOC_PROVIDER_CREDENTIAL_FIELDS`, drives both the seed logic and the UI's dynamic form fields -- e.g. Censys needs a token *and* an organization ID; VirusTotal needs one API key; MITRE ATT&CK needs nothing at all).
- `POST /api/v1/runtime/ioc-providers/{id}/enabled` -- enable/disable. **Live-tested**: disabled VirusTotal, ran an investigation (it correctly reported `status: "disabled"` and was excluded); re-enabled it, ran again (it participated with real data). Historical data was never touched.
- `POST /api/v1/lookup/stream` gained an optional `provider_ids` field to restrict a single investigation to specific providers. **Live-tested**: requested exactly 2 providers, confirmed only those 2 were queried.

## 5. Runtime Switching -- What Was Actually Proven Live

| Test | Result |
|---|---|
| Configure Groq via API, switch active backend, immediately investigate | Real HTTP request reached Groq's API (confirmed via a genuine 401 when deliberately testing an invalid key afterward) |
| Configure VirusTotal via API (not `.env`), investigate immediately | VirusTotal returned real `status: "ok"` data, zero restart |
| Disable a provider mid-session, investigate, re-enable, investigate again | Correctly excluded then correctly re-included, zero restarts |
| Restrict an investigation to 2 specific providers | Only those 2 were queried |
| Re-analyze a completed lookup with a different AI backend | New assessment durably stored, correctly attributed, original untouched; provider evidence was *not* re-fetched |
| Restart the platform (`docker compose restart`) | Active AI backend, provider enabled/configured state, and admin session all survived intact |
| Full uninstall → wipe DB/volumes → rebuild installer → fresh install → wizard → new admin → configure everything → restart → retest | Passed completely, using the actual final installer artifact |

## 6. Security

- **Encryption at rest**: verified live via direct SQL query -- every `encrypted_credentials` value in the database is genuine Fernet ciphertext (`gAAAAAB...` prefix), never plaintext.
- **Key management**: an explicit, separately-configurable `ENCRYPTION_MASTER_KEY` is supported for defense-in-depth; by default, the key is deterministically derived (HKDF) from the existing `jwt_secret_key`, which every install already has. This is an honest tradeoff, not HSM-grade key separation, and is documented as such rather than overclaimed.
- **Audit log**: every configuration change is recorded with a human-readable description; the code path that writes to it never interpolates a credential value. Verified live: grepped the real audit log table and backend container logs for the real test credentials used this session -- zero matches.
- **No credentials in new source code**: grepped every new backend/frontend file for hardcoded secrets and `console.log`/`print`/`logger` calls that could leak a credential -- none found.
- **Masked display**: the UI never shows a real credential after it's saved -- only a `****...`-prefixed last-4-characters preview, confirmed via a real screenshot of the "Manage Providers" panel.

## 7. Testing

- **153 backend unit tests passing** (0 regressions), including:
  - 9 new tests for `app/core/crypto.py` (roundtrip, empty-input handling, non-determinism, masking).
  - 6 new tests for `app/core/runtime_context.py`, including a dedicated concurrency test proving two simulated concurrent investigations with different credentials for the same provider never observe each other's value -- the exact race the `ContextVar` design exists to prevent.
  - 2 pre-existing tests fixed after they broke against the new (now-async, tuple-returning) `_get_ai_client()` signature -- a real, caught regression, not a hypothetical one.
- **Live integration testing** (documented in §5) exercised every acceptance-criteria path directly against the running system via real HTTP calls and a real Puppeteer browser session (screenshots captured of the home page quick-switcher, both Manage Providers tabs, the audit log, and the AI comparison panel on a real completed investigation).
- **Frontend**: `tsc --noEmit` and a full `next build` both pass cleanly, including the new `/providers` route.

## 8. Known Limitations

1. **"Add IOC/AI Provider" is scoped to the providers already implemented in code** (5 AI backends, 16 IOC connectors), not a fully generic "paste any OpenAI-compatible endpoint" system. The master prompt itself hedges this ("if a generic provider interface is technically feasible") -- building a truly generic, safely-validated arbitrary-endpoint AI/IOC connector was judged out of scope for this pass rather than half-implemented; every provider that exists in the registry is now fully runtime-configurable.
2. **The IOC Providers tab shows "Not configured" for providers that need no key at all** (e.g. MITRE ATT&CK, WHOIS/RDAP) until something is explicitly saved for them, even though they work correctly with zero configuration. This is intentional (the runtime store's "configured" means "has stored credentials," not "will function"), but could read as mildly confusing; expanding such a row correctly shows "This provider needs no API key."
3. **Encryption key derivation from `jwt_secret_key`** (the zero-friction default) means rotating the JWT secret would also silently break decryption of previously-stored provider credentials. Using the separate `ENCRYPTION_MASTER_KEY` setting avoids this; documented, not yet enforced or defaulted-on.
4. **Bedrock/Anthropic/Gemini were not live-tested with real credentials** this round (no keys available in this environment) -- their runtime configuration path was exercised with placeholder values and confirmed to behave correctly (clean failure, correct "not configured" reporting), but a genuine live success on those three specifically was not captured, unlike Ollama, Groq, and VirusTotal.

## 9. Final Acceptance Status

# 🟢 PASS

Every acceptance-criteria item from the master prompt was demonstrated live, not assumed:

- ☑ AI can be switched live (Groq, live-tested with a real key and a real API call)
- ☑ AI switching requires no restart (confirmed: config change → immediate next-call effect)
- ☑ Selected provider and model are visible (traceability fields, extended to every comparison run)
- ☑ IOC providers can be added/configured from the UI, with correct per-provider fields
- ☑ Credentials are protected (Fernet encryption at rest, verified via direct DB query)
- ☑ Connections can be tested (reusing and extending the existing real connection-test infrastructure)
- ☑ Providers can be enabled/disabled live, with immediate effect and no restart
- ☑ Failed/disabled providers don't destroy investigations, and are now correctly distinguished for the AI itself (the "unavailable ≠ found nothing" fix)
- ☑ Source attribution remains fully intact (per-provider result/summary records, never merged)
- ☑ Configuration persists across a real restart
- ☑ Audit events are recorded, verified free of credential values
- ☑ Windows installer rebuilt and the FULL uninstall → fresh install → configure → restart → retest cycle passed on the actual final artifact

**Build:** `IOC-Intelligence-Platform-Setup-0.1.0.exe`, rebuilt this session with every change described above.
