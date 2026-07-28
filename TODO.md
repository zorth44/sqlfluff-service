# SQLFluff Service 架构改进 TODO

按依赖与风险排序；一次只处理一个编号。

## 第一阶段：修复明确错误，建立测试基线

- [x] T00：建立真实 MySQL Worker 集成测试环境
- [x] T01：修复运行环境名称
- [x] T02：修复健康检查 HTTP 状态码
- [x] T03：修复手动重试接口

## 第二阶段：补齐可靠队列核心语义

- [x] T04：增加任务租约字段
- [x] T05：实现带租约的原子领取
- [x] T06：实现任务级租约续期
- [x] T07：为所有结果更新增加 fencing 校验
- [x] T08：重写僵尸任务回收逻辑

## 第三阶段：保证结果一致性

- [x] T09：将 violations 和 Task SUCCESS 放入同一事务
- [x] T10：结果文件版本化并避免覆盖

## 第四阶段：执行隔离与超时

- [x] T11：将 SQLFluff 分析从线程改为独立进程
- [x] T12：实现自动重试和指数退避

## 第五阶段：Job 生命周期可靠性

- [x] T13：将 ZIP/目录展开改成持久化任务
- [x] T14：修正 Job 状态聚合规则

## 第六阶段：监控和生产验证

- [x] T15：增加 DB Queue 指标
- [x] T16：调整数据库连接池
- [x] T17：修复 Worker 水平扩展部署配置
- [x] T18：执行故障与并发验收测试

## 验证命令

```bash
export NFS_SHARE_ROOT_PATH=/tmp/sqlfluff_nfs_test
export DATABASE_URL=sqlite:///./test.db
export ENVIRONMENT=test
pytest tests/worker tests/services tests/config tests/api/test_health.py -q

MYSQL_TEST_DATABASE_URL=mysql+pymysql://sqlfluff:sqlfluff@127.0.0.1:3307/sqlfluff_test \
  ./scripts/run_mysql_integration_tests.sh
```

## 迁移

```bash
alembic upgrade head   # 含 task_lease_001
```

注意：迁移期间新旧 Worker 不要混用；先升级 schema 再滚动发布 Worker。
