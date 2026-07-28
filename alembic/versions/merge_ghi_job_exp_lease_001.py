"""merge alembic heads

Merge parallel heads:
- ghi789012345 (task severity index)
- job_exp_lease_001 (job expansion lease)

Revision ID: merge_heads_001
Revises: ghi789012345, job_exp_lease_001
Create Date: 2026-07-28
"""
from typing import Sequence, Union


revision: str = 'merge_heads_001'
down_revision: Union[str, Sequence[str], None] = ('ghi789012345', 'job_exp_lease_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
