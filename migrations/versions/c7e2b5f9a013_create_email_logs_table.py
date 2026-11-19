"""create email logs table

Revision ID: c7e2b5f9a013
Revises: a4d81e6b92c7
Create Date: 2026-11-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e2b5f9a013'
down_revision: Union[str, Sequence[str], None] = 'a4d81e6b92c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('email_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('recipient', sa.String(length=320), nullable=False),
    sa.Column('purpose', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('create_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_logs'))
    )
    op.create_index(op.f('ix_email_logs_recipient'), 'email_logs', ['recipient'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_email_logs_recipient'), table_name='email_logs')
    op.drop_table('email_logs')
