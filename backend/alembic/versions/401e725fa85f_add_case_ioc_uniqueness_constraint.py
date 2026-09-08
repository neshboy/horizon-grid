"""add case_iocs uniqueness constraint

Revision ID: 401e725fa85f
Revises: 157fc4148d76
Create Date: 2026-09-07 00:00:00.000000

Confirmed P3 finding: unlike basket_items (uq_basket_owner_ioc, see
a6d3ad2bb63c_add_evidence_basket_and_case_management_.py), case_iocs had no
uniqueness constraint on (case_id, ioc_value), so concurrent identical
POST /api/v1/cases/{case_id}/iocs requests (double-click, network retry)
each landed a separate row -- confirmed live: 3 concurrent POSTs of the
same {"ioc_value": "198.51.100.148", "ioc_type": "ipv4"} against the same
case each returned 201 and left 3 duplicate case_iocs rows behind.

Any pre-existing exact-duplicate (case_id, ioc_value) rows are collapsed
down to the earliest one (by created_at) before the constraint is added,
so this migration doesn't fail against data that already accumulated
duplicates via the bug being fixed here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '401e725fa85f'
down_revision: Union[str, None] = '157fc4148d76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Collapse any pre-existing exact duplicates (same case_id + ioc_value)
    # down to one row (the earliest by created_at) so the new unique
    # constraint below can actually be created against real data.
    op.execute(
        """
        DELETE FROM case_iocs a
        USING case_iocs b
        WHERE a.case_id = b.case_id
          AND a.ioc_value = b.ioc_value
          AND (a.created_at, a.id) > (b.created_at, b.id)
        """
    )
    op.create_unique_constraint('uq_case_ioc_case_value', 'case_iocs', ['case_id', 'ioc_value'])


def downgrade() -> None:
    op.drop_constraint('uq_case_ioc_case_value', 'case_iocs', type_='unique')
