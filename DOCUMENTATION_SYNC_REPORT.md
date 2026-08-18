# Documentation Sync Report

Comparison of the audit dossier (ground truth, gathered by reading the live source in
`C:\Users\User\ioc-intel-platform`) against the existing documentation source files in
`documentation\DOCUMENTATION_SOURCE\*.md` and `docs\*.md`.

**Summary of what was checked:** every file with "provider", "ai", "dashboard",
"scoring", "rbac", or "admin" in its name in both directories, plus every
README-equivalent (`standalone-readme.md`, `docs\*.md` overview files) and
changelog-equivalent (`standalone-changelog.md`, `standalone-release-notes.md`,
`docs\CHANGELOG.md`) file, plus targeted greps across both trees for provider counts,
AI-backend counts, `urlscan`/`google safe browsing`/`groq`/`openai`/`AppImage`/
vulnerability-claim keywords, and the dashboard/scoring-engine feature.

**Headline finding:** the entire legacy `docs\*.md` tree (29 files) appears to predate
the addition of two providers (urlscan.io, Google Safe Browsing) and two AI backends
(Groq, OpenAI), and never mentions the Executive Dashboard or deterministic scoring
engine at all — while the newer `documentation\DOCUMENTATION_SOURCE\` tree is mostly
in sync with the dossier, except for five specific files that were evidently missed in
the last update pass (still say "16 providers" / "four AI backends" / stale test-file
counts) even though sibling files dated the same day in the same directory already say
18 providers / six backends / current test counts.

---

## `documentation\DOCUMENTATION_SOURCE\` (newer tree — mostly in sync, but 5 files are stale)

1. **File:** `documentation\DOCUMENTATION_SOURCE\tech-11-future-roadmap.md`, line 9 (and line 43)
   **Says:** "Multi-backend AI client: four interchangeable backends — Ollama (local, default, no key), Anthropic, AWS Bedrock, and Google Gemini" as a *current capability*, and later lists "Expanded AI backend support" (going beyond "the four existing backends") under **Future Possibilities** — i.e., framed as not-yet-built.
   **Dossier confirms:** `AI_BACKENDS = ["ollama", "anthropic", "bedrock", "gemini", "groq", "openai"]` — Groq and OpenAI are already fully implemented today (own client files, live model discovery, connection tests), per `runtime_config.py`. This same document set's own `tech-03-ai-architecture.md` describes Groq's live model discovery as already built.
   **Fix:** Update to "six interchangeable backends" (add Groq, OpenAI) and remove "Expanded AI backend support" from Future Possibilities, since it's already done.

2. **File:** `documentation\DOCUMENTATION_SOURCE\tech-11-future-roadmap.md`, lines 8, 20, 42
   **Says:** "16 working providers" (line 8), "16-provider registry" (line 42), and "pytest unit tests (13 files) and integration tests (3 files)" (line 20).
   **Dossier confirms:** 17 providers listed in `registry.py`'s `_ALL_PROVIDERS` table plus `internet_intelligence` = 18 total (consistent with sibling files `tech-04-provider-architecture.md`, `standalone-provider-guide.md`, `standalone-quick-start.md`, `standalone-operations-guide.md`, all of which already say 18). Test suite is 25 unit-test files + 12 integration-test files (325 `def test_` total), not 13/3.
   **Fix:** Update to "18 providers" / "18-provider registry" and "25 unit-test files and 12 integration-test files."

3. **File:** `documentation\DOCUMENTATION_SOURCE\tech-10-limitations.md`, lines 7, 19, 23, 62
   **Says:** "The platform registers 16 providers" (line 7), "Most of the 16 providers" (line 19), AI alternative backends listed as only "`anthropic`, `bedrock` (AWS), `gemini`, and `groq`" (line 23, omits OpenAI), and "`backend/app/tests/unit/` (13 files, ~1,486 lines) and `backend/app/tests/integration/` (3 files, ~1,009 lines)" (line 62).
   **Dossier confirms:** 18 total registered providers; 6 AI backends including OpenAI (`openai_client.py`, `DEFAULT_MODEL = "gpt-4o-mini"`, live model discovery); 25 unit-test files / 12 integration-test files.
   **Fix:** Update provider count to 18, add OpenAI to the alternative-backends list, and update test-file counts to 25/12.

4. **File:** `documentation\DOCUMENTATION_SOURCE\architecture-facts.md`, line 58
   **Says:** "16 providers registered in `backend/app/providers/registry.py` (`_ALL_PROVIDERS`)."
   **Dossier confirms:** 17 providers in the registry table plus `internet_intelligence` = 18 total.
   **Fix:** Update to 18 (or 17 formally-listed + `internet_intelligence`).

5. **File:** `documentation\DOCUMENTATION_SOURCE\dev-06-testing-and-build.md`, lines 55 and 160
   **Says:** "the real 16-provider registry" (line 55), and "144 pytest test functions across 16 unit and 3 integration files" (line 160).
   **Dossier confirms:** 18-provider registry; 325 `def test_` functions across 25 unit-test files and 12 integration-test files.
   **Fix:** Update to "18-provider registry" and the current unit/integration file and test-function counts.

6. **File:** `documentation\DOCUMENTATION_SOURCE\user-06-providers.md`, lines 9, 11, 63, 90-95 (whole chapter)
   **Says:** "The platform has **16 providers built in**," "All 16 Providers at a Glance" (a table listing only 16 rows — no urlscan.io or Google Safe Browsing row anywhere in the file), and an explicit walkthrough concluding "= **16 providers total**."
   **Dossier confirms:** 18 total providers, including urlscan.io and Google Safe Browsing (both real, registered, key-required providers configured via the Providers page rather than the setup wizard). Sibling files in the same document set (`standalone-provider-guide.md`, `standalone-quick-start.md`, `tech-04-provider-architecture.md`) already state 18 and specifically explain that urlscan.io/Google Safe Browsing are the two providers configured post-install rather than via the wizard.
   **Fix:** Add urlscan.io and Google Safe Browsing to the at-a-glance table and narrative, update every "16" to "18," and extend the wizard-math walkthrough to account for the 2 additional key-required, non-wizard providers (10 wizard-covered + 6 always-on + 2 key-required-but-not-in-wizard = 18).

---

## `docs\*.md` (legacy tree — systemically out of sync with the current build)

7. **File:** `docs\AI_ENGINE.md` (entire document, e.g. lines 8-9, 24, 29-32, 37-38, 45-48, 62-65, 396-399, 480-494)
   **Says:** The AI backend architecture is described throughout as exactly four backends — Ollama, Anthropic, Gemini, Bedrock (`ai_backend: str = "ollama" # "ollama", "anthropic", "gemini", or "bedrock"`). Zero mentions of Groq or OpenAI anywhere in the file.
   **Dossier confirms:** 6 AI backends exist and are fully wired in — `ollama`, `anthropic`, `bedrock`, `gemini`, `groq`, `openai` — each with its own client file, and Groq/OpenAI additionally have live model-list discovery (`groq_client.list_models()` / `openai_client.list_models()` hitting the real provider APIs) that the other four backends lack.
   **Fix:** Add `groq_client.py` and `openai_client.py` sections (mirroring the existing per-backend tables/diagrams) and update every "four backends" framing to six, including the live-model-discovery distinction for Groq/OpenAI.

8. **File:** `docs\PROVIDERS.md` (entire document, e.g. line 323, and the "All providers at a glance" section starting line 389)
   **Says:** Internet Intelligence Collector is described as "the 16th and last entry in the registry's `_ALL_PROVIDERS` list." Zero mentions of urlscan.io or Google Safe Browsing anywhere in the file, and no `## urlscan.io` / `## Google Safe Browsing` sections exist alongside the other provider sections (`## VirusTotal`, `## AbuseIPDB`, etc.).
   **Dossier confirms:** 18 total registered providers, including urlscan.io (`urlscan_io.py`, sandbox category, submit-then-poll scan model) and Google Safe Browsing (`google_safe_browsing.py`, threat_intel category, Lookup API v4) — both real, working, key-required connectors.
   **Fix:** Add `## urlscan.io` and `## Google Safe Browsing` sections in the same format as the existing provider entries, and update the registry-position/count language from 16th/16 to 18 total.

9. **File:** `docs\ARCHITECTURE.md`, lines 24, 32-35, 66-69, 124-127, 187-188
   **Says:** The architecture diagram and text list only four AI backends (Ollama, Bedrock, Gemini, Anthropic — no Groq/OpenAI nodes in the Mermaid diagram) and state the provider registry has "15 connector modules" with `internet_intelligence` as the "16th/last entry." The document has no section on the Executive Dashboard or the deterministic scoring engine anywhere (confirmed via full-file search — zero matches for "dashboard," "kpi," "scoring engine," or "executive summary").
   **Dossier confirms:** 6 AI backends (add Groq, OpenAI nodes); 18 total providers; and the Executive Dashboard (`/dashboard`, `GET /dashboard/kpis`, `GET /dashboard/executive-summary`) plus the deterministic scoring engine (`app/scoring/engine.py`, wired into `lookup.py` and `security_assessment.py`) are both real, shipped, and load-bearing architecture components that this file — the platform's main architecture reference in this tree — never mentions.
   **Fix:** Add Groq/OpenAI to the AI-backend diagram/text, update the provider-registry count to 18, and add an Executive Dashboard + Deterministic Scoring Engine section (the newer `documentation\DOCUMENTATION_SOURCE\tech-01-architecture.md` already has a template for this under its "Executive Dashboard and Deterministic Scoring Engine" heading).

10. **Files:** `docs\API.md` and `docs\API_DOCUMENTATION.md` (both, entire documents)
    **Says:** Neither file documents a `/dashboard` route at all — no `GET /api/v1/dashboard/kpis` or `GET /api/v1/dashboard/executive-summary` entry exists anywhere in either file (confirmed via full-file search for "dashboard"/"kpi"/"executive" — the only hits are an unrelated `executive_summary` JSON field example in `API.md` and an unrelated frontend export-menu reference in `API_DOCUMENTATION.md`).
    **Dossier confirms:** these two endpoints are real, wired-in, read-only aggregation endpoints backing the Executive Dashboard, and are already documented in the newer tree's `documentation\DOCUMENTATION_SOURCE\standalone-api-documentation.md` (§13, "Executive Dashboard — `/api/v1/dashboard`").
    **Fix:** Add a `/api/v1/dashboard` section to both files, documenting `GET /dashboard/kpis` and `GET /dashboard/executive-summary`.

11. **File:** `docs\USER_GUIDE.md`, lines 238-239 (minor)
    **Says:** The AI-backend comparison feature lists candidate backends as "Anthropic, Gemini, Groq, Bedrock, or a local Ollama model" — five backends, omitting OpenAI.
    **Dossier confirms:** OpenAI is a sixth fully-implemented, selectable AI backend (`openai_client.py`, `DEFAULT_MODEL = "gpt-4o-mini"`).
    **Fix:** Add OpenAI to the list of comparable backends.

---

## Checked and found consistent with the dossier (no mismatch)

- No AppImage claims found anywhere in either `docs\*.md` or `documentation\DOCUMENTATION_SOURCE\*.md` — consistent with the dossier's confirmation that no AppImage exists or is built by this repo.
- No "0 vulnerabilities" / "fully patched" / "no known vulnerabilities" dependency claims found anywhere that would contradict the real pip-audit (32 findings) / npm-audit (11 findings) results.
- Version string `0.1.0` appears consistently across the files that state a version; no file was found asserting a different version number.
- RBAC role/permission descriptions in `docs\ADMIN_GUIDE.md` (three roles: admin/analyst/viewer, static `ROLE_PERMISSIONS` matrix, `user:manage` gating admin routes) match the dossier exactly.
- `docs\SECURITY_ASSESSMENT_TOOLKIT.md` accurately describes the Security Assessment Toolkit as a real, implemented, non-exploitation active-scan module reusing the existing evidence/correlation/AI pipeline — matches the dossier.
- The Executive Dashboard, deterministic scoring engine, urlscan.io, and Google Safe Browsing are all correctly documented as already-implemented (not planned/future) throughout the bulk of `documentation\DOCUMENTATION_SOURCE\` — e.g. `tech-01-architecture.md`, `tech-04-provider-architecture.md`, `standalone-provider-guide.md`, `standalone-changelog.md`, `standalone-release-notes.md`, `backend-02-api-reference.md`, `standalone-api-documentation.md`. Only the five files listed in items 1-6 above lag behind this otherwise-current picture.
