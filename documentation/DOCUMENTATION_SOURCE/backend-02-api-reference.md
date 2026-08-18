# API Reference

This chapter is the exhaustive endpoint-by-endpoint reference for the HORIZON GRID backend's HTTP API. Every route defined under `backend/app/api/routes/*.py` is documented here — method, path, purpose, authentication/permission requirement, request body, response shape, and error cases — traced directly to the route source. Narrative context (why the pipeline is shaped this way, how the pieces fit together) is covered in the Architecture and Data Flow chapters; this chapter is deliberately just the contract.

All 51 routes share one global prefix, `settings.api_v1_prefix = "/api/v1"` (`backend/app/core/config.py:20`), applied in `backend/app/main.py:38-47` via `app.include_router(..., prefix=settings.api_v1_prefix)`. Routers are registered, and therefore documented below, in this order: **auth → lookup → providers → ai_config → analysis → hunting → pivot → basket → cases → runtime**, plus a newer `dashboard` router documented as an addendum in §11 below. (`app/main.py` also registers `routes/admin.py` and `routes/security_assessment.py` after `runtime` and ahead of `dashboard` in real registration order; both are out of scope for this update and are not yet covered by this reference.)

| # | Router file | Base path | Endpoints |
|---|---|---|---|
| 1 | `routes/auth.py` | `/api/v1/auth` | 4 |
| 2 | `routes/lookup.py` | `/api/v1/lookup` | 5 |
| 3 | `routes/providers.py` | `/api/v1/providers` | 2 |
| 4 | `routes/ai_config.py` | `/api/v1/ai` | 2 |
| 5 | `routes/analysis.py` | `/api/v1/lookup/{lookup_id}/analysis` | 10 |
| 6 | `routes/hunting.py` | `/api/v1/lookup/{lookup_id}` | 2 |
| 7 | `routes/pivot.py` | `/api/v1/lookup/{lookup_id}/pivots` | 1 |
| 8 | `routes/basket.py` | `/api/v1/basket` | 5 |
| 9 | `routes/cases.py` | `/api/v1/cases` | 8 |
| 10 | `routes/runtime.py` | `/api/v1/runtime` | 10 |
| 11 | `routes/dashboard.py` | `/api/v1/dashboard` | 2 |

**Total: 51 endpoints.** Two additional endpoints are defined directly in `app/main.py`, outside `app/api/routes/`, and are out of scope for this reference but noted for completeness at the end of the chapter: `GET /health` (`main.py:63-65`, no prefix, no auth) and `GET /metrics` (Prometheus instrumentator, `main.py:36`).

[FIGURE: backend-02-api-reference-diagram-1.png | Diagram: API Reference]
Diagram: Router registration order and base paths, all mounted under the global `/api/v1` prefix. Registration order determines only documentation order here -- FastAPI's routing is path-based, not order-sensitive, except where two routers could otherwise share an ambiguous prefix (none do in this codebase).

## How to Read This Reference

Every endpoint below follows the same template:

- **Purpose** — what the endpoint does and why it exists.
- **Auth** — the FastAPI dependency gating the route. Most routes call `require_permission("<permission-string>")`; a few require only a valid access token via `Depends(get_current_user)`; the three public auth routes require neither.
- **Path/Query params** — any parameters embedded in the URL or passed as query strings.
- **Request body** — the Pydantic schema fields the client must/may send, or "none" for routes with no body.
- **Response** — the shape of a successful response, including the HTTP status code when it is not the default `200`.
- **Errors** — HTTP status codes and the specific condition that triggers each one, beyond FastAPI's automatic `422` for a request body that fails Pydantic validation (which applies to every typed request body and is not re-stated per endpoint unless it has a distinct, hand-written `422`).

### Authentication and permission mechanics

Every `require_permission(...)` dependency resolves through the same two-step chain, defined in `app/auth/rbac.py`:

1. `Depends(get_current_user)` (`rbac.py:32-47`) decodes the request's `Authorization: Bearer <token>` header as a JWT access token. It raises **401** with detail `"Could not validate credentials"` if the header is missing, the token is invalid/expired, the token's type claim is not `"access"` (e.g. a refresh token was used where an access token was expected), or the resolved user's `is_active` flag is false.
2. `require_permission(permission)` (`rbac.py:50-62`) then checks whether `permission in ROLE_PERMISSIONS.get(user.role, set())`. If not, it raises **403** with detail `f"Role '{user.role.value}' lacks permission '{permission}'"`.

There are exactly three roles (`app/models/user.py:11-14`): `admin`, `analyst`, `viewer`. The full permission-to-role matrix (`ROLE_PERMISSIONS`) lives in `app/models/user.py` and is described in the Security Architecture chapter; the permission string required by each route is called out individually below. Fourteen distinct permission strings are checked anywhere in the API: `provider:manage`, `lookup:create`, `lookup:read`, `evidence:read`, `analysis:generate`, `copilot:query`, `hunting:generate`, `basket:manage`, `case:read`, `case:create`, `case:write`, `case:close`, `audit:read`, `dashboard:read`. `dashboard:read` is the newest of the fourteen — deliberately granted to all three roles (admin, analyst, viewer) alike, since it gates read-only operational-visibility endpoints only, never anything credential-management or write-capable.

---

## 1. Authentication — `routes/auth.py`

Base path `/api/v1/auth`. All four endpoints are unauthenticated at the route level except `/me`; `/register` and `/login` are the only ways to obtain a token in the first place.

### `POST /api/v1/auth/register`
`app/api/routes/auth.py:20`

- **Purpose:** Register a new user account. **Bootstrap-only:** the very first account ever created on an instance is automatically granted the `admin` role; every registration attempt after that is rejected outright rather than receiving `analyst`.
- **Auth:** None (public), but only succeeds while the `users` table is empty.
- **Request body** (`RegisterRequest`, `app/schemas/auth.py:16-19`):

| Field | Type | Notes |
|---|---|---|
| `email` | `EmailStr` | required |
| `password` | `str` | min 8, max 72 characters (72 is bcrypt's real input limit) |
| `full_name` | `str` | optional, defaults to `""` |

- **Response** (`UserResponse`, HTTP **201**, only on an empty `users` table): `id: str`, `email: str`, `full_name: str`, `role: Role` (always `admin` for this route).
- **Errors:** **400** `"Email already registered"` if the email already exists (`auth.py:25`); **403** `"Self-registration is closed. Ask an administrator to create your account from the Administration page."` if at least one user already exists (`auth.py:32-35`) — use `POST /api/v1/admin/users` instead.

### `POST /api/v1/auth/login`
`app/api/routes/auth.py:42`

- **Purpose:** Authenticate with email and password; issues a JWT access token and refresh token pair.
- **Auth:** None (public).
- **Request body** (`LoginRequest`): `email: EmailStr`, `password: str` (max 72 characters).
- **Response** (`TokenResponse`): `access_token: str`, `refresh_token: str`, `token_type: str` (always `"bearer"`).
- **Errors:** **401** `"Invalid email or password"` on bad credentials (`auth.py:47`); **403** `"Account disabled"` if the matched user's `is_active` is false (`auth.py:49`).

### `POST /api/v1/auth/refresh`
`app/api/routes/auth.py:56`

- **Purpose:** Exchange a still-valid refresh token for a new access/refresh token pair, without re-sending a password.
- **Auth:** None at the dependency level — validity is enforced by decoding the refresh token itself, not a bearer dependency.
- **Request body** (`RefreshRequest`): `refresh_token: str`.
- **Response** (`TokenResponse`): identical shape to `/login`.
- **Errors:** **401** `"Invalid refresh token"` if the token is missing, malformed, or its type claim is not `"refresh"` (`auth.py:60`); **401** (same message) if the user it resolves to is missing or inactive (`auth.py:64`).

### `GET /api/v1/auth/me`
`app/api/routes/auth.py:71`

- **Purpose:** Return the identity of the caller associated with the presented access token.
- **Auth:** `Depends(get_current_user)` — a valid access token is required; there is no specific permission string on this route.
- **Request body:** none.
- **Response** (`UserResponse`): `id`, `email`, `full_name` (hard-coded to `""` in this handler — not populated from the database on this particular route), `role`.
- **Errors:** **401** `"Could not validate credentials"` for any invalid/missing/expired token or inactive user.

---

## 2. IOC Lookup — `routes/lookup.py`

Base path `/api/v1/lookup`. This is the core investigation pipeline: creating a lookup, streaming its lifecycle, re-running the AI assessment, and reading back results.

### `POST /api/v1/lookup/stream`
`app/api/routes/lookup.py:51`

- **Purpose:** Create a lookup, fan the submitted IOC out to every applicable provider in parallel, and stream the entire investigation lifecycle back to the client as Server-Sent Events (SSE) — detection, each provider's result and AI summary as they complete, the correlation graph, and the final AI assessment.
- **Auth:** `require_permission("lookup:create")`.
- **Request body** (`LookupCreateRequest`, `app/schemas/lookup.py:9-20`):

| Field | Type | Notes |
|---|---|---|
| `value` | `str` | the raw IOC string |
| `ioc_type_hint` | `Optional[IOCType]` | forces type classification if auto-detection would be ambiguous |
| `provider_ids` | `Optional[list[str]]` | restricts the fan-out to specific providers; omit to use all applicable providers |
| `ai_backend` | `Optional[str]` | overrides the active AI backend for this one lookup |

- **Response:** `StreamingResponse`, media type `text/event-stream` — not a single JSON body. Named SSE events, in order: `detected` (`{lookup_id, ioc_value, ioc_type}`), then a `provider_result` (the provider's `to_dict()`) followed by a `provider_summary` for each provider as it finishes, `correlation` (`{nodes, edges}`), `final_assessment` (the final assessment's `model_dump()`), and `done` (`{lookup_id}`). On a mid-stream failure, an `error` event (`{message}`) is emitted in place of `final_assessment`/`done`.
- **Errors:** **429** with a message referencing `settings.lookup_rate_limit_max_calls` / `lookup_rate_limit_window_seconds` when the caller's rate limit is exceeded (`lookup.py:68-75`); **422** `"Could not determine IOC type; pass ioc_type_hint."` if automatic type detection fails and no hint was supplied (`lookup.py:80`). Provider or pipeline exceptions raised mid-stream are caught, logged, the lookup is marked `FAILED`, and the failure is surfaced as an `error` SSE event rather than an HTTP error status (`lookup.py:256-260`) — a client must inspect the event stream itself to detect failure, not just the initial HTTP response code.

### `POST /api/v1/lookup/{lookup_id}/reanalyze`
`app/api/routes/lookup.py:310`

- **Purpose:** Re-run only the final-assessment AI step against an already-completed lookup's persisted evidence, using an explicitly chosen AI backend, without re-querying providers. The result is stored as an additional, non-primary `FinalAssessmentRecord` — the lookup's original primary verdict is untouched.
- **Auth:** `require_permission("lookup:create")`.
- **Path param:** `lookup_id` (UUID string).
- **Request body** (`ReanalyzeRequest`, inline `lookup.py:306-307`): `ai_backend: str`.
- **Response:** `{id: str, ai_backend: str, ai_model: str | None, assessment: dict}`.
- **Errors:** **404** `"Lookup not found"` (`lookup.py:331`); **400** `"Lookup must be completed before it can be re-analyzed."` if the lookup's status is not `COMPLETED` (`lookup.py:333`).

### `GET /api/v1/lookup/{lookup_id}/assessments`
`app/api/routes/lookup.py:387`

- **Purpose:** List every final assessment ever generated for a lookup — the original plus every subsequent re-analysis — so backends can be compared side by side against the same evidence.
- **Auth:** `require_permission("lookup:read")`.
- **Path param:** `lookup_id`.
- **Request body:** none.
- **Response:** list of `{id, ai_backend, ai_model, is_primary: bool, assessment: dict, created_at: str}`, ordered ascending by `created_at`.
- **Errors:** none explicit — an unknown or row-less `lookup_id` simply returns an empty list; this route does not 404 on a missing lookup.

### `GET /api/v1/lookup/{lookup_id}`
`app/api/routes/lookup.py:416`

- **Purpose:** Fetch full detail for a single lookup — provider results, AI summaries, the primary final assessment, and a correlation graph rebuilt from persisted rows.
- **Auth:** `require_permission("lookup:read")`.
- **Path param:** `lookup_id`.
- **Request body:** none.
- **Response:** `{id, ioc_value, ioc_type, status, final_verdict: str | None, risk_score, confidence_score, final_assessment: dict | None, provider_results: [{provider_id, provider_name, category, status, data, source_url, error_message, latency_ms}], ai_summaries: [dict], created_at, correlation: {nodes: [{node_id, ioc_type, value, labels: []}], edges: [{source, target, relationship, confidence, provenance}]}}`. The correlation payload is rebuilt by `_correlation_payload` (`lookup.py:462-501`) and always includes the seed IOC node even when it has zero edges.
- **Errors:** **404** `"Lookup not found"` (`lookup.py:433`).

### `GET /api/v1/lookup` (list)
`app/api/routes/lookup.py:504`

- **Purpose:** List recent lookups across the whole team — this is a shared, not per-user, view.
- **Auth:** `require_permission("lookup:read")`.
- **Query params:** `limit: int = 50`, clamped server-side to the range `[1, 200]` (`lookup.py:513`).
- **Request body:** none.
- **Response:** list of `{id, ioc_value, ioc_type, status, final_verdict: str | None, risk_score, confidence_score, created_at}`, ordered by `created_at` descending.
- **Errors:** none explicit.

---

## 3. Providers — `routes/providers.py`

Base path `/api/v1/providers`. Read-only health reporting plus a live credential test used by the setup wizard and the Manage Providers UI.

### `GET /api/v1/providers/health`
`app/api/routes/providers.py:11`

- **Purpose:** Report the real, database-backed health of every registered IOC provider across four rolling time windows (1h/24h/7d/30d) — status, success rate, average latency, consecutive-failure count, and rate-limited count per window, computed from actual persisted provider-call outcomes. **This route's behavior changed in this update:** it previously returned only static configuration metadata (`configured`/`requires_key`/`supported_types`) from a stub, `get_provider_health()` (`app/providers/registry.py`), which never touched the database or reported any real status, latency, or failure information — that stub is now dead code. The route now delegates to `get_provider_health_history()` (`app/core/dashboard.py`), covered in the Architecture chapter's Executive Dashboard subsection.
- **Auth:** `require_permission("dashboard:read")` — changed from the prior `lookup:read`. Every role that previously had `lookup:read` also has `dashboard:read`, so this change does not reduce anyone's access.
- **Request body:** none.
- **Response:** a list of per-provider dicts, one for every registered provider (including providers with zero recorded calls ever) — `{provider_id, provider_name, category, configured, requires_key, supported_types: list[str], "1h": {...}, "24h": {...}, "7d": {...}, "30d": {...}}`, where each window object is `{status, success_rate, avg_latency_ms, consecutive_failures, rate_limited_count}`. `status` is one of `"healthy"`/`"degraded"`/`"down"`/`"unknown"` — a window with zero real attempts always reports `"unknown"`, never `"healthy"`; a provider correctly reporting "nothing found" (`no_data`) or "doesn't apply to this IOC type" (`unsupported_ioc`) for an attempt counts as a healthy outcome, not a failure. `success_rate` and `avg_latency_ms` are `null` (not `0`) when the window has zero qualifying attempts, so "no data" is never rendered as a misleading zero.
- **Errors:** none explicit.

### `POST /api/v1/providers/{provider_id}/test`
`app/api/routes/providers.py:20`

- **Purpose:** Live credential check for a single IOC provider — makes one real outbound call using candidate credentials supplied in the request body. The credentials are never persisted by this route; it exists purely to validate a key before it is saved.
- **Auth:** `require_permission("provider:manage")`.
- **Path param:** `provider_id: str`.
- **Request body** (`ProviderTestRequest`, inline `providers.py:16-17`): `credentials: dict[str, str]`.
- **Response:** `{provider_id: str, ok: bool, message: str, latency_ms: <type per test_provider_connection result>}`.
- **Errors:** none raised as `HTTPException` in this route — failures from the underlying connection test surface through the `ok`/`message` fields of a `200` response, not as an HTTP error status.

---

## 4. AI Configuration — `routes/ai_config.py`

Base path `/api/v1/ai`. Live AI-backend credential testing and model-list discovery for the setup wizard / Manage Providers UI.

### `POST /api/v1/ai/test`
`app/api/routes/ai_config.py:39`

- **Purpose:** Live credential check for any of the five AI backends (Ollama, Anthropic, Bedrock, Gemini, Groq) — makes one real, minimal chat request with candidate credentials. Never persists anything.
- **Auth:** `require_permission("provider:manage")`.
- **Request body** (`AITestRequest`, inline `ai_config.py:33-36`): `backend: str`, `credentials: dict[str, str]` (default `{}`), `model: str | None` (default `None`).
- **Response:** `{backend: str, ok: bool, message: str, model: str | None, latency_ms: <type>}`.
- **Errors:** none raised as `HTTPException` — failures surface through `ok`/`message`.

### `POST /api/v1/ai/{backend}/models`
`app/api/routes/ai_config.py:63`

- **Purpose:** Return the model list for the AI-backend picker's dropdown. Live discovery for Groq (its `/models` API) and Ollama (`GET {base_url}/api/tags`); static curated lists for Anthropic, Gemini, and Bedrock; an empty list for an unrecognized backend.
- **Auth:** `require_permission("provider:manage")`.
- **Path param:** `backend: str`.
- **Request body** (`ModelListRequest`, inline `ai_config.py:59-60`): `credentials: dict[str, str]` (default `{}`).
- **Response** (shape varies by backend, always includes `backend` and `models`):
  - Groq: `{backend, models: list[str], source: "fallback" | "live", default: str}` — falls back to a hard-coded model list if no `api_key` is supplied or the live call raises `httpx.HTTPError` (`ai_config.py:76-85`).
  - Ollama: `{backend, models: list[str], source: "live" | "fallback", default: str}` — live via `GET {base_url}/api/tags` if a `base_url` is supplied and returns HTTP 200 with model names; otherwise a static two-item fallback list (`ai_config.py:87-99`).
  - Anthropic / Gemini / Bedrock: `{backend, models: list[str], source: "static", default: str}` (`ai_config.py:101-104`).
  - Unknown backend: `{backend, models: [], source: "unknown", default: None}` (`ai_config.py:102-103`).
- **Errors:** none raised as `HTTPException` — provider-side HTTP errors are caught and logged, degrading to the fallback/static response instead of failing the request.

---

## 5. Lookup Analysis — `routes/analysis.py`

Base path `/api/v1/lookup/{lookup_id}/analysis`. These are the "explain the verdict" endpoints: on-demand AI generations grounded in a *completed* lookup's persisted evidence ledger. Every endpoint in this section shares one loader, `_load_lookup` (`analysis.py:45-51`), which raises **404** `"Lookup not found"` if the lookup does not exist, and — for every endpoint except `/evidence` — also raises **409** `f"Lookup is not completed yet (status={lookup.status.value})"` if the lookup's status is not `COMPLETED`. That shared behavior is stated once here and referenced, not repeated, in each endpoint's Errors line below.

### `GET /api/v1/lookup/{lookup_id}/analysis/evidence`
`app/api/routes/analysis.py:70`

- **Purpose:** Return the raw evidence ledger for a lookup (the "Show Receipts" / Evidence tab). Purely deterministic — no AI call is made.
- **Auth:** `require_permission("evidence:read")`.
- **Request body:** none.
- **Response:** list of `{id, evidence_type: str, source_label, provider_id, claim, interpretation, confidence, related_ioc_type, related_ioc_value, source_url, observed_at, created_at: str}`.
- **Errors:** **404** `"Lookup not found"` only — this is the one endpoint in this router with no `409` completed-status gate.

### `POST /api/v1/lookup/{lookup_id}/analysis/why`
`app/api/routes/analysis.py:99`

- **Purpose:** AI explanation of why the IOC is, or is not, considered malicious, grounded in the evidence ledger.
- **Auth:** `require_permission("analysis:generate")`.
- **Request body:** none.
- **Response** (`WhyMaliciousExplanation`, `app/ai/analysis_schemas.py:41-44`): `verdict_restated: str`, `reasons: list[{reason: str, evidence_ids: list[str]}]`, `caveat: str | None`.
- **Errors:** **404** / **409** per the shared loader above.

### `POST /api/v1/lookup/{lookup_id}/analysis/what-is-this`
`app/api/routes/analysis.py:110`

- **Purpose:** AI plain-language and technical explanation of what the IOC actually is.
- **Auth:** `require_permission("analysis:generate")`.
- **Request body:** none.
- **Response** (`WhatIsThisIOC`, `analysis_schemas.py:47-52`): `plain_language_summary: str`, `technical_explanation: str`, `evidence_ids: list[str]`, `confidence_narrative: str`, `related_infrastructure: list[str]`.
- **Errors:** **404** / **409**.

### `POST /api/v1/lookup/{lookup_id}/analysis/disagreement`
`app/api/routes/analysis.py:121`

- **Purpose:** AI summary of where the queried providers agree and disagree on this IOC.
- **Auth:** `require_permission("analysis:generate")`.
- **Request body:** none.
- **Response** (`DisagreementSummary`, `analysis_schemas.py:55-60`): `agreement: str`, `conflict: str`, `missing_data: str`, `most_reliable_evidence: str`, `evidence_ids: list[str]`.
- **Errors:** **404** / **409**.

### `POST /api/v1/lookup/{lookup_id}/analysis/false-positive`
`app/api/routes/analysis.py:132`

- **Purpose:** AI assessment of false-positive likelihood — e.g. is the IOC actually a CDN edge, shared-hosting IP, or scanner rather than genuinely malicious infrastructure.
- **Auth:** `require_permission("analysis:generate")`.
- **Request body:** none.
- **Response** (`FalsePositiveAssessment`, `analysis_schemas.py:63-73`): `likely_false_positive: bool`, `candidate_categories: list[Literal["cdn","cloud_provider","shared_hosting","nat","vpn","proxy","security_scanner","search_crawler","monitoring_system","legitimate_business_infrastructure","none"]]`, `explanation: str`, `evidence_ids: list[str]`.
- **Errors:** **404** / **409**.

### `POST /api/v1/lookup/{lookup_id}/analysis/challenge`
`app/api/routes/analysis.py:143`

- **Purpose:** AI "red-team" self-challenge of the current verdict — actively argues against the assessment the platform already produced.
- **Auth:** `require_permission("analysis:generate")`.
- **Request body:** none.
- **Response** (`ChallengeVerdict`, `analysis_schemas.py:76-82`): `supporting_evidence: list[{reason, evidence_ids}]`, `contradictory_evidence: list[{reason, evidence_ids}]`, `missing_evidence: list[str]`, `alternative_explanation: str`, `final_confidence: Literal["low","medium","high"]`, `final_confidence_rationale: str`.
- **Errors:** **404** / **409**.

### `POST /api/v1/lookup/{lookup_id}/analysis/next-actions`
`app/api/routes/analysis.py:154`

- **Purpose:** AI-suggested next investigative actions, informed by the evidence ledger and the correlation graph.
- **Auth:** `require_permission("analysis:generate")`.
- **Request body:** none.
- **Response** (`SmartNextActions`, `analysis_schemas.py:85-94`): `actions: list[{action: str, target_ioc_value: str | None, target_ioc_type: str | None, rationale: str, priority: Literal["low","medium","high"]}]`.
- **Errors:** **404** / **409**.

### `POST /api/v1/lookup/{lookup_id}/analysis/gaps`
`app/api/routes/analysis.py:167`

- **Purpose:** AI-identified intelligence gaps, informed by which providers returned data and which did not.
- **Auth:** `require_permission("analysis:generate")`.
- **Request body:** none.
- **Response** (`IntelligenceGaps`, `analysis_schemas.py:97-103`): `gaps: list[{gap: str, how_to_close: str}]`.
- **Errors:** **404** / **409**.

### `POST /api/v1/lookup/{lookup_id}/analysis/score-explanation`
`app/api/routes/analysis.py:185`

- **Purpose:** AI explanation of how the lookup's numeric risk score was derived.
- **Auth:** `require_permission("analysis:generate")`.
- **Request body:** none.
- **Response** (`ScoreExplanation`, `analysis_schemas.py:106-114`): `components: list[{component: str, contribution: str, evidence_ids: list[str]}]`, `summary: str`.
- **Errors:** **404** / **409**.

### `POST /api/v1/lookup/{lookup_id}/analysis/copilot`
`app/api/routes/analysis.py:196`

- **Purpose:** Free-form Q&A ("Copilot") over a lookup's evidence, correlation graph, and optional analyst notes.
- **Auth:** `require_permission("copilot:query")` — note this is the one endpoint in this router gated by a different permission string than `analysis:generate`.
- **Request body:** raw, untyped `dict`, documented inline as `{"question": str, "notes": list[str] (optional)}` (`analysis.py:203`).
- **Response** (`CopilotAnswer`, `analysis_schemas.py:153-156`): `answer: str`, `evidence_ids: list[str]`, `suggested_follow_ups: list[str]` (max 4 items).
- **Errors:** **422** `"question is required"` if `question` is empty or whitespace-only after stripping (`analysis.py:206`); plus **404** / **409** from the shared loader.

---

## 6. Threat Hunting — `routes/hunting.py`

Base path `/api/v1/lookup/{lookup_id}`. Both endpoints share a local `_load_lookup` helper (`hunting.py:26-30`) that only checks existence — **404** `"Lookup not found"` — with **no completed-status gate**, unlike `analysis.py`'s helper. A hunting package or detection rule can therefore be requested even for a lookup that is still `RUNNING` or has `FAILED`.

### `POST /api/v1/lookup/{lookup_id}/hunt`
`app/api/routes/hunting.py:33`

- **Purpose:** Generate an exact-match plus expansion threat-hunting query package (Sigma, Splunk SPL, Sentinel KQL, etc.) for the lookup's seed IOC and its correlated related indicators.
- **Auth:** `require_permission("hunting:generate")`.
- **Query params:** `formats: list[str]`, default `["sigma","splunk_spl","sentinel_kql","elastic","qradar_aql","chronicle_yara_l","suricata","snort","zeek"]` (`hunting.py:21-23,36`).
- **Request body:** none.
- **Response** (`HuntingPackage`, `analysis_schemas.py:129-138`): `exact_match_queries: list[{format, query, detects}]`, `expansion_targets: list[{related_ioc_value, related_ioc_type, rationale}]`, `broader_queries: list[{format, query, detects}]`.
- **Errors:** **404** `"Lookup not found"` (`hunting.py:29`).

### `POST /api/v1/lookup/{lookup_id}/detection`
`app/api/routes/hunting.py:48`

- **Purpose:** Generate a single detection-rule draft, in a specified format, for the lookup's IOC and its current verdict/risk score.
- **Auth:** `require_permission("hunting:generate")`.
- **Query params:** `format: str`, required (`hunting.py:51`); valid values are constrained downstream by the `_DetectionRuleFormat` literal — `sigma, yara, splunk_spl, sentinel_kql, elastic, qradar_aql, chronicle_yara_l, suricata, snort, zeek`.
- **Request body:** none.
- **Response** (`DetectionRuleDraft`, `analysis_schemas.py:141-150`): `format`, `title`, `rule`, `detection_objective`, `data_source`, `logic_explanation`, `false_positive_considerations`, `severity: Literal["none","low","medium","high","critical"]`, `mitre_technique_ids: list[str]`.
- **Errors:** **404** `"Lookup not found"`.

---

## 7. Pivoting — `routes/pivot.py`

Base path `/api/v1/lookup/{lookup_id}/pivots`. A single deterministic (non-AI) endpoint.

### `GET /api/v1/lookup/{lookup_id}/pivots`
`app/api/routes/pivot.py:23`

- **Purpose:** Deterministic ranking of directly-related IOCs pulled from the correlation graph, ordered by confidence/corroboration, to support one-click pivoting from an investigation.
- **Auth:** `require_permission("lookup:read")`.
- **Query params:** `limit: int = 10`.
- **Request body:** none.
- **Response:** the return value of `rank_pivots(lookup.ioc_value, edge_likes, limit)` (`app/evidence/pivot.py`) — a ranked list; the exact field shape is defined in that module and is deliberately a pure, non-AI sort over correlation edges.
- **Errors:** **404** `"Lookup not found"` (`pivot.py:32`).

---

## 8. IOC Basket — `routes/basket.py`

Base path `/api/v1/basket`. A per-analyst scratch space of saved IOCs, scoped by the caller's own user ID — every endpoint here operates only on the requesting user's own basket items.

### `GET /api/v1/basket`
`app/api/routes/basket.py:34`

- **Purpose:** List the caller's own basket items, newest first.
- **Auth:** `require_permission("basket:manage")`.
- **Request body:** none.
- **Response:** list of `{id, ioc_value, ioc_type, note: str | None, latest_lookup_id: str | None, created_at}` (via the `_serialize` helper, `basket.py:23-31`).
- **Errors:** none explicit.

### `POST /api/v1/basket`
`app/api/routes/basket.py:45`

- **Purpose:** Add an IOC to the caller's basket. Deduplicates by exact `ioc_value` per owner, and best-effort attaches the most recent *completed* lookup for that value if one exists.
- **Auth:** `require_permission("basket:manage")`.
- **Request body** (`BasketAddRequest`, `app/schemas/basket.py:8-11`): `ioc_value: str`, `ioc_type_hint: Optional[IOCType]`, `note: Optional[str]`.
- **Response** (HTTP **201** for a new item, or the same serializer's output for an item that already existed): `{id, ioc_value, ioc_type, note, latest_lookup_id, created_at}`.
- **Errors:** **422** `"Could not determine IOC type; pass ioc_type_hint."` if the type cannot be auto-detected and no hint was supplied (`basket.py:54`).

### `DELETE /api/v1/basket/{item_id}`
`app/api/routes/basket.py:89`

- **Purpose:** Remove one basket item owned by the caller.
- **Auth:** `require_permission("basket:manage")`.
- **Path param:** `item_id`.
- **Request body:** none.
- **Response:** **204 No Content** (empty body).
- **Errors:** **404** `"Basket item not found"` if no such item exists, or it exists but is owned by a different user (`basket.py:98-99`) — ownership mismatch is indistinguishable from non-existence in the response.

### `DELETE /api/v1/basket`
`app/api/routes/basket.py:104`

- **Purpose:** Clear all of the caller's own basket items in one call.
- **Auth:** `require_permission("basket:manage")`.
- **Request body:** none.
- **Response:** **204 No Content**.
- **Errors:** none explicit.

### `POST /api/v1/basket/compare`
`app/api/routes/basket.py:115`

- **Purpose:** Build a deterministic side-by-side comparison table across 2–10 already-looked-up IOCs (referenced by `lookup_id`), then generate an AI narrative comparing them.
- **Auth:** `require_permission("basket:manage")`.
- **Request body:** raw `dict`, documented inline as `{"lookup_ids": list[str]}` (`basket.py:121-122`).
- **Response:** `{rows: list[{ioc_value, ioc_type, verdict: str, risk_score, confidence_score, asn: list[str], malware_families: list[str], threat_actors: list[str], related_domains: list[str], first_seen: str}], narrative: {most_dangerous_ioc_value: str | None, narrative: str, key_differences: list[str]}}` — the narrative fields come from `IOCComparisonNarrative` (`analysis_schemas.py:159-165`).
- **Errors:** **422** `"Provide at least 2 lookup_ids to compare"` if fewer than 2 are supplied (`basket.py:128`); **422** `"Cannot compare more than 10 IOCs at once"` if more than 10 are supplied (`basket.py:130`); **422** `"Fewer than 2 of the given lookup_ids resolved to completed lookups"` if resolution yields fewer than 2 valid, completed rows (`basket.py:161`).

---

## 9. Case Management — `routes/cases.py`

Base path `/api/v1/cases`. Cases are team-shared (not per-analyst) investigation containers grouping IOCs, notes, and reports. Most endpoints share a loader, `_load_case` (`cases.py:68-77`), which raises **404** `"Case not found"` for a missing case; that is stated once here and referenced, not repeated, below.

### `GET /api/v1/cases`
`app/api/routes/cases.py:80`

- **Purpose:** List cases across the whole team, optionally filtered by status.
- **Auth:** `require_permission("case:read")`.
- **Query params:** `status_filter: str | None = None`, `limit: int = 50` (clamped to `[1, 200]`, `cases.py:87`).
- **Request body:** none.
- **Response:** list of `{id, title, severity: str, status: str, tags: list[str], created_at}`.
- **Errors:** none explicit.

### `POST /api/v1/cases`
`app/api/routes/cases.py:105`

- **Purpose:** Create a new case, owned by the calling analyst.
- **Auth:** `require_permission("case:create")`.
- **Request body** (`CaseCreateRequest`, `app/schemas/case.py:8-12`):

| Field | Type | Notes |
|---|---|---|
| `title` | `str` | 1–255 characters |
| `description` | `Optional[str]` | — |
| `severity` | `CaseSeverity` | default `MEDIUM`; one of `low`/`medium`/`high`/`critical` |
| `tags` | `list[str]` | default `[]` |

- **Response** (HTTP **201**): full case object via `_serialize_case` (`cases.py:22-65`) — `{id, title, description, analyst_id, severity, status, tags, created_at, updated_at, iocs: [{id, ioc_value, ioc_type, lookup_id, added_by, created_at}], notes: [{id, author_id, body, anchor_type, anchor_ref, created_at}], reports: [{id, report_type, title, generated_by, created_at}]}`.
- **Errors:** none explicit — invalid field values fail standard FastAPI/Pydantic `422` validation.

### `GET /api/v1/cases/{case_id}`
`app/api/routes/cases.py:124`

- **Purpose:** Fetch full detail for one case — its IOCs, notes, and reports.
- **Auth:** `require_permission("case:read")`.
- **Path param:** `case_id`.
- **Request body:** none.
- **Response:** the full case object, as above.
- **Errors:** **404** `"Case not found"`.

### `PATCH /api/v1/cases/{case_id}`
`app/api/routes/cases.py:133`

- **Purpose:** Partially update a case's mutable fields — only fields explicitly present in the request body are applied.
- **Auth:** `require_permission("case:write")`.
- **Request body** (`CaseUpdateRequest`, `app/schemas/case.py:15-20`, all fields optional, applied via `model_dump(exclude_unset=True)`): `title: Optional[str]`, `description: Optional[str]`, `severity: Optional[CaseSeverity]`, `status: Optional[CaseStatus]` (`open`/`investigating`/`contained`/`resolved`/`false_positive`/`closed`), `tags: Optional[list[str]]`.
- **Response:** the full updated case object.
- **Errors:** **404** `"Case not found"`.

### `POST /api/v1/cases/{case_id}/close`
`app/api/routes/cases.py:148`

- **Purpose:** Force-close a case — sets `status` to `CLOSED` regardless of its current status.
- **Auth:** `require_permission("case:close")` — note this is a distinct permission string from `case:write`, allowing a role matrix where closing is more restricted than editing.
- **Request body:** none.
- **Response:** the full updated case object.
- **Errors:** **404** `"Case not found"`.

### `POST /api/v1/cases/{case_id}/iocs`
`app/api/routes/cases.py:162`

- **Purpose:** Attach an IOC to a case, optionally linking it to an existing lookup.
- **Auth:** `require_permission("case:write")`.
- **Request body** (`CaseIOCAddRequest`, `app/schemas/case.py:23-26`): `ioc_value: str`, `ioc_type: str`, `lookup_id: Optional[str]`.
- **Response** (HTTP **201**): the full updated case object.
- **Errors:** **404** `"Case not found"` (from `_load_case`). Note: supplying an `lookup_id` that is not a syntactically valid UUID raises an unhandled `ValueError` from `uuid.UUID(...)` (`cases.py:174`) — this surfaces as an unhandled server error rather than a documented `HTTPException`/`422`, and is a real gap rather than an intentional error path.

### `DELETE /api/v1/cases/{case_id}/iocs/{ioc_id}`
`app/api/routes/cases.py:182`

- **Purpose:** Remove an IOC from a case.
- **Auth:** `require_permission("case:write")`.
- **Path params:** `case_id`, `ioc_id`.
- **Request body:** none.
- **Response:** **204 No Content**.
- **Errors:** **404** `"Case IOC not found"` if no `CaseIOC` row matches that `case_id`/`ioc_id` pair (`cases.py:193`).

### `POST /api/v1/cases/{case_id}/notes`
`app/api/routes/cases.py:198`

- **Purpose:** Add an analyst note to a case, optionally anchored to a specific artifact (an IOC, an evidence item, a graph node, a timeline event, or a provider result — a free string, not a foreign key).
- **Auth:** `require_permission("case:write")`.
- **Request body** (`CaseNoteCreateRequest`, `app/schemas/case.py:29-32`): `body: str` (min length 1), `anchor_type: Optional[str]`, `anchor_ref: Optional[str]`.
- **Response** (HTTP **201**): the full updated case object.
- **Errors:** **404** `"Case not found"`.

---

## 10. Runtime Configuration — `routes/runtime.py`

Base path `/api/v1/runtime`. This is the API surface behind the DB-backed "Manage Providers" feature: configuring and activating AI backends, configuring and enabling IOC providers, and reading the audit log — all without editing `.env` or restarting a container. Business logic lives in `app/core/runtime_config.py`; every write-oriented endpoint here delegates to it.

### `GET /api/v1/runtime/ai-providers`
`app/api/routes/runtime.py:26`

- **Purpose:** List every configured AI-backend runtime row — persisted configuration, masked credentials, active/last-test status.
- **Auth:** `require_permission("provider:manage")`.
- **Request body:** none.
- **Response:** the return value of `svc.list_ai_providers()` (`app/core/runtime_config.py`); row shape is not independently typed by this route.
- **Errors:** none explicit.

### `POST /api/v1/runtime/ai-providers/{backend}`
`app/api/routes/runtime.py:38`

- **Purpose:** Persist validated credentials and/or a model choice for one AI backend into the runtime-mutable store. Takes effect on the very next AI call — no restart required.
- **Auth:** `require_permission("provider:manage")`.
- **Path param:** `backend: str`.
- **Request body** (`ConfigureAIProviderRequest`, inline `runtime.py:31-35`): `credentials: dict[str, str]` (default `{}`), `model_id: Optional[str]`.
- **Response:** the return value of `svc.upsert_ai_provider(...)`.
- **Errors:** **400** `f"Unknown AI backend {backend!r}"` if `backend` is not in `svc.AI_BACKENDS` (`runtime.py:45`).

### `POST /api/v1/runtime/ai-active`
`app/api/routes/runtime.py:55`

- **Purpose:** Switch the platform-wide active AI backend immediately — affects the very next investigation and every subsequent AI call.
- **Auth:** `require_permission("provider:manage")`.
- **Request body** (`ActivateAIRequest`, inline `runtime.py:51-52`): `backend: str`.
- **Response:** `{active_backend: str}`.
- **Errors:** **400** with `str(exc)` as the detail message if `svc.set_active_ai_backend` raises `ValueError` — e.g. the backend is unknown or not yet configured (`runtime.py:64-65`).

### `GET /api/v1/runtime/ai-active`
`app/api/routes/runtime.py:69`

- **Purpose:** Return the currently active AI backend and model.
- **Auth:** `require_permission("lookup:read")` — note this route uses a different permission string than every other endpoint in this router, since read-only callers (e.g. the home-page AI Quick Switch) do not need `provider:manage`.
- **Request body:** none.
- **Response:** `{backend: str | None, model_id: str | None}` — both `None` if nothing has been configured yet (`runtime.py:72-73`); otherwise `{backend: config["backend"], model_id: config["model_id"]}`.
- **Errors:** none explicit.

### `POST /api/v1/runtime/ai-providers/{backend}/record-test`
`app/api/routes/runtime.py:82`

- **Purpose:** Record the outcome of a prior `/api/v1/ai/test` call against a backend's now-saved credential, so the UI can display a "last tested" status without re-running the test.
- **Auth:** `require_permission("provider:manage")`.
- **Path param:** `backend: str`.
- **Request body** (`TestResultRequest`, inline `runtime.py:77-79`): `ok: bool`, `message: str` (default `""`).
- **Response:** `{recorded: true}`.
- **Errors:** none explicit.

### `GET /api/v1/runtime/ioc-providers`
`app/api/routes/runtime.py:98`

- **Purpose:** List every known IOC provider merged with its runtime configuration row (or a synthesized default if it has never been configured), together with static metadata (`requires_key`, `credential_fields`, `category`, `supported_types`).
- **Auth:** `require_permission("provider:manage")`.
- **Request body:** none.
- **Response:** a list of dicts, each either the persisted row from `svc.list_ioc_providers()` or a synthesized default — `{provider_id, provider_name, kind: "ioc", enabled: true, is_active: false, configured, model_id: null, extra_config: {}, masked_credentials: {}, last_test_at: null, last_test_ok: null, last_test_message: null, updated_at: null}` — with `requires_key`, `credential_fields: list`, `category: str`, `supported_types: list[str]` appended in either case (`runtime.py:123-126`).
- **Errors:** none explicit.

### `POST /api/v1/runtime/ioc-providers/{provider_id}`
`app/api/routes/runtime.py:135`

- **Purpose:** Persist validated credentials and/or extra configuration for one IOC provider.
- **Auth:** `require_permission("provider:manage")`.
- **Path param:** `provider_id: str`.
- **Request body** (`ConfigureIOCProviderRequest`, inline `runtime.py:130-132`): `credentials: dict[str, str]` (default `{}`), `extra_config: Optional[dict]`.
- **Response:** the return value of `svc.upsert_ioc_provider(...)`.
- **Errors:** **404** `f"Unknown IOC provider {provider_id!r}"` if the ID is not in the known provider registry (`runtime.py:144`).

### `POST /api/v1/runtime/ioc-providers/{provider_id}/enabled`
`app/api/routes/runtime.py:159`

- **Purpose:** Enable or disable an IOC provider at runtime — takes effect on the next investigation, no restart required.
- **Auth:** `require_permission("provider:manage")`.
- **Path param:** `provider_id: str`.
- **Request body** (`EnableRequest`, inline `runtime.py:155-156`): `enabled: bool`.
- **Response:** `{provider_id: str, enabled: bool}`.
- **Errors:** none explicit.

### `POST /api/v1/runtime/ioc-providers/{provider_id}/record-test`
`app/api/routes/runtime.py:172`

- **Purpose:** Record the outcome of a prior connection test for an IOC provider.
- **Auth:** `require_permission("provider:manage")`.
- **Path param:** `provider_id: str`.
- **Request body** (`TestResultRequest`): `ok: bool`, `message: str` (default `""`).
- **Response:** `{recorded: true}`.
- **Errors:** none explicit.

### `GET /api/v1/runtime/audit-log`
`app/api/routes/runtime.py:185`

- **Purpose:** Retrieve the runtime-configuration audit log — who changed which provider or AI configuration, and when.
- **Auth:** `require_permission("audit:read")` — the only route gated by this permission string.
- **Query params:** `limit: int = 200`.
- **Request body:** none.
- **Response:** the return value of `svc.list_audit_log(limit)`.
- **Errors:** none explicit.

---

## 11. Dashboard — `routes/dashboard.py`

Base path `/api/v1/dashboard`. Both endpoints back the Executive Dashboard added in this update. Both are read-only aggregations over already-persisted data — neither makes a new provider call, a new AI call outside the one described below, or persists anything.

### `GET /api/v1/dashboard/kpis`
`app/api/routes/dashboard.py:20`

- **Purpose:** Return the seven real-time KPI values shown as tiles on the Executive Dashboard — every number a live database aggregate, never hardcoded. See `get_kpis()` (`app/core/dashboard.py`) and the Architecture chapter's Executive Dashboard subsection for exactly how each KPI is defined.
- **Auth:** `require_permission("dashboard:read")` — granted to all three roles (admin, analyst, viewer).
- **Request body:** none.
- **Response:** `{active_investigations: int, critical_high_risk_iocs: int, open_cases: int, open_critical_cases: int, avg_threat_score: float, provider_health_percentage: float, ai_success_rate: float | None}`. `ai_success_rate` is `null` (not `0`) when there is no qualifying AI activity in the lookback window, rather than misrepresenting "no data" as a 0% success rate.
- **Errors:** none explicit.

### `GET /api/v1/dashboard/executive-summary`
`app/api/routes/dashboard.py:25`

- **Purpose:** Return an AI-generated (or, on any AI failure, deterministic template-fallback) 2–4 sentence executive narrative, grounded exclusively in the same seven KPI values `GET /api/v1/dashboard/kpis` returns — the AI, or its fallback, is only ever handed those values as given facts and never computes or restates a number independently. See `generate_executive_summary()` (`app/ai/dashboard_summary.py`).
- **Auth:** `require_permission("dashboard:read")` — reuses the same permission as `/dashboard/kpis`; no new permission was introduced for this route.
- **Request body:** none.
- **Response:** `{summary: str, source: "ai" | "template_fallback", kpis: <the same object GET /api/v1/dashboard/kpis returns>}`. `source` honestly reports which path produced the text: `"template_fallback"` on any AI failure that survives one validation retry (an unreachable AI backend, or a structured response that fails schema validation twice) — the fallback sentence is still built directly from the real KPI numbers, never an error message and never fabricated data.
- **Errors:** none explicit — an AI failure is reported via `source: "template_fallback"` in a `200` response, not an HTTP error status.

---

## Out-of-Scope Endpoints

Two endpoints exist in `app/main.py` directly, outside `app/api/routes/`, with no `/api/v1` prefix and no permission check:

- `GET /health` (`main.py:63-65`) — liveness probe, no authentication.
- `GET /metrics` (`main.py:36`) — Prometheus metrics, exposed by `prometheus-fastapi-instrumentator`, no authentication.

Both are excluded from the router/permission inventory above because they are not defined in `app/api/routes/*.py` and carry no RBAC gate, but are noted here so this reference remains a complete map of every HTTP-reachable route in the backend process.

## Summary: Endpoint and Permission Counts

| Router file | Endpoints | Distinct permission strings used |
|---|---|---|
| `auth.py` | 4 | none (public) / implicit `get_current_user` on `/me` |
| `lookup.py` | 5 | `lookup:create`, `lookup:read` |
| `providers.py` | 2 | `dashboard:read`, `provider:manage` |
| `ai_config.py` | 2 | `provider:manage` |
| `analysis.py` | 10 | `evidence:read`, `analysis:generate`, `copilot:query` |
| `hunting.py` | 2 | `hunting:generate` |
| `pivot.py` | 1 | `lookup:read` |
| `basket.py` | 5 | `basket:manage` |
| `cases.py` | 8 | `case:read`, `case:create`, `case:write`, `case:close` |
| `runtime.py` | 10 | `provider:manage`, `lookup:read`, `audit:read` |
| `dashboard.py` | 2 | `dashboard:read` |
| **Total** | **51** | **14 distinct permission strings** |
