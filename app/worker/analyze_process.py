"""
Run SQLFluff analysis in an isolated child process.

Uses spawn context so the child does not inherit SQLAlchemy connections.
"""

import logging
import multiprocessing as mp
import threading
import time
from typing import Any, Dict, List, Optional

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
    result_queue: mp.Queue,
) -> None:
    try:
        from app.services.sqlfluff_service import SQLFluffService

        service = SQLFluffService()
        result = service.analyze_sql_file(source_file_path, dialect, rules)
        result_queue.put({"ok": True, "result": result})
    except Exception as exc:
        result_queue.put({"ok": False, "error": repr(exc), "exc_type": type(exc).__name__})


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

    Args:
        source_file_path: Relative or absolute SQL file path
        dialect: SQL dialect
        rules: Optional rule list
        soft_timeout: Seconds before terminate() is sent
        hard_timeout: Total seconds before kill() if still running
        concurrency: Max concurrent analyze processes (semaphore size)

    Returns:
        Analysis result dict from SQLFluffService

    Raises:
        TimeoutError: Process exceeded hard timeout
        RuntimeError: Child process failed
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


def _run_analyze_subprocess(
    source_file_path: str,
    dialect: Optional[str],
    rules: Optional[List[str]],
    soft_timeout: float,
    hard_timeout: float,
) -> Dict[str, Any]:
    ctx = mp.get_context("spawn")
    result_queue: mp.Queue = ctx.Queue()
    proc = ctx.Process(
        target=_child_analyze,
        args=(source_file_path, dialect, rules, result_queue),
        daemon=True,
    )
    proc.start()
    proc.join(timeout=soft_timeout)

    if proc.is_alive():
        logger.warning(
            "Analyze process soft timeout (%.1fs) for %s, terminating",
            soft_timeout,
            source_file_path,
        )
        proc.terminate()
        remaining = max(0.1, hard_timeout - soft_timeout)
        proc.join(timeout=remaining)

    if proc.is_alive():
        logger.error(
            "Analyze process hard timeout (%.1fs) for %s, killing",
            hard_timeout,
            source_file_path,
        )
        proc.kill()
        proc.join(timeout=5)
        raise TimeoutError(
            f"SQLFluff analysis exceeded hard timeout ({hard_timeout}s)"
        )

    if proc.exitcode not in (0, None) and not _queue_has_item(result_queue):
        raise RuntimeError(
            f"Analyze process exited with code {proc.exitcode}"
        )

    try:
        payload = result_queue.get(timeout=1)
    except Exception as exc:
        raise RuntimeError(
            f"Analyze process produced no result (exitcode={proc.exitcode})"
        ) from exc

    if payload.get("ok"):
        return payload["result"]

    raise RuntimeError(payload.get("error", "Analyze process failed"))

def _queue_has_item(queue: mp.Queue) -> bool:
    try:
        return not queue.empty()
    except Exception:
        return False
