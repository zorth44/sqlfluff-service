"""add job expansion lease fields

为 Job 展开过程增加租约，避免 Worker 崩溃后永久停在 EXPANDING。

Revision ID: job_exp_lease_001
Revises: task_lease_001
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME


revision: str = 'job_exp_lease_001'
down_revision: Union[str, Sequence[str], None] = 'task_lease_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'linting_jobs',
        sa.Column(
            'expansion_lease_token', sa.String(64), nullable=True,
            comment='Job 展开租约令牌',
        ),
    )
    op.add_column(
        'linting_jobs',
        sa.Column(
            'expansion_lease_expires_at', DATETIME(6), nullable=True,
            comment='Job 展开租约过期时间',
        ),
    )
    op.add_column(
        'linting_jobs',
        sa.Column(
            'expansion_started_at', DATETIME(6), nullable=True,
            comment='Job 展开开始时间',
        ),
    )
    op.create_index(
        'idx_job_expansion_lease',
        'linting_jobs',
        ['status', 'expansion_lease_expires_at'],
    )


def downgrade() -> None:
    # 先把仍在 EXPANDING 的 Job 回退，避免移除枚举值时失败
    op.execute("""
        UPDATE linting_jobs
        SET status = 'ACCEPTED',
            expansion_lease_token = NULL,
            expansion_lease_expires_at = NULL,
            expansion_started_at = NULL,
            error_message = COALESCE(
                error_message,
                'Rolled back from EXPANDING during migration downgrade'
            )
        WHERE status = 'EXPANDING'
    """)

    op.drop_index('idx_job_expansion_lease', table_name='linting_jobs')
    op.drop_column('linting_jobs', 'expansion_started_at')
    op.drop_column('linting_jobs', 'expansion_lease_expires_at')
    op.drop_column('linting_jobs', 'expansion_lease_token')
