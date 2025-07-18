"""add_sql_lines_to_linting_tasks

Revision ID: 120558137241
Revises: add_rules_column
Create Date: 2025-07-15 21:42:23.668742

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '120558137241'
down_revision: Union[str, Sequence[str], None] = 'add_rules_column'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('linting_tasks', sa.Column('sql_lines', sa.Integer(), nullable=True, comment='SQL文件行数'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('linting_tasks', 'sql_lines')
