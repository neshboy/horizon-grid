# Data Flow

This section traces exactly what happens, in code, when a user submits one IOC (Indicator of Compromise — a piece of evidence such as an IP address, domain, URL, file hash, CVE ID, or MITRE ATT&CK technique ID that a security analyst wants to investigate) to the platform, from the initial HTTP request through to the final "done" event. It then states plainly which of the platform's four datastores actually participate in that flow today, and which do not.

The entry point for a lookup is a single endpoint: `POST /api/v1/lookup/stream` (`backend/app/api/routes/lookup.py`). It is a Server-Sent Events (SSE) endpoint — the client opens one HTTP connection and receives a sequence of typed events as the lookup progresses, rather than blocking for a single response. The sequence below is verified directly against that endpoint's implementation.

## 🔍 The 9-Step Lookup Pipeline

1. **Rate limit check.** A Redis-backed fixed-window rate limiter (`RateLimiter`, `app/core/cache.py`) rejects the request if the calling user has exceeded the configured quota — 10 calls per 60 seconds per user by default (`app/core/config.py`), both values configurable.

2. **IOC type detection.** `detect_ioc_type()` (`app/ioc/detector.py`) classifies the raw input string using ordered regex and heuristic checks into one of 33 `IOCType` enum values (`app/ioc/types.py`) — for example, distinguishing an IPv4 address from a domain from a SHA256 hash.

3. **Lookup record created.** An `IOCLookup` row is created in Postgres immediately, with `status = RUNNING`. This is the row that will later be updated with the final verdict and risk scores.

4. **Provider fan-out.** `run_all_providers()` (`app/providers/orchestrator.py`) concurrently invokes every registered provider (of 18 total) whose `supports(ioc_type)` returns true for this IOC's type, using `asyncio.create_task` and `asyncio.as_completed` — providers run in parallel, not sequentially. A "provider" here is an external threat-intelligence, vulnerability, or OSINT source the platform queries (for example VirusTotal, AbuseIPDB, NVD). Each provider call passes through a Redis cache check first, then `BaseProvider.run()` (timeout and retry handled by `tenacity`, with configurable `provider_timeout_seconds` and `provider_max_retries`), producing a normalized `ProviderResult`.

5. **Per-provider persistence and summary.** As each provider result arrives (not waiting for all of them), it is persisted to Postgres as a `ProviderResultRecord`. If that provider's status is `ok`, `summarize_provider()` (`app/ai/service.py`) makes one AI call for that provider alone, grounded only in that provider's own JSON response, and the result is persisted as an `AISummaryRecord` tagged with that `provider_id`. Both the raw result and the summary are streamed to the client as SSE events (`provider_result`, `provider_summary`) and committed to Postgres after every single provider completes — a deliberate design so that a client disconnecting mid-lookup does not lose already-completed provider data (`lookup.py`, lines 118-157).

6. **Correlation.** Once every provider has finished, `correlate()` (`app/correlation/engine.py`) runs. This is a pure, I/O-free function: it extracts typed relationship edges from normalized provider fields (`resolved_ips`, `related_hashes`, `malware_families`, `mitre_techniques`, `cves`, and others), deduplicates and corroborates them — each additional provider that independently reports the same fact boosts its confidence score by a fixed increment (`_CORROBORATION_BONUS_PER_PROVIDER = 0.15`) — and returns a `CorrelationResult` (nodes, edges, deduplicated facts, provider agreement). The resulting edges are persisted as `CorrelationEdgeRecord` rows in Postgres and streamed as a `correlation` SSE event.

7. **Final AI assessment.** `generate_final_assessment()` (`app/ai/service.py`) makes exactly one consolidated AI call, grounded in all of the per-provider summaries plus the correlation output — never in the raw provider JSON directly. The result is validated against the `FinalAssessment` schema, cross-checked against the deterministic correlation data by `_ground_final_assessment()` (which silently strips any agreeing/disagreeing provider citation that isn't actually backed by real correlation data, and separately flags — rather than removes — any cited MITRE technique that isn't backed by a real correlation edge, by setting that technique mapping's `grounded` field to `False`), and written onto the `IOCLookup` row as `final_verdict`, `risk_score`, `confidence_score`, and the full `final_assessment` JSON.

8. **Evidence ledger build.** `build_evidence()` (`app/evidence/builder.py`) deterministically converts the provider results, AI summaries, and correlation edges into `EvidenceItem` rows. This step is explicitly **not AI-generated** (per the module's own docstring) — it exists so that later AI-driven explanations elsewhere in the product can cite real, checkable evidence records instead of re-summarizing from memory.

9. **Final SSE events.** The stream emits a `final_assessment` event, then a `done` event, closing the connection.

[FIGURE: tech-02-dataflow-diagram-1.png | Diagram: The 9-Step Lookup Pipeline]

## 🗄️ Where Data Actually Lives

The Docker Compose stack provisions four datastores — Postgres, Redis, Neo4j, and OpenSearch. Reading the pipeline above, it would be easy to assume all four are in play. They are not.

> [!IMPORTANT]
> This distinction matters enough that it is called out separately: **only Postgres and Redis have any application code that actually reads from or writes to them.** Neo4j and OpenSearch are running containers with nothing in the backend that talks to them.

| Datastore | Provisioned in `docker-compose.yml`? | Application code that uses it? | What it actually holds today |
|---|---|---|---|
| **Postgres** | Yes (`postgres:16-alpine`) | Yes | Everything: `IOCLookup` rows, `ProviderResultRecord`s, `AISummaryRecord`s (per-provider and final), `CorrelationEdgeRecord`s, `EvidenceItem`s, plus users, cases, and analyst baskets |
| **Redis** | Yes (`redis:7-alpine`) | Yes | Provider-result cache (keyed `provider_cache:{provider_id}:{ioc_type}:{sha256(value)}`, default TTL 3600s), the lookup-creation rate limiter, and the Celery broker/result-backend queues |
| **Neo4j** | Yes (`neo4j:5-community` + APOC plugin) | **No** | Nothing. Config fields only (`neo4j_uri`, `neo4j_user`, `neo4j_password`) |
| **OpenSearch** | Yes (`opensearchproject/opensearch:2.17.0`) | **No** | Nothing. A config field only (`opensearch_url`) |

### Postgres is the correlation graph today

Step 6 of the pipeline above talks about a "correlation graph" of nodes and edges between IOCs. It is tempting to assume that graph lives in Neo4j, since Neo4j is a graph database and is sitting right there in the stack. It does not. **The correlation graph is a set of rows in Postgres's `correlation_edges` table, queried relationally — full stop.** `CorrelationEdgeRecord`'s own docstring (`models/lookup.py`) and the correlation engine's module docstring (`correlation/engine.py`) both describe edges as being "mirrored into Neo4j," but that describes an intended future design, not current behavior. A full-repo search of `backend/app` for `neo4j`, `Neo4j`, or `GraphDatabase` (outside the Python virtual environment) turns up zero driver instantiations, zero Cypher queries, and zero read or write calls anywhere in the application. The only things Neo4j-related in the codebase are the three unused config fields and those two docstrings.

### There is no search functionality

The same is true of OpenSearch, with even less ambiguity: there are no docstrings suggesting an intended integration, no indexing pipeline, and a full-repo search finds zero OpenSearch client, index, or search code anywhere in `backend/app`. The container runs; nothing in the product talks to it. Any full-text search a user might expect (e.g., searching historical lookups by free text) is not implemented against OpenSearch or anywhere else.

### Practical takeaway

> [!TIP]
> For a judge or engineer evaluating this build: treat Neo4j and OpenSearch as **provisioned infrastructure for a future phase**, not as working features. If asked "does this platform have a graph database backing its correlation view?" or "does it support full-text search?", the accurate answer is no — both containers exist and are healthy, but the entire correlation and evidence pipeline described in the nine steps above runs, end to end, on Postgres and Redis alone.
