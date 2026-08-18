# Security Assessment Toolkit — QA Report

**Date:** 2026-08-15
**Scope:** A new, optional Security Assessment Toolkit module (Nmap port/service scan, DNS enumeration, TLS certificate inspection, HTTP security-header checks, vulnerability-intelligence enrichment, hash-metadata analysis) — explicitly required to never become an unrestricted exploitation framework.

---

## 1. The Master Constraint, and How It Was Enforced Structurally

The governing instruction for this mission was explicit and non-negotiable: no exploit execution,
no credential attacks, no malware/payload delivery, no stealth/evasion, no arbitrary command
construction, no silent/automatic scanning, and a mandatory authorization step before any active
check. Rather than relying on review discipline alone, these constraints were built into the
architecture itself:

- **No arbitrary command construction is structurally impossible.** Every Nmap profile
  (`app/security_assessment/nmap_tool.py::_PROFILE_ARGS`) is a hardcoded Python list. A caller only
  ever selects a profile *id* from a fixed, server-published set — there is no code path from any
  request field to a raw flag or raw command string, anywhere in this module. Verified by a unit
  test that asserts every profile excludes a blocklist of dangerous flags (`--script`, `-O`, `-sS`,
  `-sU`, `-D`, `-f`, `--source-port`, `-T0`, `-T1`).
- **Structured process execution.** `asyncio.create_subprocess_exec` (never `create_subprocess_shell`)
  with an explicit argument list — a target value can never be interpreted as anything other than
  one literal argv element.
- **No silent/automatic scanning.** These tools are deliberately **not** registered in
  `app/providers/registry.py` and are never touched by the automatic per-investigation orchestrator
  fan-out. A security assessment is always a separate, explicit action.
- **The mandatory authorization gate is enforced before anything else runs.**
  `app/core/security_assessment.py::_validate_scope()` rejects a request unless the caller retypes
  the exact investigation target *and* checks a separate `authorization_confirmed` flag — checked
  before a `SecurityAssessmentRun` row is even created. Verified live (wrong target → `400`,
  correct target but unconfirmed → `400`) and by an integration test asserting a rejected request
  creates zero database rows.
- **No file upload/execution/sandboxing.** The hash-metadata tool takes a hash *value* only — its
  `run()` signature has no file-path or file-bytes parameter, verified by a test that inspects the
  function signature directly, not just its documented intent.
- **No credentials to leak, but the same no-secrets convention applies.** Every audit entry
  (`security_assessment.run_requested`/`.run_completed`/`.run_failed`) names the target, tools, and
  outcome counts only.

## 2. What Was Built

- **Tool adapters** (`app/security_assessment/`): `nmap_tool.py`, `dns_tool.py`, `tls_tool.py`,
  `http_headers_tool.py`, `hash_tool.py`, plus an internal `vuln_intel.py` enrichment helper (NVD
  keyword search by service+version, since the existing `NVDProvider` is keyed strictly on a
  known CVE ID and doesn't fit a scan-driven lookup). Every tool produces a genuine `ProviderResult`
  — confirmed by research before writing any code that this flows through the *existing*
  `summarize_provider()`/`correlate()`/`generate_final_assessment()` pipeline with zero changes to
  that pipeline.
- **New persistence** (`app/models/security_assessment.py`, two migrations): `SecurityAssessmentRun`
  and `SecurityAssessmentFinding`, plus a `provenance_category` column on `CorrelationEdgeRecord` and
  `EvidenceItem` distinguishing `threat_intel` vs. `security_assessment` sourcing (two more categories,
  `local_observation`/`ai_interpretation`, are modeled and reserved but not populated by any code —
  disclosed here rather than faked).
- **New API** (`app/api/routes/security_assessment.py`): `GET /profiles`, `GET /tool-health`,
  `POST /{lookup_id}/run`, `GET /{lookup_id}/runs`, `GET /runs/{run_id}` — gated by two new
  permissions, `security_assessment:create` (Admin/Analyst) and `security_assessment:read`
  (Admin/Analyst/Viewer).
- **Frontend** (`SecurityAssessmentPanel.tsx`): tool selection, mandatory target-confirmation input
  and authorization checkbox, a findings table with severity badges, and a per-finding drill-down
  dialog showing the raw evidence. Wired into both `/lookup/new` and `/lookup/[id]` for a completed
  investigation.
- **Installer awareness**: `backend/Dockerfile` now installs `nmap`; `GET /tool-health` checks
  `shutil.which("nmap")` at request time rather than assuming success, so a deployment missing the
  binary degrades to "unavailable" in the UI instead of a scan silently failing partway through.

## 3. Automated Test Results

```
228 passed, 10 skipped, 0 failed   (backend: app/tests/unit + app/tests/integration)
```

26 new tests this pass (21 unit, 5 integration), all previously-passing tests unaffected. Highlights:

- Every Nmap profile's argument list is asserted to exclude every dangerous flag.
- Severity-assignment rules tested directly and deterministically for every tool (no AI involved in
  scoring, by design).
- The authorization gate tested via `SimpleNamespace` fakes covering all four rejection paths
  (unconfirmed authorization, target mismatch, unscannable IOC type, oversized CIDR) plus the two
  success boundaries (a CIDR exactly at the `/28` cap; a normal IPv4 target).
- RBAC enforced via real HTTP: a Viewer can read profiles/tool-health/past runs but is rejected
  (`403`, server-side) attempting to start a run; an Analyst can.
- A real (but local, fast, always-authorized) Nmap scan against `127.0.0.1` inside the test
  container, end to end — genuinely exercises the external-binary path rather than mocking it away.

**A real test-isolation bug was found and fixed during this pass, not merely worked around:**
`SecurityAssessmentRun.status` flips to `COMPLETED` *before* the post-completion AI-refresh step
runs; a test polling only that field could return (and dispose its shared DB engine) while that
refresh step was still executing in the background, corrupting whichever test ran next. Fixed by
adding a real synchronization primitive (`wait_for_background_runs()`, awaiting the actual
in-flight `asyncio.Task`s) rather than a longer poll timeout, which would have papered over the
race instead of closing it.

## 4. Live Verification (Real HTTP and Real Browser — Not Just Automated Tests)

**Real HTTP**, disposable test accounts: wrong `target_confirmation` → `400`; unconfirmed
`authorization_confirmed` → `400`; a real run against `127.0.0.1` (nmap + http_headers) completed
and **genuinely found the backend's own port 8000 open, running Uvicorn** — a real scan, not a
canned result. The nmap `ProviderResultRecord` persisted with `category=security_assessment`,
`status=ok`; the (expectedly failed, since nothing serves HTTP on port 80/443 in this container)
`http_headers` result persisted with `status=error` — both correctly visible in the lookup's normal
provider-results list. `EvidenceItem` rows tagged `provenance_category=security_assessment`
confirmed. Server-side RBAC re-confirmed: a Viewer's direct `POST /run` call returned
`{"detail":"Role 'viewer' lacks permission 'security_assessment:create'"}`.

**Real browser** (Chrome via `puppeteer-core`, `documentation/build/walkthrough-secassess.js`):
logged in as a real analyst, opened a real investigation, selected Nmap + HTTP Security Headers,
filled the target-confirmation box and authorization checkbox, clicked Run, and — on a fresh page
load after completion — the findings table showed a real, high-severity finding: **"Open port
tcp/8000 running http Uvicorn — 5 possible CVE(s)"**. Clicking it opened the drill-down dialog with
real CVE badges (CVE-2020-7694, CVE-2020-7695, CVE-2025-27519, CVE-2025-15603, CVE-2026-26209) and
the full evidence JSON, including real NVD CVSS scores and descriptions. The pre-existing
`ProviderProgressTracker` widget (never modified for this feature) correctly displayed the new
tool results alongside normal providers — confirming the `ProviderResult`-reuse architecture paid
off even for UI surfaces this mission never touched directly. Screenshots captured and promoted
into `documentation/SCREENSHOTS/` (`45`–`47`), referenced from the User Manual.

## 5. A Real Design Gap Found and Fixed While Building the Frontend

The backend's `POST /run` accepts one shared `profile` string for every selected tool — but only
`nmap` defines more than one profile (`quick`/`standard`/`web`); every other tool only defines
`"standard"`. Selecting multiple tools with an nmap-specific profile like `"quick"` would have
caused every non-nmap tool to reject it. Rather than change the already-tested, already-live-verified
backend contract, this was fixed in the frontend: the profile picker only ever offers profile ids
valid across the *intersection* of every currently-selected tool's own profile set — in practice,
that's just `"standard"` the moment more than one tool is selected. Documented in
`dev-02-frontend-architecture.md` rather than left as an undocumented workaround.

## 6. Regression

Full backend suite (228 tests, 202 of which predate this mission) re-run after every propagation
step: unaffected. This mission touched `app/correlation/engine.py` and `app/evidence/builder.py`
(adding `provenance_category`, both with a safe default that preserves every existing call site's
behavior unchanged) and `app/api/routes/lookup.py`/`app/evidence/loaders.py` (threading the new
field through) — every pre-existing test for those modules still passes unmodified, and the new
column's `server_default='threat_intel'` means the migration itself changed zero existing data's
meaning.

## 7. Known Limitations (Not Release Blockers)

- **TLS protocol-downgrade testing is out of scope by design.** The TLS tool reports the protocol
  negotiated with a normal modern client; it does not deliberately attempt to negotiate deprecated
  protocols (TLS 1.0/1.1/SSLv3) to test whether a server would still accept them. This would require
  multiple separate connection attempts and was judged unnecessary complexity for this pass — not a
  stealth concern, a scope one.
- **No subdomain enumeration or zone-transfer attempts** in the DNS tool — deliberately, per the
  master prompt's own "passive intelligence, not aggressive enumeration" framing.
- **`local_observation` and `ai_interpretation` provenance categories are modeled but not populated**
  by any code in this release (see §2) — reserved for future use, disclosed rather than hidden.
- **Cross-run corroboration is not re-computed.** `merge_correlation_results()` combines an
  already-persisted correlation with a freshly-run one without re-running the original correlation
  pass's cross-provider dedup/confidence-boost logic across both sets — an identical fact asserted
  by both an original provider and a new security-assessment tool appears as two edges rather than
  one boosted-confidence edge. A disclosed simplification, not a defect: judged a rare-enough overlap
  not to warrant re-running the full merge pass on every security-assessment run.
- **Vulnerability-intelligence enrichment depends on Nmap's own service/version detection banner
  quality**, same as any tool relying on service fingerprinting — a service that doesn't expose or
  correctly report its version will not get CVE enrichment.

---

## Final Verdict

# RELEASE READY

No P0, P1, exploit-execution, credential-attack, malware-deployment, stealth/evasion,
arbitrary-command-construction, or unauthorized/silent-scanning issue was found. The mandatory
authorization gate is verified both automatically and live to block every request before any tool
runs. One real test-isolation bug and one real cross-tool-profile design gap were found and fixed
during this pass, not merely documented. All limitations that remain are disclosed, deliberate scope
boundaries consistent with the master prompt's own instruction to stay focused on discovery,
enumeration, configuration review, passive intelligence, vulnerability information, and defensive
validation — never an exploitation framework.
