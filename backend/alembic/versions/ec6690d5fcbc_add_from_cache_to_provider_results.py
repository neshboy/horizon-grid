"""add from_cache to provider_results

Revision ID: ec6690d5fcbc
Revises: 9123b075e962
Create Date: 2026-09-07 05:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ec6690d5fcbc'
down_revision: Union[str, None] = '9123b075e962'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='false' backfills every pre-existing row as a real
    # attempt (not a cache hit) -- accurate, since app/providers/orchestrator.py's
    # caching behavior predates this column but ProviderResult.from_cache was
    # simply dropped on the floor at insert time before this fix, so every row
    # persisted so far genuinely was whatever the insert-time code recorded
    # (real attempts included some replayed cache hits mislabeled as real,
    # but there is no way to retroactively recover which ones -- this column
    # only prevents the mislabeling from here forward).
    op.add_column(
        'provider_results',
        sa.Column('from_cache', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('provider_results', 'from_cache')
