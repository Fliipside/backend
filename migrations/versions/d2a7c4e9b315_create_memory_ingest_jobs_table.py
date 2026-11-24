"""create memory ingest jobs table

Revision ID: d2a7c4e9b315
Revises: b8d3f6a1c924
Create Date: 2026-11-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2a7c4e9b315'
down_revision: Union[str, Sequence[str], None] = 'b8d3f6a1c924'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('memory_ingest_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('voice_job_id', sa.Uuid(), nullable=False),
    sa.Column('interaction_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('create_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('update_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['interaction_id'], ['interactions.id'], name=op.f('fk_memory_ingest_jobs_interaction_id_interactions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['voice_job_id'], ['voice_analysis_jobs.id'], name=op.f('fk_memory_ingest_jobs_voice_job_id_voice_analysis_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memory_ingest_jobs')),
    sa.UniqueConstraint('voice_job_id', name=op.f('uq_memory_ingest_jobs_voice_job_id'))
    )
    op.create_index(op.f('ix_memory_ingest_jobs_interaction_id'), 'memory_ingest_jobs', ['interaction_id'], unique=False)
    op.create_index(op.f('ix_memory_ingest_jobs_status'), 'memory_ingest_jobs', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_memory_ingest_jobs_status'), table_name='memory_ingest_jobs')
    op.drop_index(op.f('ix_memory_ingest_jobs_interaction_id'), table_name='memory_ingest_jobs')
    op.drop_table('memory_ingest_jobs')
