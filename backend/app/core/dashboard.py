"""Executive/operational dashboard aggregation -- GET /dashboard/kpis and the
real (DB-backed) GET /providers/health.

Both functions here are READ-ONLY aggregations over data other subsystems
already persisted (IOCLookup, Case, ProviderResultRecord,
FinalAssessmentRecord). Neither one makes a new provider call or a new AI
call -- this module exists purely to summarize history, never to generate it.

Modeled after app/core/users.py::get_stats(): one `async with new_session()`
block, one select(func.count())/select(func.avg()) per metric, no raw SQL.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select

from app.core.db import new_session
from app.models.case import Case, CaseSeverity, CaseStatus
from app.models.lookup import FinalAssessmentRecord, IOCLookup, LookupStatus, ProviderResultRecord, Verdict
from app.providers.base import ProviderStatus
from app.providers.registry import get_all_providers

logger = logging.getLogger(__name__)

# Shared 30-day lookback window for "recent" KPIs (critical_high_risk_iocs,
# avg_threat_score) and for ai_success_rate below. This is a JUDGMENT CALL,
# not a spec requirement: 30 days keeps these numbers focused on "what's
# happening lately" instead of drifting as ioc_lookups/final_assessment_records
# accumulate years of history. Named once so every KPI that uses it stays
# consistent with the others by construction rather than by convention.
KPI_LOOKBACK_DAYS = 30

# provider_health_percentage looks back 24h -- deliberately shorter than the
# 30-day KPI window above, since "is the provider fleet healthy right now" is
# an operational question that should react quickly to a provider going down,
# not be smoothed out over a month of history.
PROVIDER_HEALTH_WINDOW_HOURS = 24

# ProviderResultRecord.status values that do NOT represent a real attempt to
# reach the provider (app/providers/base.py's ProviderStatus) -- an
# administrator's deliberate choice to leave a provider unconfigured/disabled
# is not an operational health failure, so these are excluded from BOTH the
# numerator and denominator of every success-rate calculation in this module
# (the KPI's provider_health_percentage AND get_provider_health_history()'s
# per-window success_rate/status).
_NON_ATTEMPT_STATUSES = (ProviderStatus.NOT_CONFIGURED.value, ProviderStatus.DISABLED.value)

# Statuses that represent the provider being reached and behaving CORRECTLY --
# as opposed to a genuine problem (ERROR/TIMEOUT/RATE_LIMITED). NO_DATA means
# the provider was queried fine and truthfully reported "nothing on this
# indicator" (confirmed by reading real providers: app/providers/virustotal.py
# maps VirusTotal's HTTP 404 "not in our database" straight to NO_DATA; most
# real-world IOCs legitimately get NO_DATA from most sources, since no
# indicator is in every dataset). UNSUPPORTED_IOC means the provider correctly
# recognized it doesn't handle this IOC type -- also not a failure of the
# provider itself. Counting either as a failure would report a perfectly
# healthy, correctly-functioning provider as "down"/"degraded" for doing
# exactly what it's supposed to do -- this is the mirror image of the
# "provider incorrectly reporting HEALTHY" defect class this endpoint exists
# to avoid, and just as real: a healthy provider incorrectly reported as
# unhealthy is exactly as misleading to an operator.
_HEALTHY_OUTCOME_STATUSES = (ProviderStatus.OK.value, ProviderStatus.NO_DATA.value, ProviderStatus.UNSUPPORTED_IOC.value)

# avg_latency_ms is deliberately narrower than "healthy outcome": OK and
# NO_DATA both represent a completed real network round-trip (worth
# averaging), but UNSUPPORTED_IOC is typically rejected locally before any
# request is made, so including it would understate real provider latency.
_LATENCY_ELIGIBLE_STATUSES = (ProviderStatus.OK.value, ProviderStatus.NO_DATA.value)


def _round_or(value: "float | None", default: "float | None") -> "float | None":
    """`value` is a raw scalar straight off a `func.avg(...)`/nullable
    aggregate -- Postgres returns SQL NULL (None) when there are zero
    qualifying rows. `default` is what THIS metric should report for that
    "no data" case; different KPIs deliberately choose different defaults
    (see get_kpis()'s avg_threat_score -- default 0.0 -- vs.
    get_provider_health_history()'s avg_latency_ms -- default None), so this
    helper takes the default as a parameter rather than hardcoding one."""
    return round(float(value), 2) if value is not None else default


def _rate_or(numerator: int, denominator: int, default: "float | None") -> "float | None":
    """Percentage of `numerator`/`denominator`, or `default` when
    `denominator` is 0 -- a rate is undefined with no data, so callers pick
    the honest default for their metric (see _round_or()'s docstring for why
    this is a parameter, not a hardcoded choice): provider_health_percentage
    uses 0.0 (a KPI tile that must always render a number), while
    ai_success_rate and every per-window success_rate use None (there truly
    is no rate to report, and showing 0%/100% would misrepresent it)."""
    return round(numerator / denominator * 100, 2) if denominator else default


async def get_kpis() -> dict:
    """Six executive KPIs for the ops/exec dashboard. Every definition below
    is a decision, documented here so a future reader never has to
    reverse-engineer it from the query alone.
    """
    now = datetime.now(timezone.utc)
    kpi_window_start = now - timedelta(days=KPI_LOOKBACK_DAYS)
    health_window_start = now - timedelta(hours=PROVIDER_HEALTH_WINDOW_HOURS)

    async with new_session() as db:
        # active_investigations: count of IOCLookup currently pending/running.
        # No time window -- this is a LIVE snapshot of what's in flight right
        # now, not a historical count.
        active_investigations = (
            await db.execute(
                select(func.count())
                .select_from(IOCLookup)
                .where(IOCLookup.status.in_([LookupStatus.PENDING, LookupStatus.RUNNING]))
            )
        ).scalar_one()

        # critical_high_risk_iocs: completed lookups verdicted
        # highly_malicious/malicious, created within the last
        # KPI_LOOKBACK_DAYS (30) days. The 30-day window is a judgment call
        # (see module docstring/constant above), not a spec requirement.
        critical_high_risk_iocs = (
            await db.execute(
                select(func.count())
                .select_from(IOCLookup)
                .where(
                    IOCLookup.status == LookupStatus.COMPLETED,
                    IOCLookup.final_verdict.in_([Verdict.HIGHLY_MALICIOUS, Verdict.MALICIOUS]),
                    IOCLookup.created_at >= kpi_window_start,
                )
            )
        ).scalar_one()

        # open_cases / open_critical_cases: reported as two SEPARATE fields
        # (not collapsed into one) -- a SOC dashboard needs to distinguish
        # "everything open" from "open AND critical" at a glance.
        open_cases = (
            await db.execute(select(func.count()).select_from(Case).where(Case.status == CaseStatus.OPEN))
        ).scalar_one()
        open_critical_cases = (
            await db.execute(
                select(func.count())
                .select_from(Case)
                .where(Case.status == CaseStatus.OPEN, Case.severity == CaseSeverity.CRITICAL)
            )
        ).scalar_one()

        # avg_threat_score: AVG(risk_score) over completed lookups in the
        # SAME 30-day window as critical_high_risk_iocs, for consistency
        # between the two "recent risk" KPIs (also a judgment call). NULL (no
        # qualifying rows) -> 0, never an error and never a fabricated
        # number -- mirrors app/scoring/engine.py's own "zero evidence
        # produces an all-zero result, not an error" philosophy.
        avg_threat_score_raw = (
            await db.execute(
                select(func.avg(IOCLookup.risk_score)).where(
                    IOCLookup.status == LookupStatus.COMPLETED,
                    IOCLookup.created_at >= kpi_window_start,
                )
            )
        ).scalar_one()
        avg_threat_score = _round_or(avg_threat_score_raw, 0.0)

        # provider_health_percentage: % of ProviderResultRecord rows with a
        # HEALTHY outcome (see _HEALTHY_OUTCOME_STATUSES above -- OK or the
        # provider correctly reporting NO_DATA/UNSUPPORTED_IOC) out of all
        # rows in the last 24h, EXCLUDING not_configured/disabled from BOTH
        # numerator and denominator (see _NON_ATTEMPT_STATUSES above) -- a
        # provider nobody configured must never drag this number down, and a
        # provider correctly reporting "nothing found" must never look like a
        # failure either.
        provider_attempts = (
            await db.execute(
                select(func.count())
                .select_from(ProviderResultRecord)
                .where(
                    ProviderResultRecord.created_at >= health_window_start,
                    ProviderResultRecord.status.notin_(_NON_ATTEMPT_STATUSES),
                )
            )
        ).scalar_one()
        provider_ok = (
            await db.execute(
                select(func.count())
                .select_from(ProviderResultRecord)
                .where(
                    ProviderResultRecord.created_at >= health_window_start,
                    ProviderResultRecord.status.in_(_HEALTHY_OUTCOME_STATUSES),
                )
            )
        ).scalar_one()
        provider_health_percentage = _rate_or(provider_ok, provider_attempts, 0.0)

        # ai_success_rate: success / (success + failed) from
        # FinalAssessmentRecord.ai_outcome, created within the last 30 days
        # (same KPI_LOOKBACK_DAYS window as above). ai_outcome='skipped_no_evidence'
        # is EXCLUDED entirely from both numerator and denominator -- a
        # correct decision not to call the AI is neither a success nor a
        # failure of the AI.
        #
        # DECISION: counts EVERY final_assessment_records row in the window,
        # including non-primary rows created by reanalyze_lookup's
        # AI-backend-comparison feature (is_primary=False) -- not just
        # is_primary=True rows. Rationale: this KPI answers "how reliable is
        # the AI backend, in general", and a comparison re-run against a
        # different backend (Groq/Bedrock/etc.) is just as real an AI
        # invocation as a primary run; restricting to is_primary=True would
        # silently discard real reliability signal every time an analyst uses
        # the comparison feature. If success+failed == 0 in the window,
        # returns None (not 0, not 100) -- there is no rate when there is no
        # data, and reporting either number would misrepresent AI reliability.
        ai_success = (
            await db.execute(
                select(func.count())
                .select_from(FinalAssessmentRecord)
                .where(
                    FinalAssessmentRecord.ai_outcome == "success",
                    FinalAssessmentRecord.created_at >= kpi_window_start,
                )
            )
        ).scalar_one()
        ai_failed = (
            await db.execute(
                select(func.count())
                .select_from(FinalAssessmentRecord)
                .where(
                    FinalAssessmentRecord.ai_outcome == "failed",
                    FinalAssessmentRecord.created_at >= kpi_window_start,
                )
            )
        ).scalar_one()
        ai_denominator = ai_success + ai_failed
        ai_success_rate = _rate_or(ai_success, ai_denominator, None)

    return {
        "active_investigations": active_investigations,
        "critical_high_risk_iocs": critical_high_risk_iocs,
        "open_cases": open_cases,
        "open_critical_cases": open_critical_cases,
        "avg_threat_score": avg_threat_score,
        "provider_health_percentage": provider_health_percentage,
        "ai_success_rate": ai_success_rate,
    }


# Rolling windows reported for every provider by get_provider_health_history().
_HEALTH_WINDOWS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

# Health-status thresholds -- judgment calls (documented, not agonized over).
# "success_rate" here means % of real attempts with a _HEALTHY_OUTCOME_STATUSES
# outcome (OK or a correct NO_DATA/UNSUPPORTED_IOC response) -- NOT literal
# status='ok' alone, since most real-world IOCs legitimately get NO_DATA from
# most providers and that must never look like the provider failing:
#   - "unknown": zero real attempts (rows outside _NON_ATTEMPT_STATUSES) in
#     the window. This provider was simply never exercised in this window --
#     silence is NOT evidence of health, so this must never be "healthy".
#   - "healthy": >=1 real attempt AND success_rate >= _HEALTHY_SUCCESS_RATE.
#   - "degraded": >=1 real attempt AND 0% < success_rate < _HEALTHY_SUCCESS_RATE.
#   - "down": >=1 real attempt AND success_rate == 0%.
_HEALTHY_SUCCESS_RATE = 90.0

# How many of a provider's most-recent ProviderResultRecord rows (across ALL
# time) to inspect when walking back for consecutive_failures. A genuine
# failure streak this long is already a severe, obvious outage; capping the
# query keeps it cheap without ever under-counting a realistic streak.
_CONSECUTIVE_FAILURE_LOOKBACK_ROWS = 500


def _status_for_window(attempts: int, ok: int) -> str:
    if attempts == 0:
        return "unknown"
    success_rate = ok / attempts * 100
    if success_rate == 0:
        return "down"
    if success_rate >= _HEALTHY_SUCCESS_RATE:
        return "healthy"
    return "degraded"


async def _consecutive_failures(db, provider_id: str) -> int:
    """Walks this provider's most-recent ProviderResultRecord rows, most-recent
    first, across ALL time (not scoped to any window -- a genuine current
    failure streak doesn't reset just because it crossed a window boundary).
    Skips (doesn't count, doesn't break on) rows in _NON_ATTEMPT_STATUSES,
    since those aren't real attempts. Stops at the first row with a HEALTHY
    outcome (_HEALTHY_OUTCOME_STATUSES -- OK or a correct NO_DATA/
    UNSUPPORTED_IOC response), not just a literal 'ok' row -- otherwise a
    provider that's been correctly returning NO_DATA would show a fictitious,
    ever-growing "failure streak" for doing nothing wrong.
    """
    rows = (
        (
            await db.execute(
                select(ProviderResultRecord.status)
                .where(ProviderResultRecord.provider_id == provider_id)
                .order_by(ProviderResultRecord.created_at.desc())
                .limit(_CONSECUTIVE_FAILURE_LOOKBACK_ROWS)
            )
        )
        .scalars()
        .all()
    )
    count = 0
    for status in rows:
        if status in _NON_ATTEMPT_STATUSES:
            continue
        if status in _HEALTHY_OUTCOME_STATUSES:
            break
        count += 1
    return count


async def _all_provider_window_metrics(db, provider_ids: list[str], now: datetime) -> dict[str, dict]:
    """Replaces what used to be 4 windows x 4 metrics = 16 separate
    `await db.execute(...)` round-trips PER PROVIDER with ONE round-trip for
    ALL of `provider_ids` at once, via SQL conditional aggregation
    (`func.sum(case((condition, 1), else_=0))` / `func.avg(case((condition,
    latency_ms), else_=None))`) plus `GROUP BY provider_id` -- the database
    computes every window's attempts/ok/avg_latency/rate_limited in a single
    SELECT instead of get_provider_health_history() issuing one query per
    (provider, window, metric) combination. This is the dominant fix for the
    "25 concurrent requests to /providers/health times out" load-test finding
    documented in this module's callers: the bottleneck was never connection-
    pool sizing, it was ~306 sequential awaited round-trips held open on one
    connection for the whole request.

    Filters to `created_at >= widest window start` up front (the 4
    _HEALTH_WINDOWS all share the same `now` anchor and are strictly nested --
    1h subset-of 24h subset-of 7d subset-of 30d -- so no row that could
    satisfy ANY window's `in_window` condition is ever excluded by this
    pre-filter; it only skips rows already too old to matter for any window,
    exactly as the old per-window queries did via their own window_start
    filter). Also filters to `provider_id IN provider_ids` so a query against
    a real, long-lived production table never pays to aggregate history for
    providers that were since removed from the registry.

    Returns a dict keyed by provider_id -> {"attempts_<label>": int,
    "ok_<label>": int, "avg_latency_<label>": float | Decimal | None,
    "rate_limited_<label>": int} for each label in _HEALTH_WINDOWS.
    A provider_id with literally zero ProviderResultRecord rows in the
    lookback window (including one with ZERO rows ever) is simply ABSENT from
    this dict -- callers must default that to the same "zero rows" values the
    old per-window queries would have produced (attempts=0, ok=0,
    avg_latency=None, rate_limited=0), preserving
    test_zero_rows_reports_unknown_never_healthy_in_every_window's contract
    byte-for-byte.
    """
    if not provider_ids:
        return {}

    window_starts = {label: now - delta for label, delta in _HEALTH_WINDOWS.items()}
    widest_start = min(window_starts.values())

    columns = [ProviderResultRecord.provider_id]
    for label, window_start in window_starts.items():
        in_window = ProviderResultRecord.created_at >= window_start
        columns.append(
            func.sum(
                case((and_(in_window, ProviderResultRecord.status.notin_(_NON_ATTEMPT_STATUSES)), 1), else_=0)
            ).label(f"attempts_{label}")
        )
        columns.append(
            func.sum(
                case((and_(in_window, ProviderResultRecord.status.in_(_HEALTHY_OUTCOME_STATUSES)), 1), else_=0)
            ).label(f"ok_{label}")
        )
        columns.append(
            func.avg(
                case(
                    (
                        and_(
                            in_window,
                            ProviderResultRecord.status.in_(_LATENCY_ELIGIBLE_STATUSES),
                            ProviderResultRecord.latency_ms.is_not(None),
                        ),
                        ProviderResultRecord.latency_ms,
                    ),
                    else_=None,
                )
            ).label(f"avg_latency_{label}")
        )
        columns.append(
            func.sum(
                case(
                    (and_(in_window, ProviderResultRecord.status == ProviderStatus.RATE_LIMITED.value), 1), else_=0
                )
            ).label(f"rate_limited_{label}")
        )

    rows = (
        (
            await db.execute(
                select(*columns)
                .where(
                    ProviderResultRecord.provider_id.in_(provider_ids),
                    ProviderResultRecord.created_at >= widest_start,
                )
                .group_by(ProviderResultRecord.provider_id)
            )
        )
        .mappings()
        .all()
    )
    return {row["provider_id"]: dict(row) for row in rows}


async def get_provider_health_history() -> list[dict]:
    """Real, DB-backed replacement for the old static-config-only
    get_provider_health() stub -- computed from app/models/lookup.py's
    ProviderResultRecord (one row per provider per real investigation).

    Response shape -- a list with one dict per provider returned by
    app/providers/registry.py::get_all_providers() (every registered
    provider, even ones with zero rows ever), shaped like:

        [
          {
            "provider_id": "virustotal",
            "provider_name": "VirusTotal",
            "category": "threat_intel",
            "configured": True,
            "requires_key": True,
            "supported_types": ["domain", "ipv4", ...],
            "1h":  {"status": ..., "success_rate": ..., "avg_latency_ms": ..., "consecutive_failures": ..., "rate_limited_count": ...},
            "24h": {...},
            "7d":  {...},
            "30d": {...},
          },
          ...
        ]

    Per-window fields:
      - status: "healthy" | "degraded" | "down" | "unknown" -- see
        _status_for_window()/_HEALTHY_SUCCESS_RATE above for the exact rule.
        CRITICAL: a window with zero ProviderResultRecord rows is ALWAYS
        "unknown", never "healthy" -- a provider that was never exercised has
        no evidence of health, and reporting "healthy" for it is exactly the
        release-blocking defect class this endpoint exists to avoid.
      - success_rate: % of this window's real attempts with a HEALTHY outcome
        (_HEALTHY_OUTCOME_STATUSES -- status='ok' OR the provider correctly
        reporting no_data/unsupported_ioc), excluding not_configured/disabled
        from the denominator too. None if this window has zero real attempts
        (there is no rate to report).
      - avg_latency_ms: AVG(latency_ms) over status IN (ok, no_data) rows
        (_LATENCY_ELIGIBLE_STATUSES -- both represent a completed real
        network round-trip) with latency_ms IS NOT NULL, for this window.
        None if no qualifying rows.
      - consecutive_failures: see _consecutive_failures() -- NOT scoped to
        this window (identical across all four windows for a given
        provider, by design, since a failure streak is a single ongoing
        fact about the provider, not a per-window one).
      - rate_limited_count: count of status='rate_limited' rows in this
        window.
    """
    now = datetime.now(timezone.utc)
    providers = get_all_providers()
    provider_ids = [provider.provider_id for provider in providers]

    result: list[dict] = []
    async with new_session() as db:
        # ONE query for every provider's attempts/ok/avg_latency/rate_limited
        # across all 4 windows (was 4 windows x 4 metrics x len(providers)
        # separate queries -- see _all_provider_window_metrics()'s docstring).
        metrics_by_provider = await _all_provider_window_metrics(db, provider_ids, now)

        for provider in providers:
            # Still one query per provider (unchanged from before this
            # optimization) -- see _consecutive_failures()'s docstring for why
            # this stays a small, individually-indexed, LIMIT-bounded query
            # per provider rather than a single all-providers window-function
            # query: it's already cheap (index scan on provider_id +
            # LIMIT _CONSECUTIVE_FAILURE_LOOKBACK_ROWS) and stays cheap
            # regardless of how large the table grows, which a single
            # unbounded "top N per provider_id" window function over the
            # whole table would not guarantee without a supporting composite
            # index this change doesn't introduce.
            consecutive_failures = await _consecutive_failures(db, provider.provider_id)
            metrics = metrics_by_provider.get(provider.provider_id)

            entry: dict = {
                "provider_id": provider.provider_id,
                "provider_name": provider.provider_name,
                "category": provider.category.value,
                # Kept from the old static-config stub this function replaces
                # (app/providers/registry.py::get_provider_health(), now dead) --
                # frontend/app/lookup/new/page.tsx's getProviderHealth() caller
                # already depends on `supported_types` today (to compute how
                # many providers are expected to respond for the detected IOC
                # type) and was NOT told about when this endpoint's response
                # shape changed. Keeping these three fields makes the new,
                # richer response a strict superset of the old one instead of
                # a breaking change for that existing caller.
                "configured": provider.configured,
                "requires_key": provider.requires_key,
                "supported_types": sorted(t.value for t in provider.supported_types),
            }

            for label in _HEALTH_WINDOWS:
                if metrics is None:
                    # No ProviderResultRecord rows at all within the widest
                    # (30d) lookback -- identical to the old per-window
                    # queries' zero-matching-rows result: count()==0,
                    # avg()==NULL.
                    attempts, ok, avg_latency_raw, rate_limited = 0, 0, None, 0
                else:
                    attempts = metrics[f"attempts_{label}"] or 0
                    ok = metrics[f"ok_{label}"] or 0
                    avg_latency_raw = metrics[f"avg_latency_{label}"]
                    rate_limited = metrics[f"rate_limited_{label}"] or 0

                entry[label] = {
                    "status": _status_for_window(attempts, ok),
                    "success_rate": _rate_or(ok, attempts, None),
                    "avg_latency_ms": _round_or(avg_latency_raw, None),
                    "consecutive_failures": consecutive_failures,
                    "rate_limited_count": rate_limited,
                }

            result.append(entry)

    return result
