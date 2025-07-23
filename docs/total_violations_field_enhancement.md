# 添加total_violations字段到linting_tasks表

## 概述

本次更改在`linting_tasks`表中添加了`total_violations`字段，用于记录每个SQL文件的违规项总数。这个字段在SQL文件处理完成后会自动填充，提供了快速获取文件违规项数量的能力。

## 更改内容

### 1. 数据库迁移

**文件**: `alembic/versions/e35de558fc86_add_total_violations_to_linting_tasks.py`

```sql
ALTER TABLE linting_tasks 
ADD COLUMN total_violations INTEGER NULL 
COMMENT 'SQL文件违规项总数';
```

### 2. 数据库模型更新

**文件**: `app/models/database.py`

在`LintingTask`模型中添加了新字段：

```python
total_violations = Column(
    Integer,
    nullable=True,
    comment="SQL文件违规项总数"
)
```

### 3. Celery任务更新

**文件**: `app/celery_app/tasks.py`

在`process_sql_file`任务中，当SQL文件处理完成后，提取并记录违规项总数：

```python
# 提取违规项总数
total_violations = analysis_result.get("summary", {}).get("total_violations", 0)

# 更新任务状态为SUCCESS
task.status = TaskStatusEnum.SUCCESS
task.result_file_path = result_relative_path
task.total_violations = total_violations
db.commit()
```

### 4. API Schema更新

**文件**: `app/schemas/task.py`

在`TaskResponse`和`TaskDetailResponse`模型中添加了`total_violations`字段：

```python
total_violations: Optional[int] = Field(default=None, description="违规项总数")
```

### 5. 服务层更新

**文件**: `app/services/task_service.py`

更新了`TaskService`中的响应构造逻辑，确保API响应包含`total_violations`字段。

## 使用方式

### 1. 查看任务违规项总数

当调用任务相关的API时，响应会包含`total_violations`字段：

```json
{
  "task_id": "task-xxx",
  "status": "SUCCESS",
  "total_violations": 5,
  "sql_lines": 100,
  "created_at": "2025-07-18T15:40:00Z"
}
```

### 2. 数据库查询

可以直接查询数据库获取违规项总数：

```sql
SELECT task_id, total_violations, sql_lines 
FROM linting_tasks 
WHERE job_id = 'job-xxx' 
ORDER BY total_violations DESC;
```

## 特性

- **自动填充**: 在SQL文件处理完成后自动记录违规项总数
- **可为空**: 字段可以为NULL，兼容现有数据
- **API友好**: 通过API响应直接获取违规项数量，无需解析结果文件
- **查询优化**: 支持基于违规项数量的快速查询和排序

## 测试

已通过以下测试：
- 数据库字段正确添加
- 数据正确存储和检索
- API响应包含新字段
- 模型`to_dict`方法包含新字段

## 兼容性

- 现有数据：对于已存在的任务记录，`total_violations`字段为NULL
- 新数据：所有新处理的任务都会自动填充此字段
- API：现有API客户端会收到新字段，但不会影响现有功能

## 注意事项

- 只有成功处理的任务（状态为SUCCESS）才会有`total_violations`值
- 失败的任务此字段为NULL
- 字段值来源于SQLFluff分析结果中的`summary.total_violations` 