"""create interactions table and link voice analysis jobs

Revision ID: b8d3f6a1c924
Revises: e5b1c8d4f2a7
Create Date: 2026-11-22 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d3f6a1c924'
down_revision: Union[str, Sequence[str], None] = 'e5b1c8d4f2a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('interactions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('create_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('update_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_interactions_customer_id_customers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_interactions_owner_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interactions'))
    )
    op.create_index(op.f('ix_interactions_customer_id'), 'interactions', ['customer_id'], unique=False)

    # Jobs created before this migration have no interaction, so the column is nullable.
    op.add_column('voice_analysis_jobs', sa.Column('interaction_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f('fk_voice_analysis_jobs_interaction_id_interactions'),
        'voice_analysis_jobs',
        'interactions',
        ['interaction_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f('fk_voice_analysis_jobs_interaction_id_interactions'),
        'voice_analysis_jobs',
        type_='foreignkey',
    )
    op.drop_column('voice_analysis_jobs', 'interaction_id')
    op.drop_index(op.f('ix_interactions_customer_id'), table_name='interactions')
    op.drop_table('interactions')
