# SQLFluff方言配置功能

## 概述

SQLFluff服务现在支持为每个任务配置不同的SQL方言，允许您根据具体的数据库类型优化SQL分析规则。

## 新功能特性

### 1. 方言配置支持

- **Job级别方言配置**: 每个Job可以指定使用的SQL方言
- **动态Linter缓存**: 系统会缓存不同方言的SQLFluff Linter实例以提高性能
- **方言验证**: 在创建Job时会验证方言的有效性

### 2. 支持的方言

常见的支持方言包括：
- `mysql` - MySQL数据库
- `postgres` / `postgresql` - PostgreSQL数据库
- `sqlite` - SQLite数据库
- `bigquery` - Google BigQuery
- `snowflake` - Snowflake数据库
- `redshift` - Amazon Redshift
- `oracle` - Oracle数据库
- `tsql` - Microsoft SQL Server
- `ansi` - 标准SQL (默认)

## 使用示例

### 创建不同方言的Job

```python
from app.schemas.job import JobCreateRequest

# MySQL方言
request = JobCreateRequest(
    sql_content="SELECT * FROM users WHERE id = 1;",
    dialect="mysql"
)

# PostgreSQL方言
request = JobCreateRequest(
    sql_content="SELECT * FROM users WHERE id = 1;",
    dialect="postgres"
)
```

### 直接使用SQLFluffService

```python
from app.services.sqlfluff_service import SQLFluffService

service = SQLFluffService()

# 分析MySQL SQL
result = service.analyze_sql_content(
    sql_content="SELECT * FROM users WHERE id = 1",
    file_name="query.sql",
    dialect="mysql"
)
```

## 运行演示

```bash
python examples/dialect_demo.py
``` 