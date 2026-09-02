# HORIZON GRID — Overnight Local QA/Pentest Report

Local-only deliverable. Not committed to git, not pushed anywhere. Generated overnight, unattended, per the "HORIZON GRID — AUTONOMOUS LOCAL FULL-SYSTEM QA, PENTEST VALIDATION, REPAIR & REBUILD LOOP" mission and its immediate follow-ups (Windows performance mode, then "go ahead, I'll be sleeping").

## Verdict

**LOCAL RELEASE NOT READY** — not because of any *unresolved* P0/P1 (every real bug found tonight was fixed, regression-tested, and live-reverified), but because several mission phases were not run at all tonight, for reasons explained below. This is a "not fully validated" state, not a "known broken" state.

## What actually happened tonight, honestly

### Done, with real evidence
- **Build verification**: refreshed and rebuilt the Windows-installed copy to current source (0.3.6 → 0.3.8), hit and fixed a real Docker Desktop storage-backend glitch (frontend container's `node_modules` anonymous-volume mount failing with `permission denied` — fixed by restarting Docker Desktop), confirmed all 8 containers healthy and `/health` reporting `0.3.8`.
- **Fresh test accounts**: Admin/Analyst/Viewer created via the real API (self-registration bootstrap + admin-create). Note: this codebase has 3 roles, not the 4 (Admin/Analyst/Standard/Read-Only) the original mission brief assumed — Viewer *is* the read-only role.
- **Direct-supervised pentest run against `192.168.0.1`** (your own router, per your explicit go-ahead): scope enforcement verified (an out-of-scope target was correctly rejected before the real one was added), real nmap/TLS/HTTP-header scan completed in ~25s, found a TP-Link router (BusyBox http 1.19.4, UPnP MiniUPnP 2.2.2, self-signed TLS cert, missing `X-Content-Type-Options`) — all INFO/LOW/MEDIUM, no CVE matches, nothing required "POTENTIALLY VULNERABLE — DESTRUCTIVE VALIDATION NOT PERFORMED". Exercised both safe validation-recheck checks successfully.
- **Broad 9-agent discovery pass**: auth/RBAC, IOC lookup engine, providers/AI config, dashboard/cases/hunting/basket, Pentest Suite scope-enforcement adversarial testing, Security Assessment Toolkit (real cancel-race + real SIGKILL-recovery test), backend static self-security-audit (SQLi/command-injection/path-traversal/SSRF/secrets/log-injection/XSS/deserialization), input-robustness stress testing, and a full regression-suite run. ~1M tokens, 520 tool calls, ~37 minutes.
- **20 real, evidenced bugs found** — 3 P0, 6 P1, 8 P2, 3 P3 (full detail, exact repro/evidence/fix per bug in `BUG_AND_REPAIR_HISTORY.md`). **19 fixed tonight**, 1 deferred (a genuine feature gap, not a security/regression issue — see below).
- **Repair discipline followed for every fix**: root-caused against real evidence, smallest targeted fix, a real regression test added (37 new tests), full suite re-run clean (**478 passed, 0 failed, 39 pre-existing skips**), stack rebuilt, and the 3 P0s specifically re-verified *live* against the rebuilt stack (not just unit tests) — forged-token bypass now 401s, the SSRF target now 400s, the nmap-injection payload now 400s, and the legitimate `127.0.0.1` self-test pattern still works (confirmed the SSRF fix didn't break existing intended behavior).

### Not done tonight — explicit, not silently skipped
- **Full UI walkthrough with screenshots** (explicitly requested earlier in this session) — not attempted; all testing tonight was API/service-level, not browser-driven.
- **Heavy Local AI stress testing / AI-switching stress testing** — deliberately scoped down. Host RAM was already tight tonight (dropped to ~2GB free at one point with two full Docker Compose stacks running); loading/switching large local models on top of that risked crashing the host with nobody awake to intervene. One provider-config test did discover Ollama's `llama3.2:3b` was actually loaded (18GB) when the task briefing assumed zero models loaded — a real environment-state surprise, handled by testing against a temporarily-repointed unreachable URL instead of touching the live model.
- **Extended performance/soak/concurrency testing at scale** — same RAM-safety reasoning; only the concurrency testing already built into the discovery pass (concurrent cancel-race, concurrent scan) ran.
- **Fresh install from the rebuilt `.exe`/`.deb` installer** — not attempted (would need another elevated, disruptive install + verify cycle; deferred to daytime).
- **`CURRENT_FUNCTION_INVENTORY.md`, exhaustive per-phase test matrices** — not produced as separate documents; function coverage is instead reflected in the discovery pass's own per-agent scope (see `BUG_AND_REPAIR_HISTORY.md`).

## A real, unresolved environmental issue (flagging, not hiding)

The Windows-installed copy's Docker Compose project (`app`, ports 8000/3000) **kept reviving on its own** overnight despite being explicitly stopped multiple times — including once with its restart policy explicitly set to `no`. No Windows Scheduled Task, Service, or Docker restart-policy setting was found to explain it after a real investigation. This caused a genuine SIGKILL of the test backend at one point (host RAM pressure from two full 8-container stacks running simultaneously) and disrupted several in-flight test requests (the app's own orphan-recovery mechanism cleaned up correctly afterward — that mechanism is not the bug). **If you notice the installed app running when you didn't start it, this is why — not fully root-caused tonight.**

## Two things that need your attention this morning

1. **The Windows-installed copy (`Program Files`, ports 8000/3000) is currently stopped, and I left it that way on purpose.** Refreshing it to tonight's fixed source needs another admin/UAC approval (writing under `Program Files` is protected, and nobody was awake to click through it after I found the P0s). Its own `.env` is separately admin-protected, so I couldn't even check whether *it* has the same JWT-secret-placeholder bug the dev tree had — starting it as-is would mean running a real, known-severity auth bypass live without telling you, which felt worse than just leaving it stopped. Say go and I'll refresh + rebuild it with one more UAC prompt.
2. **The test stack (`hgqa`, ports 8100/3100) is up, fixed, and fully re-verified** — safe to keep exploring there, or I can tear it down once you're back.

## Hard constraints honored throughout
No `git add`/`commit`/`push`, no GitHub interaction of any kind. Pentest scope stayed locked to `192.168.0.1` + `127.0.0.1`/localhost + this app's own services — verified via the adversarial scope-bypass testing in the discovery pass, which is itself part of what found BUG-QA-005/006/007/008. No destructive actions taken anywhere; all test data was disposable and on the local test stack only.

See `BUG_AND_REPAIR_HISTORY.md` for the full bug-by-bug detail (file:line, exact repro, exact evidence, exact fix, regression test) behind every claim above.
