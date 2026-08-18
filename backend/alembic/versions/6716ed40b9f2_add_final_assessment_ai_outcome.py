"""add final assessment ai outcome

Revision ID: 6716ed40b9f2
Revises: 6d2f4b8e1a7c
Create Date: 2026-08-17 10:10:03.426265

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6716ed40b9f2'
down_revision: Union[str, None] = '6d2f4b8e1a7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='success' backfills the OVERWHELMING MAJORITY of
    # existing rows correctly: app/ai/service.py's generate_final_assessment()
    # only ever leaves ai_backend null/"unknown" on its two non-success return
    # paths (no-evidence short-circuit, total-failure fallback) -- the success
    # path always overwrites ai_backend with the real, invoked backend name
    # right before returning, and always did, even before this migration.
    # Verified this holds against the live table before writing this
    # migration (`SELECT ai_backend, count(*) FROM final_assessment_records
    # GROUP BY ai_backend`): every row with a real backend name (groq, ollama,
    # test-stub -- 46 of 72 rows at the time of writing) is unambiguously a
    # historical success, so 'success' is not a guess for those rows.
    op.add_column(
        'final_assessment_records',
        sa.Column('ai_outcome', sa.String(length=32), nullable=False, server_default='success'),
    )

    # The remaining 26 of 72 rows all had ai_backend='unknown' -- the sentinel
    # every call site (app/api/routes/lookup.py, app/core/security_assessment.py)
    # substitutes for `final.ai_backend or "unknown"` when the assessment came
    # from EITHER non-success path, which is exactly the ambiguity this whole
    # migration exists to resolve. Blindly defaulting those 26 rows to
    # 'success' too would be dishonest: they are, by construction, NOT
    # successes. Unlike a future caller trying to infer outcome from
    # ai_backend alone (fragile, and exactly what this migration avoids going
    # forward), this one-time backfill can lean on a second, independent
    # signal that IS reliable for these already-persisted rows: the
    # executive_summary text on both non-success paths is deterministic,
    # hardcoded prose that the AI never generates and never sees (it's
    # returned before/without any AI call), so an exact match against it
    # losslessly recovers which of the two paths a historical 'unknown' row
    # actually took. Confirmed live against this table: all 26 rows matched
    # exactly one of the two patterns below (15 no-evidence, 11 failed) with
    # zero unmatched rows.
    op.execute(
        sa.text(
            "UPDATE final_assessment_records SET ai_outcome = 'skipped_no_evidence' "
            "WHERE ai_backend = 'unknown' AND assessment->>'executive_summary' = "
            "'No provider returned usable data for this indicator -- insufficient evidence for an assessment.'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE final_assessment_records SET ai_outcome = 'failed' "
            "WHERE ai_backend = 'unknown' AND assessment->>'executive_summary' = "
            "'AI-generated assessment unavailable (generation error). "
            "See individual provider results and summaries below for raw findings.'"
        )
    )
    # server_default is deliberately left in place (not dropped after
    # backfill) -- matches the precedent in 3b9e7a2c1d4f_add_user_token_version
    # and 6d2f4b8e1a7c_add_provenance_category, both of which keep their
    # server_default permanently as a safety net for any insert path that
    # doesn't explicitly set the column. Every real code path now sets
    # ai_outcome explicitly (see app/ai/service.py / the three
    # FinalAssessmentRecord(...) call sites), so this default should never
    # actually apply going forward -- it's a backstop, not documentation of
    # the common case.


def downgrade() -> None:
    op.drop_column('final_assessment_records', 'ai_outcome')
