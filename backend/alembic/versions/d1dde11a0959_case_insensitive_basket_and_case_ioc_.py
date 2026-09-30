"""make basket_items and case_iocs uniqueness case-insensitive

Revision ID: d1dde11a0959
Revises: b3f0587f2493
Create Date: 2026-09-30 00:00:00.000000

Confirmed finding: add_to_basket() (app/api/routes/basket.py) and
add_case_ioc() (app/api/routes/cases.py) both dedupe case-insensitively in
their pre-insert SELECT (func.lower(...) == value.lower()), on the stated
rationale that the same logical IOC re-entered in different casing (e.g.
"EXAMPLE.COM" vs "example.com") should collapse to one row. But the DB
constraints backing them -- uq_basket_owner_ioc on (owner_id, ioc_value) and
uq_case_ioc_case_value on (case_id, ioc_value) -- were plain case-sensitive
UniqueConstraints. Two concurrent adds of the same IOC in different casing
both passed the case-insensitive SELECT (both saw no existing row) and both
successfully INSERTed, since Postgres's case-sensitive constraint sees them
as distinct values -- leaving two rows for one logical IOC and never raising
the IntegrityError each route's rollback/re-SELECT recovery path expects
(that path only ever fires for a same-casing race).

Replaces both UniqueConstraints with functional unique indexes on
(owner_id, lower(ioc_value)) / (case_id, lower(ioc_value)) so the constraint
itself is case-insensitive, matching the routes' own dedup intent -- once
in place, a cross-casing race raises IntegrityError the same way a
same-casing race already does, and the existing recovery code handles it
correctly.

Any pre-existing cross-casing duplicates (rows differing only by ioc_value's
case) are collapsed down to the earliest one (by created_at) before each
index is created, following 401e725fa85f_add_case_ioc_uniqueness_constraint's
own precedent for the equivalent same-casing case, so this migration doesn't
fail against data that already accumulated duplicates via the bug being
fixed here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd1dde11a0959'
down_revision: Union[str, None] = 'b3f0587f2493'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Collapse any pre-existing cross-casing duplicates (same owner_id +
    # lower(ioc_value)) down to one row (the earliest by created_at) so the
    # new unique index below can actually be created against real data.
    op.execute(
        """
        DELETE FROM basket_items a
        USING basket_items b
        WHERE a.owner_id = b.owner_id
          AND lower(a.ioc_value) = lower(b.ioc_value)
          AND (a.created_at, a.id) > (b.created_at, b.id)
        """
    )
    op.drop_constraint('uq_basket_owner_ioc', 'basket_items', type_='unique')
    op.create_index(
        'uq_basket_owner_ioc_ci',
        'basket_items',
        ['owner_id', sa.text('lower(ioc_value)')],
        unique=True,
    )

    op.execute(
        """
        DELETE FROM case_iocs a
        USING case_iocs b
        WHERE a.case_id = b.case_id
          AND lower(a.ioc_value) = lower(b.ioc_value)
          AND (a.created_at, a.id) > (b.created_at, b.id)
        """
    )
    op.drop_constraint('uq_case_ioc_case_value', 'case_iocs', type_='unique')
    op.create_index(
        'uq_case_ioc_case_value_ci',
        'case_iocs',
        ['case_id', sa.text('lower(ioc_value)')],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_case_ioc_case_value_ci', table_name='case_iocs')
    op.create_unique_constraint('uq_case_ioc_case_value', 'case_iocs', ['case_id', 'ioc_value'])

    op.drop_index('uq_basket_owner_ioc_ci', table_name='basket_items')
    op.create_unique_constraint('uq_basket_owner_ioc', 'basket_items', ['owner_id', 'ioc_value'])
