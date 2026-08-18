"""add security assessment tables

Revision ID: 5c8e1f3a9b2d
Revises: 3b9e7a2c1d4f
Create Date: 2026-08-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5c8e1f3a9b2d'
down_revision: Union[str, None] = '3b9e7a2c1d4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('security_assessment_runs',
    sa.Column('lookup_id', sa.UUID(), nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=True),
    sa.Column('target', sa.String(length=2048), nullable=False),
    sa.Column('tool_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('profile', sa.String(length=64), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', name='securityassessmentrunstatus'), nullable=False),
    sa.Column('authorization_confirmed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['lookup_id'], ['ioc_lookups.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_security_assessment_runs_lookup_id'), 'security_assessment_runs', ['lookup_id'], unique=False)

    op.create_table('security_assessment_findings',
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('tool_id', sa.String(length=64), nullable=False),
    sa.Column('finding_type', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.Enum('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='severity'), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('target_detail', sa.String(length=255), nullable=True),
    sa.Column('cve_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['security_assessment_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_security_assessment_findings_run_id'), 'security_assessment_findings', ['run_id'], unique=False)
    op.create_index(op.f('ix_security_assessment_findings_tool_id'), 'security_assessment_findings', ['tool_id'], unique=False)
    op.create_index(op.f('ix_security_assessment_findings_severity'), 'security_assessment_findings', ['severity'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_security_assessment_findings_severity'), table_name='security_assessment_findings')
    op.drop_index(op.f('ix_security_assessment_findings_tool_id'), table_name='security_assessment_findings')
    op.drop_index(op.f('ix_security_assessment_findings_run_id'), table_name='security_assessment_findings')
    op.drop_table('security_assessment_findings')
    op.drop_index(op.f('ix_security_assessment_runs_lookup_id'), table_name='security_assessment_runs')
    op.drop_table('security_assessment_runs')
    sa.Enum(name='severity').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='securityassessmentrunstatus').drop(op.get_bind(), checkfirst=True)
