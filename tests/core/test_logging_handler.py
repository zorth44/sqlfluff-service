"""GzipTimedRotatingFileHandler 轮转 / 压缩 / 保留策略测试。"""

import gzip
import logging
import multiprocessing
import os
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

# settings 要求 NFS_SHARE_ROOT_PATH；在导入 logging 模块前兜底
os.environ.setdefault("NFS_SHARE_ROOT_PATH", tempfile.mkdtemp(prefix="sqlfluff-test-nfs-"))

from app.config.settings import settings  # noqa: E402
from app.core.logging import (  # noqa: E402
    GzipTimedRotatingFileHandler,
    JSONFormatter,
    TextFormatter,
    setup_logging,
)


@pytest.fixture
def log_dir(tmp_path):
    return tmp_path


def _write_and_close(handler: GzipTimedRotatingFileHandler, message: str) -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    handler.flush()


def test_rollover_creates_gzip(log_dir):
    log_path = log_dir / "app.log"
    handler = GzipTimedRotatingFileHandler(
        filename=str(log_path),
        when="midnight",
        interval=1,
        backupCount=5,
        encoding="utf-8",
    )
    try:
        _write_and_close(handler, "before rollover")
        handler.doRollover()

        gz_files = sorted(log_dir.glob("app.log.*.gz"))
        assert len(gz_files) == 1
        assert not any(p.suffix == ".log" and p.name != "app.log" for p in log_dir.iterdir())

        with gzip.open(gz_files[0], "rt", encoding="utf-8") as f:
            content = f.read()
        assert "before rollover" in content
        assert log_path.exists()
    finally:
        handler.close()


def test_backup_count_deletes_oldest_gzip(log_dir):
    log_path = log_dir / "app.log"
    backup_count = 3
    handler = GzipTimedRotatingFileHandler(
        filename=str(log_path),
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
    )
    try:
        # 预置超过保留天数的历史 .gz（含一个未压缩旧文件，验证兼容）
        today = date.today()
        for i in range(1, 6):
            day = today - timedelta(days=i)
            suffix = day.strftime("%Y-%m-%d")
            if i == 5:
                # 最旧：未压缩，应一并纳入清理
                (log_dir / f"app.log.{suffix}").write_text(f"old-{i}\n", encoding="utf-8")
            else:
                gz_path = log_dir / f"app.log.{suffix}.gz"
                with gzip.open(gz_path, "wt", encoding="utf-8") as f:
                    f.write(f"old-{i}\n")

        _write_and_close(handler, "current")
        handler.doRollover()

        # 轮转后又产生 1 个今天的 .gz；总数应不超过 backupCount
        archived = [
            p for p in log_dir.iterdir()
            if p.name.startswith("app.log.") and p.name != "app.log"
        ]
        assert len(archived) <= backup_count

        # 最旧的未压缩文件应被删掉
        oldest = today - timedelta(days=5)
        assert not (log_dir / f"app.log.{oldest.strftime('%Y-%m-%d')}").exists()
    finally:
        handler.close()


def test_get_files_to_delete_respects_backup_count(log_dir):
    log_path = log_dir / "app.log"
    log_path.write_text("seed\n", encoding="utf-8")
    handler = GzipTimedRotatingFileHandler(
        filename=str(log_path),
        when="midnight",
        interval=1,
        backupCount=2,
        encoding="utf-8",
    )
    try:
        today = date.today()
        for i in range(1, 5):
            day = today - timedelta(days=i)
            gz_path = log_dir / f"app.log.{day.strftime('%Y-%m-%d')}.gz"
            with gzip.open(gz_path, "wt", encoding="utf-8") as f:
                f.write(f"day-{i}\n")

        to_delete = handler.getFilesToDelete()
        assert len(to_delete) == 2  # 4 个历史 - 保留 2 = 删 2
        # 删除的应是更旧的（字典序即日期序）
        deleted_names = sorted(Path(p).name for p in to_delete)
        assert deleted_names[0] < deleted_names[1]
    finally:
        handler.close()


def _emit_after_rollover_from_process(log_path: str, message: str, start_event) -> None:
    """子进程辅助函数：同时跨过轮转点写同一文件。"""
    handler = GzipTimedRotatingFileHandler(
        filename=log_path,
        when="midnight",
        interval=1,
        backupCount=5,
        encoding="utf-8",
    )
    try:
        start_event.wait(timeout=10)
        _write_and_close(handler, message)
    finally:
        handler.close()


def test_concurrent_processes_rollover_without_losing_archive(log_dir):
    """Gunicorn worker 同时写入时，只能有一个进程执行实际轮转。"""
    log_path = log_dir / "web.log"
    log_path.write_text("before rollover\n", encoding="utf-8")
    yesterday = time.time() - 24 * 60 * 60
    os.utime(log_path, (yesterday, yesterday))

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    processes = [
        context.Process(
            target=_emit_after_rollover_from_process,
            args=(str(log_path), f"worker-{index}", start_event),
        )
        for index in range(4)
    ]
    for process in processes:
        process.start()
    start_event.set()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    archives = list(log_dir.glob("web.log.*.gz"))
    assert len(archives) == 1
    with gzip.open(archives[0], "rt", encoding="utf-8") as f:
        assert "before rollover" in f.read()

    current_content = log_path.read_text(encoding="utf-8")
    for index in range(4):
        assert f"worker-{index}" in current_content


@pytest.mark.parametrize(
    ("console_format", "console_formatter"),
    [("json", JSONFormatter), ("text", TextFormatter)],
)
def test_file_logs_always_use_text_format(
    tmp_path, monkeypatch, console_format, console_formatter
):
    """LOG_FORMAT 只影响标准输出，本地滚动日志始终便于人工阅读。"""
    log_path = tmp_path / "service.log"
    root_logger = logging.getLogger()
    previous_handlers = root_logger.handlers[:]
    previous_level = root_logger.level

    monkeypatch.setattr(settings, "LOG_FORMAT", console_format)
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "LOG_FILE_BACKUP_COUNT", 2)

    try:
        setup_logging()

        console_handler = next(
            handler
            for handler in root_logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
            and handler.stream is sys.stdout
        )
        file_handler = next(
            handler
            for handler in root_logger.handlers
            if isinstance(handler, GzipTimedRotatingFileHandler)
        )
        assert isinstance(console_handler.formatter, console_formatter)
        assert isinstance(file_handler.formatter, TextFormatter)

        root_logger.info("human-readable file log")
        file_handler.flush()
        file_content = log_path.read_text(encoding="utf-8")
        assert "human-readable file log" in file_content
        assert " | INFO" in file_content
        assert not file_content.lstrip().startswith("{")
    finally:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            handler.close()
        for handler in previous_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(previous_level)
