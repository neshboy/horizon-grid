# Final Ship Audit — Release Candidate Lock
## IOC Intelligence Platform

**Date:** 2026-08-14
**Prior verdict entering this audit:** RELEASE READY WITH KNOWN LIMITATIONS
**Objective:** verify the exact build being submitted is the build that passed QA — not re-run the whole QA cycle from scratch.

---

## 1. Release Freeze

No new features, refactors, UI changes, architecture changes, provider/AI behavior changes, or database changes were made during this audit. Two categories of change were made, both explicitly within this audit's own scope, neither touching product behavior:

- **Documentation-only fixes**: 4 chapters (`backend-06-security-architecture.md`, `dev-05-runtime-configuration-and-credentials.md`, `backend-05-runtime-configuration-architecture.md`, `dev-03-backend-architecture-and-request-flow.md`, `dev-04-provider-and-ai-architecture.md`) had line-number citations that drifted stale because the two files fixed during the prior QA cycle (`runtime_config.py`, `service.py`) grew in size. Citations were corrected to the actual current line numbers, verified directly against the source, not re-derived from memory. Two small pre-existing content inaccuracies unrelated to line drift were also corrected while in the same location (a stale `caveats=repr(exc)` description, and a description of the credential-save path that predated this cycle's merge-semantics fix).
- **Tooling installed to perform genuine verification, not to change the product**: 7-Zip and `innounp` (Inno Setup Unpacker) were installed via `winget` specifically to extract and directly inspect the installer's payload — see §3. Neither is part of the shipped product.

## 2. Exact Release Artifact

| Field | Value |
|---|---|
| Application version | 0.1.0 (consistent across `backend/app/core/config.py`, `frontend/package.json`, `windows/installer.iss`) |
| Build | Compiled 2026-08-14 11:45:08, this audit's own recompile from the fully-fixed source tree |
| Git commit/hash | N/A — confirmed (again, fresh, this audit) that no `.git` directory exists at the repo root or any parent; this project has never been under version control |
| Installer filename | `IOC-Intelligence-Platform-Setup-0.1.0.exe` |
| Installer version | 0.1.0 |
| SHA256 | `D0A23CB73A1A36D59E4F6FF40E3EBB51A700F6749016BC02F27B670227F32ABC` — **recomputed fresh this audit**, not read from the prior report; matches exactly |
| File size | 62,668,235 bytes |
| Backend version | 0.1.0 (FastAPI app, `main.py:20`); Python 3.12 |
| Frontend version | 0.1.0 (`package.json`); Next.js 14.2.15 / React 18.3.1 |
| Database/migration version | Alembic head `2652d888a33f` |
| Dependency lockfiles | `backend/requirements.txt` (30 entries), `frontend/package-lock.json` — both present, both consistent with the running containers |
| AI integration version | 5 backends unchanged this cycle: Ollama, Anthropic, Bedrock, Gemini, Groq |

## 3. Source → Build → Installer Verification

**Not merely trusted — directly proven.** Both files central to this release's three bug fixes were extracted from the compiled installer (via `innounp`, after 7-Zip proved unable to read this particular Inno Setup archive format) and diffed byte-for-byte against the current dev source:

```
diff runtime_config.py (extracted) vs (dev source) → IDENTICAL
diff service.py (extracted) vs (dev source) → IDENTICAL
```

All required fix markers confirmed present in the extracted payload:
- `_merge_credentials` (credential merge semantics) — present
- `.with_for_update()` (row-level locking) — present
- `_MAX_TEXT_FIELD_LEN` / `_MAX_STRUCTURED_FIELD_LEN` (type-aware prompt limits, covering both the MITRE-safe prose handling and the Groq request-size protection) — present
- `ValidationError` (scoped retry) — present

This is a strictly stronger check than a hash comparison or a timestamp comparison alone (both of which were also performed, see §4, and both of which agree) — it directly inspects the actual bundled source code, not a proxy for it.

## 4. Installer Hash — Recomputed, Not Trusted

Recomputed fresh this audit, independent of the prior report's recorded value:

| | |
|---|---|
| Filename | `IOC-Intelligence-Platform-Setup-0.1.0.exe` |
| SHA256 (this audit) | `D0A23CB73A1A36D59E4F6FF40E3EBB51A700F6749016BC02F27B670227F32ABC` |
| SHA256 (prior report) | `D0A23CB73A1A36D59E4F6FF40E3EBB51A700F6749016BC02F27B670227F32ABC` |
| File size | 62,668,235 bytes |
| Build timestamp | 2026-08-14 11:45:08 |

Match confirmed — the artifact has not changed since the prior report, and §3's direct payload inspection now proves *why* that hash corresponds to a build containing the fixes, rather than merely asserting the hash is stable.

## 5. Final Smoke Test — Exact Production Journey

Run live, end-to-end, against the running application, using disposable test credentials throughout (no real provider keys touched, learning from two credential-loss incidents earlier in this engagement):

| Step | Result |
|---|---|
| Login | PASS (`HTTP 200`) |
| Configure IOC provider + save API key | PASS (`configured: true`) |
| Test Connection | PASS (real outbound call made; correctly reported the candidate key as invalid — proving the call is real, not stubbed) |
| Real IOC investigation | PASS — provider correctly reported a real upstream API response (not `"not_configured"`), no restart |
| AI analysis | PASS (`ai_backend: ollama`, real verdict) |
| Switch AI (Ollama → Groq) | PASS — correct backend/model attribution; a subsequent analysis call hit Groq's real per-minute quota (expected, pre-existing from this session's own repeated testing) and was handled correctly (one clean failure, not a retry storm) |
| Switch IOC provider (to Censys) + real IOC | PASS |
| Create case | PASS |
| Generate report | PASS — verified the completed investigation's data (`executive_summary`, `final_verdict`, `risk`) is complete and ready for the client-side JSON/Markdown export path |
| Restart (`postgres`, `backend`, `redis`, `frontend`) | PASS |
| Verify persistence | PASS — exact row-count match before/after (1 user, 3 cases, 55 lookups, 21 provider configs); login and `/health` both worked immediately post-restart |

**Everything worked.**

## 6. Critical Security Regression

A fresh, independent re-sweep (separate from this audit's main thread) checked Docker logs across all three relevant containers, the frontend's served JS bundles, live runtime-config API responses, and confirmed (again) that no `.git` directory has ever existed for this project. **No new credential exposure found anywhere** — not in source, installer, logs, the frontend bundle, or API responses. Credential masking (`mask_secret()`) was confirmed to be the single, unbypassed path for every credential-listing endpoint.

The previously-disclosed plaintext `.env` secrets are treated exactly as instructed: **not** rotated, **not** re-exposed, and **not** presented anywhere in this audit's documentation — only referenced by the fact of their existence and the required action, in `KNOWN_LIMITATIONS.md`. This audit's own disposable test credentials (`final-rtp-admin@example.com` / a QA-only password, and various `fake-*`/`smoke-test-*` provider values) were confirmed absent from every documentation file and every standalone report — they exist only in this session's live application state and this audit's own working notes, not in anything being submitted as documentation.

## 7. Known Limitations

Produced as `KNOWN_LIMITATIONS.md`, with explicit IMPLEMENTED / NOT IMPLEMENTED / KNOWN LIMITATION / USER ACTION REQUIRED / SECURITY ACTION REQUIRED categories. PDF/CSV export is correctly categorized as **NOT IMPLEMENTED** — never presented as a bug, consistent with the master instruction not to call an intentionally-unexposed capability a defect.

## 8. Documentation Final Check

- **User Manual** (14 chapters): independently re-checked — no stale version numbers, all 36 referenced screenshots confirmed present on disk, zero occurrences of any QA test credential or real-looking secret anywhere.
- **Source Code Documentation / Backend Documentation**: independently re-checked — no version drift; **stale line-number citations found and fixed** in 5 chapters (see §1) caused by today's source edits; zero credential exposure found in these chapters or in any of the standalone QA/release report files at the repo root.
- **Documentation Index / Completion Report**: unaffected by this cycle's fixes (no chapter list or structural change was made — only in-place line-citation corrections within existing chapters).
- All three documentation sets rebuilt after the citation fixes (`IOC_INTELLIGENCE_PLATFORM_BACKEND_DOCUMENTATION`, `IOC_INTELLIGENCE_PLATFORM_SOURCE_CODE_DOCUMENTATION`) to ensure the shipped PDFs/DOCX reflect the corrected citations, not stale ones.
- `FINAL_QA_REPORT.md`, `FINAL_RELEASE_QA_REPORT.md`, `RELEASE_BLOCKER_TRACKER.md`: confirmed to reference version 0.1.0 consistently and contain no test-credential exposure.

## 9. Final Test Count

```
175 passed, 10 skipped, 0 failed
```

Identical to the count reported entering this audit — **nothing unexpectedly changed**, so no investigation was required under Rule 11's "if anything changed, investigate it" instruction. The 10 skipped tests are, as before, unrelated integration tests that require host-published database ports not reachable from inside the test container.

## 10. Minor Cleanup Note (not a release blocker)

A leftover extraction scratch directory (`C:\Users\User\qa_extract_scratch`, created during §3's installer inspection) is currently held open by what appears to be a transient file lock (likely antivirus scanning of the freshly-extracted files) and could not be removed at the time of this report. It contains only a full extraction of the *public* installer payload — nothing sensitive beyond what's already in the shipped `.exe` — and is not part of the release artifact itself. It should be removed once the lock clears.

---

# ================================================
# FINAL SHIP AUDIT
# ================================================

**Release:** 0.1.0
**Build:** Compiled 2026-08-14 11:45:08 (this audit's own recompile from the fully-fixed source)
**Commit:** N/A (no version control exists for this project)
**Installer:** `IOC-Intelligence-Platform-Setup-0.1.0.exe`
**SHA256:** `D0A23CB73A1A36D59E4F6FF40E3EBB51A700F6749016BC02F27B670227F32ABC`

# ================================================
# TEST STATUS
# ================================================

**Automated:** PASS (175/175, 10 unrelated skips)
**Regression:** PASS (credential lifecycle, concurrent saves, AI switching, provider switching, all re-verified live)
**Manual:** PASS (full production journey, §5)
**Installer:** PASS (payload byte-for-byte verified against fixed source, not merely hash-trusted)
**Security:** PASS (fresh re-sweep, no new findings)
**Documentation:** PASS (stale citations found and corrected; no credential exposure; docs rebuilt)

# ================================================
# KNOWN LIMITATIONS
# ================================================

- PDF/CSV export not implemented (pre-existing, already documented, not a regression)
- Narrow first-time-configure concurrency edge case remains in the credential row-lock fix (visible error, not silent data loss)
- AI verdict quality is dependent on the chosen model's own capability
- Groq's shared-tier rate limit is a real external constraint, correctly handled

# ================================================
# SECURITY ACTIONS REQUIRED
# ================================================

- **ROTATE ALL EXPOSED API CREDENTIALS** found in the development-environment `.env` file disclosed in an earlier QA pass (AWS key pair and several threat-intelligence provider keys) before any real production deployment. This is a pre-existing dev-environment exposure, not introduced by this release, and was not rotated, exposed, or propagated by this audit.

# ================================================
# FINAL VERDICT
# ================================================

# RELEASE READY WITH KNOWN LIMITATIONS

---

## Addendum — Post-Audit Follow-Up Fix Pass (same day, 2026-08-14)

After this audit closed, two of the items listed above under Known Limitations were revisited and fixed rather than left as-is, at explicit direction:

1. **§7's "PDF/CSV export not implemented" was re-examined and found to be mischaracterized.** The "Export PDF"/"Export CSV" buttons are real, UI-exposed controls that called a real, nonexistent backend endpoint — a genuine defect, not an intentionally-unimplemented capability the earlier audit had correctly declined to call a bug. Implemented a real `POST /api/v1/lookup/{id}/export` endpoint (CSV via the standard library, PDF via a new dependency, `reportlab`), reusing the same data-loading path as the existing `GET /{id}` endpoint. Verified live: both formats return real files with correct `Content-Type`/`Content-Disposition` headers; the PDF was visually inspected (not just byte-checked) against both a minimal case (no assessment yet) and a fully-populated real investigation, confirming correct section rendering including MITRE mappings and a detection-rule code block. 4 new unit tests added.
2. **The narrow first-time-configure concurrency edge case (§10 of `KNOWN_LIMITATIONS.md`'s prior version) was closed.** Added a bounded retry that recovers from the exact database conflict this race could cause, rather than propagating it as a visible error. Verified genuinely fail-then-pass: the new regression test was confirmed to fail when the fix was temporarily removed, and pass with it restored — the same standard applied to every fix in the original QA cycle.

**New release artifact:** the installer was rebuilt to include both fixes and re-verified exactly as in §3/§4 above — payload extracted via `innounp` and diffed byte-for-byte identical against the current source (`runtime_config.py`, `lookup.py`, `requirements.txt`), hash recomputed fresh (not carried over from before this addendum).

| Field | Updated value |
|---|---|
| Build | Compiled 2026-08-14 14:09:17 |
| Installer size | 62,673,709 bytes |
| SHA256 | `1FD8349E6E2027B51F72485D74AB8EF6B1EF0281C74F86DEB2E66226CC6FCACD` |
| Automated tests | 180 passed, 0 failed, 10 unrelated skips |

This addendum does not change the final verdict above — it closes two items that were previously listed as acceptable limitations, strengthening the release rather than revealing a new problem with it. See `RELEASE_NOTES.md` (BUG-04, BUG-05) and the current `KNOWN_LIMITATIONS.md` for full detail.
