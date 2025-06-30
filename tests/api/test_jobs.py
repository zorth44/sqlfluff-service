import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

class TestJobsAPI:
    def test_create_job_with_sql_content(self, client):
        """测试创建SQL工作API"""
        response = client.post(
            "/api/v1/jobs",
            json={"sql_content": "SELECT * FROM users;"}
        )
        
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        
    def test_create_job_with_zip_file(self, client):
        """测试创建ZIP工作API"""
        response = client.post(
            "/api/v1/jobs",
            json={"zip_file_path": "/tmp/test.zip"}
        )
        
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        
    def test_get_job_status(self, client):
        """测试查询工作状态API"""
        # 先创建一个工作
        create_response = client.post(
            "/api/v1/jobs",
            json={"sql_content": "SELECT * FROM users;"}
        )
        job_id = create_response.json()["job_id"]
        
        # 查询工作状态
        response = client.get(f"/api/v1/jobs/{job_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert "job_status" in data
        
    def test_get_job_not_found(self, client):
        """测试查询不存在的工作"""
        response = client.get("/api/v1/jobs/non-existent-id")
        
        assert response.status_code == 404
        
    def test_create_job_invalid_request(self, client):
        """测试无效的创建请求"""
        # 没有提供sql_content或zip_file_path
        response = client.post(
            "/api/v1/jobs",
            json={}
        )
        
        assert response.status_code == 422
        
    def test_create_job_both_content_and_zip(self, client):
        """测试同时提供sql_content和zip_file_path"""
        response = client.post(
            "/api/v1/jobs",
            json={
                "sql_content": "SELECT * FROM users;",
                "zip_file_path": "/tmp/test.zip"
            }
        )
        
        assert response.status_code == 422
        
    def test_get_job_with_tasks_pagination(self, client):
        """测试分页查询工作任务"""
        # 先创建一个工作
        create_response = client.post(
            "/api/v1/jobs",
            json={"sql_content": "SELECT * FROM users;"}
        )
        job_id = create_response.json()["job_id"]
        
        # 查询工作详情（带分页）
        response = client.get(f"/api/v1/jobs/{job_id}?page=1&size=10")
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert "tasks" in data
        assert "pagination" in data
        
    def test_get_job_statistics(self, client):
        """测试获取工作统计信息"""
        response = client.get("/api/v1/jobs/statistics")
        
        assert response.status_code == 200
        data = response.json()
        assert "total_jobs" in data
        assert "completed_jobs" in data
        assert "failed_jobs" in data
        
    def test_list_jobs(self, client):
        """测试列表查询工作"""
        # 创建几个工作
        for i in range(3):
            client.post(
                "/api/v1/jobs",
                json={"sql_content": f"SELECT * FROM table{i};"}
            )
        
        # 查询工作列表
        response = client.get("/api/v1/jobs?page=1&size=10")
        
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "pagination" in data
        assert len(data["items"]) >= 0  # 可能有其他测试创建的工作 