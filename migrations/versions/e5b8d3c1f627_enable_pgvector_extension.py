"""enable pgvector extension

Revision ID: e5b8d3c1f627
Revises: a41c7e9b2d58
Create Date: 2026-11-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5b8d3c1f627'
down_revision: Union[str, Sequence[str], None] = 'a41c7e9b2d58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 대화 기억 검색이 쓸 pgvector 확장을 켠다. 이미 켜져 있으면 아무 일도 하지 않는다.
    # DB 서버에 pgvector가 설치돼 있지 않거나 계정에 권한이 없으면 여기서 실패한다.
    if op.get_context().dialect.name != 'postgresql':
        return
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')


def downgrade() -> None:
    """Downgrade schema."""
    # 확장은 지우지 않는다. 이 마이그레이션보다 먼저 켜져 있었을 수 있고,
    # 지우면 vector 타입을 쓰는 컬럼까지 함께 사라질 수 있다.
