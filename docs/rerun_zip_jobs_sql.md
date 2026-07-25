# ZIP Job 手动恢复 SQL 操作指南

## 适用场景

- Python 程序（Celery Worker）宕机后，ZIP 类型的 Job 停留在 `PROCESSING` 或 `ACCEPTED` 状态，无法继续执行
- 需要手动清理残留数据并重置状态，然后通过脚本重新派发 Celery 任务

## 状态说明

| Job 状态 | 含义 | 出现原因 |
|----------|------|---------|
| `PROCESSING` | Worker 已取走任务但中途崩溃 | `expand_zip_and_dispatch_tasks` 执行到一半时 Worker 宕机 |
| `ACCEPTED` | Job 已创建但 `expand_zip_and_dispatch_tasks` 从未执行 | Celery 消息丢失、`zip_processing` 队列无 Worker、API 派发时 Redis 不可达 |

## 操作流程概览

```
1. 查询匹配的 Job  →  2. 清理 Violations  →  3. 清理 Tasks  →  4. 重置 Job 状态  →  5. 运行脚本派发
```

## ⚠️ 注意事项

- **以下所有 SQL 中的 `<START_TIME>` 和 `<END_TIME>` 需要替换为实际的时间值**
- 时间格式：`'YYYY-MM-DD HH:MM:SS'`，例如 `'2026-07-20 00:00:00'`
- **建议先在 SELECT 确认影响范围，再执行 DELETE/UPDATE**
- **建议在事务中执行，确认无误后再 COMMIT**
- 所有操作针对 `submission_type = 'ZIP_ARCHIVE'` 的 Job，不会影响其他类型

---

## 1. 查询匹配的 Job（诊断）

先查询有哪些 Job 需要处理，确认影响范围：

```sql
-- 查询 PROCESSING 和 ACCEPTED 状态的 ZIP Job 数量
SELECT COUNT(*) AS job_count
FROM linting_jobs j
WHERE j.status IN ('PROCESSING', 'ACCEPTED')
  AND j.submission_type = 'ZIP_ARCHIVE'
  AND j.created_at > '<START_TIME>'
  -- AND j.created_at <= '<END_TIME>'   -- 可选：指定结束时间
;

-- 查看具体 Job 详情（含关联的 Task 数量）
SELECT
    j.job_id,
    j.status,
    j.created_at,
    COUNT(t.task_id) AS task_count
FROM linting_jobs j
LEFT JOIN linting_tasks t ON j.job_id = t.job_id
WHERE j.status IN ('PROCESSING', 'ACCEPTED')
  AND j.submission_type = 'ZIP_ARCHIVE'
  AND j.created_at > '<START_TIME>'
  -- AND j.created_at <= '<END_TIME>'
GROUP BY j.job_id
ORDER BY j.created_at DESC
;
```

> 确认 `job_count` 和 Job 列表后，再继续执行下面的清理操作。

---

## 2. 清理 Violations

删除这些 Job 关联的所有 Violation 记录：

```sql
-- 先预览将被删除的 violations
SELECT COUNT(*) AS violation_count
FROM linting_violations v
INNER JOIN linting_tasks t ON v.task_id = t.task_id
INNER JOIN linting_jobs j ON t.job_id = j.job_id
WHERE j.status IN ('PROCESSING', 'ACCEPTED')
  AND j.submission_type = 'ZIP_ARCHIVE'
  AND j.created_at > '<START_TIME>'
  -- AND j.created_at <= '<END_TIME>'
;

-- 确认后执行删除
DELETE v
FROM linting_violations v
INNER JOIN linting_tasks t ON v.task_id = t.task_id
INNER JOIN linting_jobs j ON t.job_id = j.job_id
WHERE j.status IN ('PROCESSING', 'ACCEPTED')
  AND j.submission_type = 'ZIP_ARCHIVE'
  AND j.created_at > '<START_TIME>'
  -- AND j.created_at <= '<END_TIME>'
;
```

> **说明：** 对于 `ACCEPTED` 状态的 Job，通常没有关联的 violations（因为 `expand_zip_and_dispatch_tasks` 从未执行），此操作可能删除 0 行，属于正常情况。

---

## 3. 清理 Tasks

删除这些 Job 关联的所有 Task 记录：

```sql
-- 先预览将被删除的 tasks
SELECT COUNT(*) AS task_count
FROM linting_tasks t
INNER JOIN linting_jobs j ON t.job_id = j.job_id
WHERE j.status IN ('PROCESSING', 'ACCEPTED')
  AND j.submission_type = 'ZIP_ARCHIVE'
  AND j.created_at > '<START_TIME>'
  -- AND j.created_at <= '<END_TIME>'
;

-- 确认后执行删除
DELETE t
FROM linting_tasks t
INNER JOIN linting_jobs j ON t.job_id = j.job_id
WHERE j.status IN ('PROCESSING', 'ACCEPTED')
  AND j.submission_type = 'ZIP_ARCHIVE'
  AND j.created_at > '<START_TIME>'
  -- AND j.created_at <= '<END_TIME>'
;
```

> **说明：** `ACCEPTED` 状态的 Job 可能已有 Task 记录（`create_job` 阶段会预创建），也可能没有。无论哪种情况，清理后 `expand_zip_and_dispatch_tasks` 会重新创建。

---

## 4. 重置 Job 状态

将 `PROCESSING` 状态的 Job 重置为 `ACCEPTED`：

```sql
-- 先预览将被重置的 Job
SELECT job_id, status, created_at
FROM linting_jobs
WHERE status = 'PROCESSING'
  AND submission_type = 'ZIP_ARCHIVE'
  AND created_at > '<START_TIME>'
  -- AND created_at <= '<END_TIME>'
;

-- 确认后执行重置
UPDATE linting_jobs
SET status = 'ACCEPTED'
WHERE status = 'PROCESSING'
  AND submission_type = 'ZIP_ARCHIVE'
  AND created_at > '<START_TIME>'
  -- AND created_at <= '<END_TIME>'
;
```

> **说明：**
> - **只重置 `PROCESSING` 状态的 Job**，`ACCEPTED` 状态的 Job 无需修改
> - 重置后这些 Job 将在下一步被脚本统一派发

---

## 5. 运行脚本派发 Celery 任务

完成上述 SQL 操作后，运行脚本派发 `expand_zip_and_dispatch_tasks`：

```bash
# 预览（不实际派发）
./scripts/rerun_zip_jobs.sh --dry-run "2026-07-20 00:00:00"

# 正式执行
./scripts/rerun_zip_jobs.sh "2026-07-20 00:00:00"

# 指定时间范围
./scripts/rerun_zip_jobs.sh "2026-07-20 00:00:00" "2026-07-22 23:59:59"
```

---

## 完整 SQL 模板（可直接替换时间后执行）

将 `__START__` 和 `__END__` 替换为实际值后，按顺序执行：

```sql
-- ============================================================
-- 1. 清理 Violations
-- ============================================================
DELETE v
FROM linting_violations v
INNER JOIN linting_tasks t ON v.task_id = t.task_id
INNER JOIN linting_jobs j ON t.job_id = j.job_id
WHERE j.status IN ('PROCESSING', 'ACCEPTED')
  AND j.submission_type = 'ZIP_ARCHIVE'
  AND j.created_at > '__START__'
  AND j.created_at <= '__END__';

-- ============================================================
-- 2. 清理 Tasks
-- ============================================================
DELETE t
FROM linting_tasks t
INNER JOIN linting_jobs j ON t.job_id = j.job_id
WHERE j.status IN ('PROCESSING', 'ACCEPTED')
  AND j.submission_type = 'ZIP_ARCHIVE'
  AND j.created_at > '__START__'
  AND j.created_at <= '__END__';

-- ============================================================
-- 3. 重置 Job 状态
-- ============================================================
UPDATE linting_jobs
SET status = 'ACCEPTED'
WHERE status = 'PROCESSING'
  AND submission_type = 'ZIP_ARCHIVE'
  AND created_at > '__START__'
  AND created_at <= '__END__';

-- ============================================================
-- 4. 验证结果
-- ============================================================
SELECT status, COUNT(*) AS count
FROM linting_jobs
WHERE submission_type = 'ZIP_ARCHIVE'
  AND created_at > '__START__'
  AND created_at <= '__END__'
GROUP BY status;
```

---

## 常见问题

### Q: 为什么 Violations/Tasks 删除影响 0 行？

`ACCEPTED` 状态的 Job 可能没有关联的 Task 或 Violation（`expand_zip_and_dispatch_tasks` 从未执行），删除 0 行是正常的。只要 Job 状态能正确重置即可。

### Q: 执行顺序有要求吗？

有。必须先删除 Violations（它依赖 Task），再删除 Tasks（它依赖 Job），最后重置 Job。如果先删 Tasks，Violations 的 JOIN 会找不到对应的 Task，导致 Violations 删不干净。

### Q: 脚本派发后 Job 仍然卡在 ACCEPTED？

检查 Celery Worker 是否正常运行，特别是 `zip_processing` 队列是否有 Worker 在消费：

```bash
# 查看 Celery Worker 状态
celery -A app.celery_app.celery_main inspect active_queues
```
