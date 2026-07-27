#!/usr/bin/env bash
# 运行 MySQL Worker 并发集成测试（T00 / T18）
#
# 前置:
#   1. MySQL 8 可访问（本地或 Docker）
#   2. 已创建测试库与用户
#
# 快速启动测试库:
#   docker run -d --name sqlfluff-test-mysql \
#     -e MYSQL_ROOT_PASSWORD=root \
#     -e MYSQL_DATABASE=sqlfluff_test \
#     -e MYSQL_USER=sqlfluff \
#     -e MYSQL_PASSWORD=sqlfluff \
#     -p 3307:3306 \
#     mysql:8.0 --default-authentication-plugin=mysql_native_password
#
# 用法:
#   ./scripts/run_mysql_integration_tests.sh
#   MYSQL_TEST_DATABASE_URL=mysql+pymysql://u:p@host:3306/db ./scripts/run_mysql_integration_tests.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

export NFS_SHARE_ROOT_PATH="${NFS_SHARE_ROOT_PATH:-/tmp/sqlfluff_nfs_test}"
export ENVIRONMENT="${ENVIRONMENT:-test}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///./test.db}"
export MYSQL_TEST_DATABASE_URL="${MYSQL_TEST_DATABASE_URL:-mysql+pymysql://sqlfluff:sqlfluff@127.0.0.1:3307/sqlfluff_test}"

mkdir -p "$NFS_SHARE_ROOT_PATH"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "MYSQL_TEST_DATABASE_URL=$MYSQL_TEST_DATABASE_URL"
echo "Running MySQL claim concurrency / lease fencing tests..."

python -m pytest \
  tests/worker/test_mysql_claim_concurrency.py \
  -v --tb=short \
  "$@"
