"""add cancelled security assessment run status

Revision ID: 8f4a1c2d9e6b
Revises: 6716ed40b9f2
Create Date: 2026-08-19 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '8f4a1c2d9e6b'
down_revision: Union[str, None] = '6716ed40b9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adding a value to an existing Postgres enum. Safe inside a normal
    # transaction on Postgres 12+ as long as the new value isn't referenced
    # in the SAME transaction it's added in (it isn't -- no data migration
    # here, just the type change), so this needs no special autocommit
    # handling the way some older-Postgres guides suggest.
    #
    # UPPERCASE deliberately: confirmed live (SELECT enumlabel FROM pg_enum)
    # that the 4 existing labels here are the Python enum's MEMBER NAMES
    # (PENDING/RUNNING/COMPLETED/FAILED), not their lowercase .value strings
    # -- SQLAlchemy's plain sa.Enum(SomeEnum) sends .name on the wire by
    # default, not .value, and no values_callable override exists on this
    # column. The model's SecurityAssessmentRunStatus.CANCELLED = "cancelled"
    # (lowercase) is still correct and unchanged -- that lowercase value is
    # what _serialize_run() actually returns to the API/frontend via
    # run.status.value; it was never what gets sent to Postgres.
    op.execute("ALTER TYPE securityassessmentrunstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. A real downgrade would need
    # to recreate the enum type and every column using it, which is far more
    # disruptive than this feature addition justifies -- left as a no-op,
    # consistent with this being an additive, backward-compatible change (any
    # row already written with a status the old code doesn't recognize would
    # only be produced by code that doesn't exist without this migration).
    pass
