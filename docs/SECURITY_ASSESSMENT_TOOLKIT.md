# Security Assessment Toolkit

The Security Assessment Toolkit adds **active** checks against an investigation's own
target — Nmap port/service scanning, DNS record enumeration, TLS certificate
inspection, HTTP security-header checks, vulnerability-intelligence enrichment, and
hash-metadata analysis — as a distinct capability from every existing provider under
`backend/app/providers/`, which only ever queries a third party's already-collected
data *about* a target. This document is deliberately explicit about what this module
is and is **not**, since the two are easy to conflate.

Related docs: [PROVIDERS.md](PROVIDERS.md) (the passive-provider architecture this
module deliberately does not join), [SECURITY.md](SECURITY.md) (the two new
permissions and the RBAC model), [DATA_MODEL.md](DATA_MODEL.md) (the two new tables).

---

## 1. What this is NOT

Stated first, plainly, because it is the master requirement this whole module was
built against: **this is not an exploitation framework.** None of the following exist
anywhere in this codebase, by design:

- No exploit execution, no credential attacks, no password cracking.
- No malware deployment, no destructive payloads, no sandboxing/detonation of
  anything (the hash tool identifies a hash's algorithm/format only — it never
  touches, uploads, or executes a file).
- No stealth/evasion mechanisms — every Nmap profile below explicitly excludes
  timing-evasion, decoy, fragmentation, and source-port-spoofing flags.
- No arbitrary command construction — every tool profile is a **hardcoded** argument
  list defined in the tool's own source; a caller only ever selects a profile *id*
  from a fixed, server-defined set (`GET /api/v1/security-assessment/profiles`),
  never raw flags or a raw command string.
- No automatic/silent scanning — a security assessment is never triggered by a normal
  IOC investigation. It is always a separate, explicit action requiring the caller to
  retype the exact target and check an authorization box.
- No automated attacks against arbitrary internet targets — see §3's scope
  restrictions (single host, or a capped CIDR range, always the investigation's own
  already-detected seed IOC).

## 2. Architecture

Every tool (`backend/app/security_assessment/*_tool.py`) subclasses
`SecurityAssessmentTool` (`base.py`) and produces a genuine `ProviderResult` — the
exact same normalized envelope every passive provider under `app/providers/` uses.
This is deliberate: it means tool output flows through the platform's *existing*
`summarize_provider()` → `correlate()` → `generate_final_assessment()` pipeline
(`app/ai/service.py`, `app/correlation/engine.py`) with **zero changes** to that
pipeline, confirmed by direct research before any of this was written.

Tools are **not** registered in `app/providers/registry.py` and are **never** run by
the automatic per-investigation orchestrator fan-out
(`app/providers/orchestrator.py`). They exist in a separate registry
(`app/security_assessment/registry.py`) invoked only via
`app/core/security_assessment.py`'s service layer, itself only reachable through the
authorization-gated API (`app/api/routes/security_assessment.py`).

## 3. The Mandatory Authorization Gate

`POST /api/v1/security-assessment/{lookup_id}/run` requires, in the request body:

- `target_confirmation` — must exactly match the investigation's own seed
  `ioc_value`. A caller cannot scan anything other than what they're already
  investigating; there is no free-text target field anywhere in this API.
- `authorization_confirmed: true` — an explicit, separate boolean the caller must
  set. Both checks happen server-side, before any tool runs, before a
  `SecurityAssessmentRun` row is even created — a rejected request leaves nothing
  behind (see `app/core/security_assessment.py::_validate_scope`).

Additional scope restrictions enforced the same way:

- Only IOC types with a real network-addressable target are accepted (IPv4/IPv6/
  domain/hostname/URL/CIDR for network tools; MD5/SHA1/SHA256/SHA512 for the hash
  tool) — a CVE, malware-family, threat-actor, etc. seed is rejected, since there's
  nothing to send traffic to.
- A CIDR target is capped at 16 addresses (`/28`) — active scanning an entire
  arbitrary subnet is a materially bigger action than probing one host, and this
  platform does not support that at any larger scale.

## 4. Tools, Profiles, and Severity Rules

### Nmap Port/Service Scan (`nmap`)

Requires the `nmap` binary (installed via `backend/Dockerfile`'s `apt-get install`;
surfaced as unavailable rather than erroring if the binary is missing —
`GET /tool-health`). Invoked via `asyncio.create_subprocess_exec` with a **fixed
argument list per profile**, never a shell string:

| Profile | Arguments | Notes |
|---|---|---|
| `quick` | `-T4 -F --top-ports 100` | No service/version detection — fastest, lowest footprint. |
| `standard` | `-sV -T4 --top-ports 1000` | Service/version detection on the 1000 most common ports. |
| `web` | `-p 80,443,8080,8443 -sV` | Only the common web ports. |

Explicitly excluded from every profile: `--script` (NSE = arbitrary code execution),
`-O` (OS fingerprinting, needs raw sockets), `-sS`/`-sU` (raw-socket SYN/UDP scans),
and any timing/decoy/spoofing evasion flag (`-D`, `-f`, `--source-port`, sneaky
`-T0`/`-T1`). Every run is timeboxed (120s) and the subprocess is killed, not left
running, on timeout. Output is parsed from Nmap's own XML format
(`xml.etree.ElementTree`), never scraped from human-readable text.

**Severity:** open port with no identified service → `info`. Identified service/
version with no CVE match → `low`. Matches a CVE via vulnerability-intelligence
enrichment (below) with CVSS < 7.0 → `medium`; 7.0–8.9 or `HIGH` → `high`; ≥ 9.0 or
`CRITICAL` → `critical`.

### DNS Record Enumeration (`dns`)

Standard A/AAAA/MX/TXT/NS/CAA/SOA queries only, via `dnspython`'s async resolver.
Deliberately **no** AXFR zone-transfer attempt (an intrusive technique, not a normal
client query) and **no** subdomain brute-forcing.

**Severity:** resolved records are `info` (DNS enumeration is normal client
behavior, not a vulnerability). One evidence-based exception: no CAA record at all
→ `low` (any publicly-trusted CA can issue a certificate for the domain).

### TLS Certificate Inspection (`tls`)

One ordinary TLS handshake (the same thing a browser does) using stdlib `ssl` +
`cryptography` to parse the certificate chain. Verification is deliberately disabled
for the connection itself (so an invalid certificate can still be inspected and
reported), with trust/hostname validity checked and reported as its own separate
finding.

**Severity:** expired certificate → `high`; expiring within 14 days, self-signed, or
not verifying against the trust store → `medium`; otherwise → `info`.

*Known, disclosed scope limitation:* this reports the protocol negotiated with a
normal modern TLS client. It does not deliberately attempt to negotiate deprecated
protocols (TLS 1.0/1.1/SSLv3) to test whether a server would still accept them —
that would require multiple separate connection attempts and was judged out of scope
for this pass, not a stealth concern.

### HTTP Security Headers (`http_headers`)

One ordinary GET request (HTTPS first, HTTP fallback), via `httpx` — the platform's
existing HTTP client library. Inspects the response for `Strict-Transport-Security`,
`Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, and a verbose
`Server`/`X-Powered-By` header.

**Severity:** missing HSTS (on HTTPS) or missing clickjacking protection → `low`;
missing CSP, missing `X-Content-Type-Options`, or a version-revealing `Server`
header → `info`.

### Vulnerability-Intelligence Enrichment (`vuln_intel`)

Not a user-selectable tool — an internal helper the Nmap tool calls when it detects a
service+version banner. **Not a reuse of the existing `NVDProvider`
(`app/providers/nvd.py`) unchanged** — that connector is keyed strictly on an
already-known CVE ID; a port scan's starting point is a product+version, not a CVE
ID. This module queries the same NVD REST API with a `keywordSearch` parameter
instead, sharing the exact same `NVD_API_KEY` setting.

### Hash Metadata Analysis (`hash_analysis`)

Scoped deliberately narrowly: given a hash **value** (never a file), identifies which
algorithm it is (MD5/SHA-1/SHA-256/SHA-512) and confirms it's well-formed hex of the
expected length. No file is ever uploaded, downloaded, executed, or sandboxed — there
is no file involved at all. Real hash-*reputation* lookups (is this hash known-
malicious) already exist via the platform's normal threat-intel providers
(VirusTotal, MalwareBazaar, Hybrid Analysis) when a hash-type IOC is investigated
normally; this tool's only value is the format/algorithm identification itself.

**Severity:** always `info` — format identification is never itself a finding of
concern.

## 5. Cancellation

`POST /api/v1/security-assessment/runs/{run_id}/cancel` stops a `pending` or `running` run —
requires the same `security_assessment:create` permission as starting one (any analyst/admin can
cancel any run; this is a shared-team resource, not per-user private data, matching the rest of this
module's RBAC model). Cancelling genuinely terminates the underlying work, not just the database
row: for the Nmap tool this means the real OS subprocess is killed (`SIGKILL`, then the process is
reaped) rather than left running detached from a run the UI now shows as stopped. A run already
`completed`/`failed`/`cancelled` cannot be cancelled again (`400`); an unknown `run_id` returns `404`.
Cancellation also survives a backend restart — a run left `pending`/`running` by a process that no
longer exists still resolves to `cancelled` rather than staying stuck forever with no way to clear it.

## 6. Provenance in the Correlation Graph

`CorrelationEdgeRecord` and `EvidenceItem` both carry a `provenance_category` column
(`app/core/provenance.py`), distinguishing **what kind of source** asserted a fact —
`threat_intel` (every pre-existing provider), `security_assessment` (this module),
plus two reserved-but-currently-unpopulated categories, `local_observation` and
`ai_interpretation`, modeled for future use and disclosed here rather than silently
omitted. This is a different axis from `CorrelationEdgeRecord.provenance`, which
names *which* provider/tool asserted a fact (e.g. `"virustotal"` or `"nmap"`).

## 7. Audit Logging

Every run writes to the same shared audit sink every other configuration/account
action uses (`app/core/audit.py`): `security_assessment.run_requested`,
`.run_completed`, `.run_failed`, `.run_cancelled`. Detail strings name the target,
tool set, and profile — never raw scan output, and there are no credentials involved
in any of these tools to log in the first place.

## 8. Permissions

Two new permission strings (`app/models/user.py`): `security_assessment:create`
(`ADMIN`, `ANALYST` — the same tier as `lookup:create`, since this sends real traffic
to a real target) and `security_assessment:read` (`ADMIN`, `ANALYST`, `VIEWER` — the
same tier as `lookup:read`). Both are enforced server-side on every route; the
frontend's own role check (hiding the run form from a `VIEWER`) is UX only.
Cancellation is gated on `security_assessment:create`, not a separate permission.

## 9. Result Integration

A completed run's `ProviderResult`s are persisted as ordinary `ProviderResultRecord`
rows (`category="security_assessment"`) and fed through the same evidence/
correlation/AI pipeline every investigation already uses — the lookup's
`final_verdict`/`risk_score`/`final_assessment` are refreshed in place (the previous
primary `FinalAssessmentRecord` is demoted, not deleted), reflecting that new active-
scan findings are genuine new evidence, not merely an alternate AI opinion the way the
existing AI-backend-comparison feature's re-runs are.
