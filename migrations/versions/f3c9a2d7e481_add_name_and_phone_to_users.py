"""add name and phone to users

Revision ID: f3c9a2d7e481
Revises: b14b48c6a870
Create Date: 2026-11-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3c9a2d7e481'
down_revision: Union[str, Sequence[str], None] = 'b14b48c6a870'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 기존 사용자는 빈 문자열로 채워져 아이디 찾기에 걸리지 않는다.
    op.add_column(
        'users',
        sa.Column('name', sa.String(length=50), server_default='', nullable=False),
    )
    op.add_column(
        'users',
        sa.Column('phone', sa.String(length=20), server_default='', nullable=False),
    )
    op.create_index(op.f('ix_users_phone'), 'users', ['phone'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_users_phone'), table_name='users')
    op.drop_column('users', 'phone')
    op.drop_column('users', 'name')
