# API 增强功能总结

## 概述

本次增强为 SQLFluff 核验服务的 `/api/v1/jobs` 接口增加了以下功能：

1. **新增字段支持**：在创建核验工作时支持 `boc_batch_number` 和 `boc_task_number` 字段
2. **文件上传功能**：新增 `/api/v1/jobs/upload` 接口，支持直接上传 ZIP 文件而无需预先上传到 NFS

## 新增字段

### 数据库字段

在 `linting_jobs` 表中新增了以下字段：

- `boc_batch_number` (VARCHAR(255), 可选): BOC批次号
- `boc_task_number` (VARCHAR(255), 可选): BOC任务号

### API 字段

所有相关的 API 接口都已更新以支持这两个新字段：

- `JobCreateRequest` 
- `JobCreateWithUploadRequest`
- `JobSummary`
- `JobDetailResponse`

## 新增接口

### POST /api/v1/jobs/upload

**功能**: 创建新的核验工作并支持文件上传

**请求类型**: `multipart/form-data`

**请求参数**:
- `user_id` (required): 创建工作的用户ID
- `product_name` (required): 产品名称
- `dialect` (optional, default="ansi"): SQLFluff方言
- `boc_batch_number` (optional): BOC批次号
- `boc_task_number` (optional): BOC任务号
- `sql_content` (optional): 单段SQL内容（与zip_file二选一）
- `zip_file` (optional): ZIP文件（与sql_content二选一）

**响应**: 
```json
{
  "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e"
}
```

## 使用示例

### 1. 使用原有接口创建工作（带新字段）

```bash
curl -X POST "http://localhost:8000/api/v1/jobs" \
  -H "Content-Type: application/json" \
  -d '{
    "sql_content": "SELECT * FROM users WHERE id = 1;",
    "dialect": "mysql",
    "user_id": "user123",
    "product_name": "MyProduct",
    "boc_batch_number": "BATCH_2025_001",
    "boc_task_number": "TASK_001"
  }'
```

### 2. 使用新接口上传 ZIP 文件

```bash
curl -X POST "http://localhost:8000/api/v1/jobs/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "user_id=user123" \
  -F "product_name=MyProduct" \
  -F "dialect=mysql" \
  -F "boc_batch_number=BATCH_2025_001" \
  -F "boc_task_number=TASK_001" \
  -F "zip_file=@/path/to/your/sql_files.zip"
```

### 3. 使用新接口提交单个SQL

```bash
curl -X POST "http://localhost:8000/api/v1/jobs/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "user_id=user123" \
  -F "product_name=MyProduct" \
  -F "dialect=mysql" \
  -F "boc_batch_number=BATCH_2025_001" \
  -F "boc_task_number=TASK_001" \
  -F "sql_content=SELECT * FROM users WHERE id = 1;"
```

## 文件上传处理

### 文件保存路径

上传的文件会被保存到以下路径：
- 基础路径: `{NFS_SHARE_ROOT_PATH}/uploads/`
- 文件名格式: `{uuid}.zip`
- 完整路径示例: `/nfs/share/uploads/d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e.zip`

### 文件验证

上传的文件会进行以下验证：
- 文件扩展名必须是 `.zip`
- 文件大小不能超过 50MB
- 文件内容必须是有效的 ZIP 格式

## 数据库迁移

需要运行以下数据库迁移来添加新字段：

```bash
# 进入项目目录
cd /path/to/sqlfluff-service

# 运行数据库迁移
alembic upgrade head
```

## 兼容性说明

### 向后兼容性

- 原有的 `/api/v1/jobs` 接口完全兼容，现有的客户端无需修改
- 新增的 `boc_batch_number` 和 `boc_task_number` 字段为可选字段
- 所有现有的 API 响应都包含了新字段（值为 `null` 如果未设置）

### 字段验证

- `boc_batch_number` 和 `boc_task_number` 最大长度为 255 字符
- 空字符串和纯空白字符串会被转换为 `null`
- 字段验证错误会返回 400 Bad Request

## 错误处理

### 文件上传相关错误

- 400 Bad Request: 文件格式不正确或参数验证失败
- 500 Internal Server Error: 文件保存失败或系统错误

### 示例错误响应

```json
{
  "detail": "文件必须是ZIP格式"
}
```

```json
{
  "detail": "文件大小不能超过50MB"
}
```

## 注意事项

1. **文件大小限制**: 当前设置为 50MB，可根据需要调整
2. **文件存储**: 上传的文件存储在 NFS 共享目录中，确保该目录有足够的空间
3. **清理策略**: 可能需要实现定期清理旧文件的机制
4. **安全性**: 建议在生产环境中添加文件类型的深度验证

## 测试

所有新功能都已通过测试验证：
- 新字段的创建和验证
- 文件上传功能
- 数据库模型更新
- API 接口兼容性

完整的测试覆盖了以下场景：
- 使用新字段创建工作
- 文件上传和验证
- 字段验证和错误处理
- 数据库记录完整性 