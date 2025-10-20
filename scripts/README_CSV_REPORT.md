# SQL 质量检查报告生成器（CSV格式）使用说明

## 功能简介

`generate_sql_report_csv.py` 是一个用于从 SQLFluff 服务获取检查结果并生成 CSV 格式报告的工具脚本。CSV 格式便于在 Excel/WPS 中打开，方便团队协作追踪问题解决进度。

## 特性

### 📊 CSV 格式优势
- **易于筛选排序** - 可按严重级别、文件名、状态等筛选
- **便于协作追踪** - 支持分配跟踪人和更新状态
- **信息完整** - 包含问题定位、描述和SQL代码
- **兼容性好** - 兼容 Excel、WPS、Google Sheets 等

### 🎯 报告内容
每个问题包含以下信息：
- 文件路径和文件名
- 文件行数
- 问题的精确位置（行号、列号）
- 严重级别（BLOCKER/CRITICAL/MAJOR/MINOR/INFO）
- 规则代码和名称
- 问题描述
- 完整的SQL代码行
- 检查时间
- 跟踪人（空白，用于填写）
- 状态（默认"待处理"，可修改）
- 备注（空白，用于填写）

## 安装依赖

```bash
pip install requests
```

## 使用方法

### 基本用法

```bash
# 生成CSV报告
python scripts/generate_sql_report_csv.py \
    --job-id job-abc123-def456 \
    --output report.csv

# 查看帮助
python scripts/generate_sql_report_csv.py --help
```

### 完整参数

```bash
python scripts/generate_sql_report_csv.py \
    --job-id <JOB_ID>           # 必需：要查询的 Job ID
    --api-url <API_URL>         # 可选：API地址（默认 http://localhost:8000）
    --output <OUTPUT_FILE>      # 可选：输出文件路径（默认自动生成）
    --timeout <TIMEOUT>         # 可选：API超时时间（默认 30 秒）
```

### 使用示例

#### 1. 生成报告（自动生成文件名）

```bash
python scripts/generate_sql_report_csv.py \
    --job-id job-f4eacbfa-3e83-4bf4-a597-df328300615f

# 输出：sql_report_job-f4eacbfa-3e83-4bf4-a597-df328300615f_20251017_143025.csv
```

#### 2. 指定输出文件名

```bash
python scripts/generate_sql_report_csv.py \
    --job-id job-abc123 \
    --output reports/sql_check_report.csv
```

#### 3. 指定API地址

```bash
python scripts/generate_sql_report_csv.py \
    --job-id job-abc123 \
    --api-url http://127.0.0.1:18088 \
    --output report.csv
```

## CSV 报告格式

### 列定义

| 列名 | 说明 | 示例 |
|------|------|------|
| 文件路径 | 文件的完整路径 | jobs/job-abc/sources/query_users.sql |
| 文件名 | 文件名（从路径提取） | query_users.sql |
| 文件行数 | SQL文件总行数 | 25 |
| 问题行号 | 问题所在行号 | 8 |
| 问题列号 | 问题所在列号 | 10 |
| 严重级别 | BLOCKER/CRITICAL/MAJOR/MINOR/INFO | BLOCKER |
| 规则代码 | 规则代码 | RF02 |
| 规则名称 | 规则的完整名称 | references.qualification |
| 问题描述 | 问题的详细描述 | Unqualified reference found... |
| SQL代码 | 问题所在的完整SQL行 | SELECT product5.name, category... |
| 检查时间 | 任务完成时间 | 2025-10-17 14:28:10 |
| 跟踪人 | **空白，用于填写负责人** | 张三 |
| 状态 | 默认"待处理"，可修改 | 待处理/进行中/已完成/已忽略 |
| 备注 | **空白，用于记录说明** | 已修复并重新测试 |

### 输出示例

```csv
文件路径,文件名,文件行数,问题行号,问题列号,严重级别,规则代码,规则名称,问题描述,SQL代码,检查时间,跟踪人,状态,备注
jobs/job-abc/sources/query_users.sql,query_users.sql,25,8,10,BLOCKER,RF02,references.qualification,"Unqualified reference 'product5' found in select","SELECT product5.name, category.name FROM products...",2025-10-17 14:28:10,,"待处理",
jobs/job-abc/sources/query_users.sql,query_users.sql,25,12,5,MINOR,L010,capitalisation.keywords,Keywords must be consistently upper case.,select * from users where id = 1;,2025-10-17 14:28:10,,"待处理",
jobs/job-abc/sources/insert_data.sql,insert_data.sql,42,-,-,-,-,-,无问题,-,2025-10-17 14:28:15,,"无问题",
```

## 工作流程

```
1. 调用 /api/v1/jobs/tasks?job_id={job_id}
   ├─ 获取该 Job 下的所有 Task IDs
   └─ 示例返回：{"task_ids": ["task-xxx", "task-yyy", ...], "total_count": 15}

2. 遍历每个 Task ID：
   ├─ 调用 /api/v1/tasks?task_id={task_id}
   │  ├─ 获取任务元数据（状态、文件路径、行数等）
   │  └─ 检查状态是否为 SUCCESS
   │
   └─ 如果状态是 SUCCESS：
      └─ 调用 /api/v1/tasks/result/lint?task_id={task_id}
         └─ 获取带 sql_line 的 violations 列表

3. 数据整合：
   ├─ 有问题的文件：每个 violation 生成一行
   └─ 无问题的文件：生成一行，标记为"无问题"

4. 输出CSV文件（UTF-8 with BOM 编码，兼容Excel）

5. 显示统计摘要
```

## 使用 Excel/WPS 进行协作

### 1. 打开报告

使用 Excel 或 WPS 打开生成的 CSV 文件：
- 双击 CSV 文件自动用 Excel/WPS 打开
- 或在 Excel/WPS 中选择"文件 -> 打开"

### 2. 筛选和排序

**按严重级别筛选（优先处理阻断问题）：**
1. 点击"严重级别"列的筛选按钮
2. 选择 BLOCKER 和 CRITICAL
3. 查看并处理阻断性问题

**按文件名分组：**
1. 点击"文件名"列的筛选按钮
2. 选择特定文件
3. 集中处理该文件的所有问题

**按状态筛选：**
1. 点击"状态"列的筛选按钮
2. 选择"待处理"
3. 查看待办事项

### 3. 分配任务

在"跟踪人"列填写负责人姓名：
```
张三、李四、王五
```

### 4. 更新状态

在"状态"列更新处理进度：
- **待处理** - 尚未开始处理
- **进行中** - 正在修复
- **已完成** - 已修复并验证
- **已忽略** - 评估后决定不修复（需在备注中说明原因）

### 5. 添加备注

在"备注"列记录重要信息：
- 修复说明
- 问题原因分析
- 不修复的理由
- 相关讨论记录

### 6. 保存和共享

- **保存**: 直接保存为 Excel 格式（.xlsx）以保留格式
- **共享**: 通过邮件、共享文件夹、协作平台分享给团队

## 统计信息

脚本运行时会显示统计摘要：

```
📊 统计摘要:
  • 总文件数: 15
  • 有问题文件: 8
  • 无问题文件: 7
  • 总问题数: 48
  • 阻断问题: 8 (BLOCKER + CRITICAL)

  问题分布:
    - BLOCKER: 3
    - CRITICAL: 5
    - MAJOR: 12
    - MINOR: 20
    - INFO: 8
```

## 进度显示

脚本运行时会显示详细进度：

```
📊 开始生成CSV报告...
🆔 Job ID: job-abc123

📋 正在获取任务列表...
✓ 找到 15 个任务

🔍 正在获取任务结果...
  [1/15] task-xxx ✓ (3 个问题)
  [2/15] task-yyy ✓ (无问题)
  [3/15] task-zzz ⏭️  跳过 (状态: IN_PROGRESS)
  ...

✓ 成功获取 12/15 个任务的结果

📊 正在计算统计信息...
📝 正在生成CSV数据...

✅ CSV报告已生成: report.csv
   总行数: 48 行（不含表头）
```

## 常见使用场景

### 场景1：日常代码检查

```bash
# 每次代码检查后生成报告
python scripts/generate_sql_report_csv.py \
    --job-id job-20251017 \
    --output daily_reports/report_$(date +%Y%m%d).csv

# 在Excel中打开，快速查看问题
```

### 场景2：项目验收前批量检查

```bash
# 批量检查所有SQL文件
python scripts/generate_sql_report_csv.py \
    --job-id job-project-release \
    --output release_report.csv

# 分配给团队成员，逐个修复
# 统计"已完成"数量，确保全部修复后再发布
```

### 场景3：代码质量追踪

```bash
# 定期生成报告，对比问题数量变化
python scripts/generate_sql_report_csv.py \
    --job-id job-week01 \
    --output weekly_reports/week01.csv

python scripts/generate_sql_report_csv.py \
    --job-id job-week02 \
    --output weekly_reports/week02.csv

# 对比两次报告，查看改进情况
```

## Excel高级技巧

### 1. 条件格式（突出显示严重问题）

1. 选中"严重级别"列
2. 点击"开始 -> 条件格式 -> 新建规则"
3. 设置规则：
   - BLOCKER：红色背景
   - CRITICAL：橙红色背景
   - MAJOR：橙色背景
   - MINOR：黄色背景
   - INFO：蓝色背景

### 2. 数据透视表（统计分析）

1. 选中所有数据
2. 点击"插入 -> 数据透视表"
3. 设置：
   - 行：文件名
   - 列：严重级别
   - 值：计数
4. 查看每个文件的问题分布

### 3. 冻结窗格（便于滚动查看）

1. 选中第2行（数据行）
2. 点击"视图 -> 冻结窗格 -> 冻结首行"
3. 滚动时表头始终可见

### 4. 筛选器视图（多人协作）

1. 选中数据区域
2. 点击"数据 -> 筛选器"
3. 每个人可以使用自己的筛选条件，不影响他人

## 错误处理

脚本会自动处理以下情况：

- ✓ API 调用失败 - 显示错误信息并跳过
- ✓ 任务状态非 SUCCESS - 跳过并显示状态
- ✓ 超时 - 可通过 `--timeout` 参数调整
- ✓ 网络中断 - Ctrl+C 优雅退出

## 注意事项

1. **编码**: CSV 使用 UTF-8 with BOM 编码，确保 Excel 正确显示中文
2. **SQL代码**: 如果SQL代码中包含逗号或引号，会自动用引号包裹
3. **无问题文件**: 也会在报告中记录一行，避免遗漏
4. **并发限制**: 串行请求API，避免服务器压力过大

## 与 HTML 报告的区别

| 特性 | CSV报告 | HTML报告（已删除）|
|------|---------|----------|
| 格式 | 纯文本表格 | 网页格式 |
| 打开方式 | Excel/WPS | 浏览器 |
| 可编辑性 | ✅ 可直接编辑 | ❌ 只读 |
| 协作追踪 | ✅ 支持填写跟踪人和状态 | ❌ 不支持 |
| 美观度 | 中等 | 高 |
| 适用场景 | 团队协作、问题追踪 | 查看浏览、打印 |

## 技术细节

### API调用顺序

1. `GET /api/v1/jobs/tasks?job_id={job_id}` - 获取任务ID列表
2. `GET /api/v1/tasks?task_id={task_id}` - 获取任务元数据（循环）
3. `GET /api/v1/tasks/result/lint?task_id={task_id}` - 获取带sql_line的violations（循环）

### 为什么用 /lint 接口？

- `/api/v1/tasks/result` 接口：返回完整结果，但 violations 中**没有 sql_line 字段**
- `/api/v1/tasks/result/lint` 接口：专门返回 violations，**包含 sql_line 字段**

### 依赖说明

- **Python 3.6+** - 脚本运行环境（已移除类型注解，兼容旧版本）
- **requests** - HTTP 请求库
- **csv** - Python 标准库，无需安装

## 常见问题

### Q: 为什么有些任务被跳过？
A: 只有状态为 SUCCESS 的任务才会包含在报告中。处理中（IN_PROGRESS）、失败（FAILURE）或待处理（PENDING）的任务会被跳过。

### Q: Excel打开CSV文件乱码怎么办？
A: 脚本已使用 UTF-8 with BOM 编码，Excel应该能正确识别。如果仍有问题，尝试：
1. 右键 -> 打开方式 -> Excel
2. 或在Excel中选择"数据 -> 从文本/CSV" -> 选择UTF-8编码

### Q: 可以导入到数据库吗？
A: 可以！CSV格式可以轻松导入MySQL、PostgreSQL等数据库，方便进一步分析。

### Q: 如何批量生成多个Job的报告？
A: 可以编写简单的Shell脚本：
```bash
#!/bin/bash
for job_id in job-001 job-002 job-003; do
    python scripts/generate_sql_report_csv.py \
        --job-id $job_id \
        --output reports/${job_id}.csv
done
```

### Q: 报告太大，Excel打开很慢怎么办？
A: 
1. 使用Excel的"数据 -> 获取数据 -> 从文本/CSV"功能，按需加载
2. 使用Google Sheets或WPS云文档，性能更好
3. 考虑按严重级别或文件名拆分报告

## 维护与支持

这是一个临时工具脚本，用于快速生成CSV格式报告。如有问题或改进建议，请联系开发团队。

## 更新日志

- **2025-10-17**: 首次发布CSV格式报告生成器
  - 支持生成包含完整信息的CSV报告
  - 使用 `/api/v1/tasks/result/lint` 接口获取带sql_line的violations
  - 添加跟踪人、状态、备注等协作字段
  - 移除类型注解，兼容旧版本Python

---

**最后更新**: 2025-10-17


