# Pre-Omega Rebuild Baseline

Recorded before any Omega rebuild changes were made, per the rebuild spec's safety-baseline requirement.

## Repository state

- **Repository:** https://github.com/neshboy/horizon-grid
- **Default branch:** `main`
- **Original commit SHA:** `0f82a96a388f07737103515d3a306fd794503640`
- **Commit message:** "fix: test_backend_deployment_msfrpcd_matches_compose_pattern was comparing the wrong two things"
- **Commit date:** 2026-09-13 20:51:15 +0800
- **Latest tag at clone time:** `v0.3.13` (HEAD is 1 commit ahead of this tag)
- **Local HEAD at clone time:** matched remote HEAD exactly (fresh clone, zero divergence, zero uncommitted changes)
- **Backup tag created:** `backup/pre-omega-rebuild` -> `0f82a96a388f07737103515d3a306fd794503640`
- **Rebuild branch created:** `rebuild/omega-ui`, branched from the same commit

Recovery path if the rebuild needs to be abandoned: `git checkout main && git reset --hard backup/pre-omega-rebuild` restores the exact pre-rebuild state (backup tag is never force-moved).

## Version

- Frontend `package.json`: `ioc-intel-platform-frontend@0.3.13`
- Backend `_APP_VERSION` (`backend/app/main.py`): `0.3.13`

## Build result at baseline

- `frontend`: `npm install` succeeded (542 packages; 8 pre-existing audit findings -- 2 moderate/5 high/1 critical, all in third-party deps, not introduced by this rebuild -- see Security Review section of the final report). `npm run build` succeeded cleanly: 16 routes, all static except `/lookup/[id]` and `/pentest/[id]` (dynamic), one pre-existing ESLint warning (`pentest/[id]/page.tsx` missing-dependency, not a functional bug).
- `backend`: not yet built/tested at baseline (requires Postgres + Redis; see Test result below).

## Test result at baseline

- Frontend: `vitest` present but only 4 test files (pure `lib/*.ts` unit tests, zero component/rendering tests) -- not run yet at baseline, will run as part of the rebuild's regression pass.
- Backend: pytest suite exists but requires a live Postgres/Redis (via `docker-compose.yml`) -- not yet run at baseline; will run after bringing up the dev stack.

## Current architecture (see CURRENT_PRODUCT_FUNCTION_MAP.md for full detail)

- **Backend:** FastAPI 0.115 + SQLAlchemy 2.0 async (asyncpg), PostgreSQL system of record, Redis for caching/rate-limiting, Celery for one scheduled job (OSINT re-crawl), Alembic migrations (15 so far, all additive).
- **Frontend:** Next.js 14.2.15 (App Router), React 18.3.1, Tailwind CSS with a centralized HSL-token theme (`app/globals.css` + `tailwind.config.ts`), Radix UI primitives, hand-rolled fetch client (no React Query/SWR), manual SSE consumption for live investigations.
- **Providers:** 18 real threat-intel integrations (registry in `backend/app/providers/registry.py`), concurrent fan-out with per-provider timeout/retry/cache, one provider failing never blocks the investigation.
- **AI:** 11 real backends (Ollama local-first default, plus Anthropic/Bedrock/Gemini/Groq/OpenAI/Kimi/DeepSeek/xAI/Mistral/OpenRouter), runtime-switchable with no restart, deterministic non-AI scoring engine that the AI narrative is grounded against (AI never invents the numbers).
- **Security Assessment Toolkit:** real nmap/DNS/TLS/HTTP/vuln-intel checks, explicit scope confirmation required, structurally injection-safe (hardcoded arg lists).
- **Pentest Suite:** real assessment lifecycle + gated Metasploit exploit validation (msgpack-RPC to a real `msfrpcd`), global kill switch, 5-check gating before any real exploit execution.

## Existing features inventory (must all survive the rebuild)

Auth (register/login/refresh/logout, JWT + RBAC), Admin (user management, roles, audit log), IOC investigation (live SSE + static replay), Basket, Cases, Pentest Suite, Security Assessment Toolkit, Provider management (config/test/enable), AI provider management + switching, Executive Dashboard (KPIs + provider health), Provider Health history page, System health/metrics endpoints.

## Known pre-existing issues (not introduced by this rebuild, flagged for visibility)

- `RELEASE_NOTES.md` and `KNOWN_LIMITATIONS.md` are stale (describe v0.1.0 -- 5 AI backends, 16 providers, no Security Assessment/Pentest mention). `CHANGELOG.md` and `RELEASE_NOTES_CURRENT_VERSION.md` are accurate.
- `next@14.2.15` has a known published security advisory with a patched version available; not upgraded as part of this rebuild (out of scope -- flagged for a separate dependency-upgrade pass).
- Neo4j driver is a configured dependency with no actual call site (correlation data lives entirely in Postgres); appears aspirational, not a functional gap.
