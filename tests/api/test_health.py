import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.responses import Response

os.environ.setdefault("NFS_SHARE_ROOT_PATH", "/tmp/sqlfluff_test_nfs")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "dev")

from app.api.routes import health
from app.models.database import WorkerRegistry


class TestHealthRoutes:
    @patch("app.api.routes.health.psutil")
    @patch("app.api.routes.health.FileManager")
    @patch("app.api.routes.health.os.statvfs")
    @patch("app.api.routes.health.os.path.exists", return_value=True)
    def test_health_warning_returns_200(
        self,
        mock_exists,
        mock_statvfs,
        mock_file_manager,
        mock_psutil,
        db_session,
    ):
        mock_file_manager.return_value.check_write_permission.return_value = True
        mock_psutil.cpu_percent.return_value = 10.0
        mock_psutil.virtual_memory.return_value = MagicMock(percent=50.0, available=8 * 1024**3)
        mock_psutil.disk_usage.return_value = MagicMock(used=10, total=100)
        mock_statvfs.return_value = MagicMock(f_frsize=4096, f_bavail=1000000, f_blocks=2000000)

        db_session.execute = MagicMock()

        mock_worker_query = MagicMock()
        mock_worker_query.filter.return_value.all.return_value = []
        original_query = db_session.query

        def query_side_effect(model):
            if model is WorkerRegistry:
                return mock_worker_query
            return original_query(model)

        db_session.query = query_side_effect

        result = asyncio.run(health.health_check(db=db_session))

        assert result["status"] == "warning"

    def test_health_unhealthy_raises_503(self):
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("database unavailable")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(health.health_check(db=mock_db))

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["status"] == "unhealthy"

    def test_health_ready_db_failure_raises_503(self):
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("database unavailable")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(health.readiness_check(db=mock_db))

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["status"] == "not_ready"
        assert exc_info.value.detail["checks"]["database"]["status"] == "unhealthy"

    def test_health_ready_success(self, db_session):
        db_session.execute = MagicMock()

        result = asyncio.run(health.readiness_check(db=db_session))

        assert result["status"] == "ready"
        assert result["checks"]["database"]["status"] == "healthy"

    def test_health_live_no_db_dependency(self):
        result = asyncio.run(health.liveness_check())

        assert result["status"] == "alive"

    def test_health_quick_db_failure_raises_503(self):
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("database unavailable")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(health.quick_health_check(db=mock_db))

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["status"] == "unhealthy"

    def test_metrics_returns_raw_prometheus_response(self, db_session):
        response = asyncio.run(health.metrics_endpoint(db=db_session))

        assert isinstance(response, Response)
        assert response.headers["content-type"].startswith("text/plain")
        assert b"# HELP" in response.body
        assert not response.body.startswith(b'"')

    def test_request_metrics_use_route_template_and_actual_status(self, client):
        with patch("app.core.metrics.record_http_request") as record:
            response = client.get("/api/v1/health/live")

        assert response.status_code == 200
        record.assert_called_once()
        method, endpoint, response_status, duration = record.call_args.args
        assert method == "GET"
        assert endpoint == "/api/v1/health/live"
        assert response_status == 200
        assert duration >= 0

    def test_unmatched_request_metric_has_bounded_label(self, client):
        with patch("app.core.metrics.record_http_request") as record:
            response = client.get("/random/not-found/12345")

        assert response.status_code == 404
        assert record.call_args.args[:3] == ("GET", "__unmatched__", 404)
