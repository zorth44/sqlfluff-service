"""add_is_appealed_to_linting_violations

Revision ID: def456789012
Revises: abc123456789
Create Date: 2025-11-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'def456789012'
down_revision: Union[str, Sequence[str], None] = 'abc123456789'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 在 linting_violations 表添加 is_appealed 字段
    op.add_column(
        'linting_violations',
        sa.Column(
            'is_appealed',
            sa.Boolean(),
            nullable=False,
            server_default='0',
            comment='是否被申诉：0-未申诉，1-已申诉'
        )
    )
    
    # 创建复合索引，优化按job_id和severity_level查询时过滤is_appealed的性能
    op.create_index(
        'idx_job_severity_appealed',
        'linting_violations',
        ['job_id', 'severity_level', 'is_appealed']
    )
    
    # 创建单独的is_appealed索引，优化申诉查询
    op.create_index(
        'idx_is_appealed',
        'linting_violations',
        ['is_appealed']
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 删除索引
    op.drop_index('idx_is_appealed', table_name='linting_violations')
    op.drop_index('idx_job_severity_appealed', table_name='linting_violations')
    
    # 删除字段
    op.drop_column('linting_violations', 'is_appealed')

