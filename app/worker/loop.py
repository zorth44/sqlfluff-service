"""
Worker 主循环

实现 DB-as-Queue 的 Worker 核心逻辑：
- claim_task: 原子领取最高优先级 PENDING 任务（FOR UPDATE SKIP LOCKED）
- WorkerThread: 循环 claim → process → 更新状态的线程
- HeartbeatThread: 定期向 worker_registry 写入心跳
- ZombieSweepThread: 定期回收超时未完成的僵尸任务

每个 Worker 进程包含:
    concurrency 个 WorkerThread（执行实际任务）
    1 个 HeartbeatThread（发送心跳）
    1 个 ZombieSweepThread（回收僵尸任务）
"""

import os
import sys
import time
import socket
import signal
import uuid
import threading
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.db_session import managed_db_session
from app.models.database import LintingTask, WorkerRegistry
from app.schemas.common import TaskStatusEnum
from app.worker.config import WorkerConfig
from app.worker.processor import process_task_safe

logger = logging.getLogger(__name__)


# ───────────────────── Worker Context ─────────────────────

class WorkerContext:
    """Worker 进程的共享上下文"""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.worker_id = f"{socket.gethostname()}_{os.getpid()}"
        self.running = True


# ───────────────────── Task Claim ─────────────────────

def claim_task(db: Session, worker_id: str) -> Optional[LintingTask]:
    """
    原子领取最高优先级 PENDING 任务

    使用 SELECT ... FOR UPDATE SKIP LOCKED 确保:
    - 多个 Worker 不会领取同一任务
    - 已被其他 Worker 锁定的任务自动跳过
    - 按优先级 DESC + 创建时间 ASC 排序（优先级高的先处理）

    Args:
        db: 数据库会话
        worker_id: Worker 标识

    Returns:
        LintingTask | None: 领取到的任务，无任务时返回 None
    """
    task = db.execute(
        db.query(LintingTask)
        .filter(LintingTask.status == TaskStatusEnum.PENDING)
        .order_by(LintingTask.priority.desc(), LintingTask.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()

    if task:
        task.status = TaskStatusEnum.PROCESSING
        task.claim_id = f"{worker_id}:{uuid.uuid4().hex[:8]}"
        task.claimed_at = datetime.utcnow()
        db.commit()
        logger.debug(f"Claimed task {task.task_id} for job {task.job_id}")

    return task


# ───────────────────── Worker Thread (任务执行) ─────────────────────

class WorkerThread(threading.Thread):
    """
    Worker 线程：循环领取并处理任务

    每个线程独立运行 claim → process 循环：
    1. 从 DB 原子领取一个 PENDING 任务
    2. 调用 process_task_safe 执行 SQLFluff 分析
    3. 处理完成后更新 task/job 状态
    4. 无任务时等待 poll_interval 秒后重试
    """

    def __init__(self, ctx: WorkerContext, thread_id: int):
        super().__init__(daemon=True, name=f"worker-thread-{thread_id}")
        self.ctx = ctx
        self.thread_id = thread_id
        self.tasks_processed = 0

    def run(self):
        logger.info(f"Worker thread {self.thread_id} started")

        while self.ctx.running:
            try:
                with managed_db_session() as db:
                    task = claim_task(db, self.ctx.worker_id)

                if task:
                    # 在事务外执行耗时操作
                    process_task_safe(task.task_id, self.ctx.worker_id)
                    self.tasks_processed += 1
                    logger.debug(
                        f"Thread {self.thread_id} completed task {task.task_id} "
                        f"(total: {self.tasks_processed})"
                    )
                else:
                    # 无可用任务，等待后重试
                    time.sleep(self.ctx.config.poll_interval)

            except Exception as e:
                logger.error(
                    f"Worker thread {self.thread_id} error: {e}",
                    exc_info=True
                )
                time.sleep(min(self.ctx.config.poll_interval * 2, 10))

        logger.info(
            f"Worker thread {self.thread_id} stopped "
            f"(processed: {self.tasks_processed})"
        )


# ───────────────────── Heartbeat Thread ─────────────────────

class HeartbeatThread(threading.Thread):
    """
    心跳线程：定期向 worker_registry 写入心跳

    如果没有心跳记录则创建（Worker 注册），已有则更新 heartbeat_at。
    心跳间隔由 config.heartbeat_interval 控制。
    """

    def __init__(self, ctx: WorkerContext):
        super().__init__(daemon=True, name="heartbeat-thread")
        self.ctx = ctx

    def run(self):
        # 首次注册
        self._register()
        logger.info(f"Heartbeat thread started for {self.ctx.worker_id}")

        while self.ctx.running:
            time.sleep(self.ctx.config.heartbeat_interval)
            try:
                self._send_heartbeat()
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")

    def _register(self):
        """初始注册 Worker"""
        with managed_db_session() as db:
            worker = db.query(WorkerRegistry).filter_by(
                worker_id=self.ctx.worker_id
            ).first()

            if worker:
                worker.status = 'RUNNING'
                worker.heartbeat_at = datetime.utcnow()
                worker.pid = os.getpid()
            else:
                worker = WorkerRegistry(
                    worker_id=self.ctx.worker_id,
                    hostname=socket.gethostname(),
                    pid=os.getpid(),
                    status='RUNNING',
                    heartbeat_at=datetime.utcnow(),
                    started_at=datetime.utcnow()
                )
                db.add(worker)

        logger.info(f"Worker registered: {self.ctx.worker_id}")

    def _send_heartbeat(self):
        """发送心跳"""
        with managed_db_session() as db:
            worker = db.query(WorkerRegistry).filter_by(
                worker_id=self.ctx.worker_id
            ).first()

            if worker and worker.status == 'RUNNING':
                worker.heartbeat_at = datetime.utcnow()

                # 统计当前处理中的任务数
                active_count = db.query(LintingTask).filter(
                    LintingTask.claim_id.like(f"{self.ctx.worker_id}:%"),
                    LintingTask.status == TaskStatusEnum.PROCESSING
                ).count()
                worker.current_task_count = active_count


# ───────────────────── Zombie Sweep Thread ─────────────────────

class ZombieSweepThread(threading.Thread):
    """
    僵尸回收线程：定期回收超时的 PROCESSING 任务

    回收逻辑：
    1. 查找心跳超时的 Worker（超过 zombie_timeout 无心跳）
    2. 将关联的 PROCESSING 任务重置为 PENDING（retry_count++）
    3. 超过 max_retries 的任务标记为 FAILURE
    """

    def __init__(self, ctx: WorkerContext):
        super().__init__(daemon=True, name="zombie-sweep-thread")
        self.ctx = ctx

    def run(self):
        logger.info(
            f"Zombie sweep thread started "
            f"(timeout: {self.ctx.config.zombie_timeout}s, "
            f"interval: {self.ctx.config.zombie_sweep_interval}s)"
        )

        while self.ctx.running:
            time.sleep(self.ctx.config.zombie_sweep_interval)
            try:
                count = self._reclaim()
                if count > 0:
                    logger.warning(f"Reclaimed {count} zombie tasks")
            except Exception as e:
                logger.error(f"Zombie sweep failed: {e}", exc_info=True)

    def _reclaim(self) -> int:
        """执行僵尸任务回收"""
        with managed_db_session() as db:
            cutoff = datetime.utcnow() - timedelta(
                seconds=self.ctx.config.zombie_timeout
            )

            # 1. 查找心跳超时的 Worker
            stale_workers = db.query(WorkerRegistry).filter(
                WorkerRegistry.status == 'RUNNING',
                WorkerRegistry.heartbeat_at < cutoff
            ).all()

            if not stale_workers:
                return 0

            stale_ids = [w.worker_id for w in stale_workers]

            # 标记 Worker 为 DEAD
            for w in stale_workers:
                w.status = 'DEAD'
                w.stopped_at = datetime.utcnow()
                logger.warning(
                    f"Worker {w.worker_id} marked DEAD "
                    f"(last heartbeat: {w.heartbeat_at})"
                )

            # 2. 回收它们的 PROCESSING 任务
            # 使用 claim_id 前缀匹配查找
            reclaimed = 0

            for stale_id in stale_ids:
                tasks = db.query(LintingTask).filter(
                    LintingTask.status == TaskStatusEnum.PROCESSING,
                    LintingTask.claim_id.like(f"{stale_id}:%")
                ).all()

                for task in tasks:
                    task.retry_count = (task.retry_count or 0) + 1

                    if task.retry_count > self.ctx.config.max_retries:
                        # 超过最大重试次数，标记为永久失败
                        task.status = TaskStatusEnum.FAILURE
                        task.error_message = (
                            f"超过最大重试次数（{self.ctx.config.max_retries}次），"
                            f"最后处理 Worker: {stale_id}"
                        )
                    else:
                        # 重置为 PENDING，等待重新分配
                        task.status = TaskStatusEnum.PENDING

                    task.claim_id = None
                    task.claimed_at = None
                    reclaimed += 1

            logger.info(
                f"Zombie sweep: {len(stale_ids)} dead workers, "
                f"{reclaimed} tasks reclaimed"
            )
            return reclaimed


# ───────────────────── Main Entry Point ─────────────────────

def start_worker(config: Optional[WorkerConfig] = None):
    """
    启动 DB-as-Queue Worker 进程

    1. 创建 WorkerContext（生成 worker_id）
    2. 启动 HeartbeatThread、ZombieSweepThread
    3. 启动 concurrency 个 WorkerThread
    4. 注册信号处理器，等待关闭

    Args:
        config: Worker 配置，不传则使用默认值
    """
    if config is None:
        config = WorkerConfig()

    ctx = WorkerContext(config)

    logger.info(f"Starting DB Worker: {ctx.worker_id}")
    logger.info(
        f"Config: concurrency={config.concurrency}, "
        f"poll_interval={config.poll_interval}s, "
        f"heartbeat_interval={config.heartbeat_interval}s, "
        f"zombie_timeout={config.zombie_timeout}s, "
        f"max_retries={config.max_retries}"
    )

    # 启动后台线程
    heartbeat = HeartbeatThread(ctx)
    zombie_sweeper = ZombieSweepThread(ctx)
    heartbeat.start()
    zombie_sweeper.start()

    # 启动 Worker 线程
    worker_threads = []
    for i in range(config.concurrency):
        thread = WorkerThread(ctx, i)
        thread.start()
        worker_threads.append(thread)

    # 优雅关闭处理
    def shutdown(signum, frame):
        if not ctx.running:
            logger.warning("Force shutdown")
            sys.exit(1)

        logger.info(
            f"Received signal {signum}, shutting down worker {ctx.worker_id}..."
        )
        ctx.running = False

        # 标记 Worker 为 STOPPED
        try:
            with managed_db_session() as db:
                worker = db.query(WorkerRegistry).filter_by(
                    worker_id=ctx.worker_id
                ).first()
                if worker:
                    worker.status = 'STOPPED'
                    worker.stopped_at = datetime.utcnow()
            logger.info("Worker marked as STOPPED in registry")
        except Exception as e:
            logger.error(f"Failed to mark worker as STOPPED: {e}")

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # 等待所有任务线程结束
    for thread in worker_threads:
        thread.join()

    logger.info(f"Worker {ctx.worker_id} shut down gracefully")
