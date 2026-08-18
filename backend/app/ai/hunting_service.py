"""Threat-hunting query and detection-rule generation, grounded in the real
correlation graph so "hunting expansion" (related domains/certs/JA3/hashes)
only ever targets indicators the platform actually observed -- never an
AI-invented related indicator. Same call -> validate -> degrade shape as
app/ai/service.py and app/ai/analysis_service.py.
"""
import logging

from app.ai.analysis_schemas import DetectionRuleDraft, HuntingPackage
from app.ai.service import _get_ai_client
from app.correlation.engine import CorrelationResult

logger = logging.getLogger(__name__)

_HUNTING_SYSTEM_PROMPT = """You are a threat-hunting engineer generating copyable hunting queries for a SOC.
You are given one seed IOC and its real correlation graph (relationships actually discovered by the platform).

Rules:
- exact_match_queries: hunt for the exact seed IOC value across the requested query languages/platforms.
- expansion_targets: ONLY list related indicators (domains, certs, JA3/JA4, hashes, user agents, IPs) that literally
  appear as a node/target in the supplied correlation edges. NEVER invent a related indicator not present there.
  If no meaningful related indicators exist, return an empty list.
- broader_queries: hunting queries targeting the expansion_targets (not just the seed IOC), one query per format
  requested, referencing the actual expansion target values.
- Each query's `detects` field must plainly explain, in one sentence, what triggering that query would mean.
- Generate valid, realistic syntax for the requested query language -- do not pad with placeholder syntax.
"""

_DETECTION_SYSTEM_PROMPT = """You are a detection engineer drafting a production-quality detection rule for a SOC.
You are given one seed IOC, its type, and its real evidence ledger/verdict.

Rules:
- The rule must be valid syntax for the requested format and directly operationalize the seed IOC (e.g. match the
  exact domain/hash/IP value), not a generic template.
- detection_objective: one sentence, what this rule is meant to catch.
- data_source: what log/telemetry source this rule expects (e.g. "DNS query logs", "EDR process creation events").
- logic_explanation: how the rule's logic works, in plain language.
- false_positive_considerations: concrete scenarios that could trigger this rule benignly.
- severity should reflect the seed IOC's actual verdict/risk level supplied, not be invented independently.
- mitre_technique_ids: only include technique IDs that are actually relevant to this IOC type/behavior; leave empty if unsure.
"""


async def generate_hunting_package(
    ioc_value: str,
    ioc_type: str,
    formats: list[str],
    correlation: CorrelationResult,
) -> HuntingPackage:
    edges_block = "\n".join(
        f"{e.source} --{e.relationship}--> {e.target} [confidence={e.confidence:.2f}, via {e.provenance}]"
        for e in correlation.edges[:150]
    )
    user_prompt = (
        f"Seed IOC: {ioc_value} (type: {ioc_type})\n"
        f"Requested query formats: {', '.join(formats)}\n\n"
        f"Correlation edges (the ONLY valid source of expansion targets):\n{edges_block or '(none discovered)'}\n\n"
        "Generate the hunting package."
    )
    try:
        client, _backend, _model = await _get_ai_client()
        payload = await client.call_claude_json(
            system_prompt=_HUNTING_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            json_schema=HuntingPackage.model_json_schema(),
            tool_name="emit_hunting_package",
            max_tokens=8192,
        )
        package = HuntingPackage.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hunting package generation failed for %s: %r", ioc_value, exc)
        return HuntingPackage()

    # Grounding: strip any expansion target the model invented that isn't an
    # actual node value in the correlation graph.
    real_values = {node.value.lower() for node in correlation.nodes}
    package.expansion_targets = [
        t for t in package.expansion_targets if t.related_ioc_value.lower() in real_values
    ]
    return package


async def generate_detection_rule(
    ioc_value: str, ioc_type: str, format_: str, verdict_label: str, risk_score: float
) -> DetectionRuleDraft:
    user_prompt = (
        f"Seed IOC: {ioc_value} (type: {ioc_type})\n"
        f"Verdict: {verdict_label} (risk score: {risk_score})\n"
        f"Requested format: {format_}\n\n"
        "Draft the detection rule."
    )
    try:
        client, _backend, _model = await _get_ai_client()
        payload = await client.call_claude_json(
            system_prompt=_DETECTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            json_schema=DetectionRuleDraft.model_json_schema(),
            tool_name="emit_detection_rule",
            max_tokens=4096,
        )
        return DetectionRuleDraft.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Detection rule generation failed for %s/%s: %r", ioc_value, format_, exc)
        return DetectionRuleDraft(
            format=format_,
            title=f"Detection rule unavailable for {ioc_value}",
            rule="# Generation failed -- see platform logs.",
            detection_objective="Unavailable (generation error).",
            data_source="Unknown",
            logic_explanation="Unavailable (generation error).",
            false_positive_considerations="Unknown.",
            severity="none",
        )
