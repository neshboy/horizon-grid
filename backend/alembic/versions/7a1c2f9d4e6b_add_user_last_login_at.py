"""add user last_login_at

Revision ID: 7a1c2f9d4e6b
Revises: 2652d888a33f
Create Date: 2026-08-14 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7a1c2f9d4e6b'
down_revision: Union[str, None] = '2652d888a33f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no server_default -- existing users simply have no recorded
    # last login until their next successful sign-in. Zero data loss, zero
    # backfill required.
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_login_at')
