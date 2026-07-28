import pytest
from unittest.mock import patch, MagicMock
from app.schemas.common import TaskStatusEnum
from app.schemas.task import TaskViolationWithSQL, TaskLintResultResponse

VALID_TASK_ID = "task-00000000-0000-4000-8000-000000000001"
MISSING_TASK_ID = "task-00000000-0000-4000-8000-000000000099"


class TestTasksAPI:
    def test_get_task_detail(self, client):
        """测试获取任务详情API"""
        response = client.get(f"/api/v1/tasks?task_id={MISSING_TASK_ID}")

        assert response.status_code == 404

    def test_get_task_result(self, client):
        """测试获取任务结果API"""
        response = client.get(f"/api/v1/tasks/result?task_id={MISSING_TASK_ID}")

        assert response.status_code == 404

    def test_get_task_lint_result_not_found(self, client):
        """测试获取不存在的任务Lint结果"""
        response = client.get(f"/api/v1/tasks/result/lint?task_id={MISSING_TASK_ID}")

        assert response.status_code == 404
        data = response.json()
        assert "任务不存在" in data["detail"]

    @patch('app.services.task_service.TaskService.get_task_by_id')
    @patch('app.services.task_service.TaskService.get_task_lint_result')
    def test_get_task_lint_result_success(self, mock_get_lint_result, mock_get_task, client):
        """测试成功获取任务Lint结果"""
        mock_task = MagicMock()
        mock_task.status = TaskStatusEnum.SUCCESS
        mock_get_task.return_value = mock_task

        mock_violations = [
            TaskViolationWithSQL(
                violation_id=1,
                is_appealed=False,
                line_no=8,
                line_pos=8,
                code="RF02",
                description="Unqualified reference 'product5' found in select with more than one referenced table/view.",
                rule="references.qualification",
                severity="warning",
                fixable=False,
                sql_line="SELECT product5.name, category.name FROM products product5 JOIN categories category ON product5.category_id = category.id;"
            )
        ]
        mock_result = TaskLintResultResponse(violations=mock_violations)
        mock_get_lint_result.return_value = mock_result

        response = client.get(f"/api/v1/tasks/result/lint?task_id={VALID_TASK_ID}")

        assert response.status_code == 200
        data = response.json()
        assert "violations" in data
        assert len(data["violations"]) == 1

        violation = data["violations"][0]
        assert violation["line_no"] == 8
        assert violation["code"] == "RF02"
        assert violation["sql_line"] == "SELECT product5.name, category.name FROM products product5 JOIN categories category ON product5.category_id = category.id;"

    @patch('app.services.task_service.TaskService.get_task_by_id')
    def test_get_task_lint_result_pending_status(self, mock_get_task, client):
        """测试任务状态为PENDING时的Lint结果获取"""
        mock_task = MagicMock()
        mock_task.status = TaskStatusEnum.PENDING
        mock_get_task.return_value = mock_task

        response = client.get(f"/api/v1/tasks/result/lint?task_id={VALID_TASK_ID}")

        assert response.status_code == 409
        data = response.json()
        assert "任务还在处理中" in data["detail"]

    @patch('app.services.task_service.TaskService.get_task_by_id')
    def test_get_task_lint_result_failure_status(self, mock_get_task, client):
        """测试任务状态为FAILURE时的Lint结果获取"""
        mock_task = MagicMock()
        mock_task.status = TaskStatusEnum.FAILURE
        mock_task.error_message = "SQL解析失败"
        mock_get_task.return_value = mock_task

        response = client.get(f"/api/v1/tasks/result/lint?task_id={VALID_TASK_ID}")

        assert response.status_code == 409
        data = response.json()
        assert "任务执行失败" in data["detail"]

    @patch('app.services.task_service.TaskService.get_task_by_id')
    @patch('app.services.task_service.TaskService.get_task_lint_result')
    def test_get_task_lint_result_empty_violations(self, mock_get_lint_result, mock_get_task, client):
        """测试获取空违规项的Lint结果"""
        mock_task = MagicMock()
        mock_task.status = TaskStatusEnum.SUCCESS
        mock_get_task.return_value = mock_task

        mock_result = TaskLintResultResponse(violations=[])
        mock_get_lint_result.return_value = mock_result

        response = client.get(f"/api/v1/tasks/result/lint?task_id={VALID_TASK_ID}")

        assert response.status_code == 200
        data = response.json()
        assert "violations" in data
        assert len(data["violations"]) == 0

    def test_get_task_lint_result_invalid_task_id(self, client):
        """测试无效的task_id格式"""
        response = client.get("/api/v1/tasks/result/lint?task_id=invalid-task-id")

        assert response.status_code in [400, 422]

    def test_list_tasks(self, client):
        """测试获取任务列表API"""
        response = client.get("/api/v1/tasks/list?page=1&size=10")

        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data

    def test_get_task_statistics(self, client):
        """测试获取任务统计信息API"""
        response = client.get("/api/v1/tasks/statistics")

        assert response.status_code == 200
        data = response.json()
        assert "total_tasks" in data
        assert "successful_tasks" in data
        assert "failed_tasks" in data

    def test_retry_failed_tasks(self, client):
        """测试重试失败任务API"""
        response = client.post(
            "/api/v1/tasks/retry",
            json={"task_ids": ["task-1", "task-2"]}
        )

        assert response.status_code in [200, 202]
        data = response.json()
        assert "submitted_tasks" in data
        assert "failed_submissions" in data
