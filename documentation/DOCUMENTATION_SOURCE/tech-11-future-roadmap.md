# Future Roadmap

This section closes the technical appendix by separating what HORIZON GRID actually does today from what its existing architecture is positioned to grow into. An **IOC (Indicator of Compromise)** is the artifact a user submits for lookup — an IP address, domain, URL, file hash, CVE ID, etc. A **provider** is a connector to one external threat-intelligence, vulnerability, or OSINT data source that the platform queries for a given IOC. Everything in "Current Capabilities" below is a recap of functionality documented elsewhere in this appendix and verified directly against source code; it introduces no new claims. Everything in "Future Possibilities" is explicitly speculative and is scoped strictly to work that the existing architecture already provisions for.

## Current Capabilities

- **Streaming lookup pipeline**: `POST /api/v1/lookup/stream` is a Server-Sent Events (SSE) endpoint, rate-limited to 10 calls/60s per user by default (Redis fixed-window limiter). It classifies the submitted value into one of 31 `IOCType` values, then fans out concurrently to every registered provider that supports that type.
- **16 working providers** across 7 categories — threat intelligence, certificate intelligence, vulnerability, WHOIS, sandbox, passive DNS, and OSINT — each normalized behind a common `BaseProvider` interface with per-provider timeout/retry and Redis-backed result caching.
- **Multi-backend AI client**: four interchangeable backends — Ollama (local, default, no key), Anthropic, AWS Bedrock, and Google Gemini — all exposed through one identical `call_claude_json()` method, so the rest of the application never branches on which backend is active. Backend selection fails fast with a clear error if the chosen backend isn't configured.
- **Two distinct, separately-persisted AI call types**: a per-provider summary (grounded only in that provider's own returned data) for every provider that returned data, and one consolidated final assessment grounded only in the per-provider summaries plus the correlation engine's output — never in raw provider JSON directly.
- **Anti-fabrication safeguards**: a no-evidence short-circuit that returns a hardcoded "unknown" verdict without calling the AI at all when there is nothing to summarize; a grounding pass that strips any AI-cited provider agreement/disagreement that isn't backed by real correlation data, and flags any AI-cited MITRE ATT&CK technique that isn't backed by a real correlation edge as ungrounded; an equivalent evidence-citation stripping/backfill pass on the analyst-facing explanation features.
- **Correlation engine**: a pure, I/O-free function that extracts typed relationship edges (resolved IPs, related hashes, malware families, MITRE techniques, CVEs, and more) from normalized provider fields, boosts confidence per corroborating provider, and returns deduplicated facts and provider-agreement data. Edges are persisted to Postgres and streamed live.
- **Deterministic evidence ledger**: evidence items are built directly from provider results, AI summaries, and correlation edges — explicitly not AI-generated — so downstream AI explanations have real, checkable records to cite.
- **8 additional grounded AI analyst features** (WHY malicious, What Is This, Provider Disagreement, False-Positive Assessment, Challenge/red-team, Smart Next Actions, Intelligence Gaps, Score Explanation) plus Copilot Q&A, IOC comparison, and hunting-query/detection-rule generation — all restricted to citing indicators and evidence that genuinely exist in the correlation graph and evidence ledger.
- **Postgres as the sole system of record**: lookups, provider results, AI summaries, correlation edges, evidence items, cases, and users are all written there today; it is the only datastore actually populated during a lookup.
- **Redis in three confirmed real roles**: provider-result cache, per-user rate limiter on lookup creation, and Celery broker/result backend.
- **Scheduled OSINT re-crawl**: a single Celery Beat job (`run_osint_crawl`, hourly) re-crawls OSINT sources for IOCs looked up in the last 24 hours; the synchronous lookup pipeline itself does not go through Celery.
- **Role-based access control and auth**: JWT-based authentication (first registered user automatically becomes admin; self-registration is then rejected with `403` for everyone else, who must be created by an admin from the Administration console with their role chosen up front), a 3-role permission matrix enforced via a `require_permission()` dependency.
- **Windows deployment path**: an Inno Setup installer and WinForms Setup Wizard that configure 8 providers (each with a live "Test" button; some require an API key/token, others such as NVD and PhishTank work without one), write secrets via a CSPRNG, and run Docker Compose as the actual runtime — plus a parallel Kubernetes/Kustomize deployment alternative.
- **Automated backend test coverage**: pytest unit tests (13 files) and integration tests (3 files) covering IOC detection, provider connectors, AI grounding logic, the correlation engine, and the real orchestrator end-to-end (against fake provider stubs with mocked HTTP, using a real Redis dependency).

## Future Possibilities

**None of the items below exist today. They are described here only as architecturally plausible next steps.**

The architecture already provisions infrastructure and patterns that go further than what is currently wired up. The items below are scoped strictly to that existing provisioning — nothing here is a new subsystem.

### Provisioned infrastructure with no consuming code yet

| Capability | Already provisioned today | What "completing" it would require |
|---|---|---|
| Neo4j graph integration | The `neo4j:5-community` container (with the APOC plugin) already runs in `docker-compose.yml`; `neo4j_uri`/`neo4j_user`/`neo4j_password` config fields already exist; the `CorrelationEdgeRecord` model and the correlation engine's own module docstring already describe edges as intended to be "mirrored into Neo4j." | Actual driver instantiation and Cypher read/write code — none exists anywhere in the backend today — so the graph database consumes the correlation edges it was already provisioned to store, rather than those edges living only in Postgres as they do now. |
| OpenSearch indexing | The `opensearchproject/opensearch:2.17.0` container already runs in `docker-compose.yml`; an `opensearch_url` config field already exists in `app/core/config.py`. | An indexing pipeline and search/query code against the already-running container — zero such code exists today, so no search functionality is implemented against it. |

The diagram below reflects today's actual wiring (solid lines) versus the provisioned-but-unconsumed datastores (dashed lines):

[FIGURE: tech-11-future-roadmap-diagram-1.png | Diagram: Provisioned infrastructure with no consuming code yet]

### Extending existing patterns

- **Provider "Test" UI coverage for the 6 credential-free backend providers** (`crtsh`, `cisa_kev`, `mitre_attack`, `whois_rdap`, `spamhaus`, `internet_intelligence`) — these six already have real, working backend implementations and are already `requires_key = False`, so extending the Setup Wizard's existing 8-provider "Test" button pattern to cover them (even as a simple "no configuration needed" confirmation) would be a bounded extension of a UI pattern that already exists for the other 8 providers, not a new mechanism.
- **Additional provider integrations** — the current 16-provider registry already normalizes 7 categories of heterogeneous sources (threat intelligence, certificate intelligence, vulnerability, WHOIS, sandbox, passive DNS, OSINT) behind one common `BaseProvider`/`supports(ioc_type)` interface, so onboarding further sources is a natural extension of a registration pattern that already exists and is already proven at 16-provider scale.
- **Expanded AI backend support** — the four existing backends (Ollama, Anthropic, AWS Bedrock, Google Gemini) already share one identical `call_claude_json()` method and are selected through a single `_get_ai_client()` switch with fail-fast configuration checks, so adding further backends is a natural extension of a multi-backend abstraction that already exists today, rather than a redesign of the AI layer.
