"""Analyze subprocess IPC tests — large results must not deadlock."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.worker import analyze_process
from app.worker.analyze_process import (
    reset_analyze_semaphore,
    run_analyze_content_in_process,
    run_analyze_in_process,
)


@pytest.fixture(autouse=True)
def _reset_sem():
    reset_analyze_semaphore(4)
    yield
    reset_analyze_semaphore(4)


class _FakeProcess:
    """在同进程执行 target，模拟子进程写完临时文件后立即退出。"""

    def __init__(self, target=None, args=(), daemon=True):
        self._target = target
        self._args = args
        self.exitcode = None
        self._alive = False

    def start(self):
        self._alive = True
        try:
            self._target(*self._args)
            self.exitcode = 0
        except Exception:
            self.exitcode = 1
            raise
        finally:
            self._alive = False

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        return None

    def terminate(self):
        self._alive = False

    def kill(self):
        self._alive = False


def test_large_analyze_result_via_temp_file_does_not_deadlock():
    """多 MB 结果通过临时文件传递，不应依赖 Queue 管道缓冲。"""
    huge = {
        "summary": {"total_violations": 1, "critical_violations_count": 0},
        "violations": [
            {
                "code": "L001",
                "line_no": i,
                "description": "x" * 2000,
            }
            for i in range(3000)
        ],
    }
    assert len(json.dumps(huge)) > 1_000_000

    def fake_child(source_file_path, dialect, rules, result_path):
        import os

        payload = {"ok": True, "result": huge}
        tmp = f"{result_path}.partial"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, result_path)

    fake_ctx = MagicMock()
    fake_ctx.Process = _FakeProcess
    fake_ctx.Process = lambda target=None, args=(), daemon=True: _FakeProcess(
        target=fake_child if target else None,
        args=args,
        daemon=daemon,
    )

    with patch.object(analyze_process.mp, "get_context", return_value=fake_ctx):
        # Process 构造时 target 仍是真实 _child_analyze；改为注入 fake
        def process_factory(target=None, args=(), daemon=True):
            return _FakeProcess(target=fake_child, args=args, daemon=daemon)

        fake_ctx.Process = process_factory
        result = run_analyze_in_process(
            "a.sql",
            "ansi",
            None,
            soft_timeout=10,
            hard_timeout=15,
            concurrency=2,
        )

    assert result["summary"]["total_violations"] == 1
    assert len(result["violations"]) == 3000


def test_worker_config_rejects_invalid_timeouts():
    from app.worker.config import WorkerConfig

    with pytest.raises(ValueError, match="LEASE_RENEW_INTERVAL"):
        WorkerConfig(task_lease_seconds=30, lease_renew_interval=30)

    with pytest.raises(ValueError, match="ANALYZE_SOFT_TIMEOUT"):
        WorkerConfig(analyze_soft_timeout=900, analyze_hard_timeout=900)


def test_realtime_content_analysis_uses_isolated_process():
    expected = {"violations": [], "summary": {"total_violations": 0}}

    fake_ctx = MagicMock()
    fake_ctx.Process = _FakeProcess

    with patch.object(
        analyze_process.mp, "get_context", return_value=fake_ctx
    ), patch(
        "app.services.sqlfluff_service.SQLFluffService.analyze_sql_content",
        return_value=expected,
    ) as analyze:
        result = run_analyze_content_in_process(
            "SELECT 1;",
            "query.sql",
            "hive",
            ["LT01"],
            soft_timeout=10,
            hard_timeout=15,
            concurrency=2,
        )

    assert result == expected
    analyze.assert_called_once_with(
        sql_content="SELECT 1;",
        file_name="query.sql",
        dialect="hive",
        rules=["LT01"],
        db_session=None,
    )
