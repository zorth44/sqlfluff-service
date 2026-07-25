"""add_worker_support

为 DB-as-Queue 架构添加 Worker 支持。

Revision ID: db_worker_001
Revises: jkl789012345
Create Date: 2026-07-25

Changes:
1. linting_tasks 表新增列：priority, claim_id, claimed_at, retry_count
2. 新建 worker_registry 表
3. 新增查询索引
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import INTEGER, VARCHAR, DATETIME


# revision identifiers
revision: str = 'db_worker_001'
down_revision: Union[str, Sequence[str], None] = 'jkl789012345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 DB-as-Queue Worker 支持"""

    # 1. linting_tasks 表新增列
    op.add_column('linting_tasks',
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0',
                  comment='任务优先级，数值越大优先级越高'))
    op.add_column('linting_tasks',
        sa.Column('claim_id', sa.String(255), nullable=True,
                  comment='Worker 领取标识（格式：worker_id:random_hex）'))
    op.add_column('linting_tasks',
        sa.Column('claimed_at', DATETIME(6), nullable=True,
                  comment='任务被 Worker 领取的时间'))
    op.add_column('linting_tasks',
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0',
                  comment='已重试次数'))

    # 2. 创建队列查询索引（用于 claim_task）
    op.create_index(
        'idx_task_queue_poll',
        'linting_tasks',
        ['status', sa.text('priority DESC'), 'created_at']
    )
    op.create_index(
        'idx_task_claim',
        'linting_tasks',
        ['claim_id', 'status']
    )

    # 3. 创建 worker_registry 表
    op.create_table(
        'worker_registry',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True,
                  comment='自增主键'),
        sa.Column('worker_id', sa.String(255), nullable=False, unique=True,
                  comment='Worker 唯一标识（hostname_pid）'),
        sa.Column('hostname', sa.String(255), nullable=False,
                  comment='Worker 所在主机名'),
        sa.Column('pid', sa.Integer(), nullable=False,
                  comment='Worker 进程 ID'),
        sa.Column('status', sa.Enum('RUNNING', 'STOPPED', 'DEAD', name='worker_status_enum'),
                  nullable=False, server_default='RUNNING',
                  comment='Worker 运行状态'),
        sa.Column('heartbeat_at', DATETIME(6), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP(6)'),
                  comment='最后心跳时间'),
        sa.Column('current_task_count', sa.Integer(), nullable=False, server_default='0',
                  comment='当前处理中的任务数'),
        sa.Column('total_tasks_processed', sa.Integer(), nullable=False, server_default='0',
                  comment='累计已完成任务数'),
        sa.Column('started_at', DATETIME(6), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP(6)'),
                  comment='Worker 启动时间'),
        sa.Column('stopped_at', DATETIME(6), nullable=True,
                  comment='Worker 停止时间'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
    )

    # worker_registry 索引
    op.create_index('idx_worker_heartbeat', 'worker_registry', ['heartbeat_at'])
    op.create_index('idx_worker_status', 'worker_registry', ['status'])


def downgrade() -> None:
    """回滚 DB-as-Queue Worker 支持"""

    # 1. 删除 worker_registry 表
    op.drop_table('worker_registry')

    # 2. 删除索引
    op.drop_index('idx_task_claim', table_name='linting_tasks')
    op.drop_index('idx_task_queue_poll', table_name='linting_tasks')

    # 3. 删除 linting_tasks 新增列
    op.drop_column('linting_tasks', 'retry_count')
    op.drop_column('linting_tasks', 'claimed_at')
    op.drop_column('linting_tasks', 'claim_id')
    op.drop_column('linting_tasks', 'priority')
