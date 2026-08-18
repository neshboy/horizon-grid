# Release Notes — IOC Intelligence Platform 0.1.0

## Major Capabilities

- Multi-provider IOC investigation across 16 threat-intelligence sources and 5 AI backends, with parallel provider querying, cross-provider correlation, and an AI-generated final assessment.
- Fully runtime-configurable providers and AI backends — no restart required to add, change, enable, disable, or switch any of them.
- Case management, an audit log for every configuration change, and investigation export in all four formats offered in the UI: JSON and Markdown (client-side), PDF and CSV (server-rendered).
- LAN-accessible deployment with automatic host-IP detection and a properly scoped Windows Firewall rule.

## Major Fixes This Release

**BUG-01 (P0) — Saving a provider or AI credential without retyping every field could silently destroy an already-working configuration.** The settings UI only ever shows an existing credential as a masked placeholder, never as real input — so opening an already-configured provider and clicking Save without retyping the key used to wipe it, flipping a fully working provider to "not configured" with no warning. Fixed with merge-not-replace semantics: a save now only changes the fields actually present in the request. Also closed a related concurrency gap (two simultaneous saves to the same provider could still lose one's change) with database-level row locking, and added regression tests that exercise the real database-backed save functions, not just an in-memory helper.

**BUG-02 (P1) — The AI final assessment could fail outright on a known, already-anticipated model quirk.** Small deviations in AI output (a self-contradictory verdict/probability pair) were already correctly caught by validation, but nothing ever retried — a single bad sample discarded an entire otherwise-complete investigation's conclusion. Fixed with a bounded, precisely-scoped retry: only retries the specific validation failure it's meant for, never a rate-limit or network error (retrying those would just waste more of an already-exhausted quota).

**BUG-03 (P1) — Large provider data could bury its own severity signal from the AI, or, after an early fix attempt, overload a hosted AI provider's request-size limit.** A critical vulnerability's severity score was getting lost underneath hundreds of low-value structural entries in the same provider response, causing the AI to call a critical vulnerability "benign." Fixed with a field-size limit; verified independently on two different AI backends. A follow-up fix distinguishes prose fields (which can carry real signal even when long) from structural list/dict fields (which are reliably safe to cap tightly regardless of provider) — closing both the original bug and a real regression the first fix version introduced.

*(A fourth item, a reported "investigation export is completely broken," was re-investigated this cycle and initially retracted — JSON/Markdown export was never actually broken; it works entirely client-side. That re-investigation also surfaced that PDF/CSV export were UI-exposed and genuinely broken, not merely undocumented — the buttons exist and call a real endpoint that 404'd. That's a real defect, not an acceptable "not implemented" state, so it was implemented in a follow-up pass: see below.)*

**BUG-04 (P1) — "Export PDF"/"Export CSV" were real, UI-exposed buttons calling a nonexistent backend endpoint.** Every click 404'd. Implemented a genuine `POST /api/v1/lookup/{id}/export` endpoint rendering both formats from the same data the JSON/Markdown exports already use — CSV via the standard library, PDF via a new, minimal dependency (`reportlab`) — verified live with real investigation data (visually confirmed correct section rendering, including MITRE mappings and detection-rule code blocks) and via 4 new unit tests, including a graceful-handling test for an investigation with no assessment yet.

**BUG-05 (P3) — A narrow first-time-configure race could surface a visible error.** Two concurrent *first-ever* saves to the same brand-new provider could both attempt to create its row and one would fail with a database integrity error instead of completing normally. Fixed with a bounded retry that re-attempts the save (as a normal update, once the other request's row exists) rather than propagating the error. Verified genuinely fail-then-pass by simulating the exact collision and confirming the retry recovers.

## Testing Improvements

- 180 automated tests passing (0 failures), including 17 new regression tests added this release and its immediate follow-up fix pass, each tied to a specific confirmed-and-fixed bug.
- New integration test coverage against a real database for provider/AI credential persistence, including two genuine concurrency tests (an existing-row lock and a new-row collision retry).
- New unit test coverage for both server-rendered export formats.
- Every fix in this release was independently re-verified by a second pass explicitly tasked with trying to disprove it — this caught two real, additional problems beyond the originally-reported bugs before release, and a follow-up ship audit caught one more (the export feature) that had been mischaracterized rather than fixed.

## Runtime Configuration Improvements

- Credential saves now merge into existing configuration instead of replacing it wholesale.
- Provider/AI configuration writes are now protected against concurrent-save races.

## AI Improvements

- Bounded, precisely-scoped retry for a known AI output-validation failure mode.
- Provider data reaching an AI prompt is now bounded in a way that preserves genuine signal (in prose fields) while still suppressing structural noise (in list/dict fields), across every provider examined.

## Provider Improvements

- Provider state (disabled / configured-but-failing / not configured) is clearly and correctly distinguished in both API responses and investigation results.

## Known Limitations

See `KNOWN_LIMITATIONS.md` for the complete, categorized list. In short: AI verdict quality still depends on the chosen model's capability; Groq's shared-tier rate limit is a real external constraint; no literal GUI-driven installer click-through was performed (a test-environment limitation, not a product one); a pre-existing, already-disclosed credential-rotation action is required in the dev environment before real production use.

## Security Considerations

Every credential-handling code path was re-verified this release: encryption at rest, masking in every API response, no leakage into logs or the frontend bundle, and CORS scoped to private-network address ranges rather than a wildcard. No new security issues were found. One pre-existing, already-disclosed action item remains outside this release's scope: rotating a set of real third-party credentials found exposed in a development-environment configuration file — see `KNOWN_LIMITATIONS.md` for the required action. No credential values are included anywhere in this document or its supporting reports.
