# Security Policy

## Supported Versions

HORIZON GRID is currently a single rolling `0.2.x` release line — there is no
older major/minor version still receiving fixes, and no formal LTS or
maintenance branch. Security fixes, when made, land on the current `0.2.x`
line. As the project matures past its first release, this section will be
updated to reflect which versions are actively supported.

| Version | Supported |
| ------- | --------- |
| 0.2.3   | Yes (current release) |
| < 0.2.3 | No — upgrade to 0.2.3 |

## Reporting a Vulnerability

This is a small, privately-hosted project (`neshboy/horizon-grid`) and does
not have a dedicated security email address. Please do **not** open a public
GitHub issue for a suspected vulnerability. Instead:

1. Preferred: open a **private GitHub Security Advisory** on this repository
   (repo → **Security** tab → **Report a vulnerability**). This lets us
   discuss and fix the issue privately before any public disclosure.
2. Alternative: contact the repository owner directly through their GitHub
   profile (`neshboy`) if you are unable to use the Security Advisory flow.

When reporting, please include:
- The affected component/file or endpoint, if known.
- Steps to reproduce, or a proof-of-concept, at a level of detail sufficient
  for us to confirm and fix the issue.
- The potential impact as you understand it (e.g. data exposure,
  privilege escalation, remote code execution).

## Responsible Disclosure Expectations

This project is maintained on a best-effort basis, not by a dedicated
security team, and there is **no fixed SLA** for acknowledgment or fixes. In
good faith, we will:

- Acknowledge new reports as soon as reasonably possible.
- Investigate and work on a fix at a pace appropriate to severity and
  available time — critical issues will be prioritized, but "prioritized"
  for a small project may still mean days, not hours.
- Keep the reporter informed of progress and let them know when a fix has
  shipped.
- Credit reporters who want credit, once a fix is out, unless they ask to
  remain anonymous.

In return, we ask reporters to give us a reasonable window to investigate
and fix an issue before any public disclosure, and to avoid accessing,
modifying, or exfiltrating data beyond what is strictly necessary to
demonstrate the vulnerability.

## Known Security-Relevant Limitations

In the interest of being upfront rather than making unverified claims, here
is what is actually true about this codebase today, based on direct source
inspection:

- **RBAC is a real, enforced access-control model, not just documentation.**
  `backend/app/models/user.py` defines three roles (`ADMIN`, `ANALYST`,
  `VIEWER`) with a static permission matrix, and
  `backend/app/auth/rbac.py`'s `require_permission(...)` is wired in as a
  FastAPI `Depends(...)` on route handlers (e.g. all user-management routes
  in `admin.py` require `user:manage`, held only by `ADMIN`; launching a
  Security Assessment scan requires `security_assessment:create`, which
  `VIEWER` does not have). That said, RBAC is only as strong as the
  underlying authentication — treat network exposure of the platform
  accordingly, and do not expose it directly to the public internet without
  additional network-level controls.
- **Dependency vulnerabilities exist; some have been fixed, some remain
  open by design.** A `pip-audit` run against `backend/requirements.txt`
  originally found 32 known advisories across 7 packages. `python-multipart`
  (→0.0.31) was upgraded cleanly. `cryptography` was first bumped to 49.0.0,
  but a follow-up independent audit caught that 49.0.0 itself had a newly
  disclosed high-severity advisory (CVE-2026-69247, a PKCS7 Bleichenbacher
  oracle) — bumped again to 50.0.0, which is clean. That same follow-up
  audit also caught `pyasn1` (a transitive dependency pulled in by
  `python-jose`, not previously tracked here at all) sitting on 0.4.8 with
  4 high-severity DoS advisories. Pinning `pyasn1` to the fixed 0.6.4 first
  looked safe in an incremental local upgrade, but a genuinely fresh
  `pip install -r requirements.txt` (exactly what CI and any new clone
  does) caught what the incremental test missed: `python-jose==3.4.0`
  hard-requires `pyasn1<0.5.0`, so pip's resolver correctly refused to
  install anything at all — a real `ResolutionImpossible` failure, caught
  by CI on the very next push. Fixed properly by bumping `python-jose` to
  3.5.0, which relaxed its own constraint to `pyasn1>=0.5.0` — verified via
  a genuinely fresh install in a container matching the real
  `python:3.12-slim` runtime (not an incremental upgrade), a direct
  `jose.jwt.encode`/`decode` round trip, and the full unit suite
  (282 passed), plus a re-run of `pip-audit` in that same fresh container
  confirming `cryptography` and `pyasn1` no longer appear in the findings
  at all. `starlette` and `lxml` remain on their original versions:
  `starlette` is a transitive dependency of
  `fastapi==0.115.0` and cannot be bumped to a patched release without also
  bumping FastAPI itself (a coordinated framework upgrade, deliberately
  deferred pending its own regression pass rather than done blindly);
  `pytest`'s patched release is a major-version bump for a dev-only tool,
  also deferred pending a dedicated pass; `ecdsa` has no fix published
  upstream at all (its maintainers have declined to fix this side-channel-class
  issue). An `npm audit` run against `frontend/` originally found 11
  vulnerable packages (2 critical, 6 high, 3 moderate); `vitest` (→4.1.10)
  and `nanoid` (→latest) have since been upgraded, closing both critical
  advisories (verified via a clean `npm run lint` + `npm run build` after).
  The remaining 5 findings (`next`, `eslint-config-next`,
  `@next/eslint-plugin-next`, `glob`, `postcss`) all require a `next`
  14→16 major-version bump, which is a real breaking-change risk for a
  production Next.js app with no existing frontend test suite to catch
  regressions — deliberately deferred to its own tested upgrade pass rather
  than done blindly. (`next`'s own advisory severity has since escalated to
  critical in npm's scoring as newer Next.js CVEs were published — the
  deferral reasoning is unchanged, but this is a real, growing risk, not a
  static one; re-audit before treating "deferred" as "fine indefinitely.")
  These are dependency-level findings, not confirmed exploitable paths in
  this application's own code. Because a brand-new advisory against a
  package we'd just called "fixed" surfaced within the same day, treat any
  "closed" dependency finding as time-stamped, not permanent — re-run
  `pip-audit`/`npm audit` regularly, not just once.
- **Installers are not code-signed.** The Windows installer
  (`HORIZON-GRID-Setup-0.2.0.exe`) is explicitly unsigned — this is
  documented plainly in the release notes — so Windows SmartScreen will warn
  on first run and users must click through "Run anyway." The Linux `.deb`
  package is likewise not GPG-signed. Verify the provenance of any installer
  you download through the channel you obtained it from.
- **CI now runs on every push/PR**: `backend-tests.yml` (unit suite, always
  green; a separate job runs the integration suite against a real
  docker-compose stack), `frontend-build.yml` (lint + build), and a weekly
  `dependency-audit.yml` (pip-audit + npm audit, non-blocking). Before this,
  there was no `.github/workflows` directory and audits were manual,
  point-in-time snapshots — that gap is now closed.

This list will be updated as these items are addressed or as new,
verified findings come to light.
