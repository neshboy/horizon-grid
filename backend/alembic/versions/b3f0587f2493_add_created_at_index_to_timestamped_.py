"""add created_at index to timestamped tables

Revision ID: b3f0587f2493
Revises: 401e725fa85f
Create Date: 2026-09-24 16:27:50.745033

Real gap found live: TimestampMixin's created_at column (app/models/base.py,
inherited by every model below) had no index anywhere in the schema, yet
created_at is the primary ORDER BY / WHERE column for nearly every list and
dashboard query -- confirmed directly against the code: IOCLookup (dashboard
KPI windows, GET /lookup recent list), ProviderResultRecord (the /providers
/health window metrics, grouped by provider_id over a 30-day created_at
range -- a full-table scan on every dashboard load once this table grows),
FinalAssessmentRecord, Case, PentestAssessment, PentestFinding, and
SecurityAssessmentRun all filter or ORDER BY created_at.desc() directly.

Adds the index to all 20 TimestampMixin tables, not just the 7 confirmed
hot paths above, for the same reason app/models/base.py's mixin exists in
the first place: one shared definition that every table gets identically,
rather than a subset an autogenerate diff or a future table would have to
remember to match individually. Write overhead of one extra index on the
smaller/low-traffic tables here is negligible.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f0587f2493'
down_revision: Union[str, None] = '401e725fa85f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = [
    "basket_items",
    "cases",
    "case_iocs",
    "case_notes",
    "case_reports",
    "evidence_items",
    "ioc_lookups",
    "provider_results",
    "ai_summaries",
    "correlation_edges",
    "final_assessment_records",
    "pentest_assessments",
    "pentest_targets",
    "pentest_findings",
    "pentest_exploit_attempts",
    "pentest_global_kill_switch",
    "provider_runtime_configs",
    "security_assessment_runs",
    "security_assessment_findings",
    "users",
]


def upgrade() -> None:
    for table in _TABLES:
        op.create_index(f"ix_{table}_created_at", table, ["created_at"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_created_at", table_name=table)
