"""merge customers and pgvector heads

Revision ID: b14b48c6a870
Revises: d2a7c4e9b315, e5b8d3c1f627
Create Date: 2026-11-25 20:31:06.213509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b14b48c6a870'
down_revision: Union[str, Sequence[str], None] = ('d2a7c4e9b315', 'e5b8d3c1f627')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
