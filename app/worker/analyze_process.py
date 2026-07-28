"""
Run SQLFluff analysis in an isolated child process.

Uses spawn context so the child does not inherit SQLAlchemy connections.
Large results are written to a temp file to avoid Queue pipe deadlocks.
"""

import json
import logging
import multiprocessing as mp
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_analyze_semaphore: Optional[threading.Semaphore] = None
_semaphore_lock = threading.Lock()


def _get_analyze_semaphore(max_concurrent: int) -> threading.Semaphore:
    global _analyze_semaphore
    with _semaphore_lock:
        if _analyze_semaphore is None:
            _analyze_semaphore = threading.Semaphore(max(1, max_concurrent))
        return _analyze_semaphore


def reset_analyze_semaphore(max_concurrent: int) -> None:
    """Reset module semaphore (for tests)."""
    global _analyze_semaphore
    with _semaphore_lock:
        _analyze_semaphore = threading.Semaphore(max(1, max_concurrent))


def _child_analyze(
    source_file_path: str,
    dialect: Optional[str],
    rules: Optional[List[str]],
    result_path: str,
) -> None:
    """
    子进程入口：分析结果写入临时文件，避免大 payload 阻塞 Queue。

    成功时写 JSON: {"ok": true, "result": {...}}
    失败时写 JSON: {"ok": false, "error": "..."}
    """
    try:
        from app.services.sqlfluff_service import SQLFluffService

        service = SQLFluffService()
        result = service.analyze_sql_file(source_file_path, dialect, rules)
        payload = {"ok": True, "result": result}
    except Exception as exc:
        payload = {
            "ok": False,
            "error": repr(exc),
            "exc_type": type(exc).__name__,
        }

    _write_child_payload(result_path, payload)


def _child_analyze_content(
    sql_content: str,
    file_name: str,
    dialect: Optional[str],
    rules: Optional[List[str]],
    result_path: str,
) -> None:
    """Child-process entry point for the synchronous SQL-check API."""
    try:
        from app.services.sqlfluff_service import SQLFluffService

        service = SQLFluffService()
        result = service.analyze_sql_content(
            sql_content=sql_content,
            file_name=file_name,
            dialect=dialect,
            rules=rules,
            db_session=None,
        )
        payload = {"ok": True, "result": result}
    except Exception as exc:
        payload = {
            "ok": False,
            "error": repr(exc),
            "exc_type": type(exc).__name__,
        }

    _write_child_payload(result_path, payload)


def _write_child_payload(result_path: str, payload: Dict[str, Any]) -> None:
    """Atomically publish a child-process result payload."""
    tmp_path = f"{result_path}.partial"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, result_path)
    except Exception:
        # 尽量清理半截文件
        for path in (tmp_path, result_path):
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def run_analyze_in_process(
    source_file_path: str,
    dialect: Optional[str],
    rules: Optional[List[str]],
    soft_timeout: float,
    hard_timeout: float,
    concurrency: int = 4,
) -> Dict[str, Any]:
    """
    Run SQLFluff analysis in a spawned subprocess with soft/hard timeouts.

    Large results are exchanged via a temporary file (not Queue body),
    so join() cannot deadlock on a full pipe buffer.
    """
    sem = _get_analyze_semaphore(concurrency)
    sem.acquire()
    try:
        return _run_analyze_subprocess(
            source_file_path,
            dialect,
            rules,
            soft_timeout,
            hard_timeout,
        )
    finally:
        sem.release()


def run_analyze_content_in_process(
    sql_content: str,
    file_name: str,
    dialect: Optional[str],
    rules: Optional[List[str]],
    soft_timeout: float,
    hard_timeout: float,
    concurrency: int = 2,
) -> Dict[str, Any]:
    """Analyze SQL text in a spawned subprocess with bounded concurrency."""
    sem = _get_analyze_semaphore(concurrency)
    sem.acquire()
    try:
        return _run_analysis_subprocess(
            target=_child_analyze_content,
            args=(sql_content, file_name, dialect, rules),
            source_label=file_name,
            soft_timeout=soft_timeout,
            hard_timeout=hard_timeout,
        )
    finally:
        sem.release()


def _run_analyze_subprocess(
    source_file_path: str,
    dialect: Optional[str],
    rules: Optional[List[str]],
    soft_timeout: float,
    hard_timeout: float,
) -> Dict[str, Any]:
    return _run_analysis_subprocess(
        target=_child_analyze,
        args=(source_file_path, dialect, rules),
        source_label=source_file_path,
        soft_timeout=soft_timeout,
        hard_timeout=hard_timeout,
    )


def _run_analysis_subprocess(
    target: Callable[..., None],
    args: Tuple[Any, ...],
    source_label: str,
    soft_timeout: float,
    hard_timeout: float,
) -> Dict[str, Any]:
    fd, result_path = tempfile.mkstemp(prefix="sqlfluff_analyze_", suffix=".json")
    os.close(fd)
    # 子进程用 os.replace 写入；先删掉空文件避免读到半截
    os.unlink(result_path)

    ctx = mp.get_context("spawn")
    proc = ctx.Process(
        target=target,
        args=(*args, result_path),
        daemon=True,
    )
    proc.start()

    deadline = time.monotonic() + soft_timeout
    while proc.is_alive() and time.monotonic() < deadline:
        proc.join(timeout=0.2)

    timed_out = proc.is_alive()
    if timed_out:
        logger.warning(
            "Analyze process soft timeout (%.1fs) for %s, terminating",
            soft_timeout,
            source_label,
        )
        proc.terminate()
        remaining = max(0.1, hard_timeout - soft_timeout)
        proc.join(timeout=remaining)

    if proc.is_alive():
        logger.error(
            "Analyze process hard timeout (%.1fs) for %s, killing",
            hard_timeout,
            source_label,
        )
        proc.kill()
        proc.join(timeout=5)

    if timed_out:
        _cleanup_result_file(result_path)
        raise TimeoutError(
            f"SQLFluff analysis exceeded timeout ({soft_timeout}s)"
        )

    try:
        payload = _read_result_file(result_path)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Analyze process produced no result (exitcode={proc.exitcode})"
        ) from exc
    finally:
        _cleanup_result_file(result_path)

    if payload.get("ok"):
        return payload["result"]

    raise RuntimeError(payload.get("error", "Analyze process failed"))


def _read_result_file(result_path: str) -> Dict[str, Any]:
    path = Path(result_path)
    if not path.exists():
        raise FileNotFoundError(result_path)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _cleanup_result_file(result_path: str) -> None:
    for path in (result_path, f"{result_path}.partial"):
        try:
            os.unlink(path)
        except OSError:
            pass
