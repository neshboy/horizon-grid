"""AI-generated executive narrative for the ops/exec dashboard.

generate_executive_summary() is this module's only AI-calling function, and
it is grounded EXCLUSIVELY in the 7 KPI values already computed by
app.core.dashboard.get_kpis() -- that function remains the ONE source of
truth for every number this module's prompt (or its fallback) ever states;
this module never computes or restates a number any other way. This extends
the platform's existing deterministic-scoring discipline (app/scoring/
engine.py computes a risk score BEFORE any AI call; app/ai/service.py's
generate_final_assessment() hands that score to the AI as a GIVEN fact and
never lets the AI invent or recompute it) to KPI numbers instead of a risk
score.

Call structure (system prompt / user prompt / json_schema / tool_name) follows
app/ai/service.py::summarize_provider() -- one focused call, grounded only in
data explicitly handed to it, structured JSON validated against a small
pydantic schema. The retry behavior follows generate_final_assessment()'s
own convention instead: retry once, but ONLY on a ValidationError (a
stochastic model's next sample is not the same sample), never on a generic
exception (e.g. a rate limit or an unreachable backend, where an immediate
retry can't help and would just double the cost of a real outage).
"""
import asyncio
import logging
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from app.ai.service import _get_ai_client
from app.core.config import get_settings
from app.core.dashboard import get_kpis

logger = logging.getLogger(__name__)


class _ExecutiveSummaryNarrative(BaseModel):
    narrative: str = Field(
        min_length=1,
        description="2-4 sentence executive narrative for a SOC leadership audience, grounded only in the given KPIs",
    )


_SYSTEM_PROMPT = """You are a threat intelligence platform assistant writing a short executive narrative
for SOC (Security Operations Center) leadership.

You will be given exactly 7 KPI values, already computed by this platform's own deterministic
aggregation code. These are GIVEN FACTS -- you do not calculate, verify, or restate them differently.

Rules:
- Write 2-4 sentences, in a factual, analytical tone suitable for SOC leadership (not a raw analyst).
- Explain what the numbers mean operationally for the team (e.g. workload implied by open cases/
  active investigations, risk implied by critical/high-risk IOC counts).
- Note anything that stands out: a KPI reported as null/no-data (this means there is no data for that
  metric, not zero -- describe it as "no data" or "not enough recent data", never as zero), a low
  ai_success_rate, a high critical-IOC or open-critical-case count, or degraded provider health.
- Never invent a number, trend, provider name, or incident that is not present in the given KPIs.
- If you cite a number, it must be the exact value given -- never round, estimate, or restate it
  differently.
- Do not speculate about causes, incidents, or providers not evidenced by the given data.
"""


def _kpi_lines(kpis: dict) -> str:
    """Renders the 7 KPI values verbatim, one line per KPI -- the ONLY
    numbers the AI is ever handed for this call, in the same "GIVEN, do not
    recalculate" spirit as app/ai/service.py::generate_final_assessment()'s
    own scoring_block."""
    return (
        f"active_investigations: {kpis['active_investigations']}\n"
        f"critical_high_risk_iocs: {kpis['critical_high_risk_iocs']}\n"
        f"open_cases: {kpis['open_cases']}\n"
        f"open_critical_cases: {kpis['open_critical_cases']}\n"
        f"avg_threat_score: {kpis['avg_threat_score']}\n"
        f"provider_health_percentage: {kpis['provider_health_percentage']}\n"
        f"ai_success_rate: {kpis['ai_success_rate']}"
    )


def _template_fallback_narrative(kpis: dict) -> str:
    """Deterministic, template-generated sentence built directly from the
    real KPI numbers -- the fallback used on ANY AI failure (unreachable
    backend, or a validation failure that survives the one retry). Mirrors
    app/ai/service.py::generate_final_assessment()'s own total-failure
    fallback, which still reports the real deterministic score rather than
    an error: this fallback still reports the real KPI numbers, verbatim,
    rather than an error or an empty summary.

    ai_success_rate is None-checked explicitly (rather than interpolated
    directly) because None means "no data" here (see get_kpis()'s own
    docstring/_rate_or default) -- interpolating it as the literal string
    "None" into a sentence meant for SOC leadership would read as a bug, not
    as the "no AI runs in this window" fact it actually represents.
    """
    ai_rate = kpis["ai_success_rate"]
    ai_rate_text = (
        "no AI analyses have been recorded in the recent window"
        if ai_rate is None
        else f"the AI analysis success rate is {ai_rate}%"
    )
    return (
        f"There are currently {kpis['active_investigations']} active investigation(s) in progress and "
        f"{kpis['open_cases']} open case(s), of which {kpis['open_critical_cases']} are critical. "
        f"In the recent window, {kpis['critical_high_risk_iocs']} indicator(s) were verdicted malicious "
        f"or highly malicious, with an average threat score of {kpis['avg_threat_score']}. "
        f"Provider health is at {kpis['provider_health_percentage']}%, and {ai_rate_text}."
    )


async def _call_ai_backend(user_prompt: str) -> dict:
    """The one AI call this module makes, factored out so the caller can
    bound its ENTIRE duration (client resolution + the actual generation
    call) in a single asyncio.wait_for -- see generate_executive_summary()'s
    dashboard_summary_ai_timeout_seconds wrapping below for why."""
    client, _backend, _model = await _get_ai_client()
    return await client.call_claude_json(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        json_schema=_ExecutiveSummaryNarrative.model_json_schema(),
        tool_name="emit_executive_summary",
    )


async def generate_executive_summary() -> dict:
    """1. get_kpis() is the ONLY source of truth for numbers here -- never
       computed or restated any other way, by this function or its fallback.
    2. Hands the AI those exact 7 KPI values as GIVEN FACTS and asks for a
       2-4 sentence SOC-leadership narrative, retrying once on a
       ValidationError only (see module docstring).
    3. On any failure that survives the retry (AI unreachable, validation
       never succeeds, or the call runs past
       settings.dashboard_summary_ai_timeout_seconds), falls back to a
       deterministic, template-generated, number-accurate sentence -- never
       an error, never a silent blank.

       The timeout is real P3 bug fix: this call used to have no
       request-scoped timeout of its own at all, so it inherited whichever
       underlying AI client's own timeout was active (e.g. Ollama's 300s,
       sized for a cold CPU-only model reload -- see
       app/ai/ollama_client.py's _TIMEOUT_SECONDS comment). That backend is
       shared platform-wide with every other AI-calling feature (lookups,
       pentest, security assessments), so a busy/slow backend could leave
       this at-a-glance dashboard endpoint hanging for anywhere up to that
       same 300s with no response at all -- confirmed live: a single,
       uncontended call with Ollama active and a cold-unloaded model did not
       return within 60s. Unlike those other AI-calling features, this
       endpoint already has a documented, number-accurate, deterministic
       fallback ready to go the instant the AI call is deemed too slow, so
       there is no reason to ever wait that long here. asyncio.wait_for
       bounds each attempt to dashboard_summary_ai_timeout_seconds (default
       20s, comfortably shorter than any underlying client's own timeout)
       and a timeout is treated the same as "AI unreachable" -- fall
       straight to the template, do not retry (an immediate retry against a
       backend that is merely slow/busy cannot help, and would just double
       the wait).
    4. Returns {"summary", "source", "kpis"}: "source" ("ai" or
       "template_fallback") honestly reflects which path produced the text,
       the same "never let a fallback silently look like a real success"
       discipline already established for FinalAssessment.ai_outcome (see
       app/ai/schemas.py's docstring for that field).
    """
    kpis = await get_kpis()

    user_prompt = (
        "## Given KPIs (exact values, already computed by this platform -- do not recalculate)\n"
        f"{_kpi_lines(kpis)}\n\n"
        "Write a 2-4 sentence executive narrative for SOC leadership based only on these KPIs."
    )

    timeout_seconds = get_settings().dashboard_summary_ai_timeout_seconds
    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            payload = await asyncio.wait_for(_call_ai_backend(user_prompt), timeout=timeout_seconds)
            narrative = _ExecutiveSummaryNarrative.model_validate(payload)
            return {"summary": narrative.narrative, "source": "ai", "kpis": kpis}
        except ValidationError as exc:
            last_exc = exc
            if attempt == 0:
                logger.info("Executive summary attempt 1 failed validation: %r -- retrying once", exc)
        except asyncio.TimeoutError as exc:
            last_exc = exc
            logger.warning(
                "Executive summary AI call exceeded the %ss dashboard timeout (shared AI backend "
                "busy/slow) -- falling back to template instead of waiting for the underlying "
                "AI client's own, much longer timeout",
                timeout_seconds,
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            break

    logger.warning("Executive summary generation failed, falling back to template: %r", last_exc)
    return {"summary": _template_fallback_narrative(kpis), "source": "template_fallback", "kpis": kpis}
