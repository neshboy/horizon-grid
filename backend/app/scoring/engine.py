"""Deterministic (non-AI) threat-scoring engine.

Computes `overall_risk_score` / `confidence_score` / `malicious_probability` /
severity from already-fetched evidence -- ProviderResult data, the
correlation engine's graph, and (optionally) Security Assessment Toolkit
findings -- with NO AI call and NO network I/O, mirroring the "pure function
over already-fetched data" philosophy of app/correlation/engine.py (read that
module's own docstring/comment style; this one follows it deliberately).

WHY this exists (see the mission this module is part of): historically
risk_score/malicious_probability/confidence_score/final_verdict were 100%
AI-generated in one call (app/ai/service.py::generate_final_assessment()).
Prompt wording alone ("do not fill this in") cannot reliably stop a model --
especially a local Ollama model -- from overriding a field it was told not
to touch (this is already a known, load-bearing assumption elsewhere in this
codebase: see FinalAssessment.ai_backend/ai_model in app/ai/schemas.py, which
are "never filled in by the model itself" only because app/ai/service.py
mechanically overwrites them post-hoc, not because the prompt says so). The
fix used throughout this platform for that exact class of problem is: decide
the number deterministically FIRST, then tell the AI the decided number as a
GIVEN fact and give it a narrower job (write a verdict/rationale consistent
with the number). This module is the "decide the number deterministically"
half of that fix; app/ai/service.py's generate_final_assessment() is the
"tell the AI, then re-enforce with a post-hoc overwrite" half.

SCORING_ENGINE_VERSION exists so a persisted assessment can always be traced
back to which version of this weighting scheme produced it (audit
requirement) -- bump it whenever the weights/formulas below change in a way
that would produce a different score for the same input.

--------------------------------------------------------------------------
WEIGHTING SCHEME (read this before changing any constant below)
--------------------------------------------------------------------------

The 0-100 "how malicious does the evidence look" budget is split across two
additive families of deterministic signal:

  * _PROVIDER_VERDICT_WEIGHT (65 points) -- cross-provider verdict/reputation
    consensus, extracted directly from each OK ProviderResult.data. This is
    the dominant signal because it is the most common one this platform
    actually has: most investigations have provider data and nothing else.

  * _CORRELATION_WEIGHT (35 points) -- malicious-adjacent relationships
    discovered by app/correlation/engine.py::correlate() (malware/threat-
    actor/campaign associations, MITRE technique usage, CVE exploitation),
    using each edge's own `confidence` field, which already bakes in a
    cross-provider corroboration bonus WHEN correlate() itself merged an
    identical claim from multiple providers into one edge (see correlate()'s
    _CORROBORATION_BONUS_PER_PROVIDER). That alone is NOT sufficient: a
    single provider asserting several DISTINCT qualifying values (e.g. one
    OTX pulse listing 4 free-text malware_families) produces 4 separate,
    never-merged edges that could saturate this component with zero
    cross-provider agreement -- confirmed exploitable via a real numeric
    red-team finding using nothing but a free, unprivileged community
    account on OTX/ThreatFox/MalwareBazaar. _correlation_fraction() below
    therefore ALSO applies _corroboration_factor(), keyed off the number of
    DISTINCT providers (GraphEdge.provenance) asserting ANY qualifying edge
    -- the same anti-flood defense the provider-vote component already had,
    now applied to correlation edges too. See that function's own docstring
    for the full incident writeup.

These two sum to 100 and together produce `malicious_probability` --
deliberately a PURE reputation/relationship signal, uninflated by anything
else (see the Security Assessment discussion below for why that matters).

Deliberately NOT consumed as an input: app/evidence/builder.py's
EvidenceRecord. build_evidence_from_correlation()'s records are a strict
re-statement of correlation.edges (no new information), but
build_evidence_from_providers()'s per-provider confidence is derived from an
AI-generated ProviderSummary.confidence bucket ("low"/"medium"/"high"), not
from the provider's own raw data. Consuming that would make this
"deterministic, non-AI" engine's output silently depend on an upstream AI
judgment call, which defeats the entire point of computing the score BEFORE
the AI is asked for anything. Reading ProviderResult/CorrelationResult
directly, as this module does, avoids that dependency entirely.

Corroboration for the PROVIDER VERDICT signal specifically (distinct from
correlation edges, which already have their own bonus) is modeled with a
`_corroboration_factor(n)` multiplier: a single provider's flag, with no
other provider agreeing OR disagreeing, is deliberately capped at 40% of
this component's max strength; it takes 5 independent providers agreeing to
reach full strength. This is the direct implementation of "a single provider
flagging malicious with no corroboration should score meaningfully lower
than 5 providers agreeing" -- a plain average of votes would NOT have this
property (one voter at 100% averages to 100%, same as five voters at 100%
each), so corroboration is applied as an explicit separate multiplier, not
folded into the average.

Conflicting provider verdicts (e.g. one provider says malicious, another
says clean) are NOT resolved by silently canceling out to a bland 50%
score reported with high confidence -- that would misrepresent a genuine
split as manufactured certainty. Instead:
  - `malicious_probability` reflects the honest mean of what providers
    actually said (a real 1-vs-1 split IS, honestly, uncertain -- reporting
    it as uncertain is correct, not a bug to paper over).
  - `confidence_score`'s provider-agreement term is multiplied by
    `(1 - agreement_spread)`, where `agreement_spread` is the distance
    between the most- and least-malicious vote. Perfect agreement leaves
    confidence untouched; a 1.0-vs-0.0 split drives that term to ZERO. This
    is the concrete mechanism that keeps a conflicting-evidence case from
    reporting high confidence in a mediocre number -- confidence collapses
    specifically BECAUSE the evidence disagrees, which a naive average of
    "confidence" values across providers would not do.

Security Assessment Toolkit findings (app/models/security_assessment.py's
SecurityAssessmentFinding.severity) are modeled as a FLOOR, not an additive
term, on `overall_risk_score` and `confidence_score` ONLY -- deliberately
NOT on `malicious_probability`:
  - A critical/high finding is a DIRECT technical observation made by THIS
    platform right now (nmap/TLS/DNS/HTTP tooling actually touched the
    target) -- unlike a reputation-feed opinion, it does not need
    cross-provider corroboration to be trustworthy, and an unrelated clean
    reputation history must not be able to dilute it. Modeling it as a
    floor (`overall_risk_score = max(threat_intel_score, sa_risk_floor)`)
    guarantees a critical finding "meaningfully raises risk" regardless of
    what else is or isn't known, without needing a delicate additive weight
    tuned to never be dilutable.
  - It is deliberately EXCLUDED from `malicious_probability`, because a
    vulnerability/exposure finding ("this target is dangerous to leave
    reachable") is a different claim from "this indicator is a confirmed
    malicious actor" -- an open critical RCE on an otherwise-unknown IP does
    not, by itself, prove that IP is itself malicious. Keeping
    `malicious_probability` as the pure reputation/relationship signal means
    FinalAssessment's own `_verdict_must_agree_with_risk` validator (which
    checks `risk.malicious_probability` against `final_verdict`) continues
    to mean exactly what it always meant, and a severe-but-unconfirmed
    exposure correctly cannot force a "malicious" verdict by itself -- it
    can, correctly, still force a "high"/"critical" `overall_risk_score`.

Deliberately does NOT read `correlation.provider_agreement` (recomputes the
equivalent signal directly from `provider_results` instead). Two
independent reasons: (1) app/evidence/loaders.py::correlation_from_records()
-- the rebuild path every non-live call site (reanalyze, security-assessment
refresh) uses -- always returns `provider_agreement={}` for a
persisted/rebuilt CorrelationResult, since CorrelationEdgeRecord has no
column for it; relying on it would make this engine silently blind at every
call site except the original live SSE stream. (2) even where it IS
populated, `provider_agreement` only buckets by an exact lowercased verdict
string, discarding a provider's own graduated multi-engine detection ratio
(e.g. VirusTotal's malicious_count/total_engines) in favor of one
categorical bucket. Recomputing directly from `provider_results` -- which is
available at every one of the three call sites this module is wired into --
sidesteps the persistence gap entirely and is strictly more precise.

Conservative-by-construction properties worth calling out explicitly:
  - A provider with no decodable verdict/reputation (`"unknown"`, missing,
    or an unrecognized string) casts NO vote at all -- it is excluded from
    the denominator, not coerced into "clean". Treating silence as innocence
    would manufacture confidence no provider actually offered.
  - Zero evidence of every kind (no votes, no qualifying correlation edges,
    no Security Assessment findings) produces an all-zero result, not an
    error and not a fabricated non-zero number.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from pydantic import BaseModel, Field

from app.ai.schemas import _ThreatLevel  # reuse the ONE existing severity-band vocabulary; see module docstring
from app.correlation.engine import CorrelationResult, GraphEdge
from app.providers.base import ProviderStatus

SCORING_ENGINE_VERSION = "1.0"

# --- Weight budget for the "how malicious does the evidence look" score,
# which becomes malicious_probability and (via the SA floor) contributes to
# overall_risk_score. Sums to 100 -- see module docstring for the rationale
# behind the 65/35 split.
_PROVIDER_VERDICT_WEIGHT = 65.0
_CORRELATION_WEIGHT = 35.0

# Per-provider verdict/reputation string -> a 0.0-1.0 "how malicious does
# THIS provider think this indicator is" vote. Matches the exact vocabulary
# every real connector emits today (confirmed by reading every provider
# under app/providers/: virustotal.py, abuseipdb.py, otx.py, nvd.py,
# urlscan_io.py, urlhaus.py, malwarebazaar.py, threatfox.py, cisa_kev.py,
# google_safe_browsing.py all emit exactly one of these four strings, or
# nothing at all). "suspicious" is weighted at just over half of
# "malicious" -- a deliberately soft middle value, not a precise measurement
# of anything, since no provider's own scale claims more precision than
# that.
_VERDICT_VOTE: dict[str, float] = {"malicious": 1.0, "suspicious": 0.55, "clean": 0.0}

# Security Assessment severity -> floor applied to overall_risk_score /
# confidence_score (see module docstring for why this is a floor rather than
# an additive term, and why it does NOT apply to malicious_probability).
_SA_RISK_FLOOR: dict[str, float] = {
    "critical": 70.0,
    "high": 45.0,
    "medium": 20.0,
    "low": 5.0,
    "info": 0.0,
}
_SA_CONFIDENCE_FLOOR: dict[str, float] = {
    "critical": 60.0,
    "high": 45.0,
    "medium": 30.0,
    "low": 15.0,
    "info": 0.0,
}
_SA_SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")

# Correlation-graph relationships that plausibly indicate malice by
# themselves (malware/threat-actor/campaign association, ATT&CK technique
# usage, CVE exploitation) -- deliberately EXCLUDES purely infrastructural
# relationships (resolves_to, hosts, belongs_to_asn, serves_certificate,
# related_to), since e.g. an IP resolving to a domain is not itself evidence
# of anything malicious. Mirrors the grouping app/evidence/builder.py's own
# _relationship_evidence_type() already uses to distinguish
# malware_association/threat_actor_association/campaign_association/
# mitre_technique from generic "infrastructure" edges -- this module reuses
# that same conceptual split rather than inventing a new one.
_QUALIFYING_RELATIONSHIPS = {"associated_with", "attributed_to", "part_of_campaign", "exploits", "uses_technique"}

# Sum of qualifying-edge confidences (each 0.0-1.0) needed to reach full
# correlation-component strength. 2.0 means, for example, two independently
# corroborated malware-family edges (confidence ~1.0 each) already saturate
# this component -- a deliberately low bar, since correlate() already
# required real provider data to produce any such edge at all.
_CORRELATION_SATURATION = 2.0

# Severity band thresholds applied to overall_risk_score. Deliberately
# conservative/round numbers (not tuned against any labeled dataset -- there
# isn't one), documented here rather than buried, since a future maintainer
# adjusting them should know they are a starting judgment call, not a
# calibrated statistic.
_SEVERITY_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (80.0, "critical"),
    (55.0, "high"),
    (30.0, "medium"),
    (10.0, "low"),
)


class ScoringResult(BaseModel):
    """Deterministic scoring output. See app/scoring/engine.py's module
    docstring for exactly how each field is derived and why
    malicious_probability and overall_risk_score can legitimately differ.
    """

    overall_risk_score: float = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=100)
    malicious_probability: float = Field(ge=0, le=100)
    severity: _ThreatLevel
    engine_version: str = SCORING_ENGINE_VERSION
    # Per-factor contributions, kept for auditability/explainability (e.g. a
    # future "Score Explanation" UI feature) -- every number here is
    # reproducible directly from the inputs, unlike anything AI-authored.
    breakdown: dict[str, float] = Field(default_factory=dict)


def _clip(value: float) -> float:
    return max(0.0, min(100.0, value))


def _severity_value(raw: Any) -> Optional[str]:
    """Accepts either a plain severity string or an object exposing a
    `.value` (e.g. app/models/security_assessment.py's Severity enum) --
    callers pass whichever is convenient without this module needing to
    import that model and take on a SQLAlchemy dependency it otherwise has
    no reason to have."""
    if raw is None:
        return None
    value = getattr(raw, "value", raw)
    value = str(value).lower()
    return value if value in _SA_SEVERITY_ORDER else None


def _provider_votes(provider_results: Sequence[Any]) -> list[float]:
    """Extracts one 0.0-1.0 "how malicious" vote per OK provider result that
    offered a decodable verdict/reputation, preferring a provider's own
    graduated multi-engine detection ratio when it has one.

    Accepts anything exposing `.status` (comparable to ProviderStatus.OK --
    true for both app/providers/base.py's ProviderResult dataclass AND
    app/models/lookup.py's ProviderResultRecord ORM rows, since
    ProviderStatus is a str-enum and the ORM column stores the matching
    plain string) and `.data` (a dict) -- deliberately duck-typed rather
    than importing ProviderResult specifically, since reanalyze_lookup() in
    app/api/routes/lookup.py calls this with persisted ORM rows, not fresh
    dataclass instances, and requiring a real ProviderResult there would
    force pointless reconstruction of objects this module doesn't need.
    """
    votes: list[float] = []
    for result in provider_results:
        if result.status != ProviderStatus.OK:
            continue
        data = result.data or {}

        total_engines = data.get("total_engines")
        malicious_count = data.get("malicious_count")
        if (
            isinstance(total_engines, (int, float))
            and total_engines
            and isinstance(malicious_count, (int, float))
        ):
            suspicious_count = data.get("suspicious_count") or 0
            if not isinstance(suspicious_count, (int, float)):
                suspicious_count = 0
            vote = (malicious_count + 0.5 * suspicious_count) / total_engines
            votes.append(max(0.0, min(1.0, vote)))
            continue

        verdict = data.get("verdict") or data.get("reputation")
        if verdict is None:
            continue
        vote = _VERDICT_VOTE.get(str(verdict).lower())
        if vote is not None:
            votes.append(vote)
    return votes


def _corroboration_factor(n: int) -> float:
    """How much of _PROVIDER_VERDICT_WEIGHT a set of `n` agreeing-or-not
    provider votes can reach, before the mean-vote direction is even
    applied. n=1 -> 0.40 (a lone flag is deliberately capped well under full
    strength); n=5+ -> 1.00. Mirrors app/correlation/engine.py's own
    _CORROBORATION_BONUS_PER_PROVIDER philosophy (independent corroboration
    is itself evidence) rescaled from an additive confidence bump to a
    0.0-1.0 multiplier, since this is scaling a whole component rather than
    nudging an already-established base confidence."""
    if n <= 0:
        return 0.0
    return min(1.0, 0.40 + 0.15 * (n - 1))


def _correlation_fraction(edges: Iterable[GraphEdge]) -> float:
    """Regression test for a real, numerically-reproduced red-team finding:
    without the corroboration discount below, a SINGLE provider asserting
    multiple distinct qualifying relationships (e.g. one OTX pulse listing 4
    free-text malware_families -- correlate() gives each distinct value its
    own edge, so they never merge into one corroborated edge the way an
    identical claim from two providers would) could single-handedly saturate
    this component and push overall_risk_score/malicious_probability into
    the "high" band, with zero cross-provider corroboration and zero real
    malicious infrastructure -- exploitable via a free, unprivileged OTX/
    ThreatFox/MalwareBazaar community account, since those providers build
    malware_families/threat_actors/campaigns directly from community-
    submitted free text (see otx.py/threatfox.py/malwarebazaar.py). This
    directly contradicted the module's own "conservative by construction"
    guarantee and the provider-vote component's own explicit anti-flood
    defense (_corroboration_factor) -- correlation edges had no equivalent.

    Fix: apply that SAME _corroboration_factor(), keyed off the number of
    DISTINCT providers asserting ANY qualifying edge (GraphEdge.provenance
    is the asserting provider_id, comma-joined when correlate() already
    merged an identical claim from multiple providers -- see that module's
    edge-construction site). A single provider's edges -- however many
    distinct fabricated values they contain -- are capped at 40% strength,
    identical to a lone provider vote; genuine corroboration from 2+
    independent providers scales back up toward full strength. This does NOT
    penalize a real multi-provider corroborated finding (which already had
    boosted per-edge confidence from correlate() itself) -- it specifically
    closes the "one source, many fabricated distinct edges" flood gap.

    IMPORTANT: `total_confidence` (the sum of qualifying-edge confidences) is
    UNBOUNDED -- it grows with every additional distinct qualifying edge, and
    correlate() places no ceiling on how many edges one provider can assert.
    `corroboration` MUST therefore be applied as a multiplier on an
    already-0.0-1.0-bounded evidence fraction, never on the raw unbounded
    sum -- multiplying an unbounded sum by a fixed 0.4 and clipping the
    *product* to 100 does NOT cap the achievable fraction at 40%; it only
    raises how much raw evidence is needed to reach 100% (from
    _CORRELATION_SATURATION to _CORRELATION_SATURATION / 0.4), so enough
    distinct same-provider edges still saturate this component fully with
    zero corroboration -- this exact bug is what this docstring's own
    "capped at 40% strength" claim previously failed to deliver. Bounding
    the evidence fraction to [0, 1] FIRST (mirroring how the provider-vote
    component bounds mean_vote to [0, 1] via an average before multiplying by
    its own corroboration factor), THEN multiplying by corroboration, makes
    corroboration a true ceiling: a lone provider's fraction can never exceed
    corroboration's value (0.40) no matter how much raw confidence it piles
    up.
    """
    qualifying = [edge for edge in edges if edge.relationship in _QUALIFYING_RELATIONSHIPS]
    total_confidence = sum(edge.confidence for edge in qualifying)
    distinct_providers = {provider_id for edge in qualifying for provider_id in edge.provenance.split(",")}
    corroboration = _corroboration_factor(len(distinct_providers))
    evidence_fraction = min(1.0, total_confidence / _CORRELATION_SATURATION)
    return evidence_fraction * corroboration


def _top_severity(security_finding_severities: Optional[Iterable[Any]]) -> Optional[str]:
    if not security_finding_severities:
        return None
    present = [v for v in (_severity_value(s) for s in security_finding_severities) if v is not None]
    if not present:
        return None
    return max(present, key=_SA_SEVERITY_ORDER.index)


def _severity_band(overall_risk_score: float) -> str:
    for threshold, band in _SEVERITY_THRESHOLDS:
        if overall_risk_score >= threshold:
            return band
    return "none"


def score_investigation(
    provider_results: Sequence[Any],
    correlation: CorrelationResult,
    security_finding_severities: Optional[Iterable[Any]] = None,
) -> ScoringResult:
    """Computes the deterministic score for one investigation.

    Args:
        provider_results: every provider result collected for this lookup so
            far (any status; non-OK entries are ignored the same way
            app/correlation/engine.py::correlate() ignores them). Accepts
            either app/providers/base.py's ProviderResult or
            app/models/lookup.py's ProviderResultRecord ORM rows -- see
            _provider_votes()'s docstring.
        correlation: this lookup's CorrelationResult (freshly computed via
            correlate(), rebuilt via app/evidence/loaders.py's
            correlation_from_records(), or merged via
            app/correlation/engine.py's merge_correlation_results() -- all
            three shapes expose the same `.edges`, which is all this
            function reads).
        security_finding_severities: every SecurityAssessmentFinding.severity
            (or plain severity string) already recorded for this lookup, if
            the Security Assessment Toolkit has ever run against it. None/
            empty is the common case (most investigations never run it).

    Returns:
        A ScoringResult. Never raises for empty/absent evidence -- an
        investigation with nothing at all produces an all-zero result.
    """
    votes = _provider_votes(provider_results)
    n = len(votes)
    mean_vote = (sum(votes) / n) if n else 0.0
    corroboration = _corroboration_factor(n)
    agreement_spread = (max(votes) - min(votes)) if n else 0.0

    provider_component = _PROVIDER_VERDICT_WEIGHT * mean_vote * corroboration
    provider_confidence = _PROVIDER_VERDICT_WEIGHT * corroboration * (1.0 - agreement_spread)

    correlation_fraction = _correlation_fraction(correlation.edges)
    correlation_component = _CORRELATION_WEIGHT * correlation_fraction
    # A corroborated, high-confidence correlation edge IS its own confidence
    # signal here -- unlike independent provider votes, there is no separate
    # "how much did sources disagree" axis for a single graph, so the same
    # fraction that drives the risk contribution also drives the confidence
    # contribution.
    correlation_confidence = _CORRELATION_WEIGHT * correlation_fraction

    threat_intel_score = provider_component + correlation_component
    threat_intel_confidence = provider_confidence + correlation_confidence

    top_severity = _top_severity(security_finding_severities)
    sa_risk_floor = _SA_RISK_FLOOR.get(top_severity, 0.0) if top_severity else 0.0
    sa_confidence_floor = _SA_CONFIDENCE_FLOOR.get(top_severity, 0.0) if top_severity else 0.0

    malicious_probability = _clip(threat_intel_score)
    overall_risk_score = _clip(max(threat_intel_score, sa_risk_floor))
    confidence_score = _clip(max(threat_intel_confidence, sa_confidence_floor))

    # Round FIRST, then classify severity off that same rounded value -- the
    # severity label must always agree with _SEVERITY_THRESHOLDS applied to
    # the actual overall_risk_score returned below, not to the pre-round
    # full-precision value (which can sit just under a threshold while its
    # rounded form lands on/over it, e.g. 29.9958 -> 30.0).
    overall_risk_score_rounded = round(overall_risk_score, 1)

    return ScoringResult(
        overall_risk_score=overall_risk_score_rounded,
        confidence_score=round(confidence_score, 1),
        malicious_probability=round(malicious_probability, 1),
        severity=_severity_band(overall_risk_score_rounded),
        breakdown={
            "voting_provider_count": float(n),
            "mean_provider_vote": round(mean_vote, 3),
            "provider_corroboration_factor": round(corroboration, 3),
            "provider_agreement_spread": round(agreement_spread, 3),
            "provider_component": round(provider_component, 2),
            "correlation_qualifying_fraction": round(correlation_fraction, 3),
            "correlation_component": round(correlation_component, 2),
            "security_assessment_risk_floor": round(sa_risk_floor, 2),
            "security_assessment_confidence_floor": round(sa_confidence_floor, 2),
        },
    )
