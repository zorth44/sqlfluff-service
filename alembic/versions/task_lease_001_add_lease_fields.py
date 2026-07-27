"""add lease fields for DB queue

为 DB-as-Queue 架构添加租约语义字段。

Revision ID: task_lease_001
Revises: db_worker_001
Create Date: 2026-07-27

Changes:
1. linting_tasks 表新增租约相关列
2. 迁移现有数据（next_attempt_at, attempt_count, lease 字段）
3. linting_jobs.status 枚举新增 EXPANDING
4. 创建 idx_task_lease_claim 索引
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME


# revision identifiers
revision: str = 'task_lease_001'
down_revision: Union[str, Sequence[str], None] = 'db_worker_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加租约字段并迁移现有数据"""

    # 1. 新增列
    op.add_column(
        'linting_tasks',
        sa.Column(
            'lease_token', sa.String(64), nullable=True,
            comment='任务租约令牌',
        ),
    )
    op.add_column(
        'linting_tasks',
        sa.Column(
            'lease_expires_at', DATETIME(6), nullable=True,
            comment='租约过期时间',
        ),
    )
    op.add_column(
        'linting_tasks',
        sa.Column(
            'next_attempt_at', DATETIME(6), nullable=True,
            server_default=sa.text('CURRENT_TIMESTAMP(6)'),
            comment='下次可领取时间',
        ),
    )
    op.add_column(
        'linting_tasks',
        sa.Column(
            'attempt_count', sa.Integer(), nullable=False, server_default='0',
            comment='已尝试次数',
        ),
    )
    op.add_column(
        'linting_tasks',
        sa.Column(
            'started_at', DATETIME(6), nullable=True,
            comment='开始处理时间',
        ),
    )
    op.add_column(
        'linting_tasks',
        sa.Column(
            'finished_at', DATETIME(6), nullable=True,
            comment='完成时间',
        ),
    )
    op.add_column(
        'linting_tasks',
        sa.Column(
            'last_error', sa.Text(), nullable=True,
            comment='最近一次失败/回收原因',
        ),
    )

    # 2. 数据迁移
    op.execute("""
        UPDATE linting_tasks
        SET next_attempt_at = COALESCE(created_at, CURRENT_TIMESTAMP(6)),
            attempt_count = retry_count
    """)

    op.execute("""
        UPDATE linting_tasks
        SET lease_token = CASE
                WHEN claim_id IS NOT NULL AND claim_id LIKE '%:%'
                THEN SUBSTRING_INDEX(claim_id, ':', -1)
                ELSE REPLACE(UUID(), '-', '')
            END,
            lease_expires_at = CASE
                WHEN claimed_at IS NOT NULL
                THEN DATE_ADD(claimed_at, INTERVAL 1800 SECOND)
                ELSE DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 1800 SECOND)
            END
        WHERE status = 'IN_PROGRESS'
    """)

    # 3. job status 枚举新增 EXPANDING
    op.execute("""
        ALTER TABLE linting_jobs
        MODIFY COLUMN status ENUM(
            'ACCEPTED', 'EXPANDING', 'PROCESSING',
            'COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED'
        ) NOT NULL
    """)

    # 4. 重建队列索引
    op.drop_index('idx_task_queue_poll', table_name='linting_tasks')
    op.create_index(
        'idx_task_lease_claim',
        'linting_tasks',
        ['status', 'next_attempt_at', 'priority', 'created_at', 'id'],
    )


def downgrade() -> None:
    """回滚租约字段"""

    op.drop_index('idx_task_lease_claim', table_name='linting_tasks')
    op.create_index(
        'idx_task_queue_poll',
        'linting_tasks',
        ['status', sa.text('priority DESC'), 'created_at'],
    )

    op.execute("""
        ALTER TABLE linting_jobs
        MODIFY COLUMN status ENUM(
            'ACCEPTED', 'PROCESSING',
            'COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED'
        ) NOT NULL
    """)

    op.drop_column('linting_tasks', 'last_error')
    op.drop_column('linting_tasks', 'finished_at')
    op.drop_column('linting_tasks', 'started_at')
    op.drop_column('linting_tasks', 'attempt_count')
    op.drop_column('linting_tasks', 'next_attempt_at')
    op.drop_column('linting_tasks', 'lease_expires_at')
    op.drop_column('linting_tasks', 'lease_token')
