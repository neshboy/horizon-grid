# Hackathon Submission Checklist

Every item below reflects an actual check performed while assembling this submission, not an assumed pass. Where something was verified in an earlier session rather than freshly re-run in this one, that's stated rather than implied.

## Content

- [x] Product name correct — "HORIZON GRID" throughout.
- [x] Tagline correct — "Every Signal. One Operational Picture." throughout.
- [x] Current screenshots — 16/16 required screenshots present, all captured against the live v0.2.4 branded build, all opened and visually confirmed non-blank.
- [x] Executive documentation — `HORIZON_GRID_EXECUTIVE_OVERVIEW.pdf`.
- [x] User manual — `HORIZON_GRID_USER_MANUAL.pdf` (pre-existing, previously verified accurate; not regenerated this pass).
- [x] Technical documentation — architecture, backend, API, source-code-guide, security PDFs, plus a new consolidated `HORIZON_GRID_ARCHITECTURE.pdf`.
- [x] Backend documentation — `HORIZON_GRID_BACKEND_DOCUMENTATION.pdf`, rebuilt this pass after fixing stale AI-backend/provider counts.
- [x] API documentation — `HORIZON_GRID_API_REFERENCE.pdf`.
- [x] Architecture — `HORIZON_GRID_ARCHITECTURE.pdf` (data flow, AI, provider, database, Windows/Linux deployment, security), plus real architecture diagram PNGs.
- [x] Source code — complete, extracted via `git archive` from the pushed HEAD commit (so it matches GitHub exactly).
- [x] Windows installer — `HORIZON-GRID-Setup-0.2.4.exe` included with its SHA256 checksum. A silent, isolated install of this exact build was verified in an earlier session; not re-run in this packaging pass.
- [x] Linux package — `horizon-grid_0.2.4_amd64.deb` included with its SHA256 checksum. Not freshly reinstalled in this packaging pass; the package itself is the same one already verified via a real WSL upgrade test documented in the Engineering History chapter.
- [x] Demo guide — `HORIZON_GRID_HACKATHON_DEMO_GUIDE.pdf`. Every feature it walks through (dashboard, investigation, threat scoring, provider health, AI switching, Security Assessment, export) was individually confirmed working via real screenshots taken this session; the guide's exact click-by-click script was not walked start-to-finish as a timed rehearsal.
- [x] QA report — `HORIZON_GRID_FINAL_QA_REPORT.pdf` plus `HORIZON_GRID_ENGINEERING_HISTORY.pdf` (development journey and bug history).
- [x] Changelog — `CHANGELOG.md` and `HORIZON_GRID_CHANGELOG.pdf`, both reflect the current v0.2.4 state.
- [x] Design documentation — `HORIZON_GRID_DESIGN_OVERVIEW.pdf`, explicitly states HORIZON GRID is an independent project with no affiliation to any defense contractor, military organization, or government agency.
- [x] License — `LICENSE` (GNU AGPL v3, matching the badge in the project's own README).
- [x] Third-party notices — `THIRD_PARTY_NOTICES.md` plus full machine-generated dependency/license CSVs for both backend (85 packages) and frontend (523 packages). No GPL/AGPL dependencies found among them.

## Secret Scan (performed against the extracted source tree)

- [x] No AWS-style access keys (`AKIA...`) found.
- [x] No private key blocks (`-----BEGIN ... PRIVATE KEY-----`) found.
- [x] No OpenAI/GitHub/GitLab/Slack-style token patterns (`sk-`, `ghp_`, `glpat-`, `xox...`) found.
- [x] No `.env` file of any kind present in the extracted source tree.
- [x] No hardcoded credential-looking values beyond field-name-to-setting-name mapping dictionaries (e.g. `"virustotal": {"api_key": "virustotal_api_key"}` — a string naming a settings field, not a secret value).

## Cleanliness

- [x] No `.git`, `node_modules`, virtual environments, `__pycache__`, or build caches — the source folder is a clean `git archive` export, which only ever contains tracked files.
- [x] No temporary/debug files, old builds, or backup files — same reason.
- [x] No personal data identified in any included screenshot or document.

## Consistency

- [x] GitHub is current — this submission's source code matches the exact commit pushed to `main` at packaging time.
- [x] Version consistent — 0.2.4 in the installers, the backend `/health` response, `frontend/package.json`, and every generated document's cover page.
- [x] Documentation matches the application — every provider count (18), AI backend count (11), and IOC type count (32) cited in this submission was verified directly against `backend/app/providers/registry.py`, `backend/app/core/runtime_config.py`, and `backend/app/ioc/types.py` rather than carried forward from older documentation. Six files found still citing pre-v0.2.0 counts were corrected as part of this submission.

## Final Validation Performed This Session

- [x] The live application stack was confirmed running and healthy (all 8 containers up) immediately before packaging.
- [x] The full backend regression suite was re-run live: **383 passed, 39 skipped**, matching the last known-good count with zero new failures.
- [x] Every generated PDF was built without a missing-figure error, and a sample (cover + table of contents) of the newly-created PDFs was rendered and visually inspected.
- [x] One real defect was found and fixed during this session's own QA: a screenshot (`reports-export-menu.png`) had been saved as a byte-for-byte duplicate of a different screenshot; replaced with a genuine, distinct capture and the one PDF embedding it was rebuilt.

## Known, Disclosed Limitations Carried Into This Submission

This submission does not claim a level of completeness the project's own QA history doesn't support. See `HORIZON_GRID_ENGINEERING_HISTORY.pdf` and `08_TESTING/HACKATHON_TEST_REPORT.md` for the full, attributed list — headline items: the most recent functional-test report in the project's history states its own verdict as interim, not final; a handful of P2–P4 adversarial findings were not independently re-verified a second time; and a live elevated Windows installer run and a live Linux reboot test were not performed in the sessions that produced the underlying evidence for this package.
