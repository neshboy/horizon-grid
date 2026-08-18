"""Pure-logic unit tests for app.core.dashboard's DB-free helper functions --
the exact rules a future reader would otherwise have to reverse-engineer
from the query code in get_kpis()/get_provider_health_history():

  - _round_or / _rate_or: the null-vs-zero distinction. Different KPIs
    deliberately report "no data" differently (avg_threat_score -> 0.0,
    provider_health_percentage -> 0.0, but ai_success_rate and every
    per-window success_rate/avg_latency_ms -> None) -- these two tiny
    functions are the single place that distinction lives, so they are
    tested directly here rather than only indirectly through a live DB.
  - _status_for_window: the healthy/degraded/down/unknown threshold rule,
    most importantly the CRITICAL "zero attempts -> unknown, never healthy"
    rule this endpoint exists to guarantee.

DB-fixture-based coverage of the exclusion behaviors themselves (not_configured/
disabled rows actually being excluded, skipped_no_evidence actually being
excluded) lives in app/tests/integration/test_dashboard_service_db.py, since
those require real ProviderResultRecord/FinalAssessmentRecord rows -- see
that file's docstring for why.
"""
from app.core.dashboard import _rate_or, _round_or, _status_for_window


# --- _round_or -----------------------------------------------------------


def test_round_or_returns_default_when_value_is_none():
    assert _round_or(None, 0.0) == 0.0
    assert _round_or(None, None) is None


def test_round_or_rounds_a_real_value_to_two_decimals_regardless_of_default():
    assert _round_or(37.5678, 0.0) == 37.57
    assert _round_or(37.5678, None) == 37.57


def test_round_or_accepts_decimal_or_int_like_db_scalars():
    # asyncpg/SQLAlchemy can hand back a Decimal for AVG() -- must not choke.
    from decimal import Decimal

    assert _round_or(Decimal("12.345"), 0.0) == 12.35


# --- _rate_or --------------------------------------------------------------


def test_rate_or_returns_default_when_denominator_is_zero():
    assert _rate_or(0, 0, None) is None
    assert _rate_or(0, 0, 0.0) == 0.0


def test_rate_or_computes_a_percentage_when_denominator_is_nonzero():
    assert _rate_or(3, 4, None) == 75.0
    assert _rate_or(9, 10, 0.0) == 90.0


def test_rate_or_zero_numerator_with_real_denominator_is_a_real_zero_not_the_default():
    # Zero successes out of real attempts is a genuine 0% -- must NOT be
    # confused with "no data" (which is what the `default` param is for).
    assert _rate_or(0, 5, None) == 0.0


# --- _status_for_window ----------------------------------------------------


def test_status_is_unknown_when_there_are_zero_attempts():
    """THE critical rule: a provider never exercised in this window must
    report "unknown", never "healthy" -- silence is not evidence of health."""
    assert _status_for_window(attempts=0, ok=0) == "unknown"


def test_status_is_down_when_every_attempt_failed():
    assert _status_for_window(attempts=5, ok=0) == "down"


def test_status_is_degraded_between_zero_and_the_healthy_threshold():
    assert _status_for_window(attempts=10, ok=5) == "degraded"  # 50%
    assert _status_for_window(attempts=10, ok=8) == "degraded"  # 80%


def test_status_is_healthy_at_or_above_the_threshold():
    assert _status_for_window(attempts=10, ok=9) == "healthy"  # 90%, the boundary
    assert _status_for_window(attempts=10, ok=10) == "healthy"  # 100%


def test_status_just_below_the_threshold_is_degraded_not_healthy():
    assert _status_for_window(attempts=1000, ok=899) == "degraded"  # 89.9%
