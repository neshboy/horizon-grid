"""AI summarization service.

Owns all prompting logic. Two responsibilities, matching the two-step flow
the platform requires:

  1. summarize_provider() -- one call per provider that returned data,
     grounded ONLY in that provider's own payload.
  2. generate_final_assessment() -- one call after every provider has
     finished, grounded in all provider summaries + the correlation engine's
     output. Never grounded in raw provider JSON directly, to keep the prompt
     size bounded regardless of how verbose a provider's raw response is.

Every prompt explicitly instructs Claude to only state what is supported by
the supplied data and to say "no data" / "not observed" rather than infer,
which is the core anti-hallucination control for this service.
"""
import logging
from typing import Optional, Protocol

from pydantic import ValidationError

from app.ai.schemas import FinalAssessment, ProviderSummary, RiskAssessment
from app.core.config import get_settings
from app.correlation.engine import CorrelationResult
from app.models.lookup import Verdict
from app.providers.base import ProviderResult, ProviderStatus
from app.scoring.engine import ScoringResult

logger = logging.getLogger(__name__)

# For AI-result traceability (Phase 20 of the API-configuration fix): which
# model_id to attribute a final assessment to, keyed by settings.ai_backend.
# Kept here rather than reading each client's private attribute so this
# doesn't need to construct/import every backend client just to report which
# one is configured.
def _model_id_for_backend(backend: str, settings) -> Optional[str]:
    return {
        "ollama": settings.ollama_model,
        "anthropic": settings.anthropic_model_id,
        "bedrock": settings.bedrock_model_id,
        "gemini": settings.gemini_model_id,
        "groq": settings.groq_model_id,
        "openai": settings.openai_model_id,
    }.get(backend)


class _AIClient(Protocol):
    is_configured: bool

    async def call_claude_json(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict,
        tool_name: str = ...,
        max_tokens: int | None = ...,
    ) -> dict: ...


def _build_client(backend: str, credentials: Optional[dict], model_id: Optional[str]) -> _AIClient:
    """Constructs a FRESH client instance from explicit credentials when
    given (the runtime-configured path -- see app/core/runtime_config.py),
    or falls back to the legacy module-level singleton (reading the frozen
    Settings singleton) when credentials is None -- the "no runtime config
    seeded yet" safety net. A fresh instance per call (rather than reusing a
    singleton) is what makes switching backends/credentials at runtime take
    effect on the very next call, with no process restart."""
    if backend == "bedrock":
        from app.ai.bedrock_client import BedrockClaudeClient, get_bedrock_client

        if credentials is None:
            return get_bedrock_client()
        return BedrockClaudeClient(
            bedrock_api_key=credentials.get("bedrock_api_key"),
            aws_access_key_id=credentials.get("aws_access_key_id"),
            aws_secret_access_key=credentials.get("aws_secret_access_key"),
            aws_region=credentials.get("aws_region"),
            model_id=model_id,
        )
    if backend == "gemini":
        from app.ai.gemini_client import GeminiClient, get_gemini_client

        if credentials is None:
            return get_gemini_client()
        return GeminiClient(api_key=credentials.get("api_key"), model_id=model_id)
    if backend == "anthropic":
        from app.ai.anthropic_client import AnthropicClient, get_anthropic_client

        if credentials is None:
            return get_anthropic_client()
        return AnthropicClient(api_key=credentials.get("api_key"), model_id=model_id)
    if backend == "groq":
        from app.ai.groq_client import GroqClient, get_groq_client

        if credentials is None:
            return get_groq_client()
        return GroqClient(api_key=credentials.get("api_key"), model_id=model_id)
    if backend == "openai":
        from app.ai.openai_client import OpenAIClient, get_openai_client

        if credentials is None:
            return get_openai_client()
        return OpenAIClient(api_key=credentials.get("api_key"), model_id=model_id)

    from app.ai.ollama_client import OllamaClient, get_ollama_client

    if credentials is None:
        return get_ollama_client()
    return OllamaClient(base_url=credentials.get("base_url"), model=model_id)


async def _get_ai_client(backend_override: Optional[str] = None) -> tuple[_AIClient, str, Optional[str]]:
    """Resolves the AI backend to use for this call, in order:

    1. `backend_override`, if given -- an explicit non-active backend for
       the AI-comparison feature ("analyze the same evidence with Groq
       instead"), which must NOT change the platform-wide active backend.
    2. The currently *active* runtime-configured backend
       (app/core/runtime_config.get_active_ai_config()) -- this is what
       makes "switch AI, no restart" work: it's a fresh DB read every call.
    3. The legacy frozen Settings singleton (settings.ai_backend), only if
       no runtime config has been seeded yet at all.

    All six clients expose the identical call_claude_json() method name so
    the rest of this module never branches on which backend is active.
    Checks is_configured here (rather than leaving each client to discover
    its own missing key/URL deep inside an HTTP call) so a misconfigured
    backend fails with one clear message instead of a confusing low-level
    error -- e.g. httpx raising TypeError on a None header value, or Gemini
    silently sending the literal string "None" as an API key and getting
    back an ordinary-looking 4xx.
    """
    from app.core.runtime_config import get_active_ai_config, get_ai_config

    if backend_override is not None:
        config = await get_ai_config(backend_override)
    else:
        config = await get_active_ai_config()

    if config is not None:
        backend = config["backend"]
        model_id = config["model_id"] or _model_id_for_backend(backend, get_settings())
        client = _build_client(backend, config["credentials"], config["model_id"])
    else:
        settings = get_settings()
        backend = backend_override or settings.ai_backend
        model_id = _model_id_for_backend(backend, settings)
        client = _build_client(backend, None, None)

    if not client.is_configured:
        raise RuntimeError(
            f"AI backend '{backend}' is not configured (missing API key/URL/model) -- "
            "configure it from the AI Providers panel or check .env"
        )
    return client, backend, model_id


_PROVIDER_SUMMARY_SYSTEM_PROMPT = """You are a threat intelligence analyst assistant.
You will be given the raw JSON response from exactly one threat intelligence provider
for one indicator of compromise (IOC). Summarize ONLY what this provider's data shows.

Rules:
- Never state anything not directly supported by the provided JSON.
- If the provider returned no meaningful data, say so plainly (e.g. "No detections reported").
- Do not speculate about what other sources might say.
- Do not invent detection counts, dates, or relationships not present in the data.
- Read boolean fields by their literal value, not by what their name alone might
  suggest -- confirmed live that a field like "listed": false (Spamhaus DBL/ZEN
  data) was misread as "the IOC IS listed," inverting a clean result into a
  false "has been blocked" claim. `false`/`null`/empty means that condition did
  NOT occur; double-check the actual value before describing what it means.
- Keep the tone factual and analytical, suitable for a SOC analyst reading dozens of these.
"""

_FINAL_ASSESSMENT_SYSTEM_PROMPT = """You are a senior threat intelligence analyst producing a
consolidated assessment of an indicator of compromise (IOC) for a SOC audience.

You are given: (1) the per-provider summaries already produced for this IOC, and
(2) a correlation engine output listing deduplicated facts, discovered relationships,
and which providers agreed or disagreed on reputation/verdict.

Rules:
- Base every claim strictly on the supplied summaries and correlation data. Never fabricate
  detection counts, dates, actor attributions, or relationships that are not present in the input.
- Explicitly call out when providers disagree, and explain which is more credible and why
  (e.g. more engines, more recent data, higher historical accuracy) if the input supports that.
- Every provider you name in threat_assessment as agreeing with the verdict MUST also appear in the
  structured agreeing_providers list; every provider you name as disagreeing MUST also appear in
  disagreeing_providers. Use each provider's provider_id (the '### <provider_id>' heading above its
  summary), not its display name. Do not describe agreement/disagreement in prose only -- the
  structured lists are what the UI renders, so leaving them empty while naming providers in prose is
  treated as a broken response.
- Populate supporting_evidence with the concrete findings from the summaries/correlation data that
  back threat_assessment. If threat_assessment references specific findings, supporting_evidence must
  not be empty.
- If data is insufficient for a category (e.g. no MITRE mapping possible), return an empty list
  rather than guessing.
- Detection rules (Sigma/YARA/SPL/KQL/etc.) should only be generated when the IOC type and
  available data make them meaningful (e.g. do not write a Sigma rule keyed on a bare domain
  with no log-source context) -- when not meaningful, return an empty detection_rules list.
- overall_risk_score, confidence_score, malicious_probability, and severity are GIVEN to you
  exactly as already computed by this platform's deterministic scoring engine (see the
  "Deterministic risk assessment" section in the user message) -- you do NOT calculate them and
  must NOT invent different numbers. Echo the given overall_risk_score/confidence_score/
  malicious_probability/severity values back verbatim into the risk object. This platform will
  overwrite those four fields with the real values regardless of what you write, so inventing
  your own accomplishes nothing except risking a rejected response -- see the next rule.
- The final_verdict must be exactly one of the enumerated values and must be justified by the
  evidence summarized above it, AND must agree with the GIVEN risk.malicious_probability (not a
  number you invent): a "malicious" or "highly_malicious" verdict requires a high given
  malicious_probability; a "benign"/"likely_benign" verdict requires a low given
  malicious_probability. If the given numbers don't support the verdict you would otherwise
  pick, change the verdict to match the given numbers -- never the other way around. Note that
  overall_risk_score can legitimately be higher than malicious_probability when a Security
  Assessment Toolkit finding (a real, directly-observed vulnerability/exposure) is present but
  the indicator's own reputation is otherwise clean or unknown -- that reflects "this target is
  risky to interact with" and "this indicator is a confirmed malicious actor" being different
  claims, not a contradiction to flag or resolve.
- overall_risk_score, confidence_score, and malicious_probability are all on a 0-100 scale
  (e.g. 50 means 50%, 87 means 87%), and are already given to you on that scale -- never
  re-express them as a 0-1 fraction.
- If a "Providers unavailable this run" section is present, those providers errored, timed out, were
  rate-limited, were not configured, or were disabled -- they did NOT run and returned NOTHING, which
  is completely different from a provider that ran and found no malicious indicators. Never phrase an
  unavailable provider's absence as "reported clean" or "found nothing" -- describe it as a coverage
  gap instead (e.g. "OTX was unavailable this run (rate limited), so its coverage is unknown, not clean"),
  and reflect reduced coverage in confidence_score rather than treating the remaining providers' silence
  on that gap as corroboration.
"""


def _ground_final_assessment(
    assessment: FinalAssessment, correlation: CorrelationResult, known_provider_ids: Optional[set[str]] = None
) -> FinalAssessment:
    """Cross-checks AI-emitted claims against the deterministic correlation
    output, rather than trusting them as-is. Even with an unambiguous schema,
    a small local model can emit a plausible-looking MITRE technique or
    misstate which providers agreed/disagreed -- both render identically to
    real evidence-backed data in the UI unless caught here. Strips/flags
    rather than raising, since a partially-hallucinated assessment is still
    more useful to an analyst than no assessment at all (mirrors the existing
    graceful-degradation philosophy in generate_final_assessment's except block).

    known_provider_ids (every provider_id that actually returned a per-provider
    summary for this lookup, passed in by generate_final_assessment) is unioned
    into the accepted set rather than relying solely on correlation.edges'
    provenance / correlation.provider_agreement. A provider that returned real
    data but didn't produce a relationship edge or a verdict/reputation fact
    (e.g. the OSINT crawler's internet_intelligence provider, which only
    returns osint_findings/source_count -- no field the correlation engine's
    _RELATIONSHIP_EXTRACTORS table or provider_agreement tracking recognizes)
    would otherwise never appear in the "real" set, so a correct citation of
    it as agreeing/disagreeing would be indistinguishable from a hallucinated
    one and get silently stripped here.
    """
    real_provider_ids = (
        {pid for edge in correlation.edges for pid in edge.provenance.split(",")}
        | {pid for providers in correlation.provider_agreement.values() for pid in providers}
        | (known_provider_ids or set())
    )

    def _filter_providers(claimed: list[str]) -> list[str]:
        return [p for p in claimed if p in real_provider_ids] if real_provider_ids else claimed

    # No prose-mention backfill here (unlike analysis_service.py's evidence_ids
    # backfill): a bare provider-name match in threat_assessment can't tell
    # agreement from disagreement, so guessing which list to add it to could
    # silently misclassify a provider's position -- worse than leaving it
    # missing. The real fix for this pipeline is known_provider_ids above
    # (a provider that returned real data is never treated as hallucinated
    # just because it produced no relationship edge or verdict/reputation
    # fact) plus the strengthened system prompt requiring the model to keep
    # prose and structured fields in sync itself.
    assessment.agreeing_providers = _filter_providers(assessment.agreeing_providers)
    assessment.disagreeing_providers = _filter_providers(assessment.disagreeing_providers)

    grounded_technique_ids = {
        edge.target.split(":", 1)[1].upper()
        for edge in correlation.edges
        if edge.relationship == "uses_technique"
    }
    for mapping in assessment.mitre_mappings:
        mapping.grounded = mapping.technique_id.upper() in grounded_technique_ids

    return assessment


_MAX_TEXT_FIELD_LEN = 2000
_MAX_STRUCTURED_FIELD_LEN = 800


def _prune_for_prompt(data: dict) -> dict:
    """Caps any individual field's rendered length before it reaches the
    prompt -- confirmed live as a real bug (not hypothetical): NVD's
    `configurations` field for CVE-2021-44228 (Log4Shell) runs to hundreds
    of nested CPE match entries, dozens of times longer than the actual
    signal (`verdict`, `cvss_score`, `cvss_severity`, `description`).
    Feeding that unbounded blob to summarize_provider() buried the CRITICAL
    severity under noise the model's attention gravitated to instead --
    reproduced twice, on two different AI backends (a local 3B model and a
    hosted 70B model), both calling a CVSS 10.0 RCE "benign"/"unknown risk."
    This module's own docstring already states raw provider JSON should
    never reach a prompt unbounded; this was the one call site (
    summarize_provider(), not generate_final_assessment()) that didn't
    follow it.

    Went through two rounds of live tuning, not one:

    Round 1 -- a single uniform 800-char cap fixed NVD but broke MITRE
    ATT&CK: its `description` is the ONLY signal-bearing field for that
    provider (no separate short verdict/score field the way NVD has), and
    real technique descriptions routinely run 600-1800+ chars (measured
    live: T1055=934, T1059=1588, T1027=1803), so 800 silently chopped most
    real lookups mid-sentence -- the same "AI loses the actual signal"
    failure this function exists to prevent, just from being too
    aggressive rather than not aggressive enough.

    Round 2 -- raising the SAME uniform cap to 4000 fixed MITRE but broke a
    DIFFERENT thing: NVD's data has two oversized fields, not one --
    `references` (7,851 chars, a bare list of URLs) as well as
    `configurations` (67,721 chars) -- and capping both at 4000 instead of
    800 pushed a real live Groq call to HTTP 413 ("Request too large...
    Requested 12402" against a 12000 TPM limit), since neither field
    carries any analytical signal worth paying for at that size.

    The fix distinguishes WHY a field is long: `description`-style prose
    (Python `str`) is far more likely to be genuine single-field signal
    (MITRE's case) and gets the generous cap; a `list`/`dict` -- inherently
    structural/repetitive (CPE match entries, URL lists, raw report
    objects) -- gets the original tight cap regardless of provider, since
    every oversized list/dict field examined across both NVD and AbuseIPDB
    turned out to be low-signal bulk, never the primary carrier of a
    verdict. Short/scalar fields -- the ones actually carrying a verdict --
    pass through untouched either way."""
    pruned = {}
    for key, value in data.items():
        rendered = str(value)
        max_len = _MAX_TEXT_FIELD_LEN if isinstance(value, str) else _MAX_STRUCTURED_FIELD_LEN
        if len(rendered) > max_len:
            pruned[key] = rendered[:max_len] + f"... [truncated, {len(rendered)} chars total]"
        else:
            pruned[key] = value
    return pruned


def _provider_result_to_prompt(result: ProviderResult) -> str:
    return (
        f"Provider: {result.provider_name} (id={result.provider_id}, category={result.category.value})\n"
        f"Status: {result.status.value}\n"
        f"Source URL: {result.source_url or 'n/a'}\n"
        f"Data:\n{_prune_for_prompt(result.data)}\n"
    )


async def summarize_provider(
    ioc_value: str, ioc_type: str, result: ProviderResult, backend_override: Optional[str] = None
) -> ProviderSummary:
    if result.status != ProviderStatus.OK or not result.data:
        return ProviderSummary(
            provider_id=result.provider_id,
            what_it_knows="No data returned by this provider for this IOC.",
            reputation="unknown",
            detection_status="no data",
            threat_level="none",
            confidence="low",
            caveats=result.error_message,
        )

    user_prompt = (
        f"IOC: {ioc_value} (type: {ioc_type})\n\n"
        f"{_provider_result_to_prompt(result)}\n"
        "Summarize this provider's findings for this IOC."
    )
    try:
        client, _backend, _model = await _get_ai_client(backend_override)
        payload = await client.call_claude_json(
            system_prompt=_PROVIDER_SUMMARY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            json_schema=ProviderSummary.model_json_schema(),
            tool_name="emit_provider_summary",
        )
        payload["provider_id"] = result.provider_id
        return ProviderSummary.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Provider summary generation failed for %s: %r", result.provider_id, exc)
        return ProviderSummary(
            provider_id=result.provider_id,
            what_it_knows="AI summarization unavailable for this provider (generation error).",
            reputation="unknown",
            detection_status="unknown",
            threat_level="none",
            confidence="low",
            caveats="The AI backend failed to generate a summary for this provider's data (see server logs for details).",
        )


async def generate_final_assessment(
    ioc_value: str,
    ioc_type: str,
    provider_summaries: list[ProviderSummary],
    correlation: CorrelationResult,
    scoring: ScoringResult,
    backend_override: Optional[str] = None,
    unavailable_providers: Optional[list[dict]] = None,
) -> FinalAssessment:
    """unavailable_providers: [{"provider_id": ..., "reason": ...}] for
    providers that were APPLICABLE to this IOC type but did not return a
    usable result (error, timeout, rate-limited, not configured, or
    disabled) -- distinct from providers that ran fine and genuinely found
    nothing, and distinct from providers that don't apply to this IOC type
    at all. Without this, the AI has no way to distinguish "OTX was
    unavailable this run" from "OTX found nothing," which are not the same
    claim and must not be presented as if they were.

    scoring: this investigation's deterministic score (app/scoring/engine.py
    ::score_investigation(), computed by the caller from the SAME
    provider_results/correlation this call was given -- see that module for
    exactly how). This is the platform's actual risk_score/confidence_score/
    malicious_probability/severity going forward: the AI is told these
    numbers as GIVEN facts (see the "Deterministic risk assessment" block
    built into user_prompt below) and asked only to write a verdict/
    rationale consistent with them, never to invent its own -- and even if
    it ignores that instruction, this function overwrites risk.
    overall_risk_score/confidence_score/malicious_probability/severity with
    `scoring`'s values before returning, the same mechanical pattern already
    used below for ai_backend/ai_model. AI backends never influence this
    value, which is the whole point: reanalyze_lookup() re-running this
    against a different backend will (correctly) show the identical score
    every time, differing only in prose/verdict-choice-among-consistent-
    options."""
    if not provider_summaries and not correlation.edges:
        # Confirmed live with a genuinely severe bug: 44d88612fea8a8f36de
        # 82e1278abb02f (the EICAR test file's real MD5) hit four
        # not_configured providers -- zero real data of any kind -- and the
        # model still returned final_verdict="highly_malicious" with
        # malicious_probability=92, fabricating "association with ransomware
        # and trojans" wholesale. With an empty summaries_block and empty
        # correlation_block, the user_prompt below carries no actual
        # evidence, so a small model with strong pretrained knowledge of a
        # famous test hash answers from memory instead of refusing --
        # directly violating its own system prompt's "never fabricate"
        # instruction. No prompt wording fixes this reliably (the model
        # already had that instruction and ignored it), so this doesn't
        # call the AI at all when there's nothing for it to assess: an
        # empty-evidence case has exactly one correct answer regardless of
        # which AI backend is configured, so let deterministic code produce
        # it instead of hoping the model declines to guess.
        return FinalAssessment(
            ioc_value=ioc_value,
            ioc_type=ioc_type,
            executive_summary="No provider returned usable data for this indicator -- insufficient evidence for an assessment.",
            technical_summary="Every configured provider either has no data for this IOC or is not configured. "
            "No correlation relationships were discovered.",
            threat_assessment="Insufficient data to assess.",
            relationships_summary="No relationships discovered (no provider data was available to correlate).",
            # Uses `scoring` rather than hardcoded zeros so this stays correct even in the (rare)
            # edge case where a Security Assessment finding raised the score with no accompanying
            # provider summary or correlation edge -- in the overwhelmingly common case (truly zero
            # evidence of every kind) score_investigation() already produces all-zeros here too, so
            # this is a strict generalization of the previous hardcoded values, not a behavior change.
            risk=RiskAssessment(
                overall_risk_score=scoring.overall_risk_score,
                confidence_score=scoring.confidence_score,
                severity=scoring.severity,
                reputation="no data",
                malicious_probability=scoring.malicious_probability,
                analyst_confidence="low",
                scoring_engine_version=scoring.engine_version,
                scoring_breakdown=scoring.breakdown,
            ),
            final_verdict=Verdict.UNKNOWN,
            verdict_rationale="No provider returned usable data for this indicator, so no evidence-based "
            "verdict can be produced. Configure additional providers (Start Menu -> Configuration) for coverage.",
            # A CORRECT decision, not a failure: the AI was never asked to do
            # anything because there was nothing to analyze. Distinct from the
            # `ai_outcome="failed"` fallback below -- see _AIOutcome in
            # app/ai/schemas.py for why this distinction exists at all.
            ai_outcome="skipped_no_evidence",
        )

    summaries_block = "\n\n".join(
        f"### {s.provider_id}\n"
        f"Reputation: {s.reputation} | Threat level: {s.threat_level} | Confidence: {s.confidence}\n"
        f"What it knows: {s.what_it_knows}\n"
        f"Findings: {s.interesting_findings}\n"
        f"Relationships: {s.relationships}\n"
        for s in provider_summaries
    )
    correlation_block = (
        f"Provider agreement on reputation/verdict: {correlation.provider_agreement}\n"
        f"Deduplicated facts: {correlation.deduplicated_facts}\n"
        f"Relationships discovered ({len(correlation.edges)} edges): "
        + ", ".join(f"{e.source} --{e.relationship}--> {e.target} [{e.provenance}]" for e in correlation.edges[:50])
    )

    unavailable_block = ""
    if unavailable_providers:
        lines = "\n".join(f"- {u['provider_id']}: {u['reason']}" for u in unavailable_providers)
        unavailable_block = (
            "\n\n## Providers unavailable this run\n"
            "These providers applied to this IOC type but did NOT return data this run, for the reason "
            "given -- this is NOT the same as \"found nothing.\" Do not treat an unavailable provider's "
            "silence as evidence of a clean or benign reputation; simply note it as a coverage gap.\n"
            f"{lines}"
        )

    # Computed by app/scoring/engine.py BEFORE this call, from the exact same provider/
    # correlation (and, where applicable, Security Assessment) evidence summarized above --
    # never by the AI. See _FINAL_ASSESSMENT_SYSTEM_PROMPT's matching rule: these four values
    # are GIVEN, not generated, and this function overwrites whatever the model emits for them
    # regardless, so treat this block as ground truth, not a suggestion.
    scoring_block = (
        "\n\n## Deterministic risk assessment (already computed -- GIVEN, do not recalculate)\n"
        f"overall_risk_score: {scoring.overall_risk_score}\n"
        f"confidence_score: {scoring.confidence_score}\n"
        f"malicious_probability: {scoring.malicious_probability}\n"
        f"severity: {scoring.severity}\n"
        f"(scoring engine version {scoring.engine_version}; factor breakdown: {scoring.breakdown})"
    )

    user_prompt = (
        f"IOC: {ioc_value} (type: {ioc_type})\n\n"
        f"## Per-provider summaries\n{summaries_block}\n\n"
        f"## Correlation engine output\n{correlation_block}"
        f"{unavailable_block}"
        f"{scoring_block}\n\n"
        "Produce the consolidated intelligence assessment. Echo the given overall_risk_score/"
        "confidence_score/malicious_probability/severity values verbatim into the risk object; "
        "choose final_verdict and write every other field consistent with them."
    )

    # Confirmed live, reproducing consistently against a small local model
    # (Ollama llama3.2:3b): the model sometimes emits a self-contradictory
    # pair -- e.g. final_verdict="malicious" with risk.malicious_probability
    # around 10-20 -- which FinalAssessment's own validator correctly
    # rejects (the alternative, silently accepting it, would surface a
    # nonsensical assessment to an analyst). Without a retry, that single
    # bad sample threw away the whole assessment every time, even though the
    # per-provider summaries above it (same call chain, no retry either, but
    # apparently less prone to this) had already succeeded. A stochastic
    # model's next sample is not the same sample, so one retry is a cheap,
    # standard mitigation -- only give up to the generic fallback below
    # after both attempts fail.
    #
    # Retrying is scoped to ValidationError specifically, not caught
    # generically -- confirmed live: retrying a Groq 429 (rate limit)
    # immediately just consumes more of the same exhausted per-minute quota,
    # making the retry fail too, and would do the same for any other
    # backend/network-level failure. Those aren't sampling variance; an
    # immediate retry can't fix them and Phase 20's "no runaway requests on
    # rate limit" requirement rules out treating them the same as a bad
    # sample.
    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            client, used_backend, used_model = await _get_ai_client(backend_override)
            payload = await client.call_claude_json(
                system_prompt=_FINAL_ASSESSMENT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                json_schema=FinalAssessment.model_json_schema(),
                tool_name="emit_final_assessment",
                max_tokens=8192,
            )
            payload["ioc_value"] = ioc_value
            payload["ioc_type"] = ioc_type
            assessment = FinalAssessment.model_validate(payload)
            known_provider_ids = {s.provider_id for s in provider_summaries}
            assessment = _ground_final_assessment(assessment, correlation, known_provider_ids)

            # Overwrite whatever the model may have emitted for
            # overall_risk_score/confidence_score/malicious_probability/
            # severity (it's told these are given and not to invent its
            # own, but nothing besides that instruction stops it from doing
            # so anyway -- especially a small local Ollama model) with the
            # real, deterministically-computed values, the same mechanical
            # pattern used just below for ai_backend/ai_model.
            #
            # Critically, FinalAssessment.model_validate() above already ran
            # _verdict_must_agree_with_risk (app/ai/schemas.py) -- but only
            # against whatever risk.malicious_probability the MODEL itself
            # emitted, never against `scoring`'s real value. A model that
            # emits a self-consistent-but-wrong pair (e.g.
            # final_verdict="malicious" with its own invented
            # malicious_probability=92) sails through that check even
            # though its verdict may flatly contradict the REAL
            # malicious_probability this function is about to persist
            # instead. Swapping the numbers in without re-checking would
            # mean the validator's pass/fail result no longer describes the
            # object actually being returned -- exactly the gap this
            # function must not leave open.
            #
            # Fixed by re-running FinalAssessment.model_validate() on the
            # whole object with the deterministic risk spliced in, rather
            # than hand-rolling a second copy of the consistency check: this
            # re-executes EVERY validator on the model (not just
            # _verdict_must_agree_with_risk) against the values that will
            # actually be persisted, and raises the same ValidationError the
            # retry loop below already knows how to handle if the model's
            # verdict choice doesn't survive contact with the real numbers
            # -- which then retries with the SAME given numbers, giving the
            # model a second chance to pick a verdict consistent with them.
            #
            # Passes the swapped-in RiskAssessment as an already-constructed
            # INSTANCE (not `.model_dump()`'d back to a plain dict) --
            # deliberately, not for economy. Pydantic v2's default
            # `revalidate_instances="never"` means a field value that is
            # already an instance of its declared model class is used as-is,
            # skipping that model's own field validators. That matters here
            # because RiskAssessment.overall_risk_score/confidence_score/
            # malicious_probability all carry `_reject_0_to_1_scale`, which
            # multiplies any value strictly between 0 and 1 by 100 -- a
            # sensible guard against an AI emitting "0.5" for 50%, but this
            # engine can legitimately compute a real, tiny, correct score
            # like 0.4 (out of 100) for one weak, uncorroborated signal.
            # Round-tripping that through `.model_dump()` back into a plain
            # dict and re-validating it as fresh input would silently
            # mangle 0.4 into 40.0 -- confirmed against pydantic 2.x
            # directly before relying on this. Passing the instance through
            # avoids that entirely while `_verdict_must_agree_with_risk`
            # (an "after" validator on FinalAssessment itself, not on
            # RiskAssessment) still runs unconditionally either way.
            final_risk = assessment.risk.model_copy(
                update={
                    "overall_risk_score": scoring.overall_risk_score,
                    "confidence_score": scoring.confidence_score,
                    "malicious_probability": scoring.malicious_probability,
                    "severity": scoring.severity,
                    "scoring_engine_version": scoring.engine_version,
                    "scoring_breakdown": scoring.breakdown,
                }
            )
            assessment = FinalAssessment.model_validate({**assessment.model_dump(), "risk": final_risk})

            # Overwrite whatever the model may have emitted for these two
            # fields (it's told not to fill them in, but nothing stops it
            # from doing so anyway) with the real, code-derived identity of
            # the backend that was ACTUALLY invoked for this call -- not
            # settings.ai_backend, which could differ from the runtime-active
            # backend, and would be flatly wrong for an explicit
            # backend_override (AI-comparison runs).
            assessment.ai_backend = used_backend
            assessment.ai_model = used_model
            assessment.ai_outcome = "success"
            return assessment
        except ValidationError as exc:
            last_exc = exc
            if attempt == 0:
                logger.info("Final assessment attempt 1 failed for %s: %r -- retrying once", ioc_value, exc)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            break

    logger.warning("Final assessment generation failed for %s: %r", ioc_value, last_exc)
    return FinalAssessment(
        ioc_value=ioc_value,
        ioc_type=ioc_type,
        executive_summary="AI-generated assessment unavailable (generation error). "
        "See individual provider results and summaries below for raw findings.",
        technical_summary="Final assessment generation failed (see server logs for details).",
        threat_assessment="Not available -- AI generation error.",
        relationships_summary="Not available -- AI generation error.",
        # The AI's prose/verdict generation failed, but the deterministic score did not -- it was
        # computed before the AI was ever called, and remains valid regardless of whether the AI
        # call succeeded. Reporting hardcoded zeros here (as this fallback did before this
        # engine existed) would now be a regression: it would show "no risk" for an investigation
        # that may genuinely have real evidence behind a real, known, nonzero score. final_verdict
        # stays UNKNOWN (no AI-authored rationale exists to justify a more specific verdict), which
        # imposes no malicious_probability constraint via _verdict_must_agree_with_risk either way.
        risk=RiskAssessment(
            overall_risk_score=scoring.overall_risk_score,
            confidence_score=scoring.confidence_score,
            severity=scoring.severity,
            reputation="unknown",
            malicious_probability=scoring.malicious_probability,
            analyst_confidence="low",
            scoring_engine_version=scoring.engine_version,
            scoring_breakdown=scoring.breakdown,
        ),
        final_verdict="unknown",
        verdict_rationale="Could not be determined: AI assessment generation failed (see server logs for details).",
        # A GENUINE failure (every retry attempt raised) -- distinct from the
        # `ai_outcome="skipped_no_evidence"` short-circuit above, which is a
        # correct decision, not a failure. See _AIOutcome in app/ai/schemas.py.
        ai_outcome="failed",
    )
