"""add provenance_category to correlation_edges and evidence_items

Revision ID: 6d2f4b8e1a7c
Revises: 5c8e1f3a9b2d
Create Date: 2026-08-15 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '6d2f4b8e1a7c'
down_revision: Union[str, None] = '5c8e1f3a9b2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='threat_intel' backfills every existing row accurately:
    # every provider that existed before this column did some form of
    # external intelligence lookup (VirusTotal, WHOIS, NVD, etc.), never a
    # local active observation -- see app/core/provenance.py.
    op.add_column(
        'correlation_edges',
        sa.Column('provenance_category', sa.String(length=32), nullable=False, server_default='threat_intel'),
    )
    op.add_column(
        'evidence_items',
        sa.Column('provenance_category', sa.String(length=32), nullable=False, server_default='threat_intel'),
    )


def downgrade() -> None:
    op.drop_column('evidence_items', 'provenance_category')
    op.drop_column('correlation_edges', 'provenance_category')
