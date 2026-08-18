# Data Model

This document describes the persisted schema for HORIZON GRID: every SQLAlchemy
model in `backend/app/models/`, the Alembic migration history that created them, and the
relationships between tables. Postgres (via the async `asyncpg` driver) is the single system of
record for all tables below.

Source of truth: `backend/app/models/*.py` and `backend/alembic/versions/*.py`.

See also: [ARCHITECTURE.md](ARCHITECTURE.md) for how these tables fit into the overall system, and
[CONFIGURATION.md](CONFIGURATION.md) for `DATABASE_URL` and other environment settings.

---

## Conventions

- **Primary keys**: every table inherits `UUIDPrimaryKeyMixin` (`backend/app/models/base.py:14-17`)
  — a `UUID` column named `id`, `primary_key=True`, Python-side default `uuid.uuid4()`.
- **Timestamps**: every table inherits `TimestampMixin` (`base.py:20-26`) — `created_at` and
  `updated_at`, both `DateTime(timezone=True)` with `server_default=func.now()`; `updated_at` also
  sets `onupdate=func.now()`.
- **Enums**: persisted as Postgres `ENUM` types via SQLAlchemy's `Enum()`, backed by Python
  `str, enum.Enum` classes.
- **JSON columns**: use Postgres `JSONB` (`sqlalchemy.dialects.postgresql.JSONB`), not generic JSON.
- **Deletes**: there is no soft-delete / `is_deleted` column anywhere in the schema. Deletion is
  hard-delete, propagated through SQLAlchemy relationship `cascade="all, delete-orphan"` (e.g.
  deleting an `IOCLookup` cascades to its `provider_results`, `ai_summaries`, `correlation_edges`,
  and `evidence_items`; deleting a `Case` cascades to its `iocs`, `notes`, and `reports`).

---

## Entity-Relationship Diagram

```mermaid
erDiagram
    USERS ||--o{ IOC_LOOKUPS : "requested_by"
    USERS ||--o{ CASES : "analyst_id"
    USERS ||--o{ CASE_IOCS : "added_by"
    USERS ||--o{ CASE_NOTES : "author_id"
    USERS ||--o{ CASE_REPORTS : "generated_by"
    USERS ||--o{ BASKET_ITEMS : "owner_id"

    IOC_LOOKUPS ||--o{ PROVIDER_RESULTS : "lookup_id"
    IOC_LOOKUPS ||--o{ AI_SUMMARIES : "lookup_id"
    IOC_LOOKUPS ||--o{ CORRELATION_EDGES : "lookup_id"
    IOC_LOOKUPS ||--o{ EVIDENCE_ITEMS : "lookup_id"
    IOC_LOOKUPS ||--o{ CASE_IOCS : "lookup_id (nullable)"
    IOC_LOOKUPS ||--o{ BASKET_ITEMS : "latest_lookup_id (nullable)"

    CASES ||--o{ CASE_IOCS : "case_id"
    CASES ||--o{ CASE_NOTES : "case_id"
    CASES ||--o{ CASE_REPORTS : "case_id"

    USERS {
        uuid id PK
        string email
        string hashed_password
        string full_name
        enum role
        bool is_active
    }
    IOC_LOOKUPS {
        uuid id PK
        string ioc_value
        string ioc_type
        enum status
        uuid requested_by FK
        enum final_verdict
        float risk_score
        float confidence_score
        jsonb final_assessment
    }
    PROVIDER_RESULTS {
        uuid id PK
        uuid lookup_id FK
        string provider_id
        string provider_name
        string category
        string status
        jsonb data
        string source_url
        text error_message
        int latency_ms
    }
    AI_SUMMARIES {
        uuid id PK
        uuid lookup_id FK
        string provider_id
        jsonb summary
    }
    CORRELATION_EDGES {
        uuid id PK
        uuid lookup_id FK
        string source_type
        string source_value
        string target_type
        string target_value
        string relationship_type
        float confidence
        string provenance
    }
    EVIDENCE_ITEMS {
        uuid id PK
        uuid lookup_id FK
        enum evidence_type
        string source_label
        string provider_id
        text claim
        text interpretation
        float confidence
        string related_ioc_type
        string related_ioc_value
        string source_url
        string observed_at
        jsonb raw_data
    }
    BASKET_ITEMS {
        uuid id PK
        uuid owner_id FK
        string ioc_value
        string ioc_type
        uuid latest_lookup_id FK
        string note
    }
    CASES {
        uuid id PK
        string title
        text description
        uuid analyst_id FK
        enum severity
        enum status
        string_array tags
    }
    CASE_IOCS {
        uuid id PK
        uuid case_id FK
        string ioc_value
        string ioc_type
        uuid lookup_id FK
        uuid added_by FK
    }
    CASE_NOTES {
        uuid id PK
        uuid case_id FK
        uuid author_id FK
        text body
        string anchor_type
        string anchor_ref
    }
    CASE_REPORTS {
        uuid id PK
        uuid case_id FK
        string report_type
        string title
        text content_markdown
        uuid generated_by FK
        jsonb context
    }
```

Notes on the diagram:

- `IOC_LOOKUPS.requested_by`, `CASE_IOCS.lookup_id`, and `BASKET_ITEMS.latest_lookup_id` are all
  **nullable** foreign keys — an unauthenticated/system lookup can have no `requested_by`, a case
  IOC can be added without an existing lookup, and a basket item can exist before any lookup has
  run for it.
- `CORRELATION_EDGES` rows reference IOC *values* (`source_value`/`target_value`), not foreign
  keys into `ioc_lookups` — an edge's endpoints may or may not correspond to an IOC that itself has
  a lookup row.

---

## Tables

### `users`

Defined in `backend/app/models/user.py`.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK, default `uuid.uuid4()` |
| `email` | `String(255)` | unique, indexed, not null |
| `hashed_password` | `String(255)` | not null |
| `full_name` | `String(255)` | not null, default `''` |
| `role` | `Enum(Role)` | not null, default `analyst` |
| `is_active` | `Boolean` | not null, default `true` |
| `last_login_at` | `DateTime(timezone=True)` | nullable — set by `app/core/users.py`'s `record_login_success()` on every successful `/auth/login` |
| `token_version` | `Integer` | not null, default `0` — bumped by an admin-initiated password reset to immediately invalidate every access/refresh token already issued to this user (see [SECURITY.md](SECURITY.md) §1) |
| `created_at` | `DateTime(timezone=True)` | server default `now()` |
| `updated_at` | `DateTime(timezone=True)` | server default `now()`, updates `now()` on change |

Migrations: `7a1c2f9d4e6b_add_user_last_login_at.py` and `3b9e7a2c1d4f_add_user_token_version.py`,
both nullable/defaulted so no backfill was needed and no existing row or session was disrupted.

User-management actions (create, edit, enable/disable, password reset) and every login/failed-login
attempt are recorded into `config_audit_log` (below) via `app/core/audit.py` — the same
append-only table provider/AI configuration changes already used, not a separate table.

**`Role` enum** (`user.py:11-14`): `admin`, `analyst`, `viewer`.

**Permission matrix** — `ROLE_PERMISSIONS` (`user.py:31-44`), consumed by the `require_role`
dependency in `app/auth/rbac.py`:

| Permission | admin | analyst | viewer |
|---|---|---|---|
| `lookup:create` | yes | yes | |
| `lookup:read` | yes | yes | yes |
| `lookup:export` | yes | yes | |
| `provider:manage` | yes | | |
| `user:manage` | yes | | |
| `audit:read` | yes | | |
| `evidence:read` | yes | yes | yes |
| `analysis:generate` | yes | yes | |
| `hunting:generate` | yes | yes | |
| `copilot:query` | yes | yes | |
| `basket:manage` | yes | yes | |
| `case:create` | yes | yes | |
| `case:read` | yes | yes | yes |
| `case:write` | yes | yes | |
| `case:close` | yes | yes | |

---

### `config_audit_log`

Defined in `backend/app/models/runtime_config.py`. One append-only row per configuration or
account-management action — despite the provider-config-scoped name (it predates user
management), it's the single shared audit sink for both: provider/AI configuration changes
(`app/core/runtime_config.py`) and every user-management/login event (`app/core/users.py`,
`app/api/routes/auth.py`), written through the same `app/core/audit.py` helper. Never a
credential, password, or token value — `detail` is a human-readable description string only.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK, default `uuid.uuid4()` |
| `timestamp` | `DateTime(timezone=True)` | not null |
| `actor_user_id` | `UUID` | FK -> `users.id`, nullable (null for system-initiated actions, e.g. startup config seeding) |
| `actor_email` | `String(255)` | nullable, denormalized so the log stays readable if the actor account is later disabled |
| `action` | `String(100)` | not null, e.g. `user.create`, `user.disable`, `auth.login`, `auth.login_failed`, `ioc_provider.configure` |
| `detail` | `String(1000)` | not null, default `''` — human-readable only |

Read via `GET /api/v1/runtime/audit-log` (`audit:read` permission), rendered in both the
Providers page's Audit Log tab and the Administration console's Audit Log tab.

---

### `ioc_lookups`

Defined in `backend/app/models/lookup.py:37-66`. The central record of one IOC investigation.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `ioc_value` | `String(2048)` | not null, indexed |
| `ioc_type` | `String(64)` | not null, indexed |
| `status` | `Enum(LookupStatus)` | not null, default `pending` |
| `requested_by` | `UUID` | FK -> `users.id`, nullable |
| `final_verdict` | `Enum(Verdict)` | nullable |
| `risk_score` | `Float` | nullable |
| `confidence_score` | `Float` | nullable |
| `final_assessment` | `JSONB` | nullable — shape defined in `app/ai/schemas.py` |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

**`LookupStatus` enum** (`lookup.py:15-19`): `pending`, `running`, `completed`, `failed`.

**`Verdict` enum** (`lookup.py:22-34`): `highly_malicious`, `malicious`, `suspicious`, `unknown`,
`likely_benign`, `benign`, `scanner`, `tor_exit_node`, `vpn`, `cdn`, `cloud_infrastructure`,
`dormant_infrastructure`.

Relationships (all `cascade="all, delete-orphan"`, deleting a lookup deletes these children):
`provider_results`, `ai_summaries`, `correlation_edges`, `evidence_items`.

---

### `provider_results`

Defined in `backend/app/models/lookup.py:69-84`. One row per provider connector call for a lookup.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `lookup_id` | `UUID` | FK -> `ioc_lookups.id`, not null, indexed |
| `provider_id` | `String(128)` | not null, indexed |
| `provider_name` | `String(255)` | not null |
| `category` | `String(64)` | not null |
| `status` | `String(32)` | not null |
| `data` | `JSONB` | default `{}` |
| `source_url` | `String(2048)` | nullable |
| `error_message` | `Text` | nullable |
| `latency_ms` | `Integer` | nullable |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

See [PROVIDERS.md](PROVIDERS.md) for the provider connectors that populate this table.

---

### `ai_summaries`

Defined in `backend/app/models/lookup.py:87-97`. Holds both per-provider AI summaries and the
single consolidated assessment for a lookup.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `lookup_id` | `UUID` | FK -> `ioc_lookups.id`, not null, indexed |
| `provider_id` | `String(128)` | nullable, indexed — **null means this row is the final consolidated assessment**, not a per-provider summary |
| `summary` | `JSONB` | not null |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

See [AI_ENGINE.md](AI_ENGINE.md) for how these rows are generated.

---

### `correlation_edges`

Defined in `backend/app/models/lookup.py:100-118`. One row per graph edge discovered by the
correlation engine for a lookup.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `lookup_id` | `UUID` | FK -> `ioc_lookups.id`, not null, indexed |
| `source_type` | `String(64)` | not null |
| `source_value` | `String(2048)` | not null |
| `target_type` | `String(64)` | not null |
| `target_value` | `String(2048)` | not null |
| `relationship_type` | `String(64)` | not null |
| `confidence` | `Float` | default `1.0` |
| `provenance` | `String(128)` | not null — WHICH provider/tool asserted this edge |
| `provenance_category` | `String(32)` | not null, default `'threat_intel'` — WHAT KIND of source (see `app/core/provenance.py`); `'security_assessment'` for Security Assessment Toolkit-sourced edges |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

> **Note on Neo4j**: the model's docstring (`lookup.py:101-103`) says these edges are "mirrored
> into Neo4j for graph traversal but kept here too so a lookup's graph can be rebuilt from
> Postgres alone if Neo4j is unavailable." In the current codebase there is **no Neo4j driver
> usage anywhere** — **NOT IMPLEMENTED**. `correlation_edges` in Postgres is, in practice, the
> *only* store for this data; no code path writes to Neo4j. The `neo4j_uri` / `neo4j_user` /
> `neo4j_password` settings exist in configuration but are not currently exercised for graph
> writes.

---

### `evidence_items`

Defined in `backend/app/models/evidence.py:31-56`. The evidence ledger: deterministic, reproducible
facts that AI-generated text can cite by `evidence_id`, per the module docstring — rows are built
by `app/evidence/builder.py` from provider summaries and correlation edges and are **never written
directly by an AI call**.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `lookup_id` | `UUID` | FK -> `ioc_lookups.id`, not null, indexed |
| `evidence_type` | `Enum(EvidenceType)` | not null, indexed |
| `source_label` | `String(255)` | not null — human-readable origin, e.g. `"VirusTotal"`, `"Correlation Engine"` |
| `provider_id` | `String(128)` | nullable, indexed — machine-readable provider id when source is a connector; null when source is the correlation engine |
| `claim` | `Text` | not null |
| `interpretation` | `Text` | nullable |
| `confidence` | `Float` | not null — 0-100 scale, matches `RiskAssessment` |
| `related_ioc_type` | `String(64)` | nullable |
| `related_ioc_value` | `String(2048)` | nullable |
| `source_url` | `String(2048)` | nullable |
| `observed_at` | `String(64)` | nullable — provider-reported timestamp, kept as raw string (mixed formats across providers) |
| `raw_data` | `JSONB` | nullable |
| `provenance_category` | `String(32)` | not null, default `'threat_intel'` — same axis as `correlation_edges.provenance_category` above |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

**`EvidenceType` enum** (`evidence.py:19-28`): `detection`, `reputation`, `relationship`,
`malware_association`, `threat_actor_association`, `campaign_association`, `mitre_technique`,
`infrastructure`, `other`.

---

### `security_assessment_runs`

Defined in `backend/app/models/security_assessment.py`. One row per authorized Security
Assessment Toolkit invocation (see [SECURITY_ASSESSMENT_TOOLKIT.md](SECURITY_ASSESSMENT_TOOLKIT.md)).

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `lookup_id` | `UUID` | FK -> `ioc_lookups.id`, not null, indexed |
| `requested_by` | `UUID` | FK -> `users.id`, nullable |
| `target` | `String(2048)` | not null — the value the caller retyped to confirm scope |
| `tool_ids` | `JSONB` | not null — list of tool ids run (`nmap`, `dns`, `tls`, `http_headers`, `hash_analysis`) |
| `profile` | `String(64)` | not null |
| `status` | `Enum(SecurityAssessmentRunStatus)` | not null, default `pending` (`pending`/`running`/`completed`/`failed`) |
| `authorization_confirmed_at` | `DateTime(timezone=True)` | not null |
| `started_at` / `completed_at` | `DateTime(timezone=True)` | nullable |
| `error_message` | `Text` | nullable |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

### `security_assessment_findings`

One row per discrete finding produced by a run.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `run_id` | `UUID` | FK -> `security_assessment_runs.id`, not null, indexed |
| `tool_id` | `String(64)` | not null, indexed |
| `finding_type` | `String(64)` | not null — e.g. `open_port`, `dns_record`, `tls_issue`, `http_header_issue`, `hash_info` |
| `severity` | `Enum(Severity)` | not null, indexed (`info`/`low`/`medium`/`high`/`critical`) |
| `title` | `String(500)` | not null |
| `description` | `Text` | not null |
| `target_detail` | `String(255)` | nullable — e.g. `"tcp/22"` |
| `cve_ids` | `JSONB` | not null, default `[]` |
| `evidence` | `JSONB` | not null, default `{}` — the concrete data the severity was derived from |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

---

### `basket_items`

Defined in `backend/app/models/basket.py:16-29`. Per-analyst scratch space for collecting IOCs
before comparing, bulk-investigating, or promoting them into a Case. By explicit design (per the
module docstring) this table has **no status/workflow field** — "that's what Case is for." This is
an intentional omission, not a gap.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `owner_id` | `UUID` | FK -> `users.id`, not null, indexed |
| `ioc_value` | `String(2048)` | not null |
| `ioc_type` | `String(64)` | not null |
| `latest_lookup_id` | `UUID` | FK -> `ioc_lookups.id`, nullable — most recent completed lookup for this IOC, lets basket actions reuse existing intelligence instead of re-running providers |
| `note` | `String(1024)` | nullable |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

Table constraint: `UniqueConstraint("owner_id", "ioc_value", name="uq_basket_owner_ioc")` — an
analyst can only have one basket entry per IOC value.

---

### `cases`

Defined in `backend/app/models/case.py:32-44`. Groups IOCs, notes, and reports under one
investigation with a status workflow.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `title` | `String(255)` | not null |
| `description` | `Text` | nullable |
| `analyst_id` | `UUID` | FK -> `users.id`, not null, indexed |
| `severity` | `Enum(CaseSeverity)` | not null, default `medium` |
| `status` | `Enum(CaseStatus)` | not null, default `open`, indexed |
| `tags` | `ARRAY(String(64))` | default `[]` |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

**`CaseStatus` enum** (`case.py:16-22`): `open`, `investigating`, `contained`, `resolved`,
`false_positive`, `closed`.

**`CaseSeverity` enum** (`case.py:25-29`): `low`, `medium`, `high`, `critical`.

Relationships (all `cascade="all, delete-orphan"`): `iocs` -> `CaseIOC`, `notes` -> `CaseNote`,
`reports` -> `CaseReport`.

---

### `case_iocs`

Defined in `backend/app/models/case.py:47-58`. Join of a Case to an IOC, optionally tied to a
specific lookup.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `case_id` | `UUID` | FK -> `cases.id`, not null, indexed |
| `ioc_value` | `String(2048)` | not null |
| `ioc_type` | `String(64)` | not null |
| `lookup_id` | `UUID` | FK -> `ioc_lookups.id`, nullable |
| `added_by` | `UUID` | FK -> `users.id`, not null (not indexed) |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

---

### `case_notes`

Defined in `backend/app/models/case.py:61-75`. Free-text analyst notes, optionally anchored to a
target within the case.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `case_id` | `UUID` | FK -> `cases.id`, not null, indexed |
| `author_id` | `UUID` | FK -> `users.id`, not null |
| `body` | `Text` | not null |
| `anchor_type` | `String(64)` | nullable — one of `ioc` \| `evidence` \| `graph_node` \| `timeline_event` \| `provider_result` (by convention, not enforced) |
| `anchor_ref` | `String(2048)` | nullable |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

> **Note**: `anchor_type`/`anchor_ref` are deliberately loose strings, not foreign keys — per the
> model docstring, a note can point at a graph node id or timeline event id that has no dedicated
> table. There is **no database-level referential integrity** validating that an anchor points at
> a real target; any such validation would have to happen in application code.

---

### `case_reports`

Defined in `backend/app/models/case.py:78-88`. AI- or analyst-generated report documents attached
to a case.

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `case_id` | `UUID` | FK -> `cases.id`, not null, indexed |
| `report_type` | `String(64)` | not null — matches a `ReportType` literal in `app/ai/schemas.py` |
| `title` | `String(255)` | not null |
| `content_markdown` | `Text` | not null |
| `generated_by` | `UUID` | FK -> `users.id`, not null |
| `context` | `JSONB` | nullable |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | mixin defaults |

---

## Migration history

Migrations live in `backend/alembic/versions/`. There are exactly two revisions in the history
today:

| Order | Revision | File | Down-revision | Creates |
|---|---|---|---|---|
| 1 | `660d2aa3bc20` | `660d2aa3bc20_initial_schema.py` | `None` | `users`, `ioc_lookups`, `ai_summaries`, `correlation_edges`, `provider_results` (+ their indexes) |
| 2 (HEAD) | `a6d3ad2bb63c` | `a6d3ad2bb63c_add_evidence_basket_and_case_management_.py` | `660d2aa3bc20` | `cases`, `basket_items`, `case_iocs`, `case_notes`, `case_reports`, `evidence_items` (+ their indexes/constraints) |

Applying migrations:

```bash
cd backend
alembic upgrade head
```

The engine URL is resolved at runtime from `Settings.database_url`
(`backend/app/core/config.py:29`, default `postgresql+asyncpg://ioc:ioc@postgres:5432/ioc_intel`),
which Alembic's `env.py` reads via `get_settings().database_url` — so a `.env` file or
`DATABASE_URL` environment variable overrides it for both the app and migrations. See
[CONFIGURATION.md](CONFIGURATION.md).

`backend/app/models/__init__.py` imports every model module so `Base.metadata` is fully populated
for `alembic revision --autogenerate`.

---

## Session / engine wiring

- `backend/app/core/db.py:8` — `create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)`.
- `backend/app/core/db.py:9` — `async_sessionmaker(bind=_engine, expire_on_commit=False, class_=AsyncSession)`.
- `get_db()` (`db.py:12-14`) is the FastAPI dependency that yields a request-scoped session.
- `new_session()` (`db.py:17-22`) returns a session directly for use outside FastAPI request scope
  (Celery tasks, scripts) — caller owns its lifecycle, used as `async with new_session() as db:`.

---

## Known gaps / not implemented

- **NOT IMPLEMENTED**: Neo4j graph mirroring. `correlation_edges` is documented in code as being
  "mirrored into Neo4j," but no Neo4j driver call exists anywhere in the codebase. Postgres is the
  sole store for graph edges today.
- **Not implemented, by design**: soft deletes. No model has an `is_deleted`/`deleted_at` column;
  all deletion is a hard delete via ORM cascade.
- **Not implemented, by design**: `basket_items` workflow/status fields — intentionally omitted
  since `cases` covers workflow tracking.
- **Not enforced at the database level**: `case_notes.anchor_type` / `anchor_ref` reference targets
  (IOC, evidence, graph node, timeline event, provider result) by convention only; there is no FK
  or check constraint tying them to a real row.

