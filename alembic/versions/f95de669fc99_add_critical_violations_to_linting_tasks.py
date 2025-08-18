"""add_critical_violations_to_linting_tasks

Revision ID: f95de669fc99
Revises: e35de558fc86
Create Date: 2025-08-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f95de669fc99'
down_revision: Union[str, Sequence[str], None] = 'e35de558fc86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('linting_tasks', sa.Column('critical_violations', sa.Integer(), nullable=True, comment='SQL文件严重违规项数(BLOCKER和CRITICAL级别)'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('linting_tasks', 'critical_violations')