# Provider and AI Client Architecture (Developer Reference)

This chapter is the source-level companion to the *Provider Architecture* and *AI Architecture* chapters elsewhere in this documentation set. Those chapters describe what the provider and AI layers *do*; this one documents the actual interfaces, classes, and method signatures a developer extending or maintaining this codebase needs to implement or call. All facts below are drawn directly from `backend/app/providers/base.py`, `registry.py`, `orchestrator.py`, `backend/app/ai/service.py`, and the eleven AI client modules (`ollama_client.py`, `anthropic_client.py`, `bedrock_client.py`, `gemini_client.py`, `groq_client.py`, `openai_client.py`, `kimi_client.py`, `deepseek_client.py`, `xai_client.py`, `mistral_client.py`, `openrouter_client.py`).

## 1. The `BaseProvider` Contract (`app/providers/base.py`)

Every connector subclasses the abstract class `BaseProvider` (`base.py:80-183`). The module docstring states the intent directly: "the orchestrator never knows about concrete providers — it only calls this interface" (`base.py:1-7`).

**Enums.** `ProviderCategory` (`base.py:21-28`) has seven values: `THREAT_INTEL`, `SANDBOX`, `PASSIVE_DNS`, `CERTIFICATE_INTEL`, `WHOIS`, `VULNERABILITY`, `OSINT`. `ProviderStatus` (`base.py:31-42`) has eight: `OK`, `ERROR`, `TIMEOUT`, `RATE_LIMITED`, `NOT_CONFIGURED`, `UNSUPPORTED_IOC`, `NO_DATA`, `DISABLED`. The inline comment on `DISABLED` (`base.py:39-41`) explains why it is distinct from `NOT_CONFIGURED`: "a provider can have a perfectly valid key and still be intentionally disabled" — this is the runtime toggle behind `POST /api/v1/runtime/ioc-providers/{id}/enabled`.

**`ProviderResult`** (`base.py:45-77`) is a `@dataclass`, not a Pydantic model, returned by every provider regardless of vendor response shape:

| Field | Type | Notes |
|---|---|---|
| `provider_id`, `provider_name` | `str` | e.g. `"virustotal"` |
| `category` | `ProviderCategory` | |
| `status` | `ProviderStatus` | |
| `ioc_value` | `str` | submitted indicator |
| `ioc_type` | `IOCType` | detected type |
| `data` | `dict[str, Any]` | default `{}`; the normalized payload |
| `raw` | `Any` | default `None`; unused by every connector inspected |
| `source_url`, `error_message` | `Optional[str]` | |
| `latency_ms` | `Optional[int]` | set by `run()`, not `fetch()` |
| `fetched_at` | `float` | default `time.time()` |
| `from_cache` | `bool` | default `False`; set `True` by the orchestrator on a cache hit |

`to_dict()` (`base.py:63-77`) serializes the dataclass (enum members → `.value`) for the SSE stream and the Redis cache.

**Class shape.** A concrete provider sets six class attributes — `provider_id`, `provider_name`, `category`, `supported_types: set[IOCType]`, `requires_key: bool`, `base_url: str` — plus `configured: bool`, and implements exactly one abstract method, `async def fetch(self, ioc_value: str, ioc_type: IOCType, client: httpx.AsyncClient) -> ProviderResult` (`base.py:80-183`). `configured` is a plain attribute set in `__init__` (e.g. `bool(get_settings().virustotal_api_key)`), or hardcoded `True` for key-free providers such as `nvd` or `crtsh`. `supports(ioc_type)` (`base.py:94-95`) is simply `ioc_type in self.supported_types`.

**`run()`** (`base.py:97-176`) is what the orchestrator calls, never `fetch()` directly. Its docstring disclaims retry/timeout responsibility entirely: that belongs to the orchestrator (§3). `run()`'s own sequence:

1. Reads the per-investigation `ContextVar` override via `get_provider_override(self.provider_id)` (`base.py:104-111`; see §3.2), computing `effective_enabled`/`effective_configured` from it if present, else from the class attributes.
2. If disabled → `ProviderStatus.DISABLED`, `fetch()` never called (`base.py:112-123`).
3. If `supports(ioc_type)` is false → `ProviderStatus.UNSUPPORTED_IOC` (`base.py:124-134`).
4. If `requires_key` and not configured → `ProviderStatus.NOT_CONFIGURED`, `error_message=f"{self.provider_name} is not configured (missing API key/credentials)."` (`base.py:135-146`).
5. Otherwise calls `fetch()` inside `try/except`: an `httpx.HTTPStatusError` maps to `RATE_LIMITED` for status codes `429`, `403`, `509` (509 annotated as "PhishTank's documented over-limit response code", `base.py:152`) and to `ERROR` otherwise; any other exception is caught by a bare `except Exception` and normalized to `ERROR` with `error_message=str(exc)` (`base.py:147-174`).
6. `latency_ms` is stamped from a `time.monotonic()` delta on every path (`base.py:175`).

Because every branch above is centralized, a concrete `fetch()` only needs to handle its own vendor-specific success/404/no-data cases — anything else it lets propagate is normalized by `run()`.

## 2. The Provider Registry (`app/providers/registry.py`)

The registry is a flat list and two accessor functions, no logic: `_ALL_PROVIDERS: list[BaseProvider]` holds one module-level singleton instance per connector (imported from its own module, never constructed here); `get_all_providers()` returns it; `get_provider_health()` maps it to the dicts backing `GET /api/v1/providers/health` (`registry.py:8-64`). The docstring states the extensibility contract: "adding a new provider is a two-line change (import + append) and never touches the orchestrator, API routes, or correlation engine" (`registry.py:1-7`). Note `get_provider_health()` reports the class-level `configured` flag, not the per-investigation runtime-override value from §3 — worth knowing when comparing this endpoint against what an in-flight investigation actually saw.

### 2.1 The 18 registered connectors

| provider_id | Category | `IOCType`s supported | `requires_key` | Credential setting (`app/core/config.py`) | Base endpoint |
|---|---|---|---|---|---|
| `virustotal` | threat_intel | IPV4, IPV6, DOMAIN, URL, hashes | Yes | `virustotal_api_key` (header `x-apikey`) | `virustotal.com/api/v3` |
| `abuseipdb` | threat_intel | IPV4, IPV6 | Yes | `abuseipdb_api_key` (header `Key`) | `api.abuseipdb.com/api/v2/check` |
| `otx` | threat_intel | IPV4, IPV6, DOMAIN, HOSTNAME, URL, hashes | Yes | `otx_api_key` (header `X-OTX-API-KEY`) | `otx.alienvault.com/api/v1` |
| `urlhaus` | threat_intel | URL, DOMAIN, IPV4 | Yes | `abusech_auth_key` (header `Auth-Key`, shared) | `urlhaus-api.abuse.ch/v1` |
| `threatfox` | threat_intel | IPV4, IPV6, DOMAIN, URL, MD5, SHA256 | Yes | `abusech_auth_key` (shared) | `threatfox-api.abuse.ch/api/v1/` |
| `malwarebazaar` | threat_intel | MD5/SHA1/SHA256/SHA512 | Yes | `abusech_auth_key` (shared) | `mb-api.abuse.ch/api/v1/` |
| `crtsh` | certificate_intel | DOMAIN, TLS_CERTIFICATE | No | — | `crt.sh` |
| `nvd` | vulnerability | CVE | No | optional `nvd_api_key` (header `apiKey`) | `services.nvd.nist.gov/rest/json/cves/2.0` |
| `cisa_kev` | vulnerability | CVE | No | — (in-memory, 3600s TTL, lock-guarded) | CISA KEV JSON feed |
| `mitre_attack` | threat_intel | MITRE_TECHNIQUE | No | — (STIX bundle, 3600s TTL, lock-guarded) | MITRE `cti` GitHub raw JSON |
| `whois_rdap` | whois | DOMAIN (WHOIS); IPV4/IPV6/ASN (RDAP) | No | — | `python-whois`; `rdap.org` |
| `hybrid_analysis` | sandbox | SHA256 only | Yes | `hybrid_analysis_api_key` (header `api-key`) | `hybrid-analysis.com/api/v2` |
| `spamhaus` | threat_intel | IPV4, DOMAIN | No | — (raw DNS, no HTTP) | `*.zen`/`*.dbl.spamhaus.org` |
| `phishtank` | threat_intel | URL | No | optional `phishtank_api_key` (form `app_key`) | `checkurl.phishtank.com/checkurl/` |
| `censys` | passive_dns | IPV4, IPV6 | Yes (both fields) | Bearer token **and** `X-Organization-ID` | `platform.censys.io/v3/global/asset/host/{ip}` |
| `internet_intelligence` | osint | DOMAIN, IPV4, MALWARE_FAMILY, THREAT_ACTOR, CAMPAIGN, CVE, FILE_NAME | No | — | `crawler/sources/{github,reddit,rss_news,pastebin_search}.py` |
| `urlscan` | sandbox | URL, DOMAIN | Yes | `urlscan_api_key` (header `API-Key`) | `urlscan.io/api/v1` (submit-then-poll) |
| `google_safe_browsing` | threat_intel | URL, DOMAIN | Yes | `google_safe_browsing_api_key` (query param `key`) | `safebrowsing.googleapis.com/v4` |

All 18 dispatch through the identical `run()`/`fetch()` contract in §1; this table exists to show where each one's credential and endpoint live for anyone tracing a credential end to end. `urlscan` and `google_safe_browsing` are the two exceptions to the setup wizard's provider page (see the Provider Guide) — both require a key but are configured after install via the app's own Providers page instead. The `IOCType` enum (`app/ioc/types.py:5-38`) has 33 members including `UNKNOWN`; each provider's `supported_types` set is a subset.

## 3. The Orchestrator: Concurrent Fan-Out (`app/providers/orchestrator.py`)

### 3.1 `_run_with_policy()` — per-provider cache, timeout, retry

Sequence for `async def _run_with_policy(provider, ioc_value, ioc_type, client) -> ProviderResult` (`orchestrator.py:29-86`):

1. **Cache check**: `get_cached_result(provider.provider_id, ioc_type.value, ioc_value)` against Redis; on a hit, the cached dict is rehydrated into a `ProviderResult` with `from_cache=True` and no outbound call is made.
2. **Timeout**: `asyncio.wait_for(provider.run(...), timeout=settings.provider_timeout_seconds)`.
3. **Retry**: `tenacity.AsyncRetrying` — `stop_after_attempt(settings.provider_max_retries + 1)`, `wait_exponential(multiplier=0.5, max=4)`, retrying only `_RETRYABLE_EXC = (httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout)`, `reraise=True`. This retry layer sits above `BaseProvider.run()`, consistent with `run()`'s own disclaimer in §1.
4. **Exhaustion normalization**: a caught `asyncio.TimeoutError` → `ProviderStatus.TIMEOUT`; a retryable exception surviving all attempts → `ProviderStatus.ERROR` with `"Connection error after retries: {exc}"`.
5. **Cache write**: only on `ProviderStatus.OK`, `set_cached_result(...)` writes `result.to_dict()` with TTL `settings.provider_cache_ttl_seconds`. Non-OK results, including `NO_DATA`, are never cached.

### 3.2 `run_all_providers()` — the streaming fan-out generator

`async def run_all_providers(ioc_value, ioc_type, providers=None) -> AsyncIterator[ProviderResult]` (`orchestrator.py:89-127`):

1. Filters candidates (all registered providers, or an explicit subset — how the `provider_ids` field on `POST /api/v1/lookup/stream` scopes one investigation) to `applicable = [p for p in candidates if p.supports(ioc_type)]`, **before** dispatch — deliberate, per the inline comment, so a UI's total-provider count reflects only providers that could plausibly contribute.
2. Reads one fresh snapshot per investigation — `snapshot = await get_ioc_provider_snapshot()` (`app/core/runtime_config.py`) — then `set_provider_overrides(snapshot)` (`app/core/runtime_context.py`), **before** any task is spawned.
3. Opens one shared `httpx.AsyncClient` for the whole fan-out (`Limits(max_connections=50, max_keepalive_connections=20)`, `follow_redirects=True`).
4. Spawns one `asyncio.create_task(_run_with_policy(p, ...))` per applicable provider, all at once. This is why the step-2 snapshot is concurrency-safe: `asyncio.create_task()` copies the current `contextvars.Context` into each spawned task, so every task launched for *this* investigation sees the identical frozen snapshot regardless of concurrent writes to the runtime-config table.
5. Consumes via `asyncio.as_completed(tasks)` and `yield`s each `ProviderResult` the instant it is ready — not in submission order. A wrapping `try/except Exception` (annotated "last-resort guard, providers already normalize errors") logs and swallows anything that escapes `_run_with_policy`.

`run_all_providers_collected()` (`orchestrator.py:130-136`) is a non-streaming wrapper — `[r async for r in run_all_providers(...)]` — used by the correlation engine and AI service, neither of which can run until every provider has reported back.

[FIGURE: dev-04-provider-and-ai-architecture-diagram-1.png | Diagram: 3.2 `run_all_providers()` — the streaming fan-out generator]
Diagram: Provider call sequence -- registry to orchestrator to `BaseProvider.run()` to `fetch()`. The cache check and the `ContextVar` credential check both happen before any outbound HTTP call, and results stream back in whatever order each provider actually finishes, not the order tasks were spawned.

## 4. The AI Client Interface: `call_claude_json`

`app/ai/service.py` defines the required shape as a `typing.Protocol`, not a base class — each of the eleven client modules independently implements a matching method:

```python
class _AIClient(Protocol):
    is_configured: bool
    async def call_claude_json(self, system_prompt: str, user_prompt: str,
                                json_schema: dict, tool_name: str = ...,
                                max_tokens: int | None = ...) -> dict: ...
```
(`service.py:43-53`). Because this is structural typing, adding a twelfth backend requires only a class exposing this method name/signature and an `is_configured` property — no shared inheritance, no registration beyond the branch added to `_build_client()` (§5.2).

| Client class | Module | Endpoint / call | Auth | Structured-output technique |
|---|---|---|---|---|
| `OllamaClient` | `ollama_client.py` | `POST {base_url}/api/chat`, default `http://host.docker.internal:11434` | none (local) | `format` = ref-flattened JSON Schema (grammar-constrained decoding) |
| `AnthropicClient` | `anthropic_client.py` | `POST api.anthropic.com/v1/messages` | header `x-api-key` + `anthropic-version` | forced single tool call; native `$ref`/`$defs`, no flattening |
| `BedrockClaudeClient` | `bedrock_client.py` | boto3 `bedrock-runtime.converse()` via `asyncio.to_thread` | bearer token or IAM key/secret | forced tool call via `toolConfig` |
| `GeminiClient` | `gemini_client.py` | `POST {API_BASE}/models/{model_id}:generateContent` | header `x-goog-api-key` (deliberately not `?key=...`, to avoid the key landing in httpx's INFO-level URL logs) | `responseMimeType: application/json` + ref-flattened `responseSchema` |
| `GroqClient` | `groq_client.py` | `POST api.groq.com/openai/v1/chat/completions` | header `Authorization: Bearer` | forced tool-calling, ref-flattened schema |
| `OpenAIClient` | `openai_client.py` | `POST api.openai.com/v1/chat/completions` | header `Authorization: Bearer` | forced tool-calling, ref-flattened schema |
| `KimiClient` | `kimi_client.py` | `POST api.moonshot.ai/v1/chat/completions` | header `Authorization: Bearer` | forced tool-calling, ref-flattened schema; default model pinned to `kimi-k2.5` since several newer Moonshot models' always-on "thinking" mode is incompatible with a forced `tool_choice` |
| `DeepSeekClient` | `deepseek_client.py` | `POST api.deepseek.com/chat/completions` (no `/v1` segment) | header `Authorization: Bearer` | forced tool-calling, ref-flattened schema |
| `XAIClient` | `xai_client.py` | `POST api.x.ai/v1/chat/completions` | header `Authorization: Bearer` | forced tool-calling, ref-flattened schema (best-effort — xAI's own docs say `parameters` isn't strictly enforced) |
| `MistralClient` | `mistral_client.py` | `POST api.mistral.ai/v1/chat/completions` | header `Authorization: Bearer` | forced tool-calling, ref-flattened schema |
| `OpenRouterClient` | `openrouter_client.py` | `POST openrouter.ai/api/v1/chat/completions` | header `Authorization: Bearer` | forced tool-calling; model discovery filtered to `tool_choice`-capable ids, since most of the hundreds of underlying models OpenRouter fans out to don't support forced tool-calling at all |

Every constructor accepts `Optional` overrides for credentials/model/`max_tokens`, falling back to `get_settings()` when `None` — e.g. `AnthropicClient.__init__(self, api_key=None, model_id=None, max_tokens=None)` (`anthropic_client.py:26-35`) resolves against `settings.anthropic_api_key`/`anthropic_model_id`/`anthropic_max_tokens`. Each module also exposes a lazily-initialized singleton getter (e.g. `get_anthropic_client()`), used only as the no-runtime-config fallback (§5.2). Ollama, Gemini, Groq, OpenAI, Kimi, DeepSeek, xAI, Mistral, and OpenRouter all run their schema through `app/ai/schema_utils.py`'s `inline_refs()` first, since their schema compilers don't reliably resolve `$ref`/`$defs`; Anthropic and Bedrock's Converse API resolve refs natively and skip that step.

## 5. `app/ai/service.py`: Backend Resolution and the Two-Step Flow

**`_model_id_for_backend(backend, settings)`** (`service.py:33-40`) is a dict lookup (`ollama`→`settings.ollama_model`, `anthropic`→`anthropic_model_id`, etc.) used only for attribution/logging, not client construction.

**`_build_client(backend, credentials, model_id)`** (`service.py:56-99`): when `credentials` is `None` (no runtime config seeded yet), returns the legacy module-level singleton; otherwise constructs a **brand-new client instance** from the decrypted, request-scoped credentials — e.g. for Bedrock, `BedrockClaudeClient(bedrock_api_key=credentials.get("bedrock_api_key"), aws_access_key_id=..., aws_secret_access_key=..., aws_region=..., model_id=model_id)`. The docstring states the rationale: a fresh instance per call is what makes switching backends/credentials at runtime take effect on the very next call, with no restart.

**`_get_ai_client(backend_override=None) -> tuple[_AIClient, str, Optional[str]]`** (`service.py:102-145`) resolves in order: (1) `backend_override` if given — used only by the reanalyze/AI-comparison feature, and explicitly must not change the platform-wide active backend; (2) the active runtime-configured backend via `get_active_ai_config()` — a fresh DB read every call; (3) the legacy `settings.ai_backend` (default `"ollama"`), only if no runtime config exists at all. If the resolved client's `is_configured` is false, it raises immediately: `RuntimeError(f"AI backend '{backend}' is not configured (missing API key/URL/model) -- configure it from the AI Providers panel or check .env")` — a deliberate fail-fast rather than letting a misconfigured client fail deep inside an HTTP call.

**`summarize_provider(ioc_value, ioc_type, result, backend_override=None) -> ProviderSummary`** (`service.py:336-374`): if `result.status != ProviderStatus.OK` or `result.data` is empty, returns a hardcoded fallback `ProviderSummary` (`reputation="unknown"`, `detection_status="no data"`, `threat_level="none"`, `confidence="low"`) with **no AI call**. Otherwise the provider's raw data is first passed through `_prune_for_prompt()` (`service.py:273-325` — caps any oversized `str` field at 2000 chars, any oversized `list`/`dict` field at 800, so a provider's bulky structural data can't bury its own short verdict/score fields), then calls `client.call_claude_json(system_prompt=_PROVIDER_SUMMARY_SYSTEM_PROMPT, ..., json_schema=ProviderSummary.model_json_schema(), tool_name="emit_provider_summary")` and validates the result. Any exception is caught and degrades to the same fallback shape with a static `caveats` message pointing at the server logs (`service.py:365-374`), not the exception text itself.

**`generate_final_assessment(ioc_value, ioc_type, provider_summaries, correlation, backend_override=None, unavailable_providers=None) -> FinalAssessment`** (`service.py:378-540`). `unavailable_providers` (`[{"provider_id", "reason"}]`) covers providers applicable to the IOC type that produced nothing usable this run; it is rendered as a "Providers unavailable this run" prompt section with an explicit instruction never to read that absence as "reported clean." Makes at most two AI calls: `FinalAssessment`'s own model validator rejects a self-contradictory verdict/probability pair (e.g. `final_verdict="malicious"` with a low `malicious_probability`), and that specific `ValidationError` (`service.py:513`) gets one retry — a stochastic model's next sample isn't the same sample — while every other exception (`service.py:517`) fails fast after a single attempt, so a rate-limited or network-failed call doesn't get retried into wasting more of the same budget.

*No-evidence guard* (`service.py:334-370`): if both `provider_summaries` and `correlation.edges` are empty, returns a hardcoded `FinalAssessment` (`final_verdict=Verdict.UNKNOWN`, all risk fields `0`) **without calling the AI backend**. The code comment documents the incident that forced this: querying the EICAR test file's real MD5 (`44d88612fea8a8f36de82e1278abb02f`) with zero usable provider data still made `llama3.2:3b` return `final_verdict="highly_malicious"`, `malicious_probability=92`, fabricating a ransomware/trojan association from pretrained knowledge — a violation of its own "never fabricate" system-prompt rule that no prompt rewording reliably fixed.

When evidence exists, the function builds `summaries_block` (one section per `ProviderSummary`) and `correlation_block` (`provider_agreement`, `deduplicated_facts`, up to the first 50 correlation edges as `source --relationship--> target [provenance]`), calls `client.call_claude_json(..., json_schema=FinalAssessment.model_json_schema(), tool_name="emit_final_assessment", max_tokens=8192)`, validates it, and passes it through `_ground_final_assessment()` (§6). `assessment.ai_backend`/`ai_model` are then **overwritten** with the backend/model actually invoked (`service.py:426-427`) — necessary because nothing stops the model from filling those fields in itself, and because `settings.ai_backend` can disagree with the runtime-active backend or an explicit `backend_override`. On any exception, the function returns a degraded `FinalAssessment` (`final_verdict="unknown"`, exception `repr()` embedded in the summary fields) — this pipeline never raises out to its caller.

## 6. `_ground_final_assessment()` — Trusting Nothing at Face Value

`_ground_final_assessment(assessment, correlation, known_provider_ids=None) -> FinalAssessment` (`service.py:211-264`) runs on every generated (non-guard-shortcut) result. It builds `real_provider_ids` as the union of: every `provider_id` in a correlation edge's `provenance`, every provider in `correlation.provider_agreement`, and `known_provider_ids` — `{s.provider_id for s in provider_summaries}`, passed in by the caller. The third source matters because a provider like `internet_intelligence` returns only `osint_findings`/`source_count` — fields the correlation engine's relationship-extraction table doesn't recognize — so without it, a correct citation of that provider as agreeing/disagreeing would be indistinguishable from a hallucinated one and get stripped.

`agreeing_providers`/`disagreeing_providers` are each filtered down to IDs in `real_provider_ids`; anything else is **dropped, not reassigned** — the code comment notes that guessing which list a hallucinated name belongs in "could silently misclassify a provider's position — worse than leaving it missing." Separately, every `MitreMapping.grounded` is set `True` only if its `technique_id` matches the target of a real `uses_technique` correlation edge — an ungrounded technique is flagged, not removed, leaving the UI free to render it differently rather than presenting it as fact.

## 7. Extending the System

**New IOC provider**: subclass `BaseProvider`, set the six class attributes, implement `fetch()`, instantiate a module-level singleton, add two lines to `registry.py` (import + append). No other file changes — the orchestrator, correlation engine, and evidence builder consume providers exclusively through the `BaseProvider`/`ProviderResult` contract in §1.

**New AI backend**: implement a class exposing `is_configured` and an async `call_claude_json(system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None) -> dict` matching §4's Protocol, add a branch to `_build_client()` and an entry to `_model_id_for_backend()`, and add the corresponding `Settings` fields in `app/core/config.py`. No change to `summarize_provider()`, `generate_final_assessment()`, or §6's grounding logic is required — both call sites reach the backend exclusively through `_get_ai_client()`.
