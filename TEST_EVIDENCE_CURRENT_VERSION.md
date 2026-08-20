# HORIZON GRID v0.2.3 — Test Evidence

Every number below was actually executed or actually observed during this release's review, not estimated. Where a static count (files, `def test_` occurrences) differs from a live pytest run's count, the live run is authoritative — parametrized tests make one `def test_` expand into several actual test cases.

## Backend tests

| Run | Result | Notes |
|---|---|---|
| `python -m pytest app/tests/unit` (no infrastructure) | **335 passed** | Run inside the `hgmc` container after rebuilding it from source (a stale-image issue was caught and corrected mid-session — see Methodology note below) |
| `python -m pytest app/tests` (full suite, real Postgres/Redis) | **380 passed, 39 skipped** | The 39 skips are intentional: host-only tests that legitimately don't apply inside the container's own network namespace, and environment-gated tests documented as such in `backend-tests.yml`'s own comments |
| Static file/function count (cross-check only) | 29 unit test files (303 `def test_`) + 13 integration test files (86 `def test_`) = 389 by static grep | Differs from the live pytest count due to parametrization; not itself authoritative |

**New regression tests added this release** (none of these fixes had coverage before this review):
- `test_orchestrator_retry.py` (new file) + additions to `test_provider_base.py` — the dead-retry-code fix
- `test_auth_login_rate_limit.py` (new file) — the login rate limiter
- `test_ai_service_ollama_ssrf.py` (new file) + an addition to `test_runtime_config_persistence.py` — the SSRF guard on both the AI-call path and the config-save path
- An updated assertion in `test_api_health.py` for the new `/docs`/`/health/detailed` behavior

## Frontend tests

**None exist.** `vitest` is wired into `frontend/package.json`'s `test` script and installed as a dependency, but a repository-wide search (confirmed independently by two separate audit passes during this release) found zero `*.test.ts(x)`/`*.spec.ts(x)` files and no `vitest.config.*` anywhere under `frontend/`. `frontend-build.yml`'s own comment explicitly documents this: running `npm test` today finds no test files. This is a genuine, disclosed gap, not a claim of coverage that doesn't exist.

## Integration/live verification (not automated tests — real, manual reproduction)

- **RelationshipGraph list-view crash**: reproduced live in a real browser (Puppeteer + real Chrome) against the actual running app before the fix (captured the exact React error and a screenshot of the resulting "Application error" page), then re-verified after the fix with a repeated graph→list→graph→list toggle sequence — no crash, correct data every time.
- **Restore procedure**: a real backup was taken, a marker database row was inserted, the restore procedure was run, and the marker row was confirmed gone with the platform healthy afterward — on both the throwaway `hgmc` stack and, for the restore *script* specifically, the WSL Ubuntu test environment.
- **Linux package upgrade**: `horizon-grid_0.2.3_amd64.deb` was installed as a real upgrade over a live existing v0.2.1 instance. The full reconfigure wizard ran end to end: prerequisite gate passed, pre-upgrade backup ran, ports auto-remapped around the still-running old containers, new `.env` written, containers started, backend became healthy, and all three systemd units (main service, watchdog timer, backup timer) were confirmed `enabled`. `GET /health/detailed` on the resulting instance returned `healthy` with Postgres and Redis both confirmed reachable.
- **Windows installer**: compiled via Inno Setup; its build log was inspected directly to confirm every new script (`Watchdog.ps1`, `Restore-Database.ps1`) was actually packaged. A live elevated end-to-end install was **not** performed — it requires an interactive UAC prompt this review's environment could not satisfy. Every individual component script (health-check port detection, boot-task registration logic, Test-Connection gating logic) was instead verified in isolation via direct invocation.
- **Docker restart-policy behavior**: personally verified that `restart: unless-stopped` recovers a container after a real OOM-kill (`docker run --memory=20m` + a memory-hog script), and does *not* recover a container after an operator-issued `docker kill`/`docker stop` — confirmed this is Docker's own deliberate "operator explicitly wants this down" semantics, not a defect.
- **Health-check port-detection fix**: verified with a dummy HTTP server on a deliberately non-default port, confirming the watchdog's health check actually hit the configured port rather than a hardcoded default.
- **`check-prerequisites.sh`'s JSON bug**: reproduced the empty-`checks`-array bug live, fixed it, and re-verified with both an all-pass real-machine run and a simulated hard-failure run.

## Soak test

A 3-hour soak test against the live `hgmc` stack — 171 cycles, first cycle `2026-08-20T02:06:45Z`, last cycle `2026-08-20T05:06:44Z` (essentially exactly 3 hours), exited cleanly on its own (`SOAK TEST COMPLETE: 171 cycles, 5 lookups, 32 errors`).

- **Memory**: flat with no growth trend across the full run (backend 114.6 MB → 106.8 MB — a slight decrease, not a leak; Postgres 37.98 MB → 41.67 MB, a small increase consistent with the backups/restores/lookups performed *during* the run, not unbounded growth; Redis 10.23 MB → 9.03 MB, flat).
- **Restarts**: 0 for every tracked container throughout the full run — no crash-triggered automatic restarts at any point.
- **The 32 logged "errors"**: a small number are transient health-check misses directly attributable to this session's own deliberate backend container rebuilds (each fix required rebuilding the container to verify it); the remaining majority are a soak-script limitation, not a platform defect — the script fetched one JWT access token at the start and never refreshed it, so lookup attempts after the token's normal 30-minute expiry correctly received 401, which the script's simplistic counter recorded as an "error" rather than distinguishing it from a genuine failure. Every health check outside a deliberate rebuild window returned 200/healthy.

## Security scan

Secret scanning was run across the full diff for every commit in this review (`git diff <base>..HEAD` against a pattern covering API keys, passwords, tokens, and credential-shaped strings, with test/mock/placeholder values excluded from matching) — no real secrets found. See `MISSION_CRITICAL_CERTIFICATION_REPORT.md` for the full methodology.

## Post-push finding: a real CI-environment gap, found and fixed

After this document's numbers were recorded, the actual GitHub Actions "Backend Tests" workflow run
triggered by this release's push (`e27bde5`) came back **failing** on its `unit` job — 2 of 337 tests
failed, even though every number above was genuinely executed and genuinely passing inside the local
dev container. Root cause: `test_ai_service_ollama_ssrf.py`'s `test_no_credentials_override_uses_the_settings_default_and_it_passes_validation`
and `test_missing_base_url_in_credentials_does_not_raise` (both added this release, covering the SSRF
guard) construct a real `OllamaClient` against the actually-configured default `base_url`
(`host.docker.internal`), which `assert_safe_outbound_url()` resolves via a genuine `socket.getaddrinfo()`
call. `host.docker.internal` only resolves inside a Docker Desktop container network — it resolves fine
in the local dev container and in CI's own `integration-docker` job (which runs inside real Docker), but
not on the `unit` job's bare GitHub Actions Ubuntu runner, which runs pytest directly on the host with no
Docker Desktop present at all. This was a genuine gap in this release's own test evidence: the local
"335 passed" / "380 passed, 39 skipped" numbers above were real, but they were never actually exercised
against a bare-runner CI environment before this document was first written.

Fixed in commit `40ee62b` by mocking only the DNS-resolution step to a fixed, non-link-local RFC 5737
address, so both tests exercise the real `assert_safe_outbound_url()`/`OllamaClient` construction path
deterministically regardless of environment, rather than skipping or weakening what they verify.
Re-verified after the fix: all 5 tests in the file pass, full unit suite still 335 passed, full suite
(real Postgres/Redis) still 380 passed/39 skipped — confirming the fix caused no regressions.

## Methodology note: a real mistake caught mid-review

Partway through this review, a full-suite run reported exactly 365 passed — matching the *previous* known-good count, which was itself a red flag. The test container had been built with a `docker-compose.prod.yml` override that strips dev bind-mounts, and was running a stale image that predated nearly all of this session's backend changes — the run had silently validated old code. This was caught by checking whether a brand-new test file actually existed inside the running container (it didn't), the image was rebuilt, and the full suite was re-run for real. Every test number cited in this document and in `MISSION_CRITICAL_CERTIFICATION_REPORT.md` is from after this correction.
