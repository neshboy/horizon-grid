# Database Architecture

HORIZON GRID's `docker-compose.yml` provisions four datastore containers: `postgres` (postgres:16-alpine), `redis` (redis:7-alpine), `neo4j` (neo4j:5-community with the APOC plugin), and `opensearch` (opensearchproject/opensearch:2.17.0). This section describes what each one actually does in the running system, based on direct inspection of the backend code rather than the docker-compose comments or model docstrings that describe the *intended* design. Two of the four -- Neo4j and OpenSearch -- are running containers with no backend code that reads from or writes to them; that gap is documented plainly below rather than glossed over.

An **IOC** (Indicator of Compromise) is the value a user submits for lookup -- an IP address, domain, file hash, URL, CVE ID, etc. A **provider** is a connector to an external threat-intelligence source (VirusTotal, AbuseIPDB, and so on) that the platform queries for a given IOC.

## PostgreSQL: the system of record

PostgreSQL is the only datastore the application actually writes to during a lookup. Every table below is defined under `backend/app/models/`:

| Table | Holds |
|---|---|
| `users` | Account records: email, hashed password, full name, role (`admin` / `analyst` / `viewer`), active flag. |
| `ioc_lookups` | One row per lookup: the submitted IOC value and type, a status enum (`pending`/`running`/`completed`/`failed`), and the final AI output -- `final_verdict`, `risk_score`, `confidence_score`, and the full `final_assessment` as JSONB. |
| `provider_results` | One row per provider call per lookup: that provider's raw response as JSONB, plus its status and latency. |
| `ai_summaries` | AI-generated summaries as JSONB. A nullable `provider_id` distinguishes a per-provider summary from the single final consolidated assessment (null `provider_id` marks the latter). |
| `correlation_edges` | The relationship graph produced by the correlation engine: source/target type and value, relationship type, a confidence score, and provenance (which provider(s) contributed the edge). |
| `evidence_items` | The deterministic, non-AI-generated evidence ledger: an evidence-type enum (9 values), a source label, a claim, an interpretation, a confidence score (0-100), and the underlying raw data as JSONB. |
| `basket_items` | Per-analyst scratch lists of IOCs, unique per owner and IOC value. |
| `cases`, `case_iocs`, `case_notes`, `case_reports` | A lightweight case-management workflow: cases with status/severity enums, the IOCs attached to a case, and analyst notes. `case_reports` exists as a table, but report generation itself is not implemented -- the field is present and permanently empty rather than populated by any code path. |

Two things worth calling out because they matter for how the rest of this appendix should be read:

- **The correlation graph lives in Postgres.** `correlation_edges` is a plain relational table, populated by the correlation engine after every provider has returned, and streamed to the UI as part of the lookup. There is no separate graph database behind it today -- see the Neo4j section below.
- **The evidence ledger is deliberately not AI-generated.** `evidence_items` rows are built by a deterministic conversion step so that later AI-written explanations have real, checkable records to cite against, rather than citing their own prior output.

Schema changes are managed with **Alembic** (`backend/alembic/`), SQLAlchemy's migration tool. The application itself uses SQLAlchemy 2.0 in async mode over `asyncpg`.

## Neo4j: provisioned, not integrated

Neo4j (`neo4j:5-community`, with the APOC plugin) runs as a container in `docker-compose.yml`, and the backend config (`app/core/config.py`) has `neo4j_uri`, `neo4j_user`, and `neo4j_password` settings for it. Some code comments describe an intended design where correlation edges get "mirrored into Neo4j" -- this appears in the `CorrelationEdgeRecord` model docstring and in the correlation engine's module docstring.

That design was never built. A full search of the backend application code for `neo4j`, `Neo4j`, or `GraphDatabase` (excluding the Python virtual environment) turns up zero driver instantiation, zero Cypher queries, and zero read or write calls anywhere in the application. Neo4j is not used for anything today. **The correlation graph described above is, in its entirety, the `correlation_edges` table in PostgreSQL.** Anyone evaluating this platform should treat Neo4j as reserved-but-idle infrastructure, not as an active graph store.

## OpenSearch: provisioned, not integrated

The same pattern holds for OpenSearch (`opensearchproject/opensearch:2.17.0`, running with `DISABLE_SECURITY_PLUGIN: "true"`). The backend config has an `opensearch_url` setting, and the container runs as part of the stack, but a full search of the backend application code found zero OpenSearch client code, zero index definitions, and zero search calls. No indexing pipeline exists, and no user-facing search feature is backed by it. OpenSearch should be described as provisioned infrastructure only -- not as an active search index.

Neo4j and OpenSearch represent the most significant gap between the design implied by the docker-compose file and docstrings, and what the running system actually does. Both are real containers consuming real resources; neither currently does any work for the platform.

## Redis: three real uses

Unlike Neo4j and OpenSearch, Redis (`redis:7-alpine`) is genuinely load-bearing, in exactly three ways -- all confirmed against `app/core/cache.py`, `docker-compose.yml`, and `app/core/config.py`:

1. **Provider-result cache.** Each provider call is cached under a key of the form `provider_cache:{provider_id}:{ioc_type}:{sha256(value)}`, with a TTL controlled by `provider_cache_ttl_seconds` (default 3600 seconds / 1 hour). A repeat lookup for the same IOC within the TTL window skips the live provider call.
2. **Rate limiter.** A fixed-window rate limiter, implemented in the same `app/core/cache.py` module as the cache, guards the lookup-creation endpoint: by default, 10 calls per 60 seconds per user (both values configurable).
3. **Celery broker and result backend.** The `celery_worker`/`celery_beat` services use Redis as both the message broker and the result store for background jobs.

Redis is used across separate **logical database indexes** on the same Redis instance, rather than one shared keyspace:

| Redis DB index | Purpose |
|---|---|
| `/0` | Cache (provider-result cache and rate-limiter counters, both via `app/core/cache.py`) |
| `/1` | Celery broker (`redis://redis:6379/1`) |
| `/2` | Celery result backend (`redis://redis:6379/2`) |

This separation means a `FLUSHDB` or eviction event against the cache database, for example, cannot collide with in-flight Celery task state, and vice versa -- they are isolated by index even though they share one Redis process. No other use of Redis was found in the codebase.

It's worth noting that the synchronous SSE lookup pipeline (`POST /api/v1/lookup/stream`) does **not** go through Celery at all -- it runs providers directly and streams results back over the same request. The only scheduled Celery job in the system is an hourly OSINT re-crawl (`run_osint_crawl`) for IOCs looked up in the last 24 hours; Celery's broker/result-backend role is scoped to that background job, not to the interactive lookup path.

## Component overview

[FIGURE: tech-05-database-architecture-diagram-1.png | Diagram: Component overview]

## Summary

Postgres is the single source of truth for every entity in the platform, including the correlation graph. Redis does three concrete jobs -- provider-result caching, rate limiting, and Celery transport -- cleanly separated by logical database index on one instance. Neo4j and OpenSearch run as containers and appear in configuration, but as of this writing carry no application code that reads or writes to them; they should be read as forward-provisioned infrastructure, not as active components of the current architecture.
