#!/bin/bash
# ============================================================
# ZIP 类型 Job 批量重跑脚本
#
# 用法:
#   ./scripts/rerun_zip_jobs.sh "2026-07-20 00:00:00"
#   ./scripts/rerun_zip_jobs.sh "2026-07-20 00:00:00" "2026-07-22 23:59:59"
#   ./scripts/rerun_zip_jobs.sh --dry-run "2026-07-20 00:00:00"
#
# 重要: 执行本脚本之前，请先在数据库工具中手动执行 SQL！
#   详见: docs/rerun_zip_jobs_sql.md
#
# 说明:
#   SQL 操作 (手动, 参考 docs/rerun_zip_jobs_sql.md):
#     a. 查询匹配的 Job
#     b. 清理 Violations
#     c. 清理 Tasks
#     d. 重置 PROCESSING -> ACCEPTED
#
#   本脚本 (自动):
#     -> 通过 ORM 查询 ACCEPTED 状态的 ZIP Job 并派发 Celery 任务
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ---- 参数解析 ----
DRY_RUN=false
START_TIME=""
END_TIME=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *)
            if [ -z "$START_TIME" ]; then
                START_TIME="$arg"
            elif [ -z "$END_TIME" ]; then
                END_TIME="$arg"
            fi
            ;;
    esac
done

if [ -z "$START_TIME" ]; then
    echo "用法: $0 [--dry-run] <开始时间> [结束时间]"
    echo "示例: $0 '2026-07-20 00:00:00'"
    echo "      $0 '2026-07-20 00:00:00' '2026-07-22 23:59:59'"
    echo ""
    echo "执行本脚本前，请先在数据库工具中手动执行 SQL:"
    echo "    docs/rerun_zip_jobs_sql.md"
    exit 1
fi

echo "============================================"
echo "ZIP Job 批量重跑 - Celery 派发"
echo "时间范围: $START_TIME ~ ${END_TIME:-现在}"
echo "模式: $( [ "$DRY_RUN" = true ] && echo 'DRY-RUN (预览)' || echo '执行' )"
echo "============================================"
echo ""
echo "请确认你已在数据库工具中手动执行了以下 SQL 操作:"
echo "    1. 清理 linting_violations"
echo "    2. 清理 linting_tasks"
echo "    3. 将 PROCESSING 状态的 Job 重置为 ACCEPTED"
echo "    详见: docs/rerun_zip_jobs_sql.md"
echo ""

if [ "$DRY_RUN" = false ]; then
    read -p "确认已完成上述 SQL 操作? (输入 yes 继续) " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "已取消"
        exit 0
    fi
fi

# ---- 切换到项目目录 ----
cd "$PROJECT_DIR"

# ---- 构建 Python 时间过滤条件 ----
PY_START="'$START_TIME'"
if [ -n "$END_TIME" ]; then
    PY_END="'$END_TIME'"
else
    PY_END="None"
fi

# ---- 派发 Celery 任务 ----
echo ""
echo "派发 Celery 任务..."

if [ "$DRY_RUN" = true ]; then
    python3 -c "
from app.core.database import SessionLocal
from app.models.database import LintingJob
from app.schemas.common import JobStatusEnum

db = SessionLocal()
query = db.query(LintingJob).filter(
    LintingJob.status == JobStatusEnum.ACCEPTED,
    LintingJob.submission_type == 'ZIP_ARCHIVE',
    LintingJob.created_at > $PY_START
)
end_time = $PY_END
if end_time is not None:
    query = query.filter(LintingJob.created_at <= end_time)

total = query.count()
jobs = query.order_by(LintingJob.created_at.desc()).limit(20).all()
print(f'Found {total} ACCEPTED ZIP jobs (showing first 20):')
for j in jobs:
    print(f'  {j.job_id} | {j.created_at}')
if total > 20:
    print(f'  ... {total} total')
print()
print('[DRY-RUN] Preview only. Remove --dry-run to execute.')
db.close()
"
else
    python3 -c "
from app.celery_app.tasks import expand_zip_and_dispatch_tasks
from app.core.database import SessionLocal
from app.models.database import LintingJob
from app.schemas.common import JobStatusEnum

db = SessionLocal()
query = db.query(LintingJob).filter(
    LintingJob.status == JobStatusEnum.ACCEPTED,
    LintingJob.submission_type == 'ZIP_ARCHIVE',
    LintingJob.created_at > $PY_START
)
end_time = $PY_END
if end_time is not None:
    query = query.filter(LintingJob.created_at <= end_time)

jobs = query.all()
print(f'Dispatching {len(jobs)} jobs')
for j in jobs:
    expand_zip_and_dispatch_tasks.delay(j.job_id)
    print(f'  OK {j.job_id}')
db.close()
"
fi

echo ""
echo "============================================"
echo "完成!"
echo "============================================"
