"""add user token_version

Revision ID: 3b9e7a2c1d4f
Revises: 7a1c2f9d4e6b
Create Date: 2026-08-14 15:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3b9e7a2c1d4f'
down_revision: Union[str, None] = '7a1c2f9d4e6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='0' so every existing row (and every already-issued
    # JWT, which has no token_version claim and is treated as 0 by
    # get_current_user()) starts out valid -- this migration forces no one
    # to re-authenticate.
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('users', 'token_version')
