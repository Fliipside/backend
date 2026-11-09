"""create voiceprints and voice_analysis_jobs tables

Revision ID: 3f9c2a7d41b6
Revises: 508ce96da5e0
Create Date: 2026-11-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3f9c2a7d41b6'
down_revision: Union[str, Sequence[str], None] = '508ce96da5e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('voiceprints',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('engine', sa.String(length=50), nullable=False),
    sa.Column('vector', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('create_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('update_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_voiceprints_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_voiceprints'))
    )

    op.create_table('voice_analysis_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('used_voiceprint_engine', sa.String(length=50), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('create_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('update_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_voice_analysis_jobs_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_voice_analysis_jobs'))
    )
    op.create_index(op.f('ix_voice_analysis_jobs_status'), 'voice_analysis_jobs', ['status'], unique=False)
    op.create_index(op.f('ix_voice_analysis_jobs_user_id'), 'voice_analysis_jobs', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_voice_analysis_jobs_user_id'), table_name='voice_analysis_jobs')
    op.drop_index(op.f('ix_voice_analysis_jobs_status'), table_name='voice_analysis_jobs')
    op.drop_table('voice_analysis_jobs')
    op.drop_table('voiceprints')
