"""
T00 / T18: MySQL 真实并发领取与租约行为集成测试。

需要环境变量 MYSQL_TEST_DATABASE_URL，例如:
  mysql+pymysql://sqlfluff:sqlfluff@127.0.0.1:3307/sqlfluff_test

跳过条件: 未设置 MYSQL_TEST_DATABASE_URL 或无法连接。
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import List, Optional, Set

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.database import Base
import app.models.database  # noqa: F401 — register models
from app.models.database import LintingJob, LintingTask
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum, TaskStatusEnum
from app.worker.config import WorkerConfig
from app.worker.loop import (
    ClaimedTask,
    claim_task,
    reclaim_expired_leases,
    renew_lease,
)


MYSQL_URL = os.getenv("MYSQL_TEST_DATABASE_URL", "").strip()


def _mysql_available() -> bool:
    if not MYSQL_URL:
        return False
    try:
        engine = create_engine(MYSQL_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _mysql_available(),
    reason="MYSQL_TEST_DATABASE_URL not set or MySQL unreachable",
)


@pytest.fixture(scope="module")
def mysql_engine():
    engine = create_engine(
        MYSQL_URL,
        pool_pre_ping=True,
        poolclass=NullPool,
        isolation_level="READ_COMMITTED",
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def mysql_sessions(mysql_engine):
    """提供可创建多个独立 Session 的工厂（模拟多 Worker）。"""
    Session = sessionmaker(autocommit=False, autoflush=False, bind=mysql_engine)

    with mysql_engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in ("linting_violations", "linting_tasks", "linting_jobs", "worker_registry"):
            conn.execute(text(f"TRUNCATE TABLE `{table}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    sessions: List = []

    def factory():
        s = Session()
        sessions.append(s)
        return s

    yield factory

    for s in sessions:
        try:
            s.close()
        except Exception:
            pass


def _create_job(db, job_id: str) -> LintingJob:
    job = LintingJob(
        job_id=job_id,
        status=JobStatusEnum.ACCEPTED,
        submission_type=SubmissionTypeEnum.SINGLE_FILE,
        source_path=f"jobs/{job_id}/a.sql",
        dialect="ansi",
        user_id="u1",
        product_name="p1",
    )
    db.add(job)
    db.commit()
    return job


def _create_task(
    db,
    *,
    task_id: str,
    job_id: str,
    status=TaskStatusEnum.PENDING,
    priority: int = 0,
    next_attempt_at: Optional[datetime] = None,
    lease_token: Optional[str] = None,
    lease_expires_at: Optional[datetime] = None,
    attempt_count: int = 0,
) -> LintingTask:
    task = LintingTask(
        task_id=task_id,
        job_id=job_id,
        status=status,
        source_file_path=f"jobs/{job_id}/a.sql",
        priority=priority,
        next_attempt_at=next_attempt_at,  # None = 立即可领；测试勿用「刚好 now」避免秒级截断
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
        attempt_count=attempt_count,
    )
    db.add(task)
    db.commit()
    return task


class TestMysqlClaimConcurrency:
    def test_two_sessions_skip_locked_uncommitted_row(self, mysql_sessions):
        """事务未提交时，另一 Session 的 SKIP LOCKED 应跳过该行。"""
        db1 = mysql_sessions()
        db2 = mysql_sessions()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        _create_job(db1, job_id)
        _create_task(db1, task_id=task_id, job_id=job_id, priority=10)

        # Session1 锁定但故意不 commit
        claimed1 = claim_task(db1, "worker-a", lease_seconds=120)
        assert claimed1 is not None
        assert claimed1.task_id == task_id
        # 尚未 commit — 由调用方负责；这里模拟未提交
        # claim_task 本身不 commit，依赖 session 外部提交

        claimed2 = claim_task(db2, "worker-b", lease_seconds=120)
        assert claimed2 is None  # 唯一任务被锁定，应跳过

        db1.commit()  # 释放锁并提交领取

        # 再次领取应为空（已是 IN_PROGRESS）
        claimed3 = claim_task(db2, "worker-b", lease_seconds=120)
        assert claimed3 is None

    def test_two_workers_never_claim_same_task(self, mysql_sessions):
        db = mysql_sessions()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        _create_job(db, job_id)
        _create_task(db, task_id=f"task-{uuid.uuid4().hex[:8]}", job_id=job_id)

        results: List[Optional[ClaimedTask]] = [None, None]
        barrier = threading.Barrier(2)
        errors: List[BaseException] = []

        def worker(idx: int, worker_id: str):
            try:
                session = mysql_sessions()
                barrier.wait(timeout=5)
                claimed = claim_task(session, worker_id, lease_seconds=120)
                session.commit()
                results[idx] = claimed
            except BaseException as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=(0, "w1"))
        t2 = threading.Thread(target=worker, args=(1, "w2"))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors
        claimed_ids = [r.task_id for r in results if r is not None]
        assert len(claimed_ids) == 1
        assert len(set(claimed_ids)) == 1

    def test_concurrent_claimers_no_duplicates(self, mysql_sessions):
        """10～100 个并发领取者不会领取重复 Task。"""
        setup = mysql_sessions()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        _create_job(setup, job_id)

        n_tasks = 50
        n_claimers = 20
        for i in range(n_tasks):
            _create_task(
                setup,
                task_id=f"task-{i:03d}-{uuid.uuid4().hex[:6]}",
                job_id=job_id,
                priority=i % 5,
                next_attempt_at=None,
            )

        claimed: List[str] = []
        lock = threading.Lock()
        errors: List[BaseException] = []
        start = threading.Barrier(n_claimers)

        def claimer(worker_idx: int):
            session = None
            try:
                session = mysql_sessions()
                start.wait(timeout=15)
                while True:
                    result = claim_task(
                        session, f"worker-{worker_idx}", lease_seconds=120
                    )
                    if not result:
                        break
                    session.commit()
                    with lock:
                        claimed.append(result.task_id)
            except BaseException as e:
                errors.append(e)
            finally:
                if session is not None:
                    session.close()

        with ThreadPoolExecutor(max_workers=n_claimers) as pool:
            futures = [pool.submit(claimer, i) for i in range(n_claimers)]
            for f in as_completed(futures):
                f.result(timeout=60)

        assert not errors, f"claim errors: {errors[:5]}"
        assert len(claimed) == n_tasks, (
            f"claimed={len(claimed)} expected={n_tasks} unique={len(set(claimed))}"
        )
        assert len(set(claimed)) == n_tasks

        verify = mysql_sessions()
        rows = verify.query(LintingTask).filter(LintingTask.job_id == job_id).all()
        tokens = [t.lease_token for t in rows if t.lease_token]
        assert len(tokens) == n_tasks
        assert len(set(tokens)) == n_tasks
        assert all(t.status == TaskStatusEnum.IN_PROGRESS for t in rows)

    def test_next_attempt_at_gates_claim(self, mysql_sessions):
        db = mysql_sessions()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        _create_job(db, job_id)
        future = datetime.utcnow() + timedelta(hours=1)
        _create_task(
            db,
            task_id=f"task-{uuid.uuid4().hex[:8]}",
            job_id=job_id,
            next_attempt_at=future,
        )

        claimed = claim_task(db, "w1", lease_seconds=60)
        db.commit()
        assert claimed is None

    def test_priority_and_stable_id_order(self, mysql_sessions):
        db = mysql_sessions()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        _create_job(db, job_id)
        # 同优先级，先创建的 id 更小应先领取
        t_low = f"task-low-{uuid.uuid4().hex[:6]}"
        t_high = f"task-high-{uuid.uuid4().hex[:6]}"
        t_mid1 = f"task-mid-a-{uuid.uuid4().hex[:6]}"
        t_mid2 = f"task-mid-b-{uuid.uuid4().hex[:6]}"
        _create_task(db, task_id=t_low, job_id=job_id, priority=1)
        time.sleep(0.01)
        _create_task(db, task_id=t_mid1, job_id=job_id, priority=5)
        time.sleep(0.01)
        _create_task(db, task_id=t_mid2, job_id=job_id, priority=5)
        time.sleep(0.01)
        _create_task(db, task_id=t_high, job_id=job_id, priority=10)

        c1 = claim_task(db, "w1", lease_seconds=60)
        db.commit()
        c2 = claim_task(db, "w1", lease_seconds=60)
        db.commit()
        c3 = claim_task(db, "w1", lease_seconds=60)
        db.commit()

        assert c1.task_id == t_high
        assert c2.task_id == t_mid1
        assert c3.task_id == t_mid2

    def test_expired_lease_reclaim_and_no_double_attempt(self, mysql_sessions):
        """多扫描器并发回收不会重复增加 attempt_count。"""
        db = mysql_sessions()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        _create_job(db, job_id)
        _create_task(
            db,
            task_id=task_id,
            job_id=job_id,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token="old-lease",
            lease_expires_at=datetime.utcnow() - timedelta(seconds=10),
            attempt_count=1,
        )

        config = WorkerConfig(max_retries=3, max_backoff_seconds=60)
        barrier = threading.Barrier(2)
        counts: List[int] = []
        errors: List[BaseException] = []

        def sweeper():
            try:
                session = mysql_sessions()
                barrier.wait(timeout=5)
                n = reclaim_expired_leases(session, config)
                session.commit()
                counts.append(n)
            except BaseException as e:
                errors.append(e)

        t1 = threading.Thread(target=sweeper)
        t2 = threading.Thread(target=sweeper)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors
        assert sum(counts) == 1

        verify = mysql_sessions()
        task = verify.query(LintingTask).filter_by(task_id=task_id).one()
        assert task.status == TaskStatusEnum.PENDING
        assert task.attempt_count == 1  # reclaim 不增加 attempt；下次 claim 才 +1
        assert task.lease_token is None

    def test_renew_lease_fencing(self, mysql_sessions):
        db = mysql_sessions()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        token = uuid.uuid4().hex
        _create_job(db, job_id)
        _create_task(
            db,
            task_id=task_id,
            job_id=job_id,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token=token,
            lease_expires_at=datetime.utcnow() + timedelta(seconds=30),
            attempt_count=1,
        )

        assert renew_lease(db, task_id, token, lease_seconds=120) is True
        db.commit()

        assert renew_lease(db, task_id, "stale-token", lease_seconds=120) is False
        db.commit()

        task = db.query(LintingTask).filter_by(task_id=task_id).one()
        assert task.lease_token == token
        assert task.lease_expires_at is not None
        # 续租后过期时间应明显晚于「现在」
        assert task.lease_expires_at > datetime.utcnow() + timedelta(seconds=30)

    def test_explain_uses_lease_index(self, mysql_sessions):
        """用 EXPLAIN 验证领取查询能走 idx_task_lease_claim（或至少 key 非空）。"""
        db = mysql_sessions()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        _create_job(db, job_id)
        for i in range(20):
            _create_task(
                db,
                task_id=f"task-ex-{i}-{uuid.uuid4().hex[:4]}",
                job_id=job_id,
                priority=i,
            )

        sql = """
        EXPLAIN SELECT * FROM linting_tasks
        WHERE status = 'PENDING'
          AND (next_attempt_at IS NULL OR next_attempt_at <= NOW(6))
        ORDER BY priority DESC, created_at ASC, id ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """
        rows = db.execute(text(sql)).mappings().all()
        assert rows
        # 小数据量时优化器可能选全表扫描，但 possible_keys 应包含租约索引
        possible = set()
        for r in rows:
            pk = r.get("possible_keys") or ""
            for part in str(pk).split(","):
                if part:
                    possible.add(part)
        assert "idx_task_lease_claim" in possible, f"expected lease index in possible_keys, got {rows}"


class TestMysqlStaleWorkerFencing:
    def test_stale_success_update_rejected(self, mysql_sessions):
        """旧 lease_token 不能把任务改成 SUCCESS（fencing）。"""
        db = mysql_sessions()
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        current = uuid.uuid4().hex
        _create_job(db, job_id)
        job = db.query(LintingJob).filter_by(job_id=job_id).one()
        job.status = JobStatusEnum.PROCESSING
        db.commit()

        _create_task(
            db,
            task_id=task_id,
            job_id=job_id,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token=current,
            lease_expires_at=datetime.utcnow() + timedelta(seconds=120),
            attempt_count=2,
        )

        # 旧 worker 用过期 token 尝试 SUCCESS 更新
        stale_updated = (
            db.query(LintingTask)
            .filter(
                LintingTask.task_id == task_id,
                LintingTask.status == TaskStatusEnum.IN_PROGRESS,
                LintingTask.lease_token == "stale-old-token",
            )
            .update(
                {LintingTask.status: TaskStatusEnum.SUCCESS},
                synchronize_session=False,
            )
        )
        db.commit()
        assert stale_updated == 0

        # 当前持有者可以成功更新
        ok_updated = (
            db.query(LintingTask)
            .filter(
                LintingTask.task_id == task_id,
                LintingTask.status == TaskStatusEnum.IN_PROGRESS,
                LintingTask.lease_token == current,
            )
            .update(
                {
                    LintingTask.status: TaskStatusEnum.SUCCESS,
                    LintingTask.lease_token: None,
                    LintingTask.lease_expires_at: None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        assert ok_updated == 1

        task = db.query(LintingTask).filter_by(task_id=task_id).one()
        assert task.status == TaskStatusEnum.SUCCESS
        assert task.lease_token is None
