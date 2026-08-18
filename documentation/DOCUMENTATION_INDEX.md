# Documentation Index

**IOC Intelligence Platform -- Documentation Package**
Index prepared: 2026-08-12
Product version documented: **0.1.0**

This package contains **three standalone documents**, each written for a different audience and each usable entirely on its own -- no document assumes the reader has read either of the other two. All three are built from the current source code and the current running application; where an older document (`FINAL_PRODUCT_DOCUMENTATION.pdf`, see note at the bottom) disagreed with the current product, the current product won.

| # | Document | Audience | Purpose | File | Version | Last verified |
|---|---|---|---|---|---|---|
| 1 | **User Manual** | Complete beginners / end users (SOC analysts, admins) with no code access | Install, configure, and operate the product from first login through investigation, evidence review, case management, export, and troubleshooting -- using only what exists in the shipped application today | `IOC_INTELLIGENCE_PLATFORM_USER_MANUAL.pdf` / `.docx` | 0.1.0 | 2026-08-12 |
| 2 | **Source Code Documentation** | Developers and maintainers with git access | Orient a new developer in the repository: stack, structure, frontend/backend architecture, provider/AI abstractions, runtime configuration and credential flow, testing/build, and concrete extension-point walkthroughs (add a provider, add an AI backend, add an endpoint, add a migration) | `IOC_INTELLIGENCE_PLATFORM_SOURCE_CODE_DOCUMENTATION.pdf` / `.docx` | 0.1.0 | 2026-08-12 |
| 3 | **Backend / System Architecture Documentation** | Backend engineers, DevOps, security reviewers | Exhaustive API reference (49 endpoints), exhaustive database reference, provider/AI integration technical reference, the runtime-configuration architecture (why "no restart" is actually true), security architecture with an explicit Implemented-vs-Recommended split, background processing/caching, and deployment/troubleshooting | `IOC_INTELLIGENCE_PLATFORM_BACKEND_DOCUMENTATION.pdf` / `.docx` | 0.1.0 | 2026-08-12 |

## Contents at a glance

**User Manual** (86 pages, 22 sections, 54 figures) -- Front matter, User Journey, Installation, First-Run Configuration, IOC Investigation, IOC Providers (including live add/test/enable-disable), AI Analysis (including live no-restart backend switching), Evidence & Correlation, Cases & Basket, Export & Reporting, SOC Workflow, System Health & Troubleshooting, Security & Data Handling, FAQ / Best Practices / Quick Reference.

**Source Code Documentation** (34 pages, 8 sections, 6 diagrams) -- Overview/Stack/Repo Structure, Frontend Architecture, Backend Architecture & Request Flow, Provider & AI Client Architecture, Runtime Configuration & Credential Lifecycle, Testing & the Build Pipeline, Extension Points, Developer Troubleshooting.

**Backend Documentation** (47 pages, 8 sections, 9 diagrams) -- Overview & Lifecycle, API Reference (every endpoint), Database Reference (every table/column), Provider & AI Integrations, Runtime Configuration Architecture, Security Architecture (Implemented vs. Recommended), Background Processing & Caching, Deployment & Troubleshooting.

## How the three documents relate to each other

They are deliberately **not merged** -- each is a complete, standalone artifact for its audience. Where the same underlying fact appears in more than one document (e.g. "the AI backend can be switched without restarting the platform"), the User Manual states the *observable behavior*, the Source Code doc explains the *mechanism* (`_get_ai_client()`'s fresh-DB-read-plus-fresh-construction pattern), and the Backend doc gives the *exhaustive technical reference* (the runtime-configuration architecture chapter, with file:line citations and the historical bug this design fixed). Terminology is kept consistent across all three (the same feature is never given two different names).

## A note on `FINAL_PRODUCT_DOCUMENTATION.pdf` / `.docx`

A combined, single-document version of the product guide and technical appendix (`FINAL_PRODUCT_DOCUMENTATION.pdf`/`.docx`, 118 pages) was produced in an earlier documentation pass and still exists alongside this package. It is **not part of the current three-document deliverable** and is retained only for backward compatibility with whoever received it previously. It does not include the newly-added dev-/backend-oriented chapters (runtime configuration architecture, extension points, exhaustive API/database reference, security Implemented-vs-Recommended split) that are unique to documents 2 and 3 above. New readers should use the three documents in the table above, not the combined file.

## Source material

All three documents are generated from Markdown chapters under `documentation/DOCUMENTATION_SOURCE/` (`user-*.md`, `dev-*.md`, `backend-*.md`) via `documentation/build/build-doc-generic.js`, driven by `config-user-manual.json` / `config-source-code.json` / `config-backend.json`. Diagrams are authored as Mermaid code blocks in the source chapters and rendered to PNG by `documentation/build/render-diagrams.js`. See `DOCUMENTATION_COMPLETION_REPORT.md` for the full QA record.
