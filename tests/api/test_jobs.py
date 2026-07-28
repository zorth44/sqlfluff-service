import pytest
from unittest.mock import patch, MagicMock


def _job_payload(**overrides):
    data = {
        "sql_content": "SELECT * FROM users;",
        "user_id": "test-user",
        "product_name": "test-product",
    }
    data.update(overrides)
    return data


class TestJobsAPI:
    def test_create_job_with_sql_content(self, client):
        """测试创建SQL工作API"""
        response = client.post("/api/v1/jobs", json=_job_payload())

        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data

    def test_create_job_with_zip_file(self, client):
        """测试创建ZIP工作API"""
        with patch(
            "app.utils.file_utils.FileManager.file_exists",
            return_value=True,
        ):
            response = client.post(
                "/api/v1/jobs",
                json=_job_payload(
                    sql_content=None,
                    zip_file_path="archives/test.zip",
                ),
            )

        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data

    def test_get_job_status(self, client):
        """测试查询工作状态API"""
        create_response = client.post("/api/v1/jobs", json=_job_payload())
        job_id = create_response.json()["job_id"]

        response = client.get(f"/api/v1/jobs?job_id={job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert "job_status" in data or "status" in data

    def test_get_job_not_found(self, client):
        """测试查询不存在的工作"""
        response = client.get(
            "/api/v1/jobs?job_id=job-00000000-0000-4000-8000-000000000000"
        )

        assert response.status_code == 404

    def test_create_job_invalid_request(self, client):
        """测试无效的创建请求"""
        response = client.post("/api/v1/jobs", json={})

        assert response.status_code == 422

    def test_create_job_both_content_and_zip(self, client):
        """测试同时提供sql_content和zip_file_path"""
        response = client.post(
            "/api/v1/jobs",
            json=_job_payload(
                sql_content="SELECT * FROM users;",
                zip_file_path="archives/test.zip",
            ),
        )

        assert response.status_code == 422

    def test_get_job_with_tasks_pagination(self, client):
        """测试分页查询工作任务"""
        create_response = client.post("/api/v1/jobs", json=_job_payload())
        job_id = create_response.json()["job_id"]

        response = client.get(f"/api/v1/jobs?job_id={job_id}&page=1&size=10")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert "sub_tasks" in data

    def test_get_job_statistics(self, client):
        """测试获取工作统计信息"""
        response = client.get("/api/v1/jobs/statistics")

        assert response.status_code == 200
        data = response.json()
        assert "total_jobs" in data
        assert "expanding_jobs" in data
        assert "completed_jobs" in data
        assert "failed_jobs" in data

    def test_list_jobs(self, client):
        """测试列表查询工作"""
        for i in range(3):
            client.post(
                "/api/v1/jobs",
                json=_job_payload(sql_content=f"SELECT * FROM table{i};"),
            )

        response = client.get("/api/v1/jobs/list?page=1&size=10")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data or "jobs" in data

    def test_search_jobs_basic(self, client):
        """测试基本搜索功能"""
        test_jobs = [
            _job_payload(sql_content="SELECT * FROM users;", user_id="user123", product_name="ProductA"),
            _job_payload(sql_content="SELECT * FROM orders;", user_id="user456", product_name="ProductB"),
            _job_payload(sql_content="SELECT * FROM products;", user_id="user123", product_name="ProductC"),
        ]

        for job_data in test_jobs:
            client.post("/api/v1/jobs", json=job_data)

        response = client.get("/api/v1/jobs/search?user_id=user123")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert data["jobs"]["total"] >= 2

        response = client.get("/api/v1/jobs/search?product_name=Product")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert data["jobs"]["total"] >= 3

    def test_search_jobs_with_filters(self, client):
        """测试带过滤条件的搜索"""
        client.post(
            "/api/v1/jobs",
            json=_job_payload(
                user_id="test_user",
                product_name="TestProduct",
                boc_batch_number="BATCH001",
                boc_task_number="TASK001",
            ),
        )

        response = client.get(
            "/api/v1/jobs/search?"
            "user_id=test_user&"
            "product_name=TestProduct&"
            "boc_batch_number=BATCH001&"
            "boc_task_number=TASK001"
        )
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert data["jobs"]["total"] >= 1

    def test_search_jobs_pagination(self, client):
        """测试搜索分页功能"""
        for i in range(15):
            client.post(
                "/api/v1/jobs",
                json=_job_payload(
                    sql_content=f"SELECT * FROM table{i};",
                    user_id=f"user{i}",
                    product_name=f"Product{i}",
                ),
            )

        response = client.get("/api/v1/jobs/search?page=1&size=5")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert len(data["jobs"]["items"]) <= 5
        assert data["jobs"]["page"] == 1
        assert data["jobs"]["size"] == 5

        response = client.get("/api/v1/jobs/search?page=2&size=5")
        assert response.status_code == 200
        data = response.json()
        assert data["jobs"]["page"] == 2

    def test_search_jobs_sorting(self, client):
        """测试搜索排序功能"""
        for job_data in [
            _job_payload(user_id="user_a", product_name="ProductA"),
            _job_payload(user_id="user_b", product_name="ProductB"),
            _job_payload(user_id="user_c", product_name="ProductC"),
        ]:
            client.post("/api/v1/jobs", json=job_data)

        response = client.get("/api/v1/jobs/search?sort_by=user_id&sort_order=asc")
        assert response.status_code == 200
        assert "jobs" in response.json()

        response = client.get("/api/v1/jobs/search?sort_by=product_name&sort_order=desc")
        assert response.status_code == 200
        assert "jobs" in response.json()

    def test_search_jobs_invalid_params(self, client):
        """测试无效的搜索参数"""
        response = client.get("/api/v1/jobs/search?sort_by=invalid_field")
        assert response.status_code == 400

        response = client.get("/api/v1/jobs/search?sort_order=invalid")
        assert response.status_code == 400

        response = client.get("/api/v1/jobs/search?page=0")
        assert response.status_code == 400

        response = client.get("/api/v1/jobs/search?size=0")
        assert response.status_code == 400
        response = client.get("/api/v1/jobs/search?size=101")
        assert response.status_code == 400
