"""add_support_to_linting_violations

Revision ID: jkl789012345
Revises: def456789012
Create Date: 2025-01-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'jkl789012345'
down_revision: Union[str, Sequence[str], None] = 'def456789012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 在 linting_violations 表添加 support 字段
    # MySQL TEXT 不能带 DEFAULT，nullable=True 即可
    op.add_column(
        'linting_violations',
        sa.Column(
            'support',
            sa.Text(),
            nullable=True,
            comment='规则支持信息，描述对应violation如何解决的信息（来自修改后的SQLFluff）'
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 删除字段
    op.drop_column('linting_violations', 'support')


