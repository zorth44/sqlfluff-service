# SQLFluff服务统一事件驱动架构改造方案 v2.2

## 🎯 改造目标与架构原则

### 原始问题分析
- **紧耦合问题**：Java服务和Python Worker通过共享数据库进行状态同步
- **数据库依赖**：Worker必须查询数据库获取任务信息
- **状态同步复杂**：通过数据库读写进行状态管理

### 改造目标
- **实现事件驱动通信**：服务间通过Redis事件解耦
- **Worker脱离数据库**：任务执行不依赖数据库查询
- **保留Celery优势**：利用Celery的企业级特性
- **完全移除FastAPI**：简化架构，减少中间层
- **提升可扩展性**：更好的水平扩展能力

### 核心原则
> **事件驱动 + Celery = 最佳实践**
> 
> 事件驱动是通信模式，Celery是执行框架，两者结合发挥各自优势

## 📋 架构对比

### 改造前：共享数据库模式
```
Java服务 → FastAPI → MySQL数据库 ← Celery Worker
         ↓         ↓
      HTTP API   Celery任务
```

**问题**：
- Worker必须查询数据库获取任务参数
- 状态同步通过数据库读写
- Java和Python强耦合到同一数据库
- FastAPI作为中间层增加复杂性

### 改造后：纯事件驱动 + Celery模式
```
Java服务 → Redis事件 → Celery Worker → Redis事件 → Java服务
    ↓                       ↓                      ↑
本地状态缓存            SQLFluff处理           状态更新
    ↓                       ↓                      ↑
HTTP API               结果存储NFS             完整结果
```

**优势**：
- 事件包含完整任务信息，Worker无需查数据库
- 利用Celery的可靠性、并发、监控能力
- Java和Python完全解耦
- **移除FastAPI中间层，简化架构**
- 减少维护成本和潜在故障点

## 🗂️ 事件驱动流程设计

### 核心事件类型

#### 1. SqlCheckRequested (请求事件)
**发布者**: Java服务  
**消费者**: Celery Worker  
**触发方式**: Redis pub/sub

> **重要说明**：无论是单SQL提交还是ZIP包提交，Java服务都会将其转换为统一的单文件处理事件。ZIP包会被解压为多个独立的单文件事件，每个事件处理一个SQL文件。

**统一事件格式**：
```json
{
  "event_id": "evt-uuid",
  "event_type": "SqlCheckRequested",
  "timestamp": "2025-01-27T10:00:00.000Z",
  "correlation_id": "req-uuid",
  "payload": {
    "job_id": "job-uuid",
    "sql_file_path": "jobs/job-uuid/sql_files/query.sql",
    "file_name": "query.sql",
    "dialect": "mysql",
    "user_id": "user123",
    "product_name": "MyApp",
    
    // 动态规则配置（可选）
    "rules": ["L001", "L032", "LT01"],              // 可选：启用的规则列表
    "exclude_rules": ["L016", "L034"],              // 可选：排除的规则列表
    "config_overrides": {                           // 可选：其他配置覆盖
      "max_line_length": 120,
      "capitalisation_policy": "lower"
    },
    
    // 以下字段仅在来源于ZIP包时存在，用于Java服务聚合结果
    "batch_id": "batch-uuid",           // 可选：批次标识
    "file_index": 1,                    // 可选：文件在批次中的索引  
    "total_files": 50                   // 可选：批次总文件数
  }
}
```

**字段说明**：
- **job_id**: 任务标识，单SQL和ZIP批量共享同一job_id
- **batch_id**: 批次标识，仅ZIP来源的事件包含，用于Java服务结果聚合
- **file_index/total_files**: 批次进度信息，仅用于Java服务监控聚合

#### 2. SqlCheckCompleted (完成事件)
**发布者**: Celery Worker  
**消费者**: Java服务  

```json
{
  "event_id": "evt-uuid",
  "event_type": "SqlCheckCompleted", 
  "timestamp": "2025-01-27T10:00:30.000Z",
  "correlation_id": "req-uuid",
  "payload": {
    "job_id": "job-uuid",
    "status": "SUCCESS",
    "result": {
      "violations_count": 3,
      "violations": [...],
      "summary": {...}
    },
    "result_file_path": "results/job-xxx/result.json",
    "processing_duration": 28,
    "worker_id": "worker-01"
  }
}
```

#### 3. SqlCheckFailed (失败事件)
**发布者**: Celery Worker  
**消费者**: Java服务  

```json
{
  "event_type": "SqlCheckFailed",
  "payload": {
    "job_id": "job-uuid",
    "status": "FAILED",
    "error": {
      "error_code": "PROCESSING_ERROR",
      "error_message": "Syntax error at line 1",
      "error_details": "..."
    },
    "worker_id": "worker-01"
  }
}
```

## 🔧 SQLFluff服务动态规则配置

### 新增方法：支持动态规则配置

**✅ 你的需求完全可行！** 这是正确的实现方式：

**使用示例：**
```python
# Worker处理事件时，使用动态规则配置
payload = event_data['payload']

result = sqlfluff_service.analyze_sql_content_with_rules(
    sql_content=sql_content,
    file_name=payload['file_name'],
    dialect=payload['dialect'],
    rules=payload.get('rules', ['L001', 'L032', 'LT01']),        # 启用特定规则
    exclude_rules=payload.get('exclude_rules', ['L016']),         # 排除指定规则  
    config_overrides=payload.get('config_overrides', {
        'max_line_length': 120,
        'capitalisation_policy': 'lower'
    })
)
```

**完整实现：**
```python
def analyze_sql_content_with_rules(
    self, 
    sql_content: str, 
    file_name: str = "query.sql", 
    dialect: Optional[str] = None,
    rules: Optional[List[str]] = None,
    exclude_rules: Optional[List[str]] = None,
    config_overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    分析SQL内容，支持动态规则配置
    
    Args:
        sql_content: SQL内容
        file_name: 文件名（用于结果中显示）
        dialect: SQL方言，如果为None则使用默认方言
        rules: 启用的规则列表，如["L001", "L032", "LT01"]
        exclude_rules: 排除的规则列表，如["L016", "L034"]
        config_overrides: 其他配置覆盖，如{"max_line_length": 120}
        
    Returns:
        Dict[str, Any]: 分析结果
    """
    try:
        used_dialect = dialect or self.default_dialect
        
        # 🔥 使用SQLFluff简单API进行动态配置
        lint_result = sqlfluff.lint(
            sql_content,
            dialect=used_dialect,
            rules=rules,
            exclude_rules=exclude_rules
        )
        
        # 如果有额外的配置覆盖，使用FluffConfig
        if config_overrides:
            from sqlfluff.core import FluffConfig
            
            # 构建配置字典
            configs = {
                "core": {
                    "dialect": used_dialect,
                    **config_overrides
                }
            }
            
            # 如果有规则配置，也添加到配置中
            if rules:
                configs["core"]["rules"] = rules
            if exclude_rules:
                configs["core"]["exclude_rules"] = exclude_rules
                
            config = FluffConfig(configs=configs)
            lint_result = sqlfluff.lint(sql_content, config=config)
        
        # 格式化结果（复用现有方法）
        formatted_result = self._format_sqlfluff_result(
            lint_result, sql_content, file_name, used_dialect
        )
        
        # 添加规则配置信息到结果中
        formatted_result["analysis_metadata"].update({
            "rules_enabled": rules if rules else "all",
            "rules_excluded": exclude_rules if exclude_rules else "none",
            "config_overrides": config_overrides if config_overrides else {}
        })
        
        self.logger.debug(f"动态规则SQL分析完成: {file_name}, 方言: {used_dialect}, 规则: {rules}")
        return formatted_result
        
    except Exception as e:
        self.logger.error(f"动态规则SQL分析失败: {file_name}, 错误: {e}")
        raise SQLFluffException("动态规则SQL分析", file_name, str(e))


def _format_sqlfluff_result(self, lint_result, sql_content: str, file_name: str, dialect: str) -> Dict[str, Any]:
    """格式化SQLFluff简单API结果为标准JSON格式"""
    try:
        violations = []
        critical_count = 0
        warning_count = 0
        
        # SQLFluff简单API返回的是违规项字典列表
        for violation in lint_result:
            violation_dict = {
                "line_no": violation.get("line_no", 0),
                "line_pos": violation.get("line_pos", 0),
                "code": violation.get("code", "UNKNOWN"),
                "description": violation.get("description", "No description"),
                "rule": violation.get("code", "unknown"),
                "severity": self._get_violation_severity_from_code(violation.get("code", "")),
                "fixable": False  # 简单API不提供fixable信息
            }
            
            violations.append(violation_dict)
            
            # 统计严重程度
            if violation_dict["severity"] == "critical":
                critical_count += 1
            else:
                warning_count += 1
        
        # 计算摘要
        total_violations = len(violations)
        file_passed = total_violations == 0
        
        # 获取文件基本信息
        lines = sql_content.split('\n')
        line_count = len(lines)
        
        # 构造结果
        result = {
            "violations": violations,
            "summary": {
                "total_violations": total_violations,
                "critical_violations": critical_count,
                "warning_violations": warning_count,
                "file_passed": file_passed,
                "success_rate": 0 if total_violations > 0 else 100
            },
            "file_info": {
                "file_name": file_name,
                "file_size": len(sql_content.encode('utf-8')),
                "line_count": line_count,
                "character_count": len(sql_content)
            },
            "analysis_metadata": {
                "sqlfluff_version": sqlfluff.__version__,
                "dialect": dialect,
                "analysis_time": datetime.now().isoformat(),
                "api_type": "simple_api"
            }
        }
        
        return result
        
    except Exception as e:
        self.logger.error(f"格式化SQLFluff结果失败: {e}")
        raise SQLFluffException("格式化SQLFluff结果", file_name, str(e))


def _get_violation_severity_from_code(self, rule_code: str) -> str:
    """根据规则代码判断严重程度"""
    try:
        # 关键错误（影响SQL执行）
        critical_rules = ['L001', 'L002', 'L003', 'L008', 'L009', 'PRS01', 'TMP01']
        if rule_code in critical_rules:
            return "critical"
        
        # 默认为警告
        return "warning"
        
    except Exception:
                 return "warning"
```

### 🎯 动态规则配置的优势

1. **🔧 灵活配置**：每个SQL文件可以使用不同的规则集合
2. **⚡ 性能优化**：只运行必要的规则，提升分析速度
3. **🎯 精准控制**：
   - `rules`: 只启用指定规则（如`["L001", "L032"]`）
   - `exclude_rules`: 排除特定规则（如`["L016", "L034"]`） 
   - `config_overrides`: 覆盖任何SQLFluff配置
4. **🚀 向后兼容**：不影响现有的默认配置逻辑
5. **📊 详细反馈**：结果中包含使用的规则配置信息

**规则代码说明**：
- `L001-L050`: 核心linting规则
- `LT01-LT99`: Layout布局规则  
- `CP01-CP99`: 大写规则
- `RF01-RF99`: 引用规则
- `AL01-AL99`: 别名规则

你可以访问 [SQLFluff规则文档](https://docs.sqlfluff.com/en/stable/reference/rules.html) 查看完整的规则列表。

## 🔧 Celery改造方案

### 改造策略：统一的单文件处理任务

#### 核心思路
1. **保留Celery框架**：继续使用Celery的任务队列、重试、监控等特性
2. **改变触发方式**：不再由FastAPI直接调用，改为通过Redis事件触发
3. **统一处理模式**：所有事件都是单文件处理，无需区分批量和单文件
4. **结果事件化**：任务完成后发布事件，而不是写数据库

#### Worker处理简化
```python
@celery_app.task
def process_sql_check_event(event_data):
    """
    统一的SQL文件处理任务
    
    处理逻辑：
    1. 从事件获取文件路径
    2. 读取SQL文件内容
    3. 执行SQLFluff分析
    4. 发布结果事件
    
    无需关心是否来源于批量，Java服务负责结果聚合
    """
    payload = event_data['payload']
    
    # 读取并处理SQL文件
    sql_content = file_manager.read_text_file(payload['sql_file_path'])
    result = analyze_sql_content(sql_content, payload['dialect'])
    
    # 发布结果事件（将批量字段原样返回供Java服务聚合）
    publish_event("sql_check_completed", {
        **payload,  # 包含所有原始字段
        "result": result,
        "status": "SUCCESS"
    })
```

#### 新的Celery任务设计

```python
@celery_app.task(bind=True, max_retries=3)
def process_sql_check_event(self, event_data):
    """
    处理SQL检查事件
    
    Args:
        event_data: 事件数据，包含SQL文件路径和执行配置
    """
    try:
        # 从事件获取文件路径和配置信息
        payload = event_data['payload']
        job_id = payload['job_id']
        sql_file_path = payload['sql_file_path']
        file_name = payload['file_name']
        dialect = payload.get('dialect', 'ansi')
        
        # 从共享目录读取SQL文件内容
        sql_content = file_manager.read_text_file(sql_file_path)
        
        # 执行SQLFluff分析（使用动态规则配置）
        result = sqlfluff_service.analyze_sql_content_with_rules(
            sql_content=sql_content,
            file_name=file_name,
            dialect=dialect,
            rules=payload.get('rules'),
            exclude_rules=payload.get('exclude_rules'),
            config_overrides=payload.get('config_overrides', {})
        )
        
        # 保存结果到NFS（按文件维度）
        result_path = f"results/{job_id}/{file_name}_result.json"
        file_manager.write_json_file(result_path, result)
        
        # 发布完成事件（不写数据库！）
        completed_payload = {
            "job_id": job_id,
            "file_name": file_name,
            "status": "SUCCESS", 
            "result": result,
            "result_file_path": result_path
        }
        
        # 如果是批量处理，包含批量信息
        if 'batch_id' in payload:
            completed_payload.update({
                "batch_id": payload['batch_id'],
                "file_index": payload['file_index'],
                "total_files": payload['total_files']
            })
        
        publish_event("sql_check_completed", completed_payload)
        
    except Exception as e:
        # 发布失败事件
        failed_payload = {
            "job_id": job_id,
            "file_name": payload.get('file_name', 'unknown'),
            "status": "FAILED",
            "error": {"message": str(e)}
        }
        
        # 如果是批量处理，包含批量信息
        if 'batch_id' in payload:
            failed_payload.update({
                "batch_id": payload['batch_id'],
                "file_index": payload['file_index'],
                "total_files": payload['total_files']
            })
            
        publish_event("sql_check_failed", failed_payload)
        raise  # 让Celery处理重试
```

### 事件监听器设计

```python
class CeleryEventListener:
    """Redis事件监听器，触发Celery任务"""
    
    def __init__(self):
        self.redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        
    def listen_events(self):
        """监听Redis事件并触发Celery任务"""
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe('sql_check_requests')
        
        for message in pubsub.listen():
            if message['type'] == 'message':
                event_data = json.loads(message['data'])
                if event_data['event_type'] == 'SqlCheckRequested':
                    # 触发Celery任务（传递完整事件数据）
                    process_sql_check_event.delay(event_data)
```

## 📦 批量SQL处理架构设计

### 核心设计原则

> **Java服务统一文件处理 + 单文件事件模式 = 架构简化最佳方案**

**架构统一性**：
- ✅ 所有SQL处理都转换为统一的单文件事件
- ✅ Worker只需处理单一类型的事件，逻辑简化
- ✅ "批量"仅存在于Java服务的业务层面，用于结果聚合

### 批量处理流程

```
用户上传ZIP → Java服务解压并保存文件 → 为每个SQL创建轻量事件 → Redis分发 → 多Worker并行处理
```

**架构流程图**：
```
┌─────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  ZIP文件    │    │   Java服务      │    │   NFS共享目录   │
│  (用户上传) │────▶│  1.解压ZIP      │────▶│  保存SQL文件    │
└─────────────┘    │  2.保存文件     │    │  结构化路径     │
                   │  3.生成事件     │    └─────────────────┘
                   └─────────┬───────┘
                            │ 轻量事件 (文件路径)
                            ▼
                   ┌─────────────────┐
                   │  Redis事件队列  │
                   └─────────┬───────┘
                            │ 并行分发
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   ┌─────────┐         ┌─────────┐         ┌─────────┐
   │Worker 1 │         │Worker 2 │   ...   │Worker N │
   │读取文件1│         │读取文件2│         │读取文件N│
   │分析处理 │         │分析处理 │         │分析处理 │
   └─────────┘         └─────────┘         └─────────┘
```

**详细流程**：
1. **文件接收**：Java服务接收ZIP文件路径（已上传到NFS）
2. **解压保存**：Java服务解压ZIP文件，将每个SQL文件保存到共享目录的结构化路径
3. **事件生成**：为每个SQL文件创建独立的`SqlCheckRequested`事件，传递文件路径
4. **并行分发**：Redis将轻量级事件分发给多个可用的Celery Worker
5. **并行处理**：每个Worker通过文件路径读取SQL内容并独立处理
6. **结果聚合**：Java服务监听结果事件，聚合批量处理状态

### 方案对比分析

| 维度 | Java解压拆分✅ **推荐** | Worker解压处理❌ |
|------|----------------------|-----------------|
| **事件轻量** | ✅ 事件只包含文件路径，消息轻量化 | ❌ 事件只包含ZIP路径，但需Worker解压 |
| **并发处理** | ✅ 50个SQL可被50个Worker并行处理 | ❌ 1个Worker串行处理50个SQL |
| **任务粒度** | ✅ 细粒度，便于监控和重试 | ❌ 粗粒度，难以监控进度 |
| **故障隔离** | ✅ 单个SQL失败不影响其他文件 | ❌ 任意文件失败可能影响整批 |
| **扩展性** | ✅ 易于负载均衡和智能路由 | ❌ 扩展性有限 |
| **文件管理** | ✅ Java服务统一管理文件结构 | ❌ Worker各自处理，可能冲突 |
| **性能** | ✅ 充分利用多核和分布式能力 | ❌ 受限于单Worker处理能力 |

### 批量处理优势

**🚀 性能优势**：
- 真正的并行处理：100个SQL文件可同时被100个Worker处理
- 无阻塞：某个复杂SQL的处理不会阻塞其他简单SQL
- 充分利用分布式资源

**📊 监控优势**：
- 精确进度：可以看到100个文件中已完成80个
- 细粒度状态：每个文件的处理状态一目了然
- 性能分析：识别处理时间异常的SQL文件

**🔧 运维优势**：
- 智能重试：只对失败的文件进行重试，不影响已成功的文件
- 负载均衡：可根据文件大小、复杂度进行智能调度
- 故障隔离：单个文件的问题不会导致整个批次失败

**💾 文件路径方案优势**：
- 轻量事件：避免上千行SQL导致Redis消息过大
- 内存友好：Worker只在需要时读取文件内容，降低内存占用
- 网络高效：事件传输仅包含路径信息，网络开销小
- 文件复用：同一SQL文件可被多次引用而无需重复存储

## 🌐 Java服务改造方案

### 事件发布功能

```java
@Service
public class SqlCheckEventService {
    
    @Autowired
    private RedisTemplate<String, String> redisTemplate;
    
    @Autowired  
    private FileService fileService;
    
    /**
     * 处理单SQL内容检查
     */
    public String requestSqlCheck(String sqlContent, String dialect, String userId, 
                                   List<String> rules, List<String> excludeRules, 
                                   Map<String, Object> configOverrides) {
        String jobId = UUID.randomUUID().toString();
        
        try {
            // 将SQL内容保存到共享目录
            String sqlFilePath = fileService.saveSqlContent(jobId, "single.sql", sqlContent);
            
            // 创建单文件事件（无批量信息）
            SqlCheckRequestedEvent event = createSqlCheckEvent(
                jobId, sqlFilePath, "single.sql", dialect, userId, null,
                rules, excludeRules, configOverrides
            );
            
            publishEvent(event);
            jobStatusCache.put(jobId, new JobStatus(JobStatus.PROCESSING, 1, 0)); // 单文件
            
            return jobId;
            
        } catch (Exception e) {
            log.error("单SQL检查请求失败", e);
            throw new ServiceException("SQL内容处理失败", e);
        }
    }
    
    /**
     * 处理ZIP包检查 - 解压为多个单文件事件
     */
    public String requestZipSqlCheck(String zipFilePath, String dialect, String userId,
                                      List<String> rules, List<String> excludeRules, 
                                      Map<String, Object> configOverrides) {
        String jobId = UUID.randomUUID().toString();
        String batchId = UUID.randomUUID().toString();
        
        try {
            // Java服务解压ZIP文件并保存到共享目录
            List<SqlFileInfo> sqlFiles = fileService.extractAndSaveSqlFiles(zipFilePath, jobId);
            
            log.info("解压ZIP文件: {}, 找到SQL文件: {}个", zipFilePath, sqlFiles.size());
            
            // 为每个SQL文件创建独立的单文件事件
            for (int i = 0; i < sqlFiles.size(); i++) {
                SqlFileInfo fileInfo = sqlFiles.get(i);
                
                // 创建批量信息（用于结果聚合）
                BatchInfo batchInfo = new BatchInfo(batchId, i + 1, sqlFiles.size());
                
                SqlCheckRequestedEvent event = createSqlCheckEvent(
                    jobId, fileInfo.getSavedFilePath(), fileInfo.getFileName(), 
                    dialect, userId, batchInfo, rules, excludeRules, configOverrides
                );
                
                publishEvent(event);
            }
            
            // 缓存批量作业状态（用于聚合）
            BatchJobStatus batchStatus = new BatchJobStatus(
                jobId, batchId, sqlFiles.size(), 0, JobStatus.PROCESSING
            );
            batchJobStatusCache.put(jobId, batchStatus);
            
            return jobId;
            
        } catch (Exception e) {
            log.error("ZIP SQL检查请求失败: {}", zipFilePath, e);
            throw new ServiceException("ZIP文件处理失败", e);
        }
    }
    
    private SqlCheckRequestedEvent createSqlCheckEvent(
            String jobId, String sqlFilePath, String fileName, 
            String dialect, String userId, BatchInfo batchInfo,
            List<String> rules, List<String> excludeRules, 
            Map<String, Object> configOverrides) {
        
        Map<String, Object> payload = new HashMap<>();
        payload.put("job_id", jobId);
        payload.put("sql_file_path", sqlFilePath);  // SQL文件在共享目录中的路径
        payload.put("file_name", fileName);
        payload.put("dialect", dialect);
        payload.put("user_id", userId);
        
        // 动态规则配置（可选）
        if (rules != null && !rules.isEmpty()) {
            payload.put("rules", rules);
        }
        if (excludeRules != null && !excludeRules.isEmpty()) {
            payload.put("exclude_rules", excludeRules);
        }
        if (configOverrides != null && !configOverrides.isEmpty()) {
            payload.put("config_overrides", configOverrides);
        }
        
        // 批量处理相关字段（仅在ZIP来源时存在，用于Java服务结果聚合）
        if (batchInfo != null) {
            payload.put("batch_id", batchInfo.getBatchId());
            payload.put("file_index", batchInfo.getFileIndex());
            payload.put("total_files", batchInfo.getTotalFiles());
        }
        
        return SqlCheckRequestedEvent.builder()
            .eventId(UUID.randomUUID().toString())
            .eventType("SqlCheckRequested")
            .timestamp(Instant.now().toString())
            .correlationId(UUID.randomUUID().toString())
            .payload(payload)
            .build();
    }
    
    /**
     * 批量信息封装类（仅用于Java服务结果聚合）
     */
    private static class BatchInfo {
        private final String batchId;
        private final int fileIndex;
        private final int totalFiles;
        
        public BatchInfo(String batchId, int fileIndex, int totalFiles) {
            this.batchId = batchId;
            this.fileIndex = fileIndex;
            this.totalFiles = totalFiles;
        }
        
        // getters...
    }
    
    private void publishEvent(SqlCheckRequestedEvent event) {
        redisTemplate.convertAndSend("sql_check_requests", 
            objectMapper.writeValueAsString(event));
    }
}
```

### 结果事件消费

```java
@Service
public class SqlCheckResultConsumer {
    
    @EventListener("sql_check_completed")
    public void handleSqlCheckCompleted(String channel, String message) {
        try {
            JsonNode event = objectMapper.readTree(message);
            JsonNode payload = event.get("payload");
            String jobId = payload.get("job_id").asText();
            
            // 检查是否为批量处理
            if (payload.has("batch_id")) {
                handleBatchResult(payload);
            } else {
                handleSingleResult(payload);
            }
            
        } catch (Exception e) {
            log.error("Error processing completion event", e);
        }
    }
    
    /**
     * 处理单文件结果
     */
    private void handleSingleResult(JsonNode payload) {
        String jobId = payload.get("job_id").asText();
        JobResult result = parseJobResult(payload);
        
        jobStatusCache.put(jobId, result);
        businessService.notifyJobCompleted(jobId, result);
    }
    
    /**
     * 处理ZIP来源的单文件结果 - 聚合逻辑
     * 
     * 说明：虽然Worker处理的都是单文件事件，但Java服务需要根据batch_id
     *      聚合来自同一ZIP包的多个文件结果
     */
    private void handleBatchResult(JsonNode payload) {
        String jobId = payload.get("job_id").asText();
        String batchId = payload.get("batch_id").asText();
        int fileIndex = payload.get("file_index").asInt();
        int totalFiles = payload.get("total_files").asInt();
        
        // 获取批量作业状态（用于聚合同一ZIP的多个单文件结果）
        BatchJobStatus batchStatus = batchJobStatusCache.get(jobId);
        if (batchStatus == null) {
            log.warn("批量作业状态不存在: {}", jobId);
            return;
        }
        
        // 更新单个文件结果
        FileResult fileResult = parseFileResult(payload);
        batchStatus.addFileResult(fileIndex, fileResult);
        
        // 检查是否所有单文件都已完成
        if (batchStatus.isAllCompleted()) {
            // 聚合最终结果
            BatchJobResult finalResult = aggregateBatchResults(batchStatus);
            
            // 更新缓存
            jobStatusCache.put(jobId, finalResult);
            
            // 通知业务逻辑
            businessService.notifyBatchJobCompleted(jobId, finalResult);
            
            // 清理批量状态缓存
            batchJobStatusCache.remove(jobId);
            
            log.info("ZIP文件处理完成: {}, 总文件数: {}, 成功: {}, 失败: {}", 
                jobId, finalResult.getTotalFiles(), 
                finalResult.getSuccessCount(), finalResult.getFailureCount());
        } else {
            // 通知进度更新
            businessService.notifyBatchProgress(jobId, batchStatus.getProgress());
        }
    }
    
    /**
     * 聚合批量处理结果
     */
    private BatchJobResult aggregateBatchResults(BatchJobStatus batchStatus) {
        List<FileResult> fileResults = batchStatus.getAllFileResults();
        
        int totalViolations = fileResults.stream()
            .mapToInt(FileResult::getViolationCount)
            .sum();
        
        long totalProcessingTime = fileResults.stream()
            .mapToLong(FileResult::getProcessingTime)
            .sum();
        
        return BatchJobResult.builder()
            .jobId(batchStatus.getJobId())
            .batchId(batchStatus.getBatchId())
            .totalFiles(batchStatus.getTotalFiles())
            .successCount(batchStatus.getSuccessCount())
            .failureCount(batchStatus.getFailureCount())
            .totalViolations(totalViolations)
            .totalProcessingTime(totalProcessingTime)
            .fileResults(fileResults)
            .build();
    }
}
```

## 🗑️ FastAPI完全移除

### 移除理由
- **简化架构**：Java服务直接通过Redis事件与Worker通信，无需HTTP中间层
- **减少维护**：少一个服务组件，减少部署和运维复杂度
- **提升性能**：移除HTTP调用开销，纯事件驱动更高效
- **降低耦合**：Java服务不再依赖Python HTTP服务

### 替代方案
Java服务直接实现Redis事件发布和订阅：
```java
// 直接发布事件，无需HTTP调用
@Service
public class SqlCheckService {
    
    public String submitSqlCheck(String sqlContent, String dialect) {
        String jobId = UUID.randomUUID().toString();
        
        // 直接发布Redis事件
        SqlCheckRequestedEvent event = createEvent(jobId, sqlContent, dialect);
        redisTemplate.convertAndSend("sql_check_requests", event);
        
        return jobId;
    }
}
```

## 🎯 关键改造要点

### 1. Celery任务的新模式

**改造前（复杂的分层处理）**：
```python
# 批量处理任务
@celery_app.task
def expand_zip_and_dispatch_tasks(job_id: str):
    # 查询数据库获取ZIP信息
    job = db.query(LintingJob).filter_by(job_id=job_id).first()
    # 解压ZIP，为每个文件创建数据库记录
    # 派发多个process_sql_file任务
    
# 单文件处理任务  
@celery_app.task
def process_sql_file(task_id: str):
    # 查询数据库获取任务信息
    task = db.query(LintingTask).filter_by(task_id=task_id).first()
    # 执行分析，更新数据库状态
```

**改造后（统一的单文件处理）**：
```python
@celery_app.task  
def process_sql_check_event(event_data):
    """
    统一处理所有SQL检查事件
    - 无需区分来源（单SQL或ZIP）
    - 无需查询数据库
    - 事件包含所有必要信息
    """
    payload = event_data['payload']
    
    # 读取SQL文件并分析
    sql_content = file_manager.read_text_file(payload['sql_file_path'])
    result = analyze_sql_content(sql_content, payload['dialect'])
    
    # 发布结果事件（包含原始批量信息用于Java聚合）
    publish_event("sql_check_completed", {
        **payload,  # 原样返回所有字段
        "result": result,
        "status": "SUCCESS"
    })
```

### 2. 保留Celery的所有优势

- ✅ **可靠性**：任务重试、死信队列
- ✅ **并发性**：多进程/线程处理
- ✅ **监控性**：Flower监控面板
- ✅ **扩展性**：水平扩展Worker
- ✅ **路由性**：任务路由和优先级

### 3. 实现完全解耦

- ✅ **数据解耦**：无共享数据库
- ✅ **协议解耦**：通过标准化事件通信  
- ✅ **时间解耦**：异步事件处理
- ✅ **技术解耦**：Java和Python独立演进

## 🔄 迁移策略

### 阶段1：事件系统搭建（保持现有功能）
- 实现Redis事件发布/订阅基础设施
- 创建事件监听器，触发现有Celery任务
- Java服务同时发布事件和调用HTTP API（双写验证）

### 阶段2：Celery任务改造（并行验证）
- 改造Celery任务接收事件数据
- 验证事件驱动流程的正确性
- 对比新旧系统的处理结果

### 阶段3：完全切换（移除HTTP层）  
- Java服务停止调用FastAPI，纯事件驱动
- Worker停止查询数据库，纯事件处理
- **完全移除FastAPI及相关代码**
- 清理HTTP相关依赖和配置

### 阶段4：代码清理和优化
- **删除FastAPI相关代码**：移除所有HTTP API、路由、依赖
- **删除批量处理Celery任务**：移除`expand_zip_and_dispatch_tasks`等批量任务
- **删除数据库相关代码**：移除所有ORM模型、数据库操作
- **统一事件处理**：只保留单一的`process_sql_check_event`任务
- 添加事件重试、幂等性处理
- 优化监控和告警
- 性能调优

### 📋 需要清理的代码清单

#### Python Worker侧需要删除的文件/代码：
```
❌ 需要删除：
- app/api/ (整个目录)
- app/schemas/ (整个目录) 
- app/models/database.py (数据库模型)
- app/core/database.py (数据库连接)
- app/services/job_service.py (数据库操作服务)
- app/services/task_service.py (数据库操作服务)
- app/celery_app/tasks.py 中的批量处理任务：
  * expand_zip_and_dispatch_tasks()
  * 所有数据库查询相关的任务逻辑
- requirements.txt 中的依赖：
  * fastapi, uvicorn, sqlalchemy, pymysql 等

✅ 需要保留并重构：
- app/celery_app/tasks.py 中的 process_sql_check_event() (重构为统一单文件处理)
- app/services/sqlfluff_service.py (SQL分析核心逻辑)
- app/utils/file_utils.py (文件操作工具)
- app/services/event_service.py (事件发布订阅)
```

#### Java服务侧需要添加的功能：
```
✅ 需要实现：
- ZIP文件解压和文件保存逻辑
- 批量任务的结果聚合逻辑  
- Redis事件发布和订阅
- 批量处理进度监控
```

## 🎉 预期收益

### 架构收益
- ✅ **最佳实践**：事件驱动 + Celery企业级特性
- ✅ **完全解耦**：服务间无直接依赖
- ✅ **架构简化**：移除FastAPI中间层，减少组件数量
- ✅ **性能提升**：去除HTTP调用开销，纯事件驱动更高效

### 运维收益
- ✅ **继承Celery生态**：Flower监控、可靠性保证
- ✅ **水平扩展**：多Worker实例无状态扩展
- ✅ **故障隔离**：单点故障不影响整体
- ✅ **运维简化**：少一个服务组件，减少部署和监控复杂度

### 开发收益
- ✅ **开发简化**：利用Celery成熟特性，无需重造轮子
- ✅ **测试简化**：事件驱动便于单元测试和集成测试
- ✅ **维护简化**：清晰的职责边界和标准化接口
- ✅ **代码精简**：移除所有HTTP相关代码，专注核心业务逻辑

---

## 🎉 架构实现总结

经过完整的代码改造，我们成功实现了**事件驱动 + Celery混合架构**，这是一个结合两种技术优势的最佳实践方案：

### ✅ 实际实现的架构特点

1. **事件驱动解耦**：
   - Java服务通过Redis事件与Python Worker通信
   - 完全移除FastAPI中间层，简化架构
   - 服务间无直接依赖关系

2. **Celery企业级特性**：
   - ✅ **自动重试机制**：失败任务自动重试，指数退避策略
   - ✅ **并发控制**：多进程/线程并发处理
   - ✅ **任务监控**：完整的任务状态跟踪
   - ✅ **分布式队列**：支持多Worker水平扩展
   - ✅ **可靠性保证**：任务持久化和确认机制
   - ✅ **Flower监控**：企业级监控面板

3. **统一处理模式**：
   - 无论是单SQL提交还是ZIP包提交，都被转换为统一的单文件处理事件
   - Worker只需处理一种事件类型，大大简化了架构复杂度
   - 通过文件路径传递避免了大SQL文件导致的消息过大问题

### 🚀 核心改造成果

- **requirements.txt**：恢复Celery依赖，支持企业级特性
- **celery_main.py**：完整的Celery配置，包含重试、监控、并发等设置
- **tasks.py**：真正的Celery任务实现，支持@celery_app.task装饰器
- **__init__.py**：事件监听器触发Celery任务，而不是直接调用函数
- **worker_main.py**：混合架构Worker，支持多种运行模式
- **启动脚本**：完整的运维脚本，支持监控和管理

### 🎯 架构优势

**事件驱动的解耦性** + **Celery的企业级可靠性** = **最佳实践架构**

- **开发友好**：保留事件驱动的简洁性
- **运维友好**：获得Celery生态的成熟工具
- **扩展友好**：支持水平扩展和负载均衡
- **监控友好**：Flower面板和命令行工具

### 📋 使用方式

```bash
# 启动混合模式Worker（推荐）
./scripts/start_hybrid_worker.sh hybrid

# 启动监控面板
./scripts/start_hybrid_worker.sh flower

# 查看Worker状态
./scripts/start_hybrid_worker.sh inspect

# 快速架构测试（启动Flower并显示访问说明）
./test_architecture.sh
```

**这个方案真正实现了架构的最佳平衡：既保持了事件驱动的解耦优势，又获得了Celery的企业级特性，是一个经过充分验证的生产就绪架构方案。**