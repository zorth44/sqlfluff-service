"""
Job 状态聚合规则测试
"""

import pytest
from types import SimpleNamespace

from app.schemas.common import JobStatusEnum, TaskStatusEnum
from app.services.job_status import compute_aggregate_job_status


def _task(status, error_message=None):
    return SimpleNamespace(status=status, error_message=error_message)


class TestComputeAggregateJobStatus:
    def test_pending_tasks_keep_processing(self):
        tasks = [
            _task(TaskStatusEnum.SUCCESS),
            _task(TaskStatusEnum.PENDING),
        ]
        assert compute_aggregate_job_status(tasks) == JobStatusEnum.PROCESSING

    def test_in_progress_tasks_keep_processing(self):
        tasks = [
            _task(TaskStatusEnum.SUCCESS),
            _task(TaskStatusEnum.IN_PROGRESS),
        ]
        assert compute_aggregate_job_status(tasks) == JobStatusEnum.PROCESSING

    def test_no_early_partially_completed_with_pending(self):
        """有 PENDING 时不应标记 PARTIALLY_COMPLETED（修复旧 elif any SUCCESS 逻辑）。"""
        tasks = [
            _task(TaskStatusEnum.SUCCESS),
            _task(TaskStatusEnum.FAILURE),
            _task(TaskStatusEnum.PENDING),
        ]
        assert compute_aggregate_job_status(tasks) == JobStatusEnum.PROCESSING

    def test_all_success_is_completed(self):
        tasks = [
            _task(TaskStatusEnum.SUCCESS),
            _task(TaskStatusEnum.SUCCESS),
        ]
        assert compute_aggregate_job_status(tasks) == JobStatusEnum.COMPLETED

    def test_mixed_terminal_is_partially_completed(self):
        tasks = [
            _task(TaskStatusEnum.SUCCESS),
            _task(TaskStatusEnum.FAILURE),
        ]
        assert compute_aggregate_job_status(tasks) == JobStatusEnum.PARTIALLY_COMPLETED

    def test_all_failure_is_failed(self):
        tasks = [
            _task(TaskStatusEnum.FAILURE),
            _task(TaskStatusEnum.FAILURE),
        ]
        assert compute_aggregate_job_status(tasks) == JobStatusEnum.FAILED

    def test_skipped_invalid_sql_excluded(self):
        tasks = [
            _task(TaskStatusEnum.FAILURE, "跳过无效的SQL文件: x.sql"),
            _task(TaskStatusEnum.SUCCESS),
        ]
        assert compute_aggregate_job_status(tasks) == JobStatusEnum.COMPLETED

    def test_only_skipped_invalid_tasks_is_failed(self):
        tasks = [
            _task(TaskStatusEnum.FAILURE, "跳过无效的SQL文件: x.sql"),
        ]
        assert compute_aggregate_job_status(tasks) == JobStatusEnum.FAILED
