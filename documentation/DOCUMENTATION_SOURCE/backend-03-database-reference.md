# Database Reference

This chapter is the exhaustive column-level reference for the platform's PostgreSQL schema: every table, every column with its type/nullability/default, every foreign key, and every native enum. It is a companion to the narrative "Database Architecture" chapter elsewhere in this documentation set, which explains *why* Postgres is the sole system of record and what Redis/Neo4j/OpenSearch do and do not do; this chapter only documents *what the schema is*, table by table, as defined under `backend/app/models/` and applied by the twelve Alembic migrations in `backend/alembic/versions/`.

The schema was verified by reading every model file and cross-checking it column-by-column against the applied migration DDL. The migration history is a single linear chain with one head — `660d2aa3bc20` → `a6d3ad2bb63c` → `0f2dc283823e` → `2652d888a33f` → `7a1c2f9d4e6b` → `3b9e7a2c1d4f` → `5c8e1f3a9b2d` → `6d2f4b8e1a7c` → `6716ed40b9f2` → `8f4a1c2d9e6b` → `9273d7b21c79` → `9123b075e962` — and no drift was found between the ORM models and the DDL they generated: every column, enum, foreign key, and index in the migrations matches the current model files exactly. There are **20 tables** in total, six of which (`security_assessment_runs`, `security_assessment_findings`, `pentest_assessments`, `pentest_targets`, `pentest_findings`, `pentest_exploit_attempts`) back the Security Assessment Toolkit and the standalone Pentest Suite and are documented in their own sections below, alongside the original 14.

## 📋 Table of contents

- [Conventions Used Throughout This Schema](#-conventions-used-throughout-this-schema)
- [Entity-Relationship Overview](#-entity-relationship-overview)
- [Authentication and Identity](#-authentication-and-identity)
- [Investigations and AI Output](#-investigations-and-ai-output)
- [The Evidence Ledger](#-the-evidence-ledger)
- [Security Assessment Toolkit Tables](#️-security-assessment-toolkit-tables)
- [Case Management and the Analyst Workspace](#-case-management-and-the-analyst-workspace)
- [Runtime Configuration and Audit](#-runtime-configuration-and-audit)
- [Pentest Suite Tables](#️-pentest-suite-tables)
- [Enum Inventory](#-enum-inventory)
- [Migration Provenance](#-migration-provenance)

## 📐 Conventions Used Throughout This Schema

Two shared mixins (`backend/app/models/base.py:10-27`) are applied to almost every table:

- **`UUIDPrimaryKeyMixin`** (`base.py:14-17`) — a single `id` column, type `UUID`, primary key. The value is generated in Python (`uuid.uuid4()`) by the ORM at insert time, not by a Postgres `DEFAULT` — there is no database-side UUID generation function involved.
- **`TimestampMixin`** (`base.py:20-26`) — `created_at` and `updated_at`, both `TIMESTAMPTZ NOT NULL`, both with a genuine database-level `server_default=now()`. `updated_at` additionally has an ORM-side `onupdate=func.now()`, which means the refresh on update is applied by SQLAlchemy in the application layer, not by a Postgres trigger — a row updated by raw SQL outside the ORM would not have `updated_at` bumped automatically.

Every table below carries both mixins **except `config_audit_log`**, which uses only `UUIDPrimaryKeyMixin` and defines its own explicit `timestamp` column instead (with no server default — the application must set it).

> [!WARNING]
> Two structural facts apply platform-wide and are easy to miss when reading the model files in isolation:
>
> - **No foreign key in any migration specifies `ondelete=`.** At the database level, every FK below is effectively `ON DELETE NO ACTION` (RESTRICT-like behavior). Deleting a row that is still referenced by a child table will be rejected by Postgres unless the application has first deleted or reassigned the children.
> - **`cascade="all, delete-orphan"` on `IOCLookup`, `Case`, `SecurityAssessmentRun`, `PentestAssessment`, and `PentestTarget` relationships is ORM-only.** SQLAlchemy will delete child rows (provider results, evidence, case notes, pentest findings, etc.) when the parent object is deleted *through the ORM session*, but this cascade is not expressed as a database constraint and has no effect on deletes issued outside the ORM (raw SQL, a different application, a database console).

Python-side `default=` values (as opposed to `server_default=`) are likewise applied by the ORM on `INSERT`, not baked into the column's DDL `DEFAULT` — they are noted as "ORM `<value>`" in the tables below to keep that distinction visible.

## 🔗 Entity-Relationship Overview

No diagram-generation tool was used for this chapter; the description below is a deliberately textual substitute for an ER diagram, built only from the foreign keys and constraints actually present in the models and migrations (no field is inferred or assumed).

The schema has one hub table per functional domain, plus one standalone administrative domain and one standalone assessment domain:

- **`users` is the root identity table.** It has no foreign keys of its own and is referenced by twelve other tables as the actor, owner, or author of some action: `ioc_lookups.requested_by`, `final_assessment_records.requested_by`, `basket_items.owner_id`, `cases.analyst_id`, `case_iocs.added_by`, `case_notes.author_id`, `case_reports.generated_by`, `provider_runtime_configs.updated_by`, `config_audit_log.actor_user_id`, `security_assessment_runs.requested_by`, `pentest_assessments.created_by`, and `pentest_exploit_attempts.requested_by`.
- **`ioc_lookups` is the hub of the investigation domain.** One lookup fans out to child rows in six other tables, all via a `lookup_id` foreign key back to `ioc_lookups.id`: `provider_results` (raw per-provider responses), `ai_summaries` (AI-generated per-provider and consolidated summaries), `correlation_edges` (the relationship graph for that lookup), `evidence_items` (the deterministic evidence ledger), `final_assessment_records` (the full history of AI final-assessment runs against that lookup, not just the primary one), and `security_assessment_runs` (the per-lookup Security Assessment Toolkit's own active-scan runs, each owning its own child `security_assessment_findings`). Two further tables hold a nullable, non-owning reference *into* this hub rather than owning rows within it: `basket_items.latest_lookup_id` and `case_iocs.lookup_id` — a basket item or case IOC can exist and be queried whether or not a completed lookup has ever been linked to it.
- **`cases` is the hub of the case-management domain.** One case owns rows in three child tables via a `case_id` foreign key: `case_iocs`, `case_notes`, and `case_reports`. `case_iocs` additionally, and optionally, points back into the investigation domain via its nullable `lookup_id`.
- **`basket_items` is a leaf table**, owned by exactly one user (`owner_id`) and optionally pointing at one lookup (`latest_lookup_id`); it participates in no other relationship.
- **`provider_runtime_configs` and `config_audit_log` form a self-contained administrative domain.** Both reference `users` (as `updated_by` / `actor_user_id` respectively, both nullable) but are not referenced by, and do not reference, any table in the investigation or case domains. This is the storage layer behind the platform's runtime (no-restart) provider/AI credential configuration and its audit trail.
- **`pentest_assessments` is the hub of a fourth, entirely standalone domain: the Pentest Suite.** Distinct from the per-lookup Security Assessment Toolkit above, a pentest assessment declares its own scope and owns `pentest_targets`, `pentest_findings` (via both `assessment_id` and `target_id`), and `pentest_exploit_attempts` (via `assessment_id`, `finding_id`, and `target_id`) — none of which reference `ioc_lookups` or `cases` at all. The only connection back to the rest of the schema is `users`, via `pentest_assessments.created_by` and `pentest_exploit_attempts.requested_by`.

Put simply: `users` sits at the root of ownership for every domain; `ioc_lookups` is the one-to-many parent for everything a single investigation produces (now including that investigation's own Security Assessment Toolkit runs); `cases` is the one-to-many parent for everything an analyst attaches to a multi-IOC case; the runtime-configuration tables are an independent branch that only touches `users`, never the investigation or case data itself; and the Pentest Suite's tables are a fourth, fully independent branch that only touches `users` too, deliberately never `ioc_lookups` or `cases`.

## 🔑 Authentication and Identity

### `users`
Source: `app/models/user.py:19-36` · Introduced in migration `660d2aa3bc20` (`initial_schema.py:22-33`); `last_login_at` added by `7a1c2f9d4e6b_add_user_last_login_at.py`; `token_version` added by `3b9e7a2c1d4f_add_user_token_version.py`.

Application accounts and their RBAC role. This is the only root table in the schema — it has no foreign keys of its own.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK, ORM `uuid.uuid4()` | PK |
| `email` | VARCHAR(255) | NO | — | unique index `ix_users_email` |
| `hashed_password` | VARCHAR(255) | NO | — | — |
| `full_name` | VARCHAR(255) | NO | ORM `""` | — |
| `role` | ENUM `role` | NO | ORM `Role.ANALYST` | — |
| `is_active` | BOOLEAN | NO | ORM `True` | — |
| `last_login_at` | TIMESTAMPTZ | YES | — (nullable, no server default — never-yet-logged-in-since-upgrade users simply have no value) | — |
| `token_version` | INTEGER | NO | ORM `0`; migration `server_default='0'` | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

**Enum `Role`** (`user.py:11-14`): `admin`, `analyst`, `viewer`. The permission matrix keyed off this enum (`ROLE_PERMISSIONS`) lives in the same file and is covered in the Security chapter, not repeated here.

`token_version` is embedded in every issued JWT and re-checked on every request (`app/auth/rbac.py`'s `get_current_user()`); bumping it (done by `app/core/users.py`'s `reset_password()`) immediately invalidates every access/refresh token already issued to that user, not just future logins. A JWT predating this column carries no `token_version` claim at all, which the check treats as `0` — so this column shipped with zero forced logouts.

## 🔍 Investigations and AI Output

This group of five tables holds everything produced by a single IOC investigation, from the raw provider responses through to the AI's final verdict, plus a durable history of every AI re-analysis run against that lookup. (A sixth child table, `security_assessment_runs`, also hangs off `ioc_lookups` — it is documented in its own **Security Assessment Toolkit** section below rather than repeated here, since its own child, `security_assessment_findings`, belongs alongside it.)

### `ioc_lookups`
Source: `app/models/lookup.py:37-84` · Introduced in `660d2aa3bc20` (`initial_schema.py:34-50`).

The central record of one investigation: the submitted IOC, its detected type, a lifecycle status, and — once complete — the AI's final verdict, scores, and full structured assessment.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `ioc_value` | VARCHAR(2048) | NO | — | index `ix_ioc_lookups_ioc_value` (non-unique) |
| `ioc_type` | VARCHAR(64) | NO | — | index `ix_ioc_lookups_ioc_type` (non-unique) |
| `status` | ENUM `lookupstatus` | NO | ORM `PENDING` | — |
| `requested_by` | UUID | YES | — | FK → `users.id` |
| `final_verdict` | ENUM `verdict` | YES | — | — |
| `risk_score` | FLOAT | YES | — | — |
| `confidence_score` | FLOAT | YES | — | — |
| `final_assessment` | JSONB | YES | — | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

**Enum `LookupStatus`** (`lookup.py:15-19`): `pending`, `running`, `completed`, `failed`.

**Enum `Verdict`** (`lookup.py:22-34`), 12 values: `highly_malicious`, `malicious`, `suspicious`, `unknown`, `likely_benign`, `benign`, `scanner`, `tor_exit_node`, `vpn`, `cdn`, `cloud_infrastructure`, `dormant_infrastructure`.

FK: `requested_by` → `users.id` (nullable — a lookup can in principle exist without a resolvable requester). ORM relationships (`lookup.py:70-84`, `cascade="all, delete-orphan"`, ORM-only per the note above): `provider_results`, `ai_summaries`, `correlation_edges`, `evidence_items`, `security_assessment_runs`. `ioc_lookups` is referenced (via `lookup_id`) by `provider_results`, `ai_summaries`, `correlation_edges`, `final_assessment_records`, `evidence_items`, and `security_assessment_runs`, and referenced non-owningly by `basket_items.latest_lookup_id` and `case_iocs.lookup_id`.

### `provider_results`
Source: `app/models/lookup.py:69-84` · Introduced in `660d2aa3bc20` (`initial_schema.py:79-95`).

One row per provider call per lookup — the raw connector response.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `lookup_id` | UUID | NO | — | FK → `ioc_lookups.id`; index `ix_provider_results_lookup_id` |
| `provider_id` | VARCHAR(128) | NO | — | index `ix_provider_results_provider_id` |
| `provider_name` | VARCHAR(255) | NO | — | — |
| `category` | VARCHAR(64) | NO | — | — |
| `status` | VARCHAR(32) | NO | — | — |
| `data` | JSONB | NO | ORM `dict` (`{}`) | — |
| `source_url` | VARCHAR(2048) | YES | — | — |
| `error_message` | TEXT | YES | — | — |
| `latency_ms` | INTEGER | YES | — | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

No local enums; `status`/`category` are free-form strings mirroring the provider layer's own `ProviderStatus`/`ProviderCategory` Python enums, not database enum types. FK: `lookup_id` → `ioc_lookups.id`, back-populated on `IOCLookup.provider_results` (`lookup.py:84`).

### `ai_summaries`
Source: `app/models/lookup.py:87-97` · Introduced in `660d2aa3bc20` (`initial_schema.py:51-62`).

AI-generated summary output. A nullable `provider_id` disambiguates a per-provider summary from the single consolidated summary for the lookup (consolidated rows have `provider_id = NULL`).

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `lookup_id` | UUID | NO | — | FK → `ioc_lookups.id`; index `ix_ai_summaries_lookup_id` |
| `provider_id` | VARCHAR(128) | YES (NULL = consolidated) | — | index `ix_ai_summaries_provider_id` |
| `summary` | JSONB | NO | — | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

FK: `lookup_id` → `ioc_lookups.id`, back-populated on `IOCLookup.ai_summaries` (`lookup.py:97`).

### `correlation_edges`
Source: `app/models/lookup.py:118-143` · Introduced in `660d2aa3bc20` (`initial_schema.py:63-78`); `provenance_category` added by `6d2f4b8e1a7c_add_provenance_category.py`.

One graph edge produced by the correlation engine for a lookup. As documented in the Database Architecture chapter, this table is, in its entirety, where the "correlation graph" the UI renders actually lives — the Neo4j container referenced elsewhere in configuration is not written to.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `lookup_id` | UUID | NO | — | FK → `ioc_lookups.id`; index `ix_correlation_edges_lookup_id` |
| `source_type` | VARCHAR(64) | NO | — | — |
| `source_value` | VARCHAR(2048) | NO | — | — |
| `target_type` | VARCHAR(64) | NO | — | — |
| `target_value` | VARCHAR(2048) | NO | — | — |
| `relationship_type` | VARCHAR(64) | NO | — | — |
| `confidence` | FLOAT | NO | ORM `1.0` | — |
| `provenance` | VARCHAR(128) | NO | — (which provider asserted this edge) | — |
| `provenance_category` | VARCHAR(32) | NO | ORM `"threat_intel"`; migration `server_default='threat_intel'` | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

`provenance_category` is a second, distinct axis from `provenance` above — WHAT KIND of source asserted the edge (`threat_intel` / `security_assessment` / `local_observation` / `ai_interpretation`, see `app/core/provenance.py`) rather than WHICH provider. Existing rows backfilled to `"threat_intel"` because every provider that existed before this column did some form of external intelligence lookup, never a local active observation.

FK: `lookup_id` → `ioc_lookups.id`, back-populated on `IOCLookup.correlation_edges` (`lookup.py:143`).

### `final_assessment_records`
Source: `app/models/lookup.py:146-176` · Introduced in migration `2652d888a33f` (`add_final_assessment_records.py:22-36`); `ai_outcome` added by `6716ed40b9f2_add_final_assessment_ai_outcome.py`. No longer the current migration head — see **Migration Provenance** below for the full, current chain.

A durable history of every final-assessment generation run for a lookup, not just the one currently reflected on `ioc_lookups`. This backs the platform's cross-AI-backend comparison feature (e.g. comparing a Groq run against an Ollama re-run over the same evidence); `IOCLookup.final_assessment` / `final_verdict` / `risk_score` remains the single "primary" record surfaced by default.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `lookup_id` | UUID | NO | — | FK → `ioc_lookups.id`; index `ix_final_assessment_records_lookup_id` |
| `ai_backend` | VARCHAR(64) | NO | — | — |
| `ai_model` | VARCHAR(255) | YES | — | — |
| `ai_outcome` | VARCHAR(32) | NO | migration `server_default='success'` | — |
| `is_primary` | BOOLEAN | NO | ORM `False` | — |
| `assessment` | JSONB | NO | — | — |
| `requested_by` | UUID | YES | — | FK → `users.id` |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

`ai_outcome` mirrors `app/ai/schemas.py`'s `FinalAssessment.ai_outcome` (`"success"` / `"skipped_no_evidence"` / `"failed"`) as a real, queryable column rather than something a caller would otherwise have to infer by deserializing the JSONB `assessment` blob or by treating `ai_backend == "unknown"` as a proxy for failure. Pre-existing rows (predating this column) were backfilled by matching each row's deterministic, hardcoded `executive_summary` text against the two known non-success templates — confirmed live to match exactly, with zero unmatched rows.

FKs: `lookup_id` → `ioc_lookups.id`; `requested_by` → `users.id`. This model declares a bare `relationship()` with no `back_populates` (`lookup.py:144`) — `IOCLookup` does not expose a reverse collection for this table.

## 🧾 The Evidence Ledger

### `evidence_items`
Source: `app/models/evidence.py:31-56` · Introduced in migration `a6d3ad2bb63c` (`add_evidence_basket_and_case_management_.py:96-117`).

The deterministic, independently-reproducible evidence ledger. Every AI-generated explanation elsewhere in the platform must cite an `evidence_id` back to one of these rows; rows here are built by `app/evidence/builder.py` from provider results and correlation edges and are never written directly by an AI call — this table is the platform's anti-hallucination grounding mechanism.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `lookup_id` | UUID | NO | — | FK → `ioc_lookups.id`; index `ix_evidence_items_lookup_id` |
| `evidence_type` | ENUM `evidencetype` | NO | — | index `ix_evidence_items_evidence_type` |
| `source_label` | VARCHAR(255) | NO | — (e.g. `"VirusTotal"`, `"Correlation Engine"`) | — |
| `provider_id` | VARCHAR(128) | YES | — (NULL when the source is the correlation engine itself) | index `ix_evidence_items_provider_id` |
| `claim` | TEXT | NO | — | — |
| `interpretation` | TEXT | YES | — | — |
| `confidence` | FLOAT | NO | — (0-100 scale; no ORM default) | — |
| `related_ioc_type` | VARCHAR(64) | YES | — | — |
| `related_ioc_value` | VARCHAR(2048) | YES | — | — |
| `source_url` | VARCHAR(2048) | YES | — | — |
| `observed_at` | VARCHAR(64) | YES | — (provider-reported timestamp string, mixed formats, not parsed into a real timestamp type) | — |
| `raw_data` | JSONB | YES | — | — |
| `provenance_category` | VARCHAR(32) | NO | ORM `"threat_intel"`; migration `server_default='threat_intel'` | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

`provenance_category` (added by `6d2f4b8e1a7c_add_provenance_category.py`) is the same "what kind of source" axis as `CorrelationEdgeRecord.provenance_category` above, not a duplicate concept under a different name — see `app/core/provenance.py`.

**Enum `EvidenceType`** (`evidence.py:19-28`), 9 values: `detection`, `reputation`, `relationship`, `malware_association`, `threat_actor_association`, `campaign_association`, `mitre_technique`, `infrastructure`, `other`.

FK: `lookup_id` → `ioc_lookups.id`, back-populated on `IOCLookup.evidence_items` (`evidence.py:56`).

## 🛡️ Security Assessment Toolkit Tables

Two tables back the Security Assessment Toolkit (`backend/app/security_assessment/`) — the active-scanning module tied to one IOC lookup, distinct from the standalone Pentest Suite documented further below. Rows here are produced only by an explicit, authorization-gated `POST /api/v1/security-assessment/{lookup_id}/run` call, never by the passive per-investigation provider fan-out that populates `provider_results`/`evidence_items`.

### `security_assessment_runs`
Source: `app/models/security_assessment.py:38-65` · Introduced in migration `5c8e1f3a9b2d_add_security_assessment_tables.py`; the `CANCELLED` status value added by `8f4a1c2d9e6b_add_cancelled_security_assessment_status.py`.

One authorized security-assessment invocation against a lookup's own IOC.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `lookup_id` | UUID | NO | — | FK → `ioc_lookups.id`; index `ix_security_assessment_runs_lookup_id` |
| `requested_by` | UUID | YES | — | FK → `users.id` |
| `target` | VARCHAR(2048) | NO | — (the exact value the caller retyped to confirm scope; kept verbatim as part of the authorization record, not just checked-and-discarded) | — |
| `tool_ids` | JSONB | NO | ORM `list` (`[]`) | — |
| `profile` | VARCHAR(64) | NO | — | — |
| `status` | ENUM `securityassessmentrunstatus` | NO | ORM `PENDING` | — |
| `authorization_confirmed_at` | TIMESTAMPTZ | NO | — | — |
| `started_at` | TIMESTAMPTZ | YES | — | — |
| `completed_at` | TIMESTAMPTZ | YES | — | — |
| `error_message` | TEXT | YES | — | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

**Enum `SecurityAssessmentRunStatus`** (`security_assessment.py:22-27`), 5 values: `pending`, `running`, `completed`, `failed`, `cancelled` (the last added after initial release).

FKs: `lookup_id` → `ioc_lookups.id`; `requested_by` → `users.id` (nullable). Relationship (`security_assessment.py:62-65`, `cascade="all, delete-orphan"`, ORM-only): `findings` (`SecurityAssessmentFinding`).

### `security_assessment_findings`
Source: `app/models/security_assessment.py:68-91` · Introduced in migration `5c8e1f3a9b2d_add_security_assessment_tables.py`.

One discrete finding produced by one active-check tool during a run.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `run_id` | UUID | NO | — | FK → `security_assessment_runs.id`; index `ix_security_assessment_findings_run_id` |
| `tool_id` | VARCHAR(64) | NO | — | index `ix_security_assessment_findings_tool_id` |
| `finding_type` | VARCHAR(64) | NO | — | — |
| `severity` | ENUM `severity` | NO | — | index `ix_security_assessment_findings_severity` |
| `title` | VARCHAR(500) | NO | — | — |
| `description` | TEXT | NO | ORM `""` | — |
| `target_detail` | VARCHAR(255) | YES | — | — |
| `cve_ids` | JSONB | NO | ORM `list` (`[]`) | — |
| `evidence` | JSONB | NO | ORM `dict` (`{}`) | — (the concrete data the severity/claim was derived from — e.g. the raw port/service banner, parsed certificate fields, observed response headers; never AI-generated) |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

**Enum `Severity`** (`security_assessment.py:30-35`), 5 values: `info`, `low`, `medium`, `high`, `critical`. Note that the Pentest Suite's `pentest_findings.severity` column (below) deliberately does **not** reuse this DB enum — see that table's own note for why.

FK: `run_id` → `security_assessment_runs.id`, back-populated on `SecurityAssessmentRun.findings` (`security_assessment.py:88`).

## 📁 Case Management and the Analyst Workspace

### `basket_items`
Source: `app/models/basket.py:16-29` · Introduced in `a6d3ad2bb63c` (lines 37-51).

A per-analyst scratch space of saved IOCs, used ahead of formal case creation. Deliberately carries no status/workflow fields of its own.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `owner_id` | UUID | NO | — | FK → `users.id`; index `ix_basket_items_owner_id`; part of composite unique `uq_basket_owner_ioc` |
| `ioc_value` | VARCHAR(2048) | NO | — | part of composite unique `uq_basket_owner_ioc` |
| `ioc_type` | VARCHAR(64) | NO | — | — |
| `latest_lookup_id` | UUID | YES | — | FK → `ioc_lookups.id` |
| `note` | VARCHAR(1024) | YES | — | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

Table-level constraint: `UniqueConstraint(owner_id, ioc_value, name="uq_basket_owner_ioc")` (`basket.py:18`) — enforces at most one basket row per owner per exact IOC value; this is a real database-level constraint, not just an application check. FKs: `owner_id` → `users.id`; `latest_lookup_id` → `ioc_lookups.id` (nullable — an IOC can be basketed before any lookup has run).

### `cases`
Source: `app/models/case.py:32-44` · Introduced in `a6d3ad2bb63c` (lines 22-36).

A multi-IOC investigation/incident container with its own status workflow, team-shared rather than per-analyst.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `title` | VARCHAR(255) | NO | — | — |
| `description` | TEXT | YES | — | — |
| `analyst_id` | UUID | NO | — | FK → `users.id`; index `ix_cases_analyst_id` |
| `severity` | ENUM `caseseverity` | NO | ORM `MEDIUM` | — |
| `status` | ENUM `casestatus` | NO | ORM `OPEN` | index `ix_cases_status` |
| `tags` | ARRAY(VARCHAR(64)) | NO | ORM `list` (`[]`) | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

**Enum `CaseStatus`** (`case.py:16-22`), 6 values: `open`, `investigating`, `contained`, `resolved`, `false_positive`, `closed`.

**Enum `CaseSeverity`** (`case.py:25-29`), 4 values: `low`, `medium`, `high`, `critical`.

FK: `analyst_id` → `users.id`. Relationships (`case.py:42-44`, `cascade="all, delete-orphan"`, ORM-only): `iocs` (`CaseIOC`), `notes` (`CaseNote`), `reports` (`CaseReport`).

### `case_iocs`
Source: `app/models/case.py:47-58` · Introduced in `a6d3ad2bb63c` (lines 52-65).

One IOC attached to a case, optionally linked to the lookup that investigated it.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `case_id` | UUID | NO | — | FK → `cases.id`; index `ix_case_iocs_case_id` |
| `ioc_value` | VARCHAR(2048) | NO | — | — |
| `ioc_type` | VARCHAR(64) | NO | — | — |
| `lookup_id` | UUID | YES | — | FK → `ioc_lookups.id` |
| `added_by` | UUID | NO | — | FK → `users.id` |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

FKs: `case_id` → `cases.id`; `lookup_id` → `ioc_lookups.id` (nullable); `added_by` → `users.id`. Back-populated on `Case.iocs` (`case.py:58`).

### `case_notes`
Source: `app/models/case.py:61-75` · Introduced in `a6d3ad2bb63c` (lines 67-79).

A free-text analyst note attached to a case, optionally "anchored" to a specific artifact by a loose string pair rather than a real foreign key.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `case_id` | UUID | NO | — | FK → `cases.id`; index `ix_case_notes_case_id` |
| `author_id` | UUID | NO | — | FK → `users.id` |
| `body` | TEXT | NO | — | — |
| `anchor_type` | VARCHAR(64) | YES | — (free string, e.g. `"ioc"`, `"evidence"`, `"graph_node"`, `"timeline_event"`, `"provider_result"` — not an enum, not a foreign key) | — |
| `anchor_ref` | VARCHAR(2048) | YES | — | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

FKs: `case_id` → `cases.id`; `author_id` → `users.id`. Back-populated on `Case.notes` (`case.py:75`). Because `anchor_type`/`anchor_ref` are plain strings, the database performs no referential-integrity check on what a note is anchored to — an anchor referencing a since-deleted evidence item, for example, would not be caught by a database constraint.

### `case_reports`
Source: `app/models/case.py:78-88` · Introduced in `a6d3ad2bb63c` (lines 81-95).

A generated report artifact attached to a case.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `case_id` | UUID | NO | — | FK → `cases.id`; index `ix_case_reports_case_id` |
| `report_type` | VARCHAR(64) | NO | — (matches a `ReportType` literal defined in `app/ai/schemas.py`; not a database enum) | — |
| `title` | VARCHAR(255) | NO | — | — |
| `content_markdown` | TEXT | NO | — | — |
| `generated_by` | UUID | NO | — | FK → `users.id` |
| `context` | JSONB | YES | — | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

FKs: `case_id` → `cases.id`; `generated_by` → `users.id`. Back-populated on `Case.reports` (`case.py:88`).

> [!NOTE]
> The table exists and is fully wired at the schema level, but no route or service function in `app/api/routes/cases.py` currently inserts a row here — verified against the endpoint inventory: `cases.py` exposes create/list/get/update/close/add-IOC/remove-IOC/add-note, and no report-generation endpoint. Read `case_reports` as a defined-but-unpopulated table today, not a dead or removed one.

## 🧰 Runtime Configuration and Audit

These two tables are the persistence layer behind the platform's DB-backed, hot-swappable AI/provider credential system, which lets an administrator reconfigure AI backends and IOC providers without editing `.env` or restarting containers.

### `provider_runtime_configs`
Source: `app/models/runtime_config.py:30-55` · Introduced in migration `0f2dc283823e` (`add_provider_runtime_config_and_audit_.py:32-51`).

One row per `(kind, provider_id)` pair — every AI backend and every IOC provider the platform knows about. Credentials are Fernet-encrypted before storage; see the Security chapter for the encryption mechanism.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `kind` | ENUM `providerkind` | NO | — | part of composite unique `uq_provider_runtime_kind_id` |
| `provider_id` | VARCHAR(64) | NO | — | part of composite unique `uq_provider_runtime_kind_id` |
| `provider_name` | VARCHAR(255) | NO | ORM `""` | — |
| `enabled` | BOOLEAN | NO | ORM `True` | — |
| `is_active` | BOOLEAN | NO | ORM `False` | — (meaningful only for `kind=AI`; "exactly one active AI row" is enforced by application code, not a database constraint) |
| `encrypted_credentials` | TEXT | YES | — (Fernet ciphertext of a JSON object, e.g. `{"api_key": "..."}`) | — |
| `model_id` | VARCHAR(255) | YES | — | — |
| `extra_config` | JSONB | YES | — (non-secret extras, e.g. a custom endpoint URL) | — |
| `last_test_at` | TIMESTAMPTZ | YES | — | — |
| `last_test_ok` | BOOLEAN | YES | — | — |
| `last_test_message` | VARCHAR(500) | YES | — | — |
| `updated_by` | UUID | YES | — | FK → `users.id` |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

**Enum `ProviderKind`** (`runtime_config.py:25-27`): `ai`, `ioc`.

Table-level constraint: `UniqueConstraint(kind, provider_id, name="uq_provider_runtime_kind_id")` (`runtime_config.py:32`) — a real database constraint preventing duplicate rows for the same backend/provider. FK: `updated_by` → `users.id` (nullable).

### `config_audit_log`
Source: `app/models/runtime_config.py:58-75` · Introduced in `0f2dc283823e` (`add_provider_runtime_config_and_audit_.py:22-31`).

An append-only audit trail of runtime-config changes. This is the one table in the schema that intentionally omits `TimestampMixin` — it uses only `UUIDPrimaryKeyMixin` and defines its own `timestamp` column, with no `created_at`/`updated_at`.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `timestamp` | TIMESTAMPTZ | NO | — (no server default; the application must set this explicitly on insert) | — |
| `actor_user_id` | UUID | YES | — | FK → `users.id` |
| `actor_email` | VARCHAR(255) | YES | — (a denormalized copy of the actor's email, kept so the log stays human-readable even if the user account is later deleted) | — |
| `action` | VARCHAR(100) | NO | — | — |
| `detail` | VARCHAR(1000) | NO | ORM `""` | — |

No enums. FK: `actor_user_id` → `users.id`, but note this model declares no `relationship()` back to `User` — it is an informational foreign key only, not used for ORM-level joins. As documented in the Security chapter, `detail` is restricted by application convention to human-readable descriptive text; it is not a field the write path ever populates with a raw credential value.

## ⚔️ Pentest Suite Tables

Four tables back the Pentest Suite (`backend/app/pentest/`) — a standalone, scope-enforced assessment lifecycle (DISCOVER → ENUMERATE → ASSESS → CORRELATE → PRIORITIZE → REPORT) operating on its own independently-declared targets, entirely distinct from the per-lookup Security Assessment Toolkit above. None of these four tables reference `ioc_lookups` or `cases`; the only connection back into the rest of the schema is `users`. The suite reuses the existing tool adapters (`app/security_assessment/*.py`) and the existing generic `config_audit_log`/`record_audit()` audit trail rather than inventing parallel ones — there is no separate pentest-specific audit table.

### `pentest_assessments`
Source: `app/models/pentest.py:72-99` · Introduced in migration `9273d7b21c79_add_pentest_suite_tables.py`.

The top-level, scope-declaring container for one authorized engagement.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `name` | VARCHAR(255) | NO | — | — |
| `description` | TEXT | YES | — | — |
| `status` | ENUM `pentestassessmentstatus` | NO | ORM `DRAFT` | index `ix_pentest_assessments_status` |
| `profile` | ENUM `pentestprofile` | NO | — | — |
| `scope_definition` | JSONB | NO | ORM `dict` (`{}`) | — (a handful of `{"cidrs": [...], "domains": [...]}`-style entries; an empty scope authorizes nothing) |
| `max_runtime_minutes` | INTEGER | NO | ORM `120` | — |
| `max_requests` | INTEGER | NO | ORM `5000` | — |
| `emergency_stopped` | BOOLEAN | NO | ORM `False` | — (a per-assessment kill switch, checked before every step transition; kept distinct from `status` so a deliberate "cancelled" stop and an operator's mid-run emergency stop are never ambiguous in the audit trail) |
| `started_at` | TIMESTAMPTZ | YES | — | — |
| `expires_at` | TIMESTAMPTZ | YES | — | — |
| `created_by` | UUID | NO | — | FK → `users.id`; index `ix_pentest_assessments_created_by` |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

**Enum `PentestAssessmentStatus`** (`pentest.py:26-32`), 6 values: `draft`, `active`, `paused`, `completed`, `cancelled`, `expired`.

**Enum `PentestProfile`** (`pentest.py:35-40`), 5 values: `passive`, `low_impact`, `standard`, `comprehensive`, `custom`.

FK: `created_by` → `users.id`. Relationships (`pentest.py:97-99`, `cascade="all, delete-orphan"`, ORM-only): `targets` (`PentestTarget`), `findings` (`PentestFinding`), `exploit_attempts` (`PentestExploitAttempt`).

### `pentest_targets`
Source: `app/models/pentest.py:102-122` · Introduced in migration `9273d7b21c79_add_pentest_suite_tables.py`.

One in-scope target declared within an assessment.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `assessment_id` | UUID | NO | — | FK → `pentest_assessments.id`; index `ix_pentest_targets_assessment_id` |
| `target_type` | VARCHAR(32) | NO | — (reuses the platform's own `IOCType` values — `ipv4`/`ipv6`/`cidr`/`domain`/`hostname`/`url` — rather than a parallel enum) | — |
| `value` | VARCHAR(2048) | NO | — | — |
| `port` | INTEGER | YES | — | — |
| `asset_label` | VARCHAR(255) | YES | — | — |
| `environment` | VARCHAR(64) | YES | — | — |
| `target_group` | VARCHAR(128) | YES | — | — |
| `status` | ENUM `pentesttargetstatus` | NO | ORM `PENDING` | index `ix_pentest_targets_status` |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

**Enum `PentestTargetStatus`** (`pentest.py:43-50`), 7 values: `pending`, `discovering`, `enumerating`, `assessing`, `completed`, `failed`, `out_of_scope`.

FK: `assessment_id` → `pentest_assessments.id`, back-populated on `PentestAssessment.targets`. Relationship (`pentest.py:122`, `cascade="all, delete-orphan"`, ORM-only): `findings` (`PentestFinding`).

### `pentest_findings`
Source: `app/models/pentest.py:125-161` · Introduced in migration `9273d7b21c79_add_pentest_suite_tables.py`.

One finding produced against one target within an assessment.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `assessment_id` | UUID | NO | — | FK → `pentest_assessments.id`; index `ix_pentest_findings_assessment_id` |
| `target_id` | UUID | NO | — | FK → `pentest_targets.id`; index `ix_pentest_findings_target_id` |
| `tool_id` | VARCHAR(64) | NO | — | index `ix_pentest_findings_tool_id` |
| `finding_type` | VARCHAR(64) | NO | — | — |
| `severity` | VARCHAR(16) | NO | — | index `ix_pentest_findings_severity` |
| `confidence` | ENUM `pentestfindingconfidence` | NO | ORM `INFORMATIONAL` | — |
| `cvss_score` | FLOAT | YES | — | — |
| `cve_ids` | JSONB | NO | ORM `list` (`[]`) | — |
| `title` | VARCHAR(500) | NO | — | — |
| `description` | TEXT | NO | ORM `""` | — |
| `remediation` | TEXT | YES | — | — |
| `status` | ENUM `pentestfindingstatus` | NO | ORM `OPEN` | index `ix_pentest_findings_status` |
| `evidence` | JSONB | NO | ORM `list` (`[]`) | — (a LIST of `{"captured_at": ..., "tool_id": ..., "data": {...}}` entries, not a single blob — so re-validating a finding later appends a new entry instead of overwriting the original observation) |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

> [!NOTE]
> `severity` here is a plain `VARCHAR(16)`, **not** the `severity` enum used by `security_assessment_findings` above — it deliberately reuses `app/security_assessment/base.py`'s Severity vocabulary (`info` through `critical`) as free-form text rather than adding a second, redundant database enum for the same concept. `confidence` is a genuinely different axis from `severity`: severity is *how bad*, confidence is *how sure the platform is the finding is real* — a version-string match alone is never enough to reach `confirmed`.

**Enum `PentestFindingConfidence`** (`pentest.py:53-61`), 4 values: `confirmed`, `likely`, `potential`, `informational`.

**Enum `PentestFindingStatus`** (`pentest.py:64-69`), 5 values: `open`, `validated`, `false_positive`, `remediated`, `accepted_risk`.

FKs: `assessment_id` → `pentest_assessments.id`; `target_id` → `pentest_targets.id`. Relationship (`pentest.py:158`, `cascade="all, delete-orphan"`, ORM-only): `exploit_attempts` (`PentestExploitAttempt`).

### `pentest_exploit_attempts`
Source: `app/models/pentest.py:178-218` · Introduced in migration `9123b075e962_add_pentest_exploit_attempts_table.py`, the current migration head.

One gated, manually-selected, individually-approved run of a real Metasploit module against a finding's own target. Never created by the autonomous DISCOVER→ENUMERATE→ASSESS pipeline — the only way a row here exists is a human explicitly choosing a specific module and, for `mode=exploit`, explicitly confirming it, every single time.

| Column | Type | Null | Default | Index / Unique |
|---|---|---|---|---|
| `id` | UUID | NO | PK | PK |
| `assessment_id` | UUID | NO | — | FK → `pentest_assessments.id`; index `ix_pentest_exploit_attempts_assessment_id` |
| `finding_id` | UUID | NO | — | FK → `pentest_findings.id`; index `ix_pentest_exploit_attempts_finding_id` |
| `target_id` | UUID | NO | — | FK → `pentest_targets.id`; index `ix_pentest_exploit_attempts_target_id` |
| `module_fullname` | VARCHAR(255) | NO | — | — |
| `module_options` | JSONB | NO | ORM `dict` (`{}`) | — (caller-supplied options, captured *after* `app/pentest/exploit.py` force-overwrites `RHOSTS`/`RHOST` with the target's own value — a caller can never use this to point a module at a host outside the finding's own target) |
| `mode` | ENUM `pentestexploitmode` | NO | — | — |
| `status` | ENUM `pentestexploitstatus` | NO | ORM `PENDING` | index `ix_pentest_exploit_attempts_status` |
| `result_transcript` | TEXT | NO | ORM `""` | — (the verbatim `msfconsole` console transcript, deliberately never auto-parsed into a computed vulnerable/not-vulnerable verdict — a human operator reads this directly) |
| `session_id` | INTEGER | YES | — | — |
| `requested_by` | UUID | NO | — | FK → `users.id`; index `ix_pentest_exploit_attempts_requested_by` |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | server `now()` | — |

**Enum `PentestExploitMode`** (`pentest.py:164-166`), 2 values: `check`, `exploit`.

**Enum `PentestExploitStatus`** (`pentest.py:169-175`), 6 values: `pending`, `running`, `succeeded`, `session_opened`, `failed`, `error`.

> [!WARNING]
> This table exists specifically for genuine exploit-module execution, not a simulation. `module_options` cannot override the target host regardless of what a caller submits — `RHOSTS`/`RHOST` are always force-overwritten with the finding's own real target before the module runs. See the Pentest Suite's own chapter for the full safety model, including every gate between "an assessment exists" and "a real exploit ran."

FKs: `assessment_id` → `pentest_assessments.id`; `finding_id` → `pentest_findings.id`; `target_id` → `pentest_targets.id`; `requested_by` → `users.id`. Relationships back-populated on `PentestAssessment.exploit_attempts` and `PentestFinding.exploit_attempts`.

## 🔢 Enum Inventory

Every native Postgres `ENUM` type in the schema, named as the lowercase of its Python class (no model overrides this with an explicit `name=`):

| DB enum name | Python class | Values |
|---|---|---|
| `role` | `Role` | admin, analyst, viewer |
| `lookupstatus` | `LookupStatus` | pending, running, completed, failed |
| `verdict` | `Verdict` | highly_malicious, malicious, suspicious, unknown, likely_benign, benign, scanner, tor_exit_node, vpn, cdn, cloud_infrastructure, dormant_infrastructure |
| `evidencetype` | `EvidenceType` | detection, reputation, relationship, malware_association, threat_actor_association, campaign_association, mitre_technique, infrastructure, other |
| `casestatus` | `CaseStatus` | open, investigating, contained, resolved, false_positive, closed |
| `caseseverity` | `CaseSeverity` | low, medium, high, critical |
| `providerkind` | `ProviderKind` | ai, ioc |
| `securityassessmentrunstatus` | `SecurityAssessmentRunStatus` | pending, running, completed, failed, cancelled |
| `severity` | `Severity` | info, low, medium, high, critical |
| `pentestassessmentstatus` | `PentestAssessmentStatus` | draft, active, paused, completed, cancelled, expired |
| `pentestprofile` | `PentestProfile` | passive, low_impact, standard, comprehensive, custom |
| `pentesttargetstatus` | `PentestTargetStatus` | pending, discovering, enumerating, assessing, completed, failed, out_of_scope |
| `pentestfindingconfidence` | `PentestFindingConfidence` | confirmed, likely, potential, informational |
| `pentestfindingstatus` | `PentestFindingStatus` | open, validated, false_positive, remediated, accepted_risk |
| `pentestexploitmode` | `PentestExploitMode` | check, exploit |
| `pentestexploitstatus` | `PentestExploitStatus` | pending, running, succeeded, session_opened, failed, error |

`pentest_findings.severity` is a plain `VARCHAR`, not a native enum — it is intentionally excluded from this table for that reason (see that table's own note above).

## 🧬 Migration Provenance

| Migration file | Revision → down_revision | Tables created / columns added |
|---|---|---|
| `660d2aa3bc20_initial_schema.py` | `660d2aa3bc20` → (root) | `users`, `ioc_lookups`, `ai_summaries`, `correlation_edges`, `provider_results` |
| `a6d3ad2bb63c_add_evidence_basket_and_case_management_.py` | `a6d3ad2bb63c` → `660d2aa3bc20` | `cases`, `basket_items`, `case_iocs`, `case_notes`, `case_reports`, `evidence_items` |
| `0f2dc283823e_add_provider_runtime_config_and_audit_.py` | `0f2dc283823e` → `a6d3ad2bb63c` | `config_audit_log`, `provider_runtime_configs` |
| `2652d888a33f_add_final_assessment_records.py` | `2652d888a33f` → `0f2dc283823e` | `final_assessment_records` |
| `7a1c2f9d4e6b_add_user_last_login_at.py` | `7a1c2f9d4e6b` → `2652d888a33f` | adds `users.last_login_at` |
| `3b9e7a2c1d4f_add_user_token_version.py` | `3b9e7a2c1d4f` → `7a1c2f9d4e6b` | adds `users.token_version` |
| `5c8e1f3a9b2d_add_security_assessment_tables.py` | `5c8e1f3a9b2d` → `3b9e7a2c1d4f` | `security_assessment_runs`, `security_assessment_findings` |
| `6d2f4b8e1a7c_add_provenance_category.py` | `6d2f4b8e1a7c` → `5c8e1f3a9b2d` | adds `correlation_edges.provenance_category`, `evidence_items.provenance_category` |
| `6716ed40b9f2_add_final_assessment_ai_outcome.py` | `6716ed40b9f2` → `6d2f4b8e1a7c` | adds `final_assessment_records.ai_outcome` |
| `8f4a1c2d9e6b_add_cancelled_security_assessment_status.py` | `8f4a1c2d9e6b` → `6716ed40b9f2` | adds `CANCELLED` to the `securityassessmentrunstatus` enum (no new table/column) |
| `9273d7b21c79_add_pentest_suite_tables.py` | `9273d7b21c79` → `8f4a1c2d9e6b` | `pentest_assessments`, `pentest_targets`, `pentest_findings` |
| `9123b075e962_add_pentest_exploit_attempts_table.py` (head) | `9123b075e962` → `9273d7b21c79` | `pentest_exploit_attempts` |

The chain is linear with a single head at `9123b075e962`, twelve migrations deep. No table or column exists in the ORM models that is missing a corresponding migration, and no migration DDL was found that lacks a corresponding model — the schema described in this chapter is, at the time of writing, exactly the schema Alembic would produce by replaying all twelve migrations against an empty database.
