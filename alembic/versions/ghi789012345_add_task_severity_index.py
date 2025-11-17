"""add_task_severity_index

Revision ID: ghi789012345
Revises: def456789012
Create Date: 2025-11-17 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ghi789012345'
down_revision: Union[str, Sequence[str], None] = 'def456789012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 创建复合索引，优化按task_id和severity_level查询时过滤is_appealed的性能
    # 此索引支持 get_tasks_by_severity_level_v2 接口的查询性能优化
    op.create_index(
        'idx_task_severity_appealed',
        'linting_violations',
        ['task_id', 'severity_level', 'is_appealed']
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 删除索引
    op.drop_index('idx_task_severity_appealed', table_name='linting_violations')

