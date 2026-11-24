"""create customers table

Revision ID: e5b1c8d4f2a7
Revises: a41c7e9b2d58
Create Date: 2026-11-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5b1c8d4f2a7'
down_revision: Union[str, Sequence[str], None] = 'a41c7e9b2d58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('customers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('company_name', sa.String(length=100), nullable=False),
    sa.Column('industry', sa.String(length=100), nullable=True),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('department', sa.String(length=100), nullable=True),
    sa.Column('title', sa.String(length=50), nullable=True),
    sa.Column('create_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('update_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_customers_owner_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers'))
    )
    op.create_index(op.f('ix_customers_owner_user_id'), 'customers', ['owner_user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_customers_owner_user_id'), table_name='customers')
    op.drop_table('customers')
