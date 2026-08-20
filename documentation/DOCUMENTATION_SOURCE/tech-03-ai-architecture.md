# AI Architecture (Technical)

This section describes how HORIZON GRID's backend (`backend/app/ai/`) uses large language models to summarize and score an **IOC** (Indicator of Compromise — a hash, IP, domain, URL, CVE, etc. submitted for lookup) once raw provider data has been collected. It assumes the reader is technically literate but new to this codebase, so product-specific components — `ProviderResult`, `CorrelationResult`, `AISummaryRecord`, `IOCLookup`, `EvidenceItem` — are defined at first use.

All facts below are traceable to `backend/app/ai/service.py`, `schemas.py`, `analysis_service.py`, `hunting_service.py`, `analysis_schemas.py`, `ollama_client.py`, `anthropic_client.py`, `bedrock_client.py`, `gemini_client.py`, and `groq_client.py`.

## 1. Supported AI Backends and Selection

The active backend is a single configuration value, `ai_backend` (`app/core/config.py` line 69), defaulting to `"ollama"`. Five backends are implemented:

| Backend | Config value | Mode | Auth / connection detail |
|---|---|---|---|
| Ollama | `ollama` | Local, default | No key; talks to `http://host.docker.internal:11434`, model `llama3.2:3b` |
| Anthropic | `anthropic` | Direct API | Direct Messages API, tool-forced JSON output |
| AWS Bedrock | `bedrock` | Cloud | Bedrock Converse API for Claude; supports bearer-token or IAM access-key/secret auth |
| Google Gemini | `gemini` | Cloud | Gemini `generateContent` REST endpoint; JSON-schema response mode |
| Groq | `groq` | Cloud, fast inference | OpenAI-compatible chat-completions API at `api.groq.com`; Bearer-token auth; default model `llama-3.3-70b-versatile` |

All five client classes expose the **same** async method signature — `call_claude_json(system_prompt, user_prompt, json_schema, tool_name, max_tokens)` — so `app/ai/service.py`'s internal `_get_ai_client()` never has to branch on which backend is active (service.py lines 42-78). This is a straightforward adapter pattern: swapping backends is a config change, not a code change. `groq_client.py` fits this pattern by targeting Groq's `/openai/v1/chat/completions` endpoint and using the same forced-single-tool-call technique the other backends use to coerce a structured JSON response, rather than a bespoke prompt format.

Unlike the other four backends, Groq's available-model list is not hardcoded in the codebase. Because Groq's hosted model lineup changes over time, the platform instead discovers it **live** from Groq's own `GET /v1/models` endpoint (exposed to the setup wizard and API consumers via `POST /api/v1/ai/groq/models`), so the model dropdown always reflects the account's real, currently-available models rather than a list that can silently go stale as Groq deprecates or introduces models.

Selection is **fail-fast**: if the currently selected backend's `is_configured` check returns `False` (e.g. `anthropic` selected with no API key present), the service raises a `RuntimeError` immediately rather than letting the request proceed into a confusing low-level HTTP failure.

## 2. Runtime AI Backend Switching (No Restart)

Until this session, `ai_backend` and every backend's credentials were read once, at process start, from `.env` via `get_settings()` (`app/core/config.py`) — a `@lru_cache`-wrapped singleton that lives for the lifetime of the container process. Switching from Ollama to Anthropic, or adding a Groq key, meant editing `.env` and restarting the Docker containers; there was no way to change the active AI backend or its credentials while the platform was running.

`_get_ai_client()` in `service.py` now resolves the active backend on **every call**, rather than once at startup, by reading a database-backed runtime-config service (`backend/app/core/runtime_config.py`) instead of the frozen Settings object. Resolution order is: (a) an explicit `backend_override`, used only by the AI-comparison feature described below; (b) the currently **active** runtime-configured backend — a fresh row read from the `provider_runtime_configs` table (kind `"ai"`, `is_active = true`) on that call; (c) the legacy Settings-based value, kept only as a fallback for installs where no runtime config has been seeded yet. Each of the eleven AI client classes (`ollama_client.py`, `anthropic_client.py`, `bedrock_client.py`, `gemini_client.py`, `groq_client.py`, `openai_client.py`, `kimi_client.py`, `deepseek_client.py`, `xai_client.py`, `mistral_client.py`, `openrouter_client.py`) gained optional constructor parameters so `_get_ai_client()` can build a fresh, correctly-credentialed instance from the decrypted runtime credentials on each call instead of reusing a stale cached singleton built from `.env` at process start.

The practical effect: `POST /api/v1/runtime/ai-active` switches the active backend, and the very next AI call — the next per-provider summary or final assessment, for any in-flight or new lookup — uses the newly active backend and its credentials. No container restart, no `.env` edit, no redeploy.

This same on-demand resolution also underlies the AI-comparison feature: `POST /api/v1/lookup/{id}/reanalyze` re-runs only the `generate_final_assessment()` step against an already-completed lookup's existing evidence, passing a `backend_override` for whichever backend the analyst wants to compare against — no provider is re-queried. Every assessment ever produced for a lookup — the original plus every later comparison run — is written to a new `final_assessment_records` table (`app/models/lookup.py`), tagged with the `ai_backend`/`ai_model` that produced it and an `is_primary` flag distinguishing the original from comparisons; a reanalysis never overwrites or deletes an earlier result. `GET /api/v1/lookup/{id}/assessments` returns the full set for side-by-side review.

One further prompt-level change accompanies this: `generate_final_assessment()` now also receives an explicit `unavailable_providers` list — providers that were applicable to the IOC but failed, timed out, were rate-limited, or were not configured/disabled for this run — rendered in the prompt as a distinct "Providers unavailable this run" section, together with a system-prompt rule never to read an unavailable provider's absence as "found nothing" or "reported clean." This closes a gap that predates runtime switching but became more visible once providers could be disabled live: without it, the AI had no way to distinguish missing coverage from a genuinely clean result.

## 3. Two Distinct AI Call Types

The pipeline makes two structurally different kinds of AI calls, confirmed as genuinely separate in the code (not a naming convention over one code path):

| | `summarize_provider()` | `generate_final_assessment()` |
|---|---|---|
| Cardinality | One call **per provider** that returned OK data | **One** call per lookup, after all providers finish |
| Input | Only that single provider's own JSON | All per-provider `ProviderSummary` objects + the correlation engine's output — **never** raw provider JSON |
| Stored as | `AISummaryRecord` with `provider_id` set | `IOCLookup.final_assessment` **and** an `AISummaryRecord` with `provider_id = NULL` |

The `AISummaryRecord.provider_id` column is the actual database-level marker distinguishing the two: a model-level comment (`models/lookup.py` line 93) explicitly documents that a `NULL` `provider_id` row is "the final consolidated assessment, not a per-provider one."

**Why they are kept separate**, per the code's own design comments (service.py lines 8-11): the final assessment is deliberately grounded in the already-summarized per-provider outputs and the deterministic correlation result rather than being handed every provider's raw JSON again. This bounds the size of the final prompt (which would otherwise grow with the number of registered providers) and forces the "master" call to reason over an already-distilled, per-provider-attributed layer instead of re-deriving everything from scratch — which is also what makes the grounding/cross-check step in §5 possible.

## 4. No-Evidence Short-Circuit Guard

Inside `generate_final_assessment()` (service.py lines 242-284), there is a hard guard: if `provider_summaries` is empty **and** `correlation.edges` is empty, the function returns a hardcoded, deterministic `FinalAssessment` — `final_verdict=Verdict.UNKNOWN`, all risk fields set to `0` — **without invoking the AI backend at all**.

The code comment documents the concrete, reproduced failure that motivated this guard: querying the real MD5 hash of the EICAR antivirus test file (`44d88612fea8a8f36de82e1278abb02f`) with **zero configured providers** — i.e. with no actual evidence of any kind — still caused the small local model (`llama3.2:3b`) to return `final_verdict="highly_malicious"` and `malicious_probability=92`, fabricating an "association with ransomware and trojans" purely from its pretrained knowledge. This directly violated the model's own system-prompt instruction to never fabricate findings. Rather than trying to prompt-engineer around this failure mode, the team chose to bypass the model entirely whenever there is structurally no evidence to reason over — a deterministic guard is unconditionally reliable where a prompt instruction was not.

## 5. Grounding / Cross-Check Mechanism

Even when the AI backend *is* called, its structured output is not trusted at face value — it is cross-checked against the deterministic correlation data. Two related mechanisms implement this:

**`_ground_final_assessment()`** (service.py lines 137-190), run on every `generate_final_assessment()` result:
- Filters the model's `agreeing_providers` / `disagreeing_providers` lists down to only the `provider_id`s that actually appear in the correlation edges, in `provider_agreement`, or in `known_provider_ids` (the set of providers that genuinely returned a per-provider summary, passed in by the caller). Anything else the model names is **silently stripped**.
- Sets `mapping.grounded = False` on any MITRE ATT&CK technique the model cited that is not backed by a real `uses_technique` correlation edge — so a technique mention that has no supporting evidence is flagged rather than presented as fact.

**A parallel mechanism in `analysis_service.py`**, applied to the analyst-facing explanation endpoints (WHY malicious, Challenge/red-team, Copilot Q&A, and others):
- `_strip_invalid_evidence_ids()` (lines 55-71) recursively removes any `evidence_ids` citation that doesn't match a real `EvidenceItem.id` belonging to that specific lookup.
- `_backfill_evidence_ids_from_prose()` (lines 74-112) does the reverse repair: it recovers citations the model correctly referenced in free-text prose but failed to place into the structured `evidence_ids` field — but it only ever adds an ID that has already been confirmed real; it never invents one.

Together, these mean every AI-authored claim that reaches storage or the UI has either been matched against a real `EvidenceItem`/correlation edge or explicitly marked/stripped as unsupported — the deterministic correlation and evidence layers act as a check on the generative layer, not the other way around.

## 6. Verdict and Confidence Data Model

The `Verdict` enum (`app/models/lookup.py` lines 22-34) has exactly **12 values**: `highly_malicious`, `malicious`, `suspicious`, `unknown`, `likely_benign`, `benign`, `scanner`, `tor_exit_node`, `vpn`, `cdn`, `cloud_infrastructure`, `dormant_infrastructure`. Note that several of these are not "maliciousness" gradations at all but infrastructure classifications (`tor_exit_node`, `vpn`, `cdn`, `cloud_infrastructure`, `dormant_infrastructure`) — the model is expected to distinguish "this is malicious" from "this is a category of infrastructure that merits a different interpretation."

`RiskAssessment` (`app/ai/schemas.py` lines 101-131) carries `overall_risk_score`, `confidence_score`, and `malicious_probability`, all explicitly on a **0-100 scale** (not 0-1). A `field_validator` automatically rescales any value it receives between 0 and 1 by multiplying by 100 — a defensive fix added because `llama3.2:3b` was observed defaulting to a 0-1 convention despite the 0-100 instruction.

`FinalAssessment` additionally carries a `model_validator` named `_verdict_must_agree_with_risk` (schemas.py lines 187-208) that rejects egregiously self-contradictory combinations — for example, a `final_verdict="malicious"` paired with `malicious_probability < 30` is rejected rather than silently persisted. This is a second, independent layer of internal-consistency checking, separate from the evidence-grounding checks in §5.

`FinalAssessment` also carries two traceability fields, `ai_backend` and `ai_model` (`schemas.py`), populated by `service.py` at generation time and surfaced in the UI as a badge on the final-assessment panel. With eleven interchangeable backends now selectable, and the config free to change between one lookup and the next, these fields exist so that an analyst or judge reviewing a conclusion always knows exactly which provider and model produced it — never a silent or ambiguous backend switch. When the no-evidence guard in §4 fires, or a generation error occurs (as happens on a rate-limited call), both fields are left `null` rather than populated with a misleading value, consistent with this layer's broader rule of never presenting a fabricated or guessed fact as if it were real.

## 7. AI Data Flow

The diagram below shows data flowing *into* the AI layer for a single lookup: per-provider JSON feeds per-provider summaries; those summaries plus the correlation engine's output feed the one consolidated final assessment; the final assessment is grounded/cross-checked before being persisted.

[FIGURE: tech-03-ai-architecture-diagram-1.png | Diagram: 7. AI Data Flow]

## 8. Beyond the Core Pipeline

`analysis_service.py` implements eight further grounded, evidence-cited AI features on top of the same call/grounding pattern: WHY malicious, What Is This, Provider Disagreement, False-Positive Assessment, Challenge/red-team, Smart Next Actions, Intelligence Gaps, and Score Explanation, plus Copilot Q&A and IOC comparison. `hunting_service.py` implements hunting-query and detection-rule generation. Both are restricted to citing only indicators/evidence that genuinely exist in the correlation graph or evidence ledger for that lookup — `hunting_service.py` (lines 74-79) explicitly strips any invented expansion target the model produces, following the same "never trust generated output at face value" principle applied throughout this layer.
