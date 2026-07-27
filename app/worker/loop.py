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
from typing import Optional, List

from sqlalchemy.orm import Session

from app.core.db_session import managed_db_session
from app.models.database import LintingTask, LintingJob, WorkerRegistry
from app.schemas.common import TaskStatusEnum, JobStatusEnum
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
    """
    task = (
        db.query(LintingTask)
        .filter(LintingTask.status == TaskStatusEnum.PENDING)
        .order_by(LintingTask.priority.desc(), LintingTask.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )

    if task:
        task.status = TaskStatusEnum.IN_PROGRESS
        task.claim_id = f"{worker_id}:{uuid.uuid4().hex[:8]}"
        task.claimed_at = datetime.utcnow()
        task.error_message = None

        # 首次领取时把 Job 从 ACCEPTED 推进到 PROCESSING
        job = db.query(LintingJob).filter(
            LintingJob.job_id == task.job_id
        ).first()
        if job and job.status == JobStatusEnum.ACCEPTED:
            job.status = JobStatusEnum.PROCESSING

        db.commit()
        logger.debug(f"Claimed task {task.task_id} for job {task.job_id}")

    return task


def reset_task_after_failure(
    task: LintingTask,
    max_retries: int,
    reason: str,
) -> str:
    """
    按重试策略重置或永久失败一个僵尸任务。

    Returns:
        'PENDING' | 'FAILURE' — 任务最终状态
    """
    task.retry_count = (task.retry_count or 0) + 1
    task.claim_id = None
    task.claimed_at = None

    if task.retry_count > max_retries:
        task.status = TaskStatusEnum.FAILURE
        task.error_message = (
            f"超过最大重试次数（{max_retries}次），{reason}"
        )
        return TaskStatusEnum.FAILURE.value

    task.status = TaskStatusEnum.PENDING
    task.error_message = None
    return TaskStatusEnum.PENDING.value


def reclaim_zombie_tasks(db: Session, config: WorkerConfig) -> int:
    """
    回收僵尸任务。

    回收条件（满足任一即可）:
    1. Worker 心跳超时（RUNNING 且 heartbeat_at 过旧）→ 标记 DEAD，回收其任务
    2. Worker 已是 STOPPED/DEAD，但仍挂着 IN_PROGRESS 任务
    3. 任务 claimed_at 超过 task_timeout（覆盖卡住但仍有心跳的场景）

    对目标任务行使用 FOR UPDATE SKIP LOCKED，避免多 Worker 扫尸时双计 retry_count。
    """
    now = datetime.utcnow()
    heartbeat_cutoff = now - timedelta(seconds=config.zombie_timeout)
    task_cutoff = now - timedelta(seconds=config.task_timeout)
    reclaimed = 0

    # 1. 心跳超时的 RUNNING Worker → DEAD
    stale_workers = (
        db.query(WorkerRegistry)
        .filter(
            WorkerRegistry.status == 'RUNNING',
            WorkerRegistry.heartbeat_at < heartbeat_cutoff,
        )
        .with_for_update(skip_locked=True)
        .all()
    )

    for worker in stale_workers:
        worker.status = 'DEAD'
        worker.stopped_at = now
        logger.warning(
            f"Worker {worker.worker_id} marked DEAD "
            f"(last heartbeat: {worker.heartbeat_at})"
        )

    # 2. 找出候选 IN_PROGRESS 任务并加行锁
    candidates: List[LintingTask] = (
        db.query(LintingTask)
        .filter(LintingTask.status == TaskStatusEnum.IN_PROGRESS)
        .with_for_update(skip_locked=True)
        .all()
    )

    for task in candidates:
        worker_id_prefix = None
        if task.claim_id and ':' in task.claim_id:
            worker_id_prefix = task.claim_id.rsplit(':', 1)[0]

        timed_out = (
            task.claimed_at is not None and task.claimed_at < task_cutoff
        )

        worker_row = None
        if worker_id_prefix:
            worker_row = (
                db.query(WorkerRegistry)
                .filter(WorkerRegistry.worker_id == worker_id_prefix)
                .first()
            )

        # STOPPED/DEAD/缺失 Worker 的任务立即回收；仍 RUNNING 的只按 task_timeout
        worker_inactive = (
            worker_row is None or worker_row.status in ('DEAD', 'STOPPED')
        )
        should_reclaim = timed_out or worker_inactive

        if not should_reclaim:
            continue

        reason = (
            f"任务超时（claimed_at={task.claimed_at}）"
            if timed_out
            else f"Worker 不可用: {worker_id_prefix or 'unknown'}"
        )
        new_status = reset_task_after_failure(task, config.max_retries, reason)
        reclaimed += 1
        logger.warning(
            f"Reclaimed task {task.task_id} -> {new_status}: {reason}"
        )

    if reclaimed or stale_workers:
        logger.info(
            f"Zombie sweep: {len(stale_workers)} dead workers, "
            f"{reclaimed} tasks reclaimed"
        )

    return reclaimed


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
                worker.stopped_at = None
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
                    LintingTask.status == TaskStatusEnum.IN_PROGRESS
                ).count()
                worker.current_task_count = active_count


# ───────────────────── Zombie Sweep Thread ─────────────────────

class ZombieSweepThread(threading.Thread):
    """
    僵尸回收线程：定期回收超时的 IN_PROGRESS 任务

    回收逻辑见 reclaim_zombie_tasks()。
    """

    def __init__(self, ctx: WorkerContext):
        super().__init__(daemon=True, name="zombie-sweep-thread")
        self.ctx = ctx

    def run(self):
        logger.info(
            f"Zombie sweep thread started "
            f"(zombie_timeout: {self.ctx.config.zombie_timeout}s, "
            f"task_timeout: {self.ctx.config.task_timeout}s, "
            f"interval: {self.ctx.config.zombie_sweep_interval}s)"
        )

        while self.ctx.running:
            time.sleep(self.ctx.config.zombie_sweep_interval)
            try:
                with managed_db_session() as db:
                    count = reclaim_zombie_tasks(db, self.ctx.config)
                if count > 0:
                    logger.warning(f"Reclaimed {count} zombie tasks")
            except Exception as e:
                logger.error(f"Zombie sweep failed: {e}", exc_info=True)


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
        f"task_timeout={config.task_timeout}s, "
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

    # 优雅关闭处理：先停领任务并等待在途任务，再标记 STOPPED
    def shutdown(signum, frame):
        if not ctx.running:
            logger.warning("Force shutdown")
            sys.exit(1)

        logger.info(
            f"Received signal {signum}, shutting down worker {ctx.worker_id}..."
        )
        ctx.running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # 等待所有任务线程结束
    for thread in worker_threads:
        thread.join()

    # 在途任务结束后再标记 STOPPED，避免扫尸线程抢回收正在收尾的任务
    try:
        with managed_db_session() as db:
            worker = db.query(WorkerRegistry).filter_by(
                worker_id=ctx.worker_id
            ).first()
            if worker:
                worker.status = 'STOPPED'
                worker.stopped_at = datetime.utcnow()
                worker.current_task_count = 0
        logger.info("Worker marked as STOPPED in registry")
    except Exception as e:
        logger.error(f"Failed to mark worker as STOPPED: {e}")

    logger.info(f"Worker {ctx.worker_id} shut down gracefully")
