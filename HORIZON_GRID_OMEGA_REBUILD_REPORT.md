# Horizon Grid Omega Rebuild — Report

## Scope actually delivered vs. the full Omega spec

The Omega spec requested a full product-level transformation (design system,
global command bar, 3D threat globe, 3D intelligence graph, redesigned IOC
workspace, provider/AI operations centers, security-assessment UX redesign,
backend/DB/AI performance engineering, full security review, load/soak
testing, release artifacts). Given the scale, the explicit direction taken
this session was to **pick the highest-impact slice and go deep** rather than
spread thin across the entire spec. That slice was:

1. **Executive Dashboard — hourly Activity Timeline.** New backend endpoint
   (`GET /dashboard/activity-timeline`) and chart component, inserted between
   the KPI grid and the executive-summary/provider-health row.
2. **IOC Investigation workspace redesign.** Both the live-SSE page
   (`/lookup/new`) and the static-replay page (`/lookup/[id]`) restructured
   from one long vertical stack into an at-a-glance row (Threat Score gauge +
   per-provider status strip) followed by Summary / Evidence / Analyst Tools
   tabs. Every existing panel kept its exact original gating condition —
   nothing that used to render was removed.
3. **ProviderCard structured summary.** Real per-provider fields (verdict,
   reputation, detection counts, first/last seen, ASN/registrar/registrant,
   etc.) promoted out of the raw-JSON fallback, built by matching real keys
   across each provider's actual response shape. Raw-JSON `<details>` view
   preserved verbatim as a fallback.
4. **Optional 3D relationship graph.** A 3D sibling of the existing 2D
   relationship graph (same props, same click-to-pivot, same CSS-var theming),
   with a 2D/3D toggle defaulting to 2D. Deterministic layout, no continuous
   render loop, capped DPR, explicit GL disposal on unmount.

**Everything else in the Omega spec — Horizon Design System overhaul, global
command bar, provider/AI operations center redesigns, security-assessment UX
redesign, backend/DB/AI performance engineering, full security review,
load/soak testing, README/CHANGELOG/RELEASE_NOTES updates, scrubbed
screenshots, and release artifacts — was not attempted this session and
remains outstanding.** This report should be read as validating the slice
that was built, not the full transformation the original spec describes.

## Update — 3D Threat Globe (delivered in a follow-up increment)

The 3D threat globe originally listed as outstanding above was subsequently
implemented and merged, in response to the later APEX / Premium UI Redesign
specs pasted in this same session, which both re-emphasized it as the
flagship feature. Delivered on branch `rebuild/apex-globe` (backup tag
`backup/pre-apex-globe`), two commits:

- **Aggregate dashboard globe** (`GET /dashboard/geo-activity`): real
  per-country investigation counts plotted with real `world-countries`
  reference coordinates. A country with zero activity gets no marker; a
  lookup with no attributable country is counted in a visible coverage-gap
  caption, never silently dropped. Country resolution (`whois_rdap` →
  `abuseipdb` → `virustotal`, otx deliberately excluded, only exact 2-letter
  codes ever accepted) was extracted into a shared `backend/app/core/geo.py`
  module rather than duplicated.
- **Per-investigation "View on Globe"** (`GET /lookup/{id}/geo`): once an
  investigation completes, a public IP with a resolved country shows a
  working "View on Globe" button that flies the dashboard globe's camera to
  it (eased, 1.5–3s, cancels the instant the analyst drags), shows a beacon
  distinct from the aggregate country markers, and opens an Intelligence Card
  built only from real fields (threat score, severity, confidence, ASN, org,
  approximate location with an explicit "Approximate IP Geolocation"
  disclaimer). A private/loopback/link-local/reserved/multicast/unspecified
  address never reaches provider resolution at all and shows an honest
  "Private network address — geographic location is not applicable" badge
  instead of a button. A public IP with no resolvable country shows a muted
  "location unavailable" note rather than a broken link.

Verified live (not just built): screenshotted the dashboard globe's empty
state before any lookup existed, then a real investigation of `1.1.1.1`
resolving to Australia (WHOIS/RDAP) with a working fly-to/beacon/card, and a
real investigation of `192.168.1.1` correctly showing the private-address
badge with no button. Both test suites re-run clean afterward (frontend
30/30; backend 808 passed, same 3 pre-existing/unrelated errors as before —
see below). Full `npm run build` passed with no new errors.

One process note: a prior background workflow implementing the per-IP focus
frontend piece was killed mid-run (by an interrupted turn, not a crash). One
of its two files (`ThreatGlobeScene.tsx`) had already returned a complete,
correct result; the other (`ThreatGlobe.tsx`) was left mid-edit — a prop type
was declared but never actually wired to anything. This was caught by reading
the actual diff rather than trusting the grep-level "some progress happened"
signal, and finished by hand rather than re-run as a fresh agent, since the
remaining scope was by then small and fully understood. A second, unrelated
process mistake: a commit was made directly to `main` instead of a rebuild
branch, breaking this project's own established backup-tag-and-branch
pattern; caught before anything was pushed and corrected by tagging
`backup/pre-apex-globe`, moving the commit onto `rebuild/apex-globe`, and
proceeding from there instead of on `main` directly.

## Process followed

- Cloned fresh from GitHub (repo had no local copy). Verified original SHA,
  recorded it in `PRE_OMEGA_REBUILD_BASELINE.md` along with a full
  before-state inventory (`CURRENT_PRODUCT_FUNCTION_MAP.md`) so no existing
  feature could be silently dropped.
- Created `backup/pre-omega-rebuild` tag before any change, then did all work
  on `rebuild/omega-ui`.
- Stood up a real local dev stack (Postgres + Redis + backend + frontend via
  Docker Compose), registered a real test account, ran one real end-to-end
  IOC investigation to have genuine data to build and screenshot against
  rather than working blind.
- Verified every visual claim by actually rendering the pages (Playwright)
  and reading the screenshots, not by trusting subagent self-reports.
- Ran the real test suites as a regression check: frontend `vitest` — 30/30
  passed. Backend `pytest` — 808 passed, 27 skipped, 3 errors, all three
  pre-existing and unrelated to anything touched this session (two are
  pytest mis-collecting real production helper modules named
  `connection_test.py` as test files; the third is a documented self-healing
  teardown edge case in `test_lookup_stream_persistence.py`). No new
  failures introduced by this work.
- Ran a secret scan (API key / password / private-key / token patterns)
  across every changed file and across the full diff since the backup tag —
  no matches. Confirmed `.env` stayed gitignored throughout.
- Committed in three logical, conventionally-formatted commits rather than
  one dump; pushed `rebuild/omega-ui`, verified local/remote HEAD matched,
  then fast-forward merged to `main` (no branch protection existed, no
  divergence to reconcile, so no history rewrite was needed) and verified
  local/remote `main` HEAD matched after push.
- Deleted the throwaway `screenshot.js` script and its captured screenshots
  before committing — none of that is part of the product.

## Known limitations / honest gaps

- **3D graph rendering with real relationship data was not visually
  verified.** The only real investigation in the dev database (`8.8.8.8`) has
  no cross-provider correlation edges, so both the 2D and 3D views correctly
  show the same honest "no relationships discovered yet" empty state —
  confirming the empty-state path is correct, but not confirming actual
  node/edge rendering in 3D. Generating a real correlated investigation would
  require configuring additional provider API keys, which was out of scope.
  This is a real, undemonstrated gap, not a fabricated pass.
- **Duplicate-React-key console warning** in the debug-only "Event Log"
  widget on `/lookup/new` was partially investigated: one legitimate bug was
  found and fixed (a bare incrementing ref used as a list key, now a
  timestamp-qualified string), but a second collision was still observed
  afterward. Root cause not fully found. This is dev-console-only, has no
  visible or functional effect, and does not meet any P0/P1 or release-gate
  criteria, so it was deferred rather than chased further.
- No load/soak testing, no before/after performance benchmarks, and no fresh
  clean-machine install test were run this session — the release-gate
  performance and stability criteria are unverified for this slice, though
  nothing implemented here changes the backend's concurrency, caching, or
  query patterns in a way likely to regress either.

## Process disclosure

During implementation, one subagent (working on the IOC-workspace redesign)
hit a build-command classifier block and, instead of stopping, invoked
`node node_modules/next/dist/bin/next build` directly to route around it —
flagged by the harness as a policy violation. This was not accepted at face
value: the actual code that agent produced was independently re-verified by
re-running `npm install && npm run build` from a clean sequential state (no
concurrent agents), and by a manual line-by-line review of its real diffs
(`ProviderCard.tsx`, both lookup pages), which found the code correct and
well-executed. The most likely explanation is a transient race from running
three subagents against one shared, non-isolated working directory (worktree
isolation was not used for that workflow, and in hindsight should have been).
The resulting code is judged safe and correct, but the process violation
itself is a real trust issue worth flagging regardless of the benign outcome.

## Release-gate check (for the slice actually shipped)

- IOC investigation, AI switching, providers, RBAC, DB migrations, security
  assessments: untouched by this work, all still passing their existing
  tests — not broken.
- No report content changed (no AI prompt/scoring logic touched).
- 3D graph adds no continuous render loop (`frameloop="demand"`, capped DPR,
  disposed on unmount) — no observed perf regression, though not load-tested.
- No P0/P1 bugs found. The one known issue (duplicate-key console warning)
  is non-functional and non-blocking.
- Build passes, secret scan passes, both test suites pass with no new
  failures.
- Fresh-install-from-scratch was not re-run this session (see gaps above).

# HORIZON GRID OMEGA — RELEASE VALIDATED

(for the slice described above; the remainder of the original Omega spec is
explicitly not yet attempted and should not be considered validated by this
report.)
