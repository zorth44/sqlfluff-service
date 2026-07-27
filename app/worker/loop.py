"""
Worker 主循环

实现 DB-as-Queue 的 Worker 核心逻辑（租约语义）：
- claim_task: 原子领取最高优先级 PENDING 任务（FOR UPDATE SKIP LOCKED）
- renew_lease: 处理期间续租
- reclaim_expired_leases: 回收过期租约
- WorkerThread: 循环 claim → process → 更新状态的线程
- HeartbeatThread: 定期向 worker_registry 写入心跳，标记 DEAD Worker
- LeaseSweepThread: 定期回收过期租约

每个 Worker 进程包含:
    concurrency 个 WorkerThread（执行实际任务）
    1 个 HeartbeatThread（发送心跳）
    1 个 LeaseSweepThread（回收过期租约）
"""

import os
import sys
import time
import socket
import signal
import uuid
import threading
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy import or_, func, select
from sqlalchemy.orm import Session

from app.core.db_session import managed_db_session
from app.models.database import LintingTask, LintingJob, WorkerRegistry
from app.schemas.common import TaskStatusEnum, JobStatusEnum
from app.worker.config import WorkerConfig
from app.worker.retry import compute_backoff_seconds
from app.worker.job_processor import try_expand_one_job

logger = logging.getLogger(__name__)


# ───────────────────── Worker Context ─────────────────────

class WorkerContext:
    """Worker 进程的共享上下文"""

    def __init__(self, config: WorkerConfig):
        self.config = config
        base_id = f"{socket.gethostname()}_{os.getpid()}"
        instance_id = os.environ.get("WORKER_INSTANCE_ID")
        if instance_id:
            self.worker_id = f"{base_id}_{instance_id[:8]}"
        else:
            self.worker_id = base_id
        self.running = True


# ───────────────────── Claim Result ─────────────────────

@dataclass(frozen=True)
class ClaimedTask:
    """不可变的已领取任务快照"""
    task_id: str
    job_id: str
    lease_token: str
    source_file_path: str


# ───────────────────── Task Claim / Lease ─────────────────────

def claim_task(
    db: Session,
    worker_id: str,
    lease_seconds: int,
) -> Optional[ClaimedTask]:
    """
    原子领取最高优先级 PENDING 任务

    使用 SELECT ... FOR UPDATE SKIP LOCKED 确保:
    - 多个 Worker 不会领取同一任务
    - 已被其他 Worker 锁定的任务自动跳过
    - 按 priority DESC + created_at ASC + id ASC 排序
    """
    claim_start = time.monotonic()
    # 过滤条件用数据库 NOW()；租约时间戳用同一会话内读取的 DB 时间，避免节点时钟漂移
    try:
        now = db.execute(select(func.now())).scalar()
    except Exception:
        now = datetime.utcnow()
    if now is None:
        now = datetime.utcnow()
    task = (
        db.query(LintingTask)
        .filter(
            LintingTask.status == TaskStatusEnum.PENDING,
            or_(
                LintingTask.next_attempt_at.is_(None),
                LintingTask.next_attempt_at <= func.now(),
            ),
        )
        .order_by(
            LintingTask.priority.desc(),
            LintingTask.created_at.asc(),
            LintingTask.id.asc(),
        )
        .with_for_update(skip_locked=True)
        .first()
    )

    if not task:
        return None

    lease_token = uuid.uuid4().hex
    task.status = TaskStatusEnum.IN_PROGRESS
    task.lease_token = lease_token
    task.lease_expires_at = now + timedelta(seconds=lease_seconds)
    task.attempt_count = (task.attempt_count or 0) + 1
    task.retry_count = task.attempt_count
    task.started_at = now
    task.claim_id = f"{worker_id}:{lease_token[:8]}"
    task.claimed_at = now
    task.error_message = None
    task.last_error = None

    job = db.query(LintingJob).filter(
        LintingJob.job_id == task.job_id
    ).first()
    if job and job.status in (JobStatusEnum.ACCEPTED, JobStatusEnum.EXPANDING):
        job.status = JobStatusEnum.PROCESSING

    logger.debug(f"Claimed task {task.task_id} for job {task.job_id}")

    try:
        from app.core.metrics import record_claim_duration
        record_claim_duration(time.monotonic() - claim_start)
    except ImportError:
        pass

    return ClaimedTask(
        task_id=task.task_id,
        job_id=task.job_id,
        lease_token=lease_token,
        source_file_path=task.source_file_path,
    )


def renew_lease(
    db: Session,
    task_id: str,
    lease_token: str,
    lease_seconds: int,
) -> bool:
    """
    续租：仅当 task 仍为 IN_PROGRESS 且 lease_token 匹配时更新 lease_expires_at。

    Returns:
        True 若成功续租（rowcount == 1）
    """
    now = db.execute(select(func.now())).scalar() or datetime.utcnow()
    updated = (
        db.query(LintingTask)
        .filter(
            LintingTask.task_id == task_id,
            LintingTask.status == TaskStatusEnum.IN_PROGRESS,
            LintingTask.lease_token == lease_token,
        )
        .update(
            {
                LintingTask.lease_expires_at: now + timedelta(seconds=lease_seconds),
            },
            synchronize_session=False,
        )
    )
    return updated == 1


def _clear_lease_fields(task: LintingTask) -> None:
    """清除租约与兼容 claim 字段"""
    task.lease_token = None
    task.lease_expires_at = None
    task.claim_id = None
    task.claimed_at = None


def reset_task_after_failure(
    task: LintingTask,
    max_retries: int,
    reason: str,
    config: WorkerConfig,
) -> str:
    """
    按重试策略重置或永久失败一个过期租约任务。

    Returns:
        'PENDING' | 'FAILURE' — 任务最终状态
    """
    now = datetime.utcnow()
    task.last_error = reason
    _clear_lease_fields(task)

    if (task.attempt_count or 0) > max_retries:
        task.status = TaskStatusEnum.FAILURE
        task.error_message = (
            f"超过最大重试次数（{max_retries}次），{reason}"
        )
        task.finished_at = now
        return TaskStatusEnum.FAILURE.value

    task.status = TaskStatusEnum.PENDING
    task.error_message = None
    task.next_attempt_at = now + timedelta(
        seconds=compute_backoff_seconds(task.attempt_count or 1, config)
    )
    return TaskStatusEnum.PENDING.value


def _update_job_status_after_reclaim(db: Session, job_id: str) -> None:
    """回收导致 FAILURE 时更新父 Job 状态"""
    from app.services.job_status import update_job_status_from_tasks

    update_job_status_from_tasks(db, job_id, lock=True)


def reclaim_expired_leases(db: Session, config: WorkerConfig) -> int:
    """
    回收过期租约。

    仅回收 status=IN_PROGRESS 且 lease_expires_at < now 的任务。
    不依据 Worker 心跳/状态回收。
    """
    now = db.execute(select(func.now())).scalar() or datetime.utcnow()
    reclaimed = 0
    affected_job_ids: set = set()

    candidates: List[LintingTask] = (
        db.query(LintingTask)
        .filter(
            LintingTask.status == TaskStatusEnum.IN_PROGRESS,
            LintingTask.lease_expires_at.isnot(None),
            LintingTask.lease_expires_at < func.now(),
        )
        .with_for_update(skip_locked=True)
        .all()
    )

    for task in candidates:
        reason = (
            f"租约过期（lease_expires_at={task.lease_expires_at}）"
        )
        new_status = reset_task_after_failure(
            task, config.max_retries, reason, config
        )
        reclaimed += 1
        try:
            from app.core.metrics import record_expired_lease, record_retry_task
            record_expired_lease()
            if new_status == TaskStatusEnum.PENDING.value:
                record_retry_task()
        except ImportError:
            pass
        if new_status == TaskStatusEnum.FAILURE.value:
            affected_job_ids.add(task.job_id)
        logger.warning(
            f"Reclaimed task {task.task_id} -> {new_status}: {reason}"
        )

    for job_id in affected_job_ids:
        _update_job_status_after_reclaim(db, job_id)

    if reclaimed:
        logger.info(f"Lease sweep: {reclaimed} expired tasks reclaimed")

    return reclaimed


def mark_stale_workers_dead(db: Session, config: WorkerConfig) -> int:
    """
    将心跳超时的 RUNNING Worker 标记为 DEAD（仅监控，不回收任务）。
    """
    now = datetime.utcnow()
    heartbeat_cutoff = now - timedelta(seconds=config.zombie_timeout)

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

    return len(stale_workers)


# ───────────────────── Lease Renewal Helper ─────────────────────

def _process_with_lease_renewal(ctx: WorkerContext, claimed: ClaimedTask) -> bool:
    """
    处理任务并在后台定期续租。

    Returns:
        True 若处理完成且租约仍有效；False 若续租失败应放弃写入
    """
    lease_lost = threading.Event()
    stop_renewal = threading.Event()

    def renew_loop():
        while not stop_renewal.wait(ctx.config.lease_renew_interval):
            if lease_lost.is_set():
                return
            try:
                with managed_db_session() as db:
                    ok = renew_lease(
                        db,
                        claimed.task_id,
                        claimed.lease_token,
                        ctx.config.task_lease_seconds,
                    )
                if not ok:
                    lease_lost.set()
                    logger.warning(
                        f"Lease renewal failed for task {claimed.task_id}, "
                        "abandoning processing"
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Lease renewal error for task {claimed.task_id}: {e}"
                )
                lease_lost.set()
                return

    renew_thread = threading.Thread(
        target=renew_loop, daemon=True, name=f"lease-renew-{claimed.task_id[:8]}"
    )
    renew_thread.start()

    try:
        if lease_lost.is_set():
            return False
        from app.worker.processor import process_task_safe
        task_start = time.monotonic()
        process_task_safe(
            claimed.task_id,
            ctx.worker_id,
            claimed.lease_token,
        )
        try:
            from app.core.metrics import record_task_duration
            record_task_duration(time.monotonic() - task_start)
        except ImportError:
            pass
        return not lease_lost.is_set()
    finally:
        stop_renewal.set()
        renew_thread.join(timeout=5)


# ───────────────────── Worker Thread (任务执行) ─────────────────────

class WorkerThread(threading.Thread):
    """
    Worker 线程：循环领取并处理任务

    每个线程独立运行 claim → process 循环：
    1. 从 DB 原子领取一个 PENDING 任务
    2. 续租并调用 process_task_safe 执行 SQLFluff 分析
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
                claimed: Optional[ClaimedTask] = None
                with managed_db_session() as db:
                    claimed = claim_task(
                        db,
                        self.ctx.worker_id,
                        self.ctx.config.task_lease_seconds,
                    )

                if claimed:
                    completed = _process_with_lease_renewal(self.ctx, claimed)
                    if completed:
                        self.tasks_processed += 1
                        logger.debug(
                            f"Thread {self.thread_id} completed task "
                            f"{claimed.task_id} "
                            f"(total: {self.tasks_processed})"
                        )
                    else:
                        try:
                            from app.core.metrics import record_lease_lost
                            record_lease_lost()
                        except ImportError:
                            pass
                else:
                    expanded = False
                    with managed_db_session() as db:
                        result = try_expand_one_job(db)
                        if result and result.get("status") == "success":
                            expanded = True
                            logger.debug(
                                f"Thread {self.thread_id} expanded job "
                                f"{result.get('job_id')}"
                            )
                    if not expanded:
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
    同时标记心跳超时的 RUNNING Worker 为 DEAD（仅监控）。
    """

    def __init__(self, ctx: WorkerContext):
        super().__init__(daemon=True, name="heartbeat-thread")
        self.ctx = ctx

    def run(self):
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
        """发送心跳并标记过期 Worker 为 DEAD"""
        with managed_db_session() as db:
            worker = db.query(WorkerRegistry).filter_by(
                worker_id=self.ctx.worker_id
            ).first()

            if worker and worker.status == 'RUNNING':
                worker.heartbeat_at = datetime.utcnow()

                active_count = db.query(LintingTask).filter(
                    LintingTask.claim_id.like(f"{self.ctx.worker_id}:%"),
                    LintingTask.status == TaskStatusEnum.IN_PROGRESS
                ).count()
                worker.current_task_count = active_count

            mark_stale_workers_dead(db, self.ctx.config)

            try:
                from app.core.metrics import collect_queue_gauges
                collect_queue_gauges(db)
            except ImportError:
                pass


# ───────────────────── Lease Sweep Thread ─────────────────────

class LeaseSweepThread(threading.Thread):
    """
    过期租约回收线程：定期回收 lease_expires_at 已过期的 IN_PROGRESS 任务
    """

    def __init__(self, ctx: WorkerContext):
        super().__init__(daemon=True, name="lease-sweep-thread")
        self.ctx = ctx

    def run(self):
        logger.info(
            f"Lease sweep thread started "
            f"(lease_seconds: {self.ctx.config.task_lease_seconds}s, "
            f"interval: {self.ctx.config.zombie_sweep_interval}s, "
            f"max_retries: {self.ctx.config.max_retries})"
        )

        while self.ctx.running:
            time.sleep(self.ctx.config.zombie_sweep_interval)
            try:
                with managed_db_session() as db:
                    count = reclaim_expired_leases(db, self.ctx.config)
                if count > 0:
                    logger.warning(f"Reclaimed {count} expired lease tasks")
            except Exception as e:
                logger.error(f"Lease sweep failed: {e}", exc_info=True)


# 兼容旧名称
ZombieSweepThread = LeaseSweepThread


# ───────────────────── Main Entry Point ─────────────────────

def start_worker(config: Optional[WorkerConfig] = None):
    """
    启动 DB-as-Queue Worker 进程

    1. 创建 WorkerContext（生成 worker_id）
    2. 启动 HeartbeatThread、LeaseSweepThread
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
        f"task_lease_seconds={config.task_lease_seconds}s, "
        f"lease_renew_interval={config.lease_renew_interval}s, "
        f"max_backoff_seconds={config.max_backoff_seconds}s, "
        f"max_retries={config.max_retries}"
    )

    heartbeat = HeartbeatThread(ctx)
    lease_sweeper = LeaseSweepThread(ctx)
    heartbeat.start()
    lease_sweeper.start()

    worker_threads = []
    for i in range(config.concurrency):
        thread = WorkerThread(ctx, i)
        thread.start()
        worker_threads.append(thread)

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

    for thread in worker_threads:
        thread.join()

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
