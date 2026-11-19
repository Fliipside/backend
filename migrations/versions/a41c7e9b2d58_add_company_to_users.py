"""add company to users

Revision ID: a41c7e9b2d58
Revises: c7e2b5f9a013
Create Date: 2026-11-16 22:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a41c7e9b2d58'
down_revision: Union[str, Sequence[str], None] = 'c7e2b5f9a013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 기존 사용자는 빈 문자열로 채워진다. 기본값이 있어서 이 컬럼을 모르는
    # 이전 버전의 서버가 가입을 처리해도 실패하지 않는다.
    op.add_column(
        'users',
        sa.Column('company', sa.String(length=100), server_default='', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'company')
