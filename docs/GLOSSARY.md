# Glossary

Definitions for terms this platform actually uses in its code, database schema, and UI — enum
values, status codes, permission strings, and domain terms — with source references. This is not
a generic security glossary; a term only appears here if it is grep-backed in
`backend/app/` or `frontend/`.

See also: [IOC_TYPES.md](IOC_TYPES.md) for IOC-type detection details, [PROVIDERS.md](PROVIDERS.md)
for provider-specific behavior, [DATA_MODEL.md](DATA_MODEL.md) for full table schemas, and
[AI_ENGINE.md](AI_ENGINE.md) for how the AI layer consumes several of these enums.

---

## IOC (Indicator of Compromise)

A piece of data (hash, IP, domain, CVE, ATT&CK technique ID, etc.) submitted for lookup. The
platform's `IOCType` enum (`backend/app/ioc/types.py:5-38`) defines these values:

`ipv4`, `ipv6`, `domain`, `url`, `hostname`, `email`, `md5`, `sha1`, `sha256`, `sha512`,
`tls_certificate`, `ja3`, `ja4`, `asn`, `cidr`, `malware_family`, `threat_actor`, `campaign`,
`cve`, `cwe`, `capec`, `mitre_technique`, `file_name`, `registry_key`, `process_name`, `mutex`,
`windows_service`, `file_path`, `user_agent`, `crypto_wallet`, `yara_rule`, `sigma_rule`, `unknown`.

Two derived sets are used elsewhere in the codebase:

- **`HASH_TYPES`** (`types.py:42`) = `{md5, sha1, sha256, sha512}` — used by connectors that
  accept any hash type.
- **`NETWORK_TYPES`** (`types.py:44-53`) = `{ipv4, ipv6, domain, url, hostname, asn, cidr}` — used
  to seed the correlation graph and to classify evidence as `infrastructure`.

Classification is performed exclusively server-side by `detect_ioc_type()`
(`backend/app/ioc/detector.py:61`); see [IOC_TYPES.md](IOC_TYPES.md) for the full detection order.
Several enum members exist but can **never** actually be returned by the detector today — see
[Detector-only vs. reachable IOC types](#detector-only-vs-reachable-ioc-types) below.

### Detector-only vs. reachable IOC types

| Type | Reachable via `detect_ioc_type()`? | Notes |
|---|---|---|
| `ja3` | **NOT IMPLEMENTED** | Regex exists (`_JA3_RE`, `detector.py:15`) but is never called; 32-hex strings always resolve to `md5` instead. |
| `mutex` | **NOT IMPLEMENTED** | Regex exists (`_MUTEX_HINT_RE`, `detector.py:31`) but is never referenced. |
| `windows_service` | **NOT IMPLEMENTED** | No regex or logic anywhere in `detector.py`. |
| `process_name` | **NOT IMPLEMENTED** | The one code branch that returns it (`detector.py:157`) is unreachable dead code guarded by a contradictory condition. |
| `hostname` | **NOT IMPLEMENTED** (by the detector) | No public-suffix-list check exists; all bare dotted strings resolve to `domain`. `hostname` is produced elsewhere (e.g. `providers/otx.py`) but never by `detect_ioc_type()` itself. |
| `tls_certificate`, `malware_family`, `threat_actor`, `campaign` | **NOT IMPLEMENTED** (by the detector) | Never returned by `detect_ioc_type()`; produced by other subsystems (correlation engine, crawler, workers, crt.sh's `supported_types`). |

The only override mechanism is `ioc_type_hint` on `LookupCreateRequest` / `BasketAddRequest`
(`backend/app/schemas/lookup.py:11`, `backend/app/schemas/basket.py:10`) — a generic
`Optional[IOCType]`, not a type-specific hint (e.g. there is no dedicated "this is JA3, not MD5"
signal).

---

## Verdict

The `Verdict` enum (`backend/app/models/lookup.py:22-34`) is the final classification stored on
`IOCLookup.final_verdict` and produced by the AI's `FinalAssessment.final_verdict` field
(`backend/app/ai/schemas.py:158`). Twelve values:

| Value | Frontend color (`frontend/lib/utils.ts`) | Meaning |
|---|---|---|
| `highly_malicious` | destructive (red) | Confirmed high-confidence malicious |
| `malicious` | destructive (red) | Malicious |
| `suspicious` | warning (yellow) | Ambiguous / partially corroborated malicious signal |
| `unknown` | muted (default) | Insufficient data to judge |
| `likely_benign` | success (green) | Probably benign |
| `benign` | success (green) | Confirmed benign |
| `scanner` | accent | Known internet-scanning infrastructure |
| `tor_exit_node` | accent | Tor exit node |
| `vpn` | accent | VPN infrastructure |
| `cdn` | accent | CDN infrastructure |
| `cloud_infrastructure` | accent | Generic cloud provider infrastructure |
| `dormant_infrastructure` | accent | Infrastructure with no current active signal |

`malicious` and `highly_malicious` are grouped as `_MALICIOUS_VERDICTS`; `benign` and
`likely_benign` are grouped as `_BENIGN_VERDICTS` (`backend/app/ai/schemas.py:28-29`). A Pydantic
validator (`FinalAssessment._verdict_must_agree_with_risk`, `schemas.py:161-182`) rejects an AI
response where `final_verdict` is in `_MALICIOUS_VERDICTS` but `malicious_probability < 30`, or in
`_BENIGN_VERDICTS` but `malicious_probability > 50` — a sanity check against small local models
that emit an internally contradictory assessment.

The badge-color switch (`frontend/lib/utils.ts:8-26`, `components/dashboard/ProviderCard.tsx`) is
a hardcoded string match on these exact lowercase values; any off-spec string silently falls
through to the muted default style, which is why `FinalAssessment`'s AI-facing fields use real
`Literal`/enum types rather than free text (`backend/app/ai/schemas.py:10-20`).

---

## Reputation, Threat Level, Confidence (AI schema literals)

Three `Literal` types constrain the AI's structured output (`backend/app/ai/schemas.py:31-33`),
used on both `ProviderSummary` (per-provider) and `RiskAssessment` (final):

| Literal | Values |
|---|---|
| `_Reputation` | `malicious`, `suspicious`, `clean`, `unknown`, `no data` |
| `_ThreatLevel` (severity) | `none`, `low`, `medium`, `high`, `critical` |
| `_Confidence` | `low`, `medium`, `high` |

### Confidence bands

Two distinct 0–100 numeric confidence conventions exist in the platform — do not conflate them:

1. **AI assessment confidence** — `RiskAssessment.confidence_score` (`ai/schemas.py:105-109`) and
   `overall_risk_score` / `malicious_probability` are all `float` fields on a **0–100** scale
   (explicitly *not* 0–1). A validator (`_reject_0_to_1_scale`, `ai/schemas.py:119-131`) rescales
   any value strictly between 0 and 1 by ×100, because small local models (observed:
   `llama3.2:3b`) sometimes emit a 0–1 probability despite the 0–100 field description.
2. **Deterministic evidence confidence** — `EvidenceRecord.confidence` (`backend/app/evidence/builder.py`)
   is also 0–100, "same scale as `RiskAssessment` ... so evidence and risk numbers are directly
   comparable in the UI" (`builder.py:1-10` docstring). Two sources feed it:
   - Provider-summary evidence: `_CONFIDENCE_LEVEL_TO_SCORE` maps the `_Confidence` literal to a
     score — `low` → `30.0`, `medium` → `60.0`, `high` → `90.0` (`builder.py:21`); an unrecognized
     value defaults to `50.0`.
   - Correlation-edge evidence: `confidence = round(edge.confidence * 100, 1)` — the correlation
     engine's internal 0–1 edge confidence (see [Correlation confidence](#correlation-edge-confidence-and-corroboration)
     below), converted to the 0–100 scale.

The **pivot ranking** endpoint uses yet another convention on the *same* correlation-edge
confidence: `rank_pivots()` bands relevance as `high` if `provider_count > 1 or edge.confidence >= 0.85`,
`medium` if `edge.confidence >= 0.6`, else `low` — evaluated on the **raw 0–1 engine value**, even
though the pivot dict it emits also carries a `confidence` key already converted to 0–100
(`backend/app/evidence/pivot.py:45-47`). Don't assume the 0.85/0.6 thresholds apply to the 0–100
value in the same object.

---

## ProviderStatus

The `ProviderStatus` enum (`backend/app/providers/base.py:31-38`) — the outcome of a single
provider's `run()` call for one IOC lookup:

| Value | Meaning | Set by |
|---|---|---|
| `ok` | Provider returned usable data | Connector `fetch()` on success |
| `error` | Unexpected failure (non-retryable exception, or HTTP error not otherwise mapped) | `BaseProvider.run()` (`base.py:126-151`), orchestrator on exhausted retries |
| `timeout` | Provider call exceeded `provider_timeout_seconds` | Orchestrator (`orchestrator.py:59-78`), `error_message="Timed out after {N}s"` |
| `rate_limited` | Provider signaled its own rate limit | `BaseProvider.run()` maps HTTP `429`, `403`, `509` → `rate_limited` (509 is PhishTank's documented over-limit code, `base.py:129`) |
| `not_configured` | Provider requires an API key/credential that isn't set | `BaseProvider.run()` (`base.py:112-123`) when `requires_key=True` and `configured=False` |
| `unsupported_ioc` | The IOC type isn't in this provider's `supported_types` | `BaseProvider.run()` short-circuit (`base.py:101-111`), before any network call |
| `no_data` | Provider reached out successfully but had nothing on this IOC | Connector-specific (e.g. VirusTotal 404, AbuseIPDB empty `data`, abuse.ch `"ok"` status with zero entries) |

Only `ok` results are cached in Redis (`orchestrator.py:80-83`) and only `ok` results contribute
nodes/edges to the correlation graph (`correlation/engine.py:106`) or top-level evidence records
(`evidence/builder.py:75-76`). See [PROVIDERS.md](PROVIDERS.md) for the per-connector mapping
rules (e.g. why abuse.ch auth failures are deliberately `error`, not `no_data` — a misconfigured
key must never look like a clean verdict, per `abusech.py:5-9`).

---

## EvidenceType

The `EvidenceType` enum (`backend/app/models/evidence.py:19-28`) — the classification of a single
persisted `EvidenceItem` row. All 9 values are actually producible by
`backend/app/evidence/builder.py`:

| Value | Produced by | Path |
|---|---|---|
| `detection` | `build_evidence_from_providers()` | Top-level per-provider record, when `summary.reputation` is `unknown` or `no data` |
| `reputation` | `build_evidence_from_providers()` | Top-level per-provider record, for any other reputation value |
| `other` | `build_evidence_from_providers()` | One record per entry in `summary.interesting_findings` |
| `malware_association` | `build_evidence_from_correlation()` | Correlation edge whose target type is `malware_family` |
| `threat_actor_association` | `build_evidence_from_correlation()` | Correlation edge whose target type is `threat_actor` |
| `campaign_association` | `build_evidence_from_correlation()` | Correlation edge whose target type is `campaign` |
| `mitre_technique` | `build_evidence_from_correlation()` | Correlation edge whose target type is `mitre_technique` |
| `infrastructure` | `build_evidence_from_correlation()` | Correlation edge whose target type is in `NETWORK_TYPES` (see [IOC](#ioc-indicator-of-compromise)) plus `tls_certificate` / `asn` |
| `relationship` | `build_evidence_from_correlation()` | Fallback for any correlation-edge target type not covered above (e.g. `cve`) |

`build_evidence()` (`builder.py:142-147`) simply concatenates the provider-path and
correlation-path results — no other `EvidenceType` values exist. Evidence is deterministic: the
module docstring states explicitly "with NO AI involved" (`builder.py:1-10`).

---

## Correlation edge confidence and corroboration

The correlation engine (`backend/app/correlation/engine.py`) assigns each `GraphEdge` a 0–1
`confidence` float, from a fixed base-confidence table keyed by the source data field
(`_FIELD_BASE_CONFIDENCE`, `engine.py:77-90`):

| Field | Base confidence |
|---|---|
| `resolved_ips`, `resolved_domains`, `asn` | 0.9 |
| `certificates` | 0.85 |
| `related_urls`, `related_hashes`, `cves` | 0.8 |
| `mitre_techniques` | 0.75 |
| `related_domains` | 0.7 |
| `malware_families`, `threat_actors`, `campaigns` | 0.5 |
| *(any other field)* | 1.0 if the provider's category is `threat_intel`, else 0.7 |

When multiple providers independently assert the *same* `(source, target, relationship)` edge,
confidence is boosted: `boosted = min(1.0, max_base_confidence + 0.15 * (distinct_providers - 1))`
(`_CORROBORATION_BONUS_PER_PROVIDER = 0.15`, `engine.py:94, 154-175`). The provenance string
(comma-joined provider IDs) is what `rank_pivots()` and `build_evidence_from_correlation()` later
split on to decide corroboration and to label the evidence source as `"Correlation Engine
(corroborated)"` vs. a single provider ID (`evidence/builder.py:122-123`, `evidence/pivot.py:35`).

Only `correlate()` results built from providers with `status == ok` contribute edges at all — a
failed provider contributes zero nodes/edges (`engine.py:106`).

---

## ATT&CK / MITRE

References the [MITRE ATT&CK](https://attack.mitre.org/) framework. Two IOC-facing concepts:

- **`mitre_technique`** — an `IOCType` value matched by `detect_ioc_type()` via
  `^T\d{4}(\.\d{3})?$` (case-insensitive), matching both a bare technique ID (`T1059`) and a
  subtechnique (`T1059.001`) (`backend/app/ioc/detector.py:84-85`).
- **MITRE ATT&CK provider** — `provider_id="mitre_attack"` (`backend/app/providers/mitre_attack.py`),
  category `threat_intel`, `supported_types={mitre_technique}`, free/no-key, fetches the ~30MB
  public STIX enterprise-attack bundle from
  `https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json`,
  cached in-process for up to 3600s.

The AI schema's `_MitreTactic` literal (`backend/app/ai/schemas.py:41-45`) constrains
`MitreMapping.tactic` to the 14 exact ATT&CK `phase_name` slugs (e.g. `initial-access`,
`command-and-control`) so the frontend's exact-string-equality tactic grouping
(`MitreMatrix.tsx`) never splits one tactic into two differently-cased buckets.
`MitreMapping.grounded` (`ai/schemas.py:85-92`) is `true` only if the technique was explicitly
surfaced by a provider (e.g. the MITRE ATT&CK provider's `mitre_techniques` field); the AI must
set it `false` for a technique it inferred itself rather than one grounded in provider data.

Related, separate `IOCType` values that are **not** produced by `detect_ioc_type()`'s MITRE
matching but exist for adjacent standards: `cve` (`^CVE-\d{4}-\d{4,7}$`), `cwe`
(`^CWE-\d{1,5}$`), `capec` (`^CAPEC-\d{1,5}$`) — checked in the order CVE → CAPEC → CWE →
`mitre_technique` (`detector.py:78-85`).

---

## JA3 / JA4

TLS client-fingerprint identifiers.

- **JA4**: matched by `detect_ioc_type()` via
  `^[a-z0-9]{10}_[a-fA-F0-9]{12}_[a-fA-F0-9]{12}$` (case-insensitive)
  (`_JA4_RE`, `backend/app/ioc/detector.py:112-113`). The 10-character prefix encodes
  protocol(1) + version(2) + SNI(1) + cipher\_count(2) + ext\_count(2) + ALPN(2) — e.g.
  `q13i0207h3_55b375c5d22e_cd85d2d88918`. This check runs **before** the MD5 check specifically
  because JA4 has its own distinguishable shape.
- **JA3**: **NOT IMPLEMENTED** as a distinguishable classification. `IOCType.JA3` exists as an
  enum value and a regex (`_JA3_RE`, `detector.py:15`, identical shape to MD5:
  `^[a-fA-F0-9]{32}$`) exists in a comment describing a "caller hint" disambiguation scheme, but
  that regex is never invoked anywhere in `detector.py`. Every 32-hex-character string resolves to
  `md5`, never `ja3`, and no such hint mechanism exists in the reviewed request schemas (the only
  override, `ioc_type_hint`, is a generic `Optional[IOCType]`, not JA3-specific).

---

## ASN

Autonomous System Number. `IOCType.ASN` is matched by `detect_ioc_type()` via
`^(?:AS|ASN)\s?(\d+)$` (case-insensitive) (`_ASN_RE`, `backend/app/ioc/detector.py:100-101`) —
**requires** an explicit `AS`/`ASN` prefix. This was a deliberate hardening: without the required
prefix, a bare hex hash beginning with the letter `a` followed by digits (e.g.
`a1111111111111111111111111111111`) would otherwise satisfy a looser ASN pattern before the hash
regexes ran; a regression test pins this case to resolve as `md5`, not `asn`
(`backend/app/tests/unit/test_ioc_detector.py:64`).

`asn` is part of `NETWORK_TYPES` (`backend/app/ioc/types.py:44-53`) and is supported by the
WHOIS/RDAP provider (`whois_rdap.py`, via `rdap.org`) and by the correlation engine's
`_RELATIONSHIP_EXTRACTORS` table as the `belongs_to_asn` relationship, with a 0.9 base confidence
(`correlation/engine.py:57-90`).

---

## Roles and permissions (`ROLE_PERMISSIONS`)

Three roles, defined by `Role` (`backend/app/models/user.py:11-14`): `admin`, `analyst`, `viewer`.
The permission matrix `ROLE_PERMISSIONS` (`backend/app/models/user.py:31-44`) is a
`dict[Role, set[str]]` consumed by `require_permission(permission)`
(`backend/app/auth/rbac.py`), a FastAPI dependency factory that 403s with
`"Role '{role}' lacks permission '{permission}'"` if the current user's role's set doesn't
contain the requested permission string.

| Permission string | `admin` | `analyst` | `viewer` | Gates |
|---|---|---|---|---|
| `lookup:create` | ✓ | ✓ | | `POST /lookup/stream` |
| `lookup:read` | ✓ | ✓ | ✓ | `GET /lookup/{id}`, `GET /lookup`, `GET /lookup/{id}/pivots`, `GET /providers/health` |
| `lookup:export` | ✓ | ✓ | | (lookup export) |
| `provider:manage` | ✓ | | | (provider administration) |
| `user:manage` | ✓ | | | (user administration) |
| `audit:read` | ✓ | | | (audit log access) |
| `evidence:read` | ✓ | ✓ | ✓ | Evidence retrieval |
| `analysis:generate` | ✓ | ✓ | | AI analysis generation |
| `hunting:generate` | ✓ | ✓ | | Hunting-query generation |
| `copilot:query` | ✓ | ✓ | | Copilot queries |
| `basket:manage` | ✓ | ✓ | | `POST /basket` |
| `case:create` | ✓ | ✓ | | Case creation |
| `case:read` | ✓ | ✓ | ✓ | Case retrieval |
| `case:write` | ✓ | ✓ | | Case editing |
| `case:close` | ✓ | ✓ | | Case closure |

`viewer` is strictly read-only: `{lookup:read, evidence:read, case:read}` — it cannot create
lookups, manage baskets, or touch cases beyond reading them (`user.py:43`). The first user ever
registered via `POST /auth/register` is assigned `admin`; every registration attempt after that
is rejected with `403 Forbidden` — every account after the first admin must be created by an
existing admin via `POST /admin/users` or the Administration page, which lets the admin pick the
new account's role (per [SECURITY.md](SECURITY.md)). Full permission-string-to-route mapping is in
[API_DOCUMENTATION.md](API_DOCUMENTATION.md) / [SECURITY.md](SECURITY.md).

---

## Other platform-specific terms

| Term | Definition | Source |
|---|---|---|
| **Basket** | A saved collection of IOCs a user is tracking, added via `POST /basket`, gated by the `basket:manage` permission. | `backend/app/api/routes/basket.py`, `backend/app/schemas/basket.py` |
| **Case** | A grouped investigation record with associated IOCs, notes, and reports; cascade-deletes its children on removal. | `backend/app/models/case.py` (per [DATA_MODEL.md](DATA_MODEL.md)) |
| **Pivot** | A one-click suggested next-IOC-to-investigate, derived purely from correlation edges touching the seed IOC — deliberately not AI-generated ("a pure sort over real correlation edges can never hallucinate a pivot target," `backend/app/evidence/pivot.py:1-5`). Returned by `GET /api/v1/lookup/{lookup_id}/pivots`. | `backend/app/evidence/pivot.py`, `backend/app/api/routes/pivot.py` |
| **Corroborating providers** | The count of distinct provider IDs (parsed from an edge's comma-joined `provenance` string) that independently asserted the same correlation edge; drives both the pivot `relevance` band and the correlation-engine confidence boost. | `backend/app/evidence/pivot.py:35`, `backend/app/correlation/engine.py:94` |
| **Grounded** (AI mapping) | A boolean on `MitreMapping` indicating whether an ATT&CK technique the AI cited was explicitly present in provider data (`true`) vs. inferred by the model itself (`false`). Checked downstream by `_ground_final_assessment()`, which sets `grounded=False` on any technique ID that doesn't match a real correlation-graph technique. | `backend/app/ai/schemas.py:85-92`, `backend/app/ai/service.py` |
| **Provider category** | One of `threat_intel`, `sandbox`, `passive_dns`, `certificate_intel`, `whois`, `vulnerability`, `osint` (`ProviderCategory` enum). | `backend/app/providers/base.py:21-28` |
| **from_cache** | Boolean on `ProviderResult` indicating the result was served from the Redis provider cache (keyed by SHA256 of the IOC value) rather than a live network call. | `backend/app/providers/base.py:41-73`, `backend/app/core/cache.py:24-39` |

---

## Terms with NO code/UI presence (excluded deliberately)

The following would be expected in a generic threat-intel glossary but are **NOT IMPLEMENTED** in
this platform and are therefore not defined above as live concepts: Neo4j graph storage (config
vars and docstrings reference it, but no driver import, session, or write/query call exists
anywhere in `backend/`), OpenSearch, STIX/TAXII ingestion, and per-provider circuit breakers (all
retry/backoff logic lives centrally in `backend/app/providers/orchestrator.py`, not in individual
connectors). See [PROVIDERS.md](PROVIDERS.md) and [ARCHITECTURE.md](ARCHITECTURE.md) for details.
