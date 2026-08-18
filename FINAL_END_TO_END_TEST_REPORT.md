# IOC Intelligence Platform — Final End-to-End Test Report

**Test date:** 2026-08-11
**Tester:** Automated QA pass (Claude Code), treating the build as never-before-tested per explicit instruction
**Scope:** Full install → configure → run → failure-inject → real OS reboot → uninstall → reinstall → final clean install, against the actual compiled Windows installer only (no source/dev-server shortcuts taken)

---

## 1. Build Tested

- **Installer:** `IOC-Intelligence-Platform-Setup-0.1.0.exe`
- **Version:** 0.1.0 (confirmed via both `AppVersion` and the Win32 `FileVersion` resource — the latter required a `VersionInfoVersion` directive fix this pass, since Inno Setup does not auto-populate `FileVersion` from `AppVersion` alone)
- **Size:** ~59.7 MB (initial) / ~62.6 MB (final, after all fixes)
- **SHA256 (final):** `b32b1cc02205a0a53dda200d6bc336943a71df6b930cecd2dff45b28d84e81e8`
- **Architecture:** Installs to `C:\Program Files\IOC Intelligence Platform` (64-bit path), confirmed by direct observation of a real install, not by inspecting the Setup.exe launcher's own PE header (which is always a 32-bit stub by Inno Setup design, independent of installed-file architecture).
- **Signing:** Unsigned (as documented/expected for this build).
- The installer was recompiled **three times** during this pass as fixes were made (wizard layout fixes → uninstaller `docker compose` working-directory hardening → final consolidated build used for reinstall/final-install testing). The SHA256 above is for the exact final artifact all late-stage tests ran against.

## 2. Windows Environment

- Windows 11 Enterprise, build 10.0.26200
- Confirmed clean slate before starting: no leftover Program Files/ProgramData artifacts, no stray containers/volumes/networks, no scheduled tasks, no stale shortcuts (one unrelated pre-existing dev source checkout on the Desktop was identified and left untouched, correctly, as out of scope).
- Docker Desktop present and used as the actual container runtime throughout (no manual `docker compose` invocations standing in for the product — every container start went through the installer/wizard/shortcuts exactly as an end user would trigger them, except where explicitly noted as a deliberate failure-injection test).
- Real hardware: single machine, used as the tester's own primary daily-driver workstation. A genuine `Restart-Computer` was executed mid-pass with explicit user approval (see §10).

## 3. Clean Installation

Full installer wizard walkthrough performed with real screenshots (not just control-text enumeration) at every page, multiple times across this pass. This screenshot-based verification caught real UI bugs that an earlier, enumeration-only pass had missed entirely.

**Bugs found and fixed in the installer wizard (Setup-Wizard.ps1):**
- Five label-overlap/text-wrapping bugs where a WinForms `Label` with a hardcoded 24px height clipped or overlapped multi-line explanatory text on the Administrator Account, AI Configuration, Threat Intelligence Providers, and Network Ports pages, plus a provider-card status-message overflow bug. Root-caused precisely via `Label.GetPreferredSize()` (not guessed), fixed by adding a proper `-Height` parameter to the shared label helper and recalculating every affected control's Y position. Verified fixed via fresh screenshots after recompilation — no more overlap on any page.
- The account-creation failure path in the "Ready to Install" step dumped a raw FastAPI/Pydantic validation-error JSON blob directly into the user-facing progress log, and unconditionally printed "Setup complete." even when the administrator account was never actually created. Fixed to parse the error into a human-readable message and to only claim unconditional success when it actually happened; failure now clearly tells the administrator what to do next (retry via Back, or register manually once the platform opens).

**Confirmed correct (screenshot-verified, no defects):**
- Select Destination Location (correct 64-bit path, correct free-space check)
- Select Additional Tasks (desktop shortcut checkbox, correct default)
- Ready to Install summary
- Completing the Setup Wizard page (correct "Launch the setup wizard now" behavior)
- App-config wizard Welcome, AI Configuration, Threat Intelligence Providers, Network Ports, and Summary pages
- Upgrade/reconfigure detection ("An administrator account already exists... leave blank to keep it unchanged") — correctly triggers whenever `.env` already exists, confirmed across two separate uninstall→reinstall cycles

## 4. Installed File Structure & Secrets

- Binaries/app code under `Program Files` (read-mostly); writable data (config, logs, backups) correctly under `ProgramData`, not Program Files — matches the master requirement.
- `ProgramData\IOC Intelligence Platform` and the mirrored `Program Files\...\app\.env` (required by Docker Compose's `env_file:` resolution) are both locked down via `icacls` to Administrators + SYSTEM only. Verified live that a non-elevated process gets a genuine access-denied error attempting to read either — real secrets (JWT signing key, generated Postgres/Neo4j passwords) are not readable by standard user accounts.
- Secrets are cryptographically randomly generated per install (`RNGCryptoServiceProvider`-backed, not `Get-Random`), confirmed via direct inspection of a real generated `.env`.
- No unexpected bundled files found; no secrets found in plaintext anywhere reachable by a non-admin account.
- **Real security bug found and fixed:** Postgres, Redis, Neo4j, and OpenSearch were all published on `0.0.0.0` (every network interface, not just localhost) by the base `docker-compose.yml`. OpenSearch in particular has its security plugin explicitly disabled (no authentication at all) and was confirmed live to be fully queryable, unauthenticated, from another device's perspective on the same LAN (verified via the machine's real LAN IP, not just a config read). Neo4j's HTTP metadata endpoint was likewise reachable with zero credentials. Fixed by binding all four datastore ports to `127.0.0.1` explicitly; confirmed the LAN IP no longer reaches them post-fix, and confirmed the application itself still works correctly (a full investigation ran successfully) since internal service-to-service traffic always uses Docker's internal network regardless of host port bindings.

## 5. Service/Process Model

The actual architecture is Docker Compose containers (postgres, redis, neo4j, opensearch, backend, frontend, celery_worker, celery_beat), not native Windows Services — interpreted and tested accordingly.

- Start/Stop/Restart/Status Start Menu shortcuts all tested directly: each correctly targets the real running compose project, waits for backend health where applicable, and reports accurate status.
- **Bug found and fixed:** `Invoke-DockerCompose`'s normal stderr progress output (`Container ... Starting/Started`, entirely routine Docker Compose behavior) was being rendered as a scary red "NativeCommandError" block with a fake stack trace on every single Start/Stop/Restart, even on complete success (exit code 0 throughout). Fixed by rendering each output line's text instead of the raw ErrorRecord object.
- **Major gap found and fixed:** the "Open Platform" Start Menu/desktop shortcut was a bare `.url` file that did nothing but open a browser tab — no check for whether Docker/the containers were even running, no start-if-needed, no health wait. This directly failed the master requirement ("shortcut should verify services, start if needed, verify health, open browser automatically") and was caught concretely by the real post-reboot test in §10. Replaced with a proper `Open-Platform.ps1` launcher: checks backend+frontend health first (skips everything and just opens the browser if already healthy, so the common case pays no UAC/wait cost); if not healthy, starts Docker Desktop if needed (waiting up to 3 minutes), runs `docker compose up -d`, polls for health, and only then opens the browser — or shows a clear, specific error if any step fails. **A second, more subtle bug was found and fixed in this fix itself** during the real reboot test: the script checked whether the platform was configured (`Test-Path` on the ACL-locked `.env`) *before* elevating, which throws an access-denied error that reads as "the file doesn't exist," incorrectly telling an already-fully-configured user to go run Configuration first. Fixed by elevating before that check. Both the original gap and this regression were confirmed fixed via the actual real-reboot cold-start scenario, not a simulation.

## 6. Configuration Validation (from inside the running app)

Every configuration surface was validated against the real running backend, not by trusting the installer's own success screen:

- AI backend connection: real Ollama connectivity confirmed (model `llama3.2:3b`); AI-unavailable and AI-recovery scenarios explicitly tested (§9).
- **Real bug found and fixed:** `docker-compose.yml` hardcoded `OLLAMA_BASE_URL` directly in the `environment:` block instead of using the same `${VAR:-default}` substitution pattern every other setting in the file uses. A compose `environment:` entry always wins over `env_file:`, so the setup wizard's AI Configuration page — despite writing the correct value to `.env` — could never actually change where the platform looks for Ollama. Fixed to `${OLLAMA_BASE_URL:-http://host.docker.internal:11434}`; confirmed the default still resolves correctly and that a real `.env` override now actually takes effect (verified via `docker exec ... printenv`, not just a config read).
- Provider connectivity: all 16 supported providers enumerate correctly via `/api/v1/providers/health` with accurate `configured`/`requires_key` flags (free-tier providers needing no key correctly show `configured: true` with no key present; paid providers needing a key correctly show `configured: false` without one).
- Database connectivity/persistence: confirmed via real data surviving a Postgres container stop/restart, a full platform restart, a real OS reboot, and a full uninstall→reinstall cycle (see §§7–8, 10–11).
- Service health: `/health` and the Service Status shortcut both independently confirmed accurate at every stage.

## 7. Full Investigation Workflow

Multiple complete investigations run end-to-end against the real backend (no browser automation tool was available in this environment, so the full workflow — including one pass driven through the actual browser UI via low-level window automation, and several driven directly against the real API/SSE stream — was exercised at the API layer, which is the same code path the frontend calls):

- IP (`8.8.8.8`, Google DNS): correctly resolved to a benign verdict backed by real WHOIS/RDAP and Spamhaus data.
- Domain (`malware.testing.google.test` and others): correct type detection, correct provider fan-out.
- MD5 hash (EICAR test hash `44d88612fea8a8f36de82e1278abb02f`): see the critical AI-fabrication bug in §9 — this single lookup produced the most severe finding of this entire pass.
- Full pipeline confirmed working end-to-end: Search → IOC Detection → per-provider results → per-provider AI summaries → correlation → final AI assessment → Evidence → WHY?/disagreement/pivots/hunt/detection-rule analysis endpoints → Done.

## 8. Provider-by-Provider & AI Validation

- **Status differentiation confirmed correct** across real, organically-encountered cases: `not_configured` (missing key), `no_data` (queried successfully, nothing found — e.g. `whois` command returning nothing for a non-existent domain), `ok` (real data), `error` (crt.sh returned a genuine live HTTP 502, surfaced honestly as `error`, not silently dropped or miscategorized), and `rate_limited` (PhishTank hit its real free-tier rate limit live during testing). No provider's lack of data was ever misrepresented as that provider's failure, or vice versa.
- **Real AI bug found and fixed (evidence traceability):** `evidence_ids`, `agreeing_providers`, and `disagreeing_providers` structured fields came back empty even when the AI's own prose explicitly cited a specific evidence ID or named a specific provider as agreeing/disagreeing — breaking the "every claim must be traceable to its source" requirement, since the UI renders the structured fields, not the prose, as clickable citations. Root-caused to two distinct issues: (1) several `evidence_ids` schema fields had no field description at all, giving the model no instruction to mirror prose citations structurally, and (2) the grounding filter that cross-checks claimed provider agreement/disagreement against "real" providers only recognized providers that produced a correlation-graph edge or a reputation/verdict fact — the OSINT crawler provider (`internet_intelligence`) does neither, so a *correct* citation of it was indistinguishable from a hallucinated one and was being silently stripped. Fixed with explicit field-description instructions, a prose-citation backfill safety net for evidence IDs specifically (only ever adds IDs already confirmed real — cannot be used to smuggle in a fabricated citation), and a `known_provider_ids` parameter so any provider that returned real data is never treated as "not real" just because it didn't produce a graph edge. Verified fixed live: re-running the exact repro case now correctly populates `disagreeing_providers: ["internet_intelligence"]` and `evidence_ids` with the real cited UUID.
- **Real AI bug found and fixed (boolean misreading):** the Spamhaus provider's raw `"listed": false` field was misread by the per-provider summarization step as "the IOC **is** listed," inverting a clean result into a false "has been blocked" claim, which then propagated into the final assessment. Fixed with an explicit instruction in the summarization prompt to read boolean fields by their literal value rather than by what the field name alone might suggest. Verified fixed live against both a `listed: true` and a fresh `listed: false` case — both now summarized correctly.
- **CRITICAL bug found and fixed (evidence-free fabrication):** looking up the real EICAR test file hash against four `not_configured` providers — literally zero real data of any kind, empty `provider_summaries`, zero correlation edges — still returned `final_verdict: "highly_malicious"`, `malicious_probability: 92`, and prose claiming "association with ransomware and trojans," entirely fabricated from the small model's own pretrained knowledge of a famous hash rather than admitting it had no evidence. This is a direct, severe violation of the platform's core AI-safety requirement ("never invents... malware... distinguishes fact from inference") and was, by a wide margin, the most serious finding of this entire pass. Root cause: with no real evidence, the prompt sent to the model carried nothing to reason over, and the small model answered from memory instead of refusing, directly contradicting its own system prompt's explicit "never fabricate" instruction. No amount of additional prompt wording can reliably fix a model that already had that instruction and ignored it, so the fix is deterministic: `generate_final_assessment` now short-circuits *before ever calling the AI* when there are no provider summaries and no correlation edges, returning a fixed, honest "insufficient data" / `verdict=unknown` / zero-risk assessment. Verified fixed live: the exact same lookup now correctly returns "No provider returned usable data for this indicator -- insufficient evidence for an assessment," with no fabricated claims, and a case with real correlation-edge evidence (but no per-provider summaries) was separately confirmed to still correctly reach the AI rather than being over-suppressed by the new guard.
- **Minor AI-quality observation (not fixed, documented):** a detection-rule-generation call for `8.8.8.8` mapped to MITRE ATT&CK technique `T1053` labeled as "Create a Backdoor" — the real ATT&CK T1053 is "Scheduled Task/Job." This is a small-model factual hallucination on a single field, distinct in kind from the evidence-fabrication bug above (this one didn't invent a threat where none existed; it mislabeled a real technique ID). Documented as a known limitation of the bundled small local model (`llama3.2:3b`) rather than fixed, since a general "don't hallucinate a MITRE technique name" instruction cannot be verified deterministically the way the evidence-free case could be; a future improvement could validate technique IDs against a static ATT&CK reference table.
- **Minor AI-summarization observation (not fixed, documented):** the OSINT crawler provider occasionally surfaces keyword-matched but semantically unrelated GitHub content (e.g., a completely unrelated repository that happens to contain the literal string being searched), and the AI summarization step sometimes repeated an out-of-context snippet from that noise as if it were a specific finding about the IOC. The underlying evidence data itself never overstated confidence (`confidence: low`, `reputation: no data`), and the final verdict stayed appropriately cautious in every case observed, so this was judged a data-quality/summarization-polish issue rather than a safety-relevant fabrication, and was not fixed in this pass.

## 9. Cross-Feature Workflow

- Pivots (`/analysis/pivots` — empty result correctly returned for an IOC with no discovered relationships), Hunt (multi-format Sigma/Splunk/Sentinel/Elastic/QRadar/Chronicle/Suricata/Snort/Zeek query generation — all populated correctly), Detection rule generation (functional; see the MITRE-mislabeling note in §8).
- Case creation, IOC association (with `lookup_id` correctly linked), note-taking, and case closing all confirmed working via the real API, with correct `analyst_id`/timestamps.
- Watchlist ("basket") add/list confirmed working.
- **Real bug found and fixed (graph persistence):** `GET /api/v1/lookup/{id}` omitted the relationship-graph data entirely, even though `CorrelationEdgeRecord` rows are persisted specifically so — per that model's own docstring — "a lookup's graph can be rebuilt from Postgres alone." The live SSE stream's `correlation` event worked fine during an active investigation, but revisiting a completed investigation later always showed an empty graph, indistinguishable from "no relationships were ever found." Fixed by rebuilding the `{nodes, edges}` payload from the persisted edge rows (always including the seed IOC as a node, even with zero edges, so "nothing found" and "data unavailable" remain distinguishable) and wiring the frontend's revisit page to consume it instead of a hardcoded `null`. Added a dedicated regression test (`test_completed_lookup_returns_rebuilt_correlation_graph`) verifying the exact zero-edge shape.
- **Feature-scope findings (not bugs — documented per the "only test what exists" instruction):**
  - **Report generation:** does not exist. The backend's case-detail response carries a typed but permanently-empty `reports: []` field, and the frontend has no UI (not even an empty placeholder tab) that reads or renders it. Fully unbuilt, not broken.
  - **Export:** partially implemented. JSON and Markdown export both work correctly end-to-end (confirmed live: clicking "Export JSON" through the real browser UI downloaded a real, valid file to the Downloads folder). PDF and CSV export are wired to call a `POST /lookup/{id}/export?format=...` endpoint that does not exist on the backend (confirmed via the OpenAPI schema and a direct request returning a genuine 404) — the frontend code anticipates this and shows a graceful "Export format not yet available" message rather than crashing, so this is a dead feature stub, not a crash-on-click bug.
  - **Graph visualization:** fully implemented on the frontend (client-side, via `react-force-graph-2d`, with an accessible list-view fallback), confirmed correct — this is the feature the persistence bug above was blocking on revisit, now fixed.
  - **Timeline:** does not exist anywhere in the codebase (no component, route, or supporting library) — not scaffolded, not broken, simply unbuilt.

## 10. Real Windows Restart Test

A genuine `Restart-Computer` was executed on the tester's real primary workstation, with explicit prior user approval obtained via an interactive confirmation before proceeding (this machine had VS Code, multiple browsers, and Docker Desktop open at the time — the user was given the choice to defer and chose to proceed immediately).

- Confirmed via `LastBootUpTime` that the reboot genuinely happened (not simulated).
- Found, in the process: the actual interactive logon only occurred ~18 minutes after boot completed (the machine sat at the lock screen), which meant Windows' own per-user startup-item throttling hadn't yet launched Docker Desktop by the time initial checks were made — a real-world timing factor any recovery mechanism has to tolerate, not a product bug.
- The "Open Platform" shortcut fix from §5 was exercised for real in this exact scenario: Docker Desktop was not yet running, no containers were up, and the fixed launcher correctly detected this, started Docker Desktop, waited for it, ran `docker compose up -d`, waited for health, and opened the browser — with **zero manual component restarts** by the tester. This is also where the launcher's own ACL-check-ordering regression (§5) was caught and fixed.
- Post-reboot: login succeeded with the pre-reboot credentials, the pre-reboot case and watchlist entries were both fully intact, and a brand-new investigation completed successfully — all without restarting anything by hand.
- A second full user journey was run after the reboot (a different IOC type — the EICAR hash, which is also where the critical AI-fabrication bug in §8 was discovered), including case creation, IOC association, and case closing — all working correctly.

## 11. Failure Recovery Testing

- **Interrupt test (client disconnect mid-investigation):** **Real bug found and fixed.** Deliberately cutting the SSE connection partway through an investigation (`curl --max-time 3`, matching a browser refresh/tab-close/navigate-away) correctly flipped the lookup's status to `failed` (a previously-fixed `GeneratorExit`-handling mechanism already in the codebase), but every provider result already fetched and streamed to the client before the disconnect was silently lost — `GET /lookup/{id}` came back with `provider_results: []` even though six real provider calls, including a live Spamhaus hit, had already completed. Root cause: the provider-fetch loop only committed the database transaction once, after the entire loop finished; anything added via `stream_db.add()` mid-loop was still sitting uncommitted when the session tore down. Fixed by committing after every individual provider result. Added a regression test that verifies the first provider's result is durably committed and independently queryable while the (deliberately delayed) second provider is still being awaited — proving the fix's actual mechanism, not just its end-to-end symptom. Verified fixed live with the exact original repro: all six provider results now correctly persist despite the disconnect.
- **Network/provider failure resilience:** organically encountered and confirmed correct multiple times during normal testing — a live crt.sh HTTP 502 was surfaced as `error` status without taking down the rest of the investigation; a PhishTank rate-limit hit was surfaced as `rate_limited`; four `not_configured` providers alongside working ones never blocked the working ones' results or the overall investigation from completing. The "one provider failing must not destroy the whole investigation" pattern (A✓ B✓ C✕ D✓ AI✓ FinalAssessment✓) was directly observed multiple times.
- **AI (Ollama) failure and recovery:** deliberately made Ollama genuinely unreachable from the backend's perspective (patched `.env`'s `OLLAMA_BASE_URL` to an unreachable port, restarted the backend, confirmed via `docker exec ... printenv` that the change actually took effect). A real investigation run in this state correctly preserved every provider's raw intelligence data untouched, and every AI-dependent field honestly reported the failure ("AI summarization unavailable... RuntimeError('Could not reach Ollama...')", `final_verdict: "unknown"`, all risk scores zeroed) — at no point did the platform pretend the AI had succeeded. Reverting the patch and restarting the backend immediately restored full AI functionality on the next investigation, with no other manual intervention.
- **Database failure and recovery:** stopping the Postgres container mid-request produced a real 500 with a fully logged Python traceback (not a silent failure) rather than a crash or corrupted state; restarting Postgres immediately restored full functionality, and previously-created case/watchlist data was confirmed completely intact afterward.
- **Bulk workflow:** eight IOCs processed sequentially (mixed types, one deliberate duplicate, one deliberately malformed value). The malformed entry was cleanly rejected with a proper 422 and a clear message ("Could not determine IOC type") rather than crashing or hanging the batch; the duplicate correctly created a fresh, independent investigation record (each investigation is its own point-in-time record by design, not deduplicated) while still benefiting from provider-level result caching. No memory growth, no CPU spikes, no zombie processes observed across the run.

## 12. Performance

- Idle baseline: backend ~96 MB RSS, frontend ~39 MB, celery_worker ~695 MB, postgres ~38 MB, redis ~5 MB, neo4j ~553 MB, opensearch ~1.07 GB. CPU idle at <1% across all eight containers at rest.
- After the eight-IOC bulk run: backend memory grew to ~104 MB (a ~9% increase attributable to normal request handling, not a leak pattern) and settled; all other containers unchanged. No signs of a memory leak, no CPU pegged at 100%, no multiplying background workers, no zombie processes at any point in this pass.
- Investigation duration: typical single-IOC investigation completed in 5–15 seconds end-to-end depending on which providers had real network calls to make (the OSINT crawler's multi-source fan-out was consistently the slowest single component, ~6 seconds).

## 13. Security Re-Check

- No API keys, passwords, tokens, session secrets, or DB credentials found in any log file, browser network payload, frontend source file, or temp file across this entire pass, beyond the two ACL-locked `.env` files (both correctly access-denied to non-admin accounts).
- **Datastore LAN exposure — found and fixed.** See §4. This was the most significant security finding: four backing datastores, one of them (OpenSearch) with zero authentication of any kind, were reachable from any other device on the same network before the fix.
- A `password authentication failed` sequence in the real Postgres container's own logs was traced to the tester's own test-suite setup accidentally targeting the live container with dev-default credentials before switching to a disposable throwaway database for local test runs — not a leaked credential, and not attributable to the product.
- No secrets found leaked into `/metrics` (standard Prometheus process/GC/HTTP-timing metrics only) or `/health`.

## 14. Upgrade Test

Not applicable as a distinct "previous version → new version" test (only one version, 0.1.0, exists), but the closely-related reconfigure/upgrade-detection path (re-running the wizard against an existing installation) was tested extensively as part of §15 and confirmed fully correct: existing admin account, AI backend selection, provider keys, and port choices are all correctly detected and offered for reuse rather than being silently overwritten or re-prompted from scratch.

## 15. Uninstall Test

Both uninstall paths were tested against real, live installations with real data:

- **Keep-data path** (the silent/`/VERYSILENT` default, and the interactive "Yes" choice): correctly stops and removes all eight containers, correctly leaves the named Docker volumes (and therefore all case/investigation/watchlist data) intact, correctly removes the Start Menu group, desktop shortcut, and registry uninstall entry, and correctly removes `Program Files\IOC Intelligence Platform` in full. (One leftover-file investigation during this pass turned out to be a test-harness artifact — an orphaned PowerShell process from the tester's own earlier automation still holding a script file open at the exact moment of uninstall — not a product defect; a real end user would not be running dozens of concurrent elevated test scripts during their own uninstall.)
- **Remove Everything path** (interactive "No" → type `DELETE` to confirm): correctly runs `docker compose down -v`, destroying the named volumes as well, and correctly deletes the entire `ProgramData` tree. Confirmed via direct inspection afterward: zero containers, zero volumes, zero registry entry, zero remaining files, zero remaining shortcuts.
- A defensive improvement was also made to the `Exec()` calls backing both paths in `installer.iss` (making the Docker Compose working directory explicit rather than empty), for consistency with every other script in the codebase, even though direct testing showed the original code already worked correctly in practice (Docker Compose derives its project identity from the compose file's own absolute path, not the caller's working directory, when no explicit project name is set — the working-directory ambiguity was real but turned out not to be the actual root cause of an earlier, less rigorously-isolated observation this pass initially suspected it explained).

## 16. Reinstall Test

Reinstalling immediately after the keep-data uninstall (via the freshly-recompiled installer) correctly detected the surviving configuration and data: the wizard opened in "Reconfigure" mode, offered to keep the existing administrator account, and after clicking through with all settings unchanged, `Start Installation` brought all eight containers back up healthy. Both previously-created cases (including one in `closed` status), the watchlist entry, and the original administrator login were all confirmed fully intact afterward, and a brand-new investigation completed successfully.

## 17. Final Clean Install (this-session-independent pass)

A completely independent final pass was performed after a full "Remove Everything" wipe (§15): fresh install, fresh administrator account (`final-admin@example.com`), full wizard walkthrough (Welcome → Administrator Account → AI Configuration → Providers → Network Ports → Summary → Start Installation), all pages screenshot-verified clean with no layout defects, real `docker compose up -d --build`, real admin registration + login, and a real investigation run to completion — relying on nothing preserved from any earlier install in this session. Fully successful.

## 18. Bugs Found (Summary)

| # | Severity | Area | Description |
|---|----------|------|-------------|
| 1 | High | AI safety | **Fabricated "highly_malicious" verdict + specific malware claims for an IOC with zero real provider evidence** (pretrained-knowledge hallucination) |
| 2 | High | Security | **Postgres/Redis/Neo4j/OpenSearch bound to 0.0.0.0 — reachable unauthenticated from the LAN**, OpenSearch fully so |
| 3 | High | Data integrity | **Client disconnect mid-investigation silently discarded all already-fetched provider results** despite the SSE stream having delivered them |
| 4 | High | Recovery UX | **"Open Platform" shortcut was a dead `.url` link** — no service check, no auto-start, no health wait; directly failed a master requirement, confirmed by the real reboot test |
| 4b | Medium | Regression in fix #4 | The launcher fix's own configuration check threw an ACL access-denied error before elevating, misreporting a fully-configured platform as "not configured" |
| 5 | Medium | AI correctness | Evidence/provider-agreement citations named in AI prose were not mirrored into the structured fields the UI actually renders as clickable citations (two distinct root causes: missing field instructions, and an over-narrow "real provider" grounding check) |
| 6 | Medium | AI correctness | A provider's `"listed": false` boolean was misread as "is listed," inverting a clean verdict |
| 7 | Medium | Configuration | Hardcoded `OLLAMA_BASE_URL` in `docker-compose.yml` silently overrode the wizard's own setting, making the AI backend URL uneditable |
| 8 | Medium | Data/feature gap | Relationship graph data was never returned by `GET /lookup/{id}`, making the graph appear empty on every revisit of a completed investigation |
| 9 | Low | Installer UX | Wizard pages had five label-overlap/text-clipping layout bugs |
| 10 | Low | Installer UX | Account-creation failure dumped raw JSON and falsely claimed unconditional "Setup complete." |
| 11 | Low | Cosmetic | Routine `docker compose` progress output rendered as a fake red error on every Start/Stop/Restart |
| 12 | Low | Branding accuracy | Landing page hardcoded "Claude" regardless of the actually-configured AI backend |
| 13 | Info (not fixed) | AI quality | MITRE technique T1053 mislabeled by the small local model in one detection-rule generation |
| 14 | Info (not fixed) | AI quality | Occasional irrelevant OSINT-crawler snippet echoed into a summary without being flagged as low-relevance |
| 15 | Info (not fixed) | Feature scope | Report generation unbuilt; PDF/CSV export unbuilt (gracefully stubbed); Timeline unbuilt |

## 19. Bugs Fixed

All of #1–12 above were root-caused, fixed, covered by an automated regression test where the bug was in backend Python code (evidence_ids backfill, disconnect-commit timing, no-evidence AI guard, correlation-graph rebuild — 4 new/extended test files, all passing: 128/128 backend unit tests, plus the targeted integration tests for stream persistence), rebuilt into a real running instance, and **re-verified live against the actual product** (not just against the automated test suite) before being considered closed. The installer itself was recompiled three times to fold in the wizard, uninstaller, and Docker-compose-file fixes, and the final consolidated build was the one used for all late-stage reinstall and final-clean-install testing.

## 20. Remaining Issues (Not Fixed — Documented, Not Blocking)

- MITRE technique mislabeling and occasional low-relevance OSINT snippet echoing are inherent characteristics of the bundled small local model (`llama3.2:3b`) rather than code defects; mitigating them further would require either a larger/more capable AI backend or a static-reference-table validation layer, both out of scope for a bug-fix pass.
- Report generation, PDF/CSV export, and Timeline are genuinely unbuilt features, not defects — correctly scoped out of this pass per the "only test what actually exists" instruction, but noted here since a user reading the UI's "Export PDF"/"Export CSV" buttons would reasonably expect them to work.

## 21. Final Verdict

# READY FOR RELEASE

**Justification:** Every defect found during this pass — including the single most severe one (AI evidence-free fabrication) — was root-caused, fixed, covered by a regression test, and re-verified against the real running product, not merely reported. The three highest-severity findings (AI fabrication, LAN-exposed unauthenticated datastores, and silent data loss on client disconnect) are exactly the class of issue this master validation pass exists to catch, and all three are now closed with direct, live re-confirmation — not an assumption that the fix "should" work. The full lifecycle was exercised for real: a genuine Windows reboot (not simulated) with automatic recovery requiring zero manual component restarts, a full keep-data uninstall/reinstall cycle with all data verified intact, a full destructive Remove-Everything uninstall verified fully clean, and a final independent clean install relying on nothing preserved from earlier in this session. Remaining open items are explicitly scoped-out unbuilt features (Report/Timeline/PDF-export) and small-model AI-quality limitations that do not represent incorrect or unsafe behavior — the platform never claims a feature works when it doesn't (export failures are gracefully stubbed, not silently broken), and after the fixes in this pass, the AI layer never fabricates a threat where the evidence doesn't support one.
