import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import sql as sql_route
from app.api.routes.sql import check_sql
from app.schemas.sql import SQLCheckRequest


def test_check_sql_runs_analysis_in_isolated_process():
    request = SQLCheckRequest(sql_content="SELECT 1;", dialect="hive")
    result = {
        "violations": [
            {
                "line_no": 1,
                "line_pos": 1,
                "code": "LT01",
                "description": "spacing",
                "rule": "layout.spacing",
                "severity": "warning",
                "severity_level": None,
                "fixable": True,
            }
        ]
    }

    with patch(
        "app.api.routes.sql.run_analyze_content_in_process",
        return_value=result,
    ) as analyze:
        response = asyncio.run(check_sql(request))

    assert len(response.violations) == 1
    analyze.assert_called_once()


def test_check_sql_timeout_returns_504():
    request = SQLCheckRequest(sql_content="SELECT 1;", dialect="hive")

    with patch(
        "app.api.routes.sql.run_analyze_content_in_process",
        side_effect=TimeoutError("analysis timeout"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(check_sql(request))

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "SQL 分析超时"


def test_check_sql_queue_timeout_returns_503():
    class BusySemaphore:
        async def acquire(self):
            await asyncio.sleep(0.05)

        def release(self):
            raise AssertionError("a semaphore that was not acquired must not release")

    request = SQLCheckRequest(sql_content="SELECT 1;", dialect="hive")
    with patch.object(
        sql_route, "_realtime_sql_semaphore", BusySemaphore()
    ), patch.object(
        sql_route.settings, "REALTIME_SQL_QUEUE_TIMEOUT", 0.001
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(check_sql(request))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "实时 SQL 检查繁忙，请稍后重试"


def test_check_sql_rejects_payload_larger_than_one_mib():
    with pytest.raises(ValidationError):
        SQLCheckRequest(sql_content="x" * (1024 * 1024 + 1), dialect="hive")
