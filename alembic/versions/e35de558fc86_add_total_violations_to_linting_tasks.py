"""add_total_violations_to_linting_tasks

Revision ID: e35de558fc86
Revises: 120558137241
Create Date: 2025-07-18 15:40:57.764095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e35de558fc86'
down_revision: Union[str, Sequence[str], None] = '120558137241'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('linting_tasks', sa.Column('total_violations', sa.Integer(), nullable=True, comment='SQL文件违规项总数'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('linting_tasks', 'total_violations')
