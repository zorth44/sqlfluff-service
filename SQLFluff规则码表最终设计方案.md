# SQLFluff 规则码表管理方案 - 最终设计

## 1. 架构概述

### 1.1 调用流程
```
前端(product_name + dialect) 
    ↓
Java微服务接收product_name
    ↓
规则解析服务: product_name + dialect → rules[]
    ↓  
Java微服务调用Python服务(传入rules[])
    ↓
Python服务执行SQLFluff（零改动）
```

### 1.2 设计原则
- **职责清晰**: Java负责规则管理，Python专注执行
- **最小改动**: Python服务保持不变
- **向前兼容**: 支持直接传入rules[]的老方式
- **降级保障**: 规则解析失败时使用默认规则

## 2. 数据库表设计

### 2.1 规则定义表 (rule_definitions)

基于Excel字段重新设计：

```sql
CREATE TABLE rule_definitions (
    rule_code VARCHAR(50) PRIMARY KEY COMMENT '规则编号(放入rules[]的值)',
    rule_name VARCHAR(200) NOT NULL COMMENT '规则名称',
    rule_description TEXT COMMENT '规则描述', 
    applicable_tech_stack JSON NOT NULL COMMENT '适用技术栈["hive","gbase8a","ansi"]',
    source VARCHAR(50) DEFAULT 'sqlfluff' COMMENT '来源(开发规范/实施策略/生产总结)',
    verification_method VARCHAR(100) COMMENT '规则核验方式(语法检查/格式检查/约定检查)',
    statement_pattern VARCHAR(200) COMMENT '适用语句范式',
    severity_level ENUM('INFO', 'MINOR', 'MAJOR','BLOCKER','CRITICAL') DEFAULT 'INFO' COMMENT '规则分级：提示、次要、主要、阻断、严重',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

**字段说明**：
- `rule_code`: 对应Excel的"规则编号"，如"L001", "RF02"等，这是传递给Python服务接口的值
- `applicable_tech_stack`: JSON格式存储支持的方言列表，如["hive", "gbase8a"]
- `verification_method`: 规则核验方式，如"语法检查"、"格式检查"
- `statement_pattern`: 适用的SQL语句类型，如"SELECT", "INSERT", "DDL"

### 2.2 规则组表 (rule_groups)

支持系统默认规则组和产品自定义规则组：

```sql
CREATE TABLE rule_groups (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    group_name VARCHAR(100) NOT NULL COMMENT '规则组名称',
    group_type ENUM('SYSTEM_DEFAULT', 'PRODUCT_CUSTOM') NOT NULL COMMENT '规则组类型',
    dialect VARCHAR(50) NOT NULL COMMENT '方言名称',
    product_name VARCHAR(100) NULL COMMENT '产品名称(产品规则组时必填)',
    description TEXT COMMENT '规则组描述',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    created_by VARCHAR(100) COMMENT '创建人',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_group_name_type (group_name, group_type, dialect, product_name)
);
```

### 2.3 规则组明细表 (rule_group_items)

```sql  
CREATE TABLE rule_group_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    group_id BIGINT NOT NULL COMMENT '规则组ID',
    rule_code VARCHAR(50) NOT NULL COMMENT '规则编号',
    rule_name VARCHAR(200) NOT NULL COMMENT '规则名称(冗余字段，便于编辑)',
    severity_level ENUM('INFO', 'MINOR', 'MAJOR','BLOCKER','CRITICAL') DEFAULT 'INFO' COMMENT '规则分级：提示、次要、主要、阻断、严重',
    is_enabled BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    priority INT DEFAULT 0 COMMENT '优先级',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_group_id (group_id),
    UNIQUE KEY uk_group_rule (group_id, rule_code)
);
```

**关键设计**：
- `rule_groups`: 规则组表，支持系统默认组和产品自定义组
- `rule_group_items`: 规则组明细，包含冗余字段便于前端编辑
- **冗余字段**: `rule_name`和`severity_level`冗余存储，避免编辑时频繁关联查询
- **简化权限**: 产品管理员可直接编辑，暂不需要审核流程

## 3. 核心业务逻辑

### 3.1 规则解析算法

```java
public class RuleResolverService {
    
    /**
     * 解析产品最终规则列表
     */
    public List<String> resolveProductRules(String productName, String dialect) {
        try {
            // 1. 查找产品自定义规则组
            RuleGroup productGroup = ruleGroupRepository.findByProductNameAndDialect(productName, dialect);
            
            if (productGroup != null && productGroup.isActive()) {
                // 使用产品自定义规则组
                return getRuleCodesFromGroup(productGroup.getId());
            } else {
                // 使用系统默认规则组
                RuleGroup defaultGroup = ruleGroupRepository.findSystemDefaultByDialect(dialect);
                return getRuleCodesFromGroup(defaultGroup.getId());
            }
            
        } catch (Exception e) {
            log.warn("规则解析失败，使用Python默认规则: {}", e.getMessage());
            return Arrays.asList("default");
        }
    }
    
    /**
     * 从规则组获取启用的规则代码列表
     */
    private List<String> getRuleCodesFromGroup(Long groupId) {
        return ruleGroupItemRepository.findEnabledRuleCodesByGroupId(groupId);
    }
}
```

### 3.2 降级策略

```java
public List<String> resolveProductRules(String productName, String dialect) {
    try {
        // 正常解析逻辑
        return doResolveProductRules(productName, dialect);
    } catch (Exception e) {
        log.warn("规则解析失败，使用Python默认规则: {}", e.getMessage());
        // 降级策略：传递"default"让Python使用内置默认规则
        return Arrays.asList("default");
    }
}

// 也可以传递null，Python会自动使用默认规则
private List<String> fallbackToDefault() {
    return null; // Python服务会使用默认配置
}
```

## 4. API接口设计

### 4.1 规则管理API

```java
@RestController  
@RequestMapping("/api/rules")
public class RuleManagementController {
    
    // 1. 规则码表管理
    @GetMapping("/definitions")
    public List<RuleDefinition> getRuleDefinitions(@RequestParam(required = false) String dialect) {
        // 查看规则列表，支持方言过滤
    }
    
    @PostMapping("/definitions") 
    public RuleDefinition createRuleDefinition(@RequestBody RuleDefinitionRequest request) {
        // 创建新规则定义
    }
    
    @PutMapping("/definitions/{ruleCode}")
    public RuleDefinition updateRuleDefinition(@PathVariable String ruleCode, @RequestBody RuleDefinitionUpdateRequest request) {
        // 更新规则的是否启用和规则分级
    }
    
    @GetMapping("/definitions/{ruleCode}")
    public RuleDefinition getRuleDefinition(@PathVariable String ruleCode) {
        // 查看单个规则详情
    }
    
    // 2. 规则组管理
    @GetMapping("/groups")
    public List<RuleGroup> getRuleGroups(@RequestParam(required = false) String productName, @RequestParam(required = false) String dialect) {
        // 查看规则组列表
    }
    
    @PostMapping("/groups")
    public RuleGroup createRuleGroup(@RequestBody RuleGroupRequest request) {
        // 创建规则组
    }
    
    @GetMapping("/groups/{groupId}")
    public RuleGroupDetail getRuleGroupDetail(@PathVariable Long groupId) {
        // 查看规则组详情(包含规则明细)
    }
    
    @PutMapping("/groups/{groupId}")
    public void updateRuleGroup(@PathVariable Long groupId, @RequestBody RuleGroupUpdateRequest request) {
        // 更新规则组信息
    }
    
    @PostMapping("/groups/{groupId}/rules")
    public void addRulesToGroup(@PathVariable Long groupId, @RequestBody List<String> ruleCodes) {
        // 向规则组添加规则
    }
    
    @DeleteMapping("/groups/{groupId}/rules/{ruleCode}")
    public void removeRuleFromGroup(@PathVariable Long groupId, @PathVariable String ruleCode) {
        // 从规则组移除规则
    }
    
    @PutMapping("/groups/{groupId}/rules/{ruleCode}")
    public void updateGroupRule(@PathVariable Long groupId, @PathVariable String ruleCode, @RequestBody GroupRuleUpdateRequest request) {
        // 更新规则组中某个规则的启用状态
    }
    
    // 3. 规则解析服务(内部调用)
    @GetMapping("/resolve")
    public List<String> resolveRules(@RequestParam String productName, @RequestParam String dialect) {
        // 供内部调用的规则解析接口
    }
}
```

### 4.2 现有业务接口改造

```java
// 现有调用Python服务的地方需要增加规则解析
@Service
public class SqlFluffJobService {
    
    @Autowired
    private RuleResolverService ruleResolver;
    
    public void executeJob(String productName, String dialect, String sqlContent) {
        // 1. 解析产品规则，解析不到产品规则时，传递"default"或null给Python，利用其内置默认规则
        List<String> rules = ruleResolver.resolveProductRules(productName, dialect);
        if (rules.isEmpty()) {
            rules = Arrays.asList("default");
        }
        
        // 2. 调用Python服务(传入解析好的rules)
        pythonServiceClient.analyzeSql(sqlContent, dialect, rules);
    }
}
```

## 5. 实施计划

### 5.1 第一阶段：基础功能（3-4周）

#### Week 1-2: 数据层
- [ ] 创建3张数据表
- [ ] 编写基础CRUD Repository
- [ ] 导入规则码表基础数据
- [ ] 配置各方言默认规则组

#### Week 3: 业务逻辑
- [ ] 实现规则解析服务
- [ ] 实现降级策略
- [ ] 编写单元测试

#### Week 4: API集成
- [ ] 实现规则管理API
- [ ] 改造现有业务流程
- [ ] 集成测试

### 5.2 第二阶段：管理界面和优化（2-3周）

- [ ] 前端管理界面开发
- [ ] 规则组编辑功能
- [ ] 数据同步和一致性保障
- [ ] 性能优化和缓存策略

### 5.3 第三阶段：审核工作流（后续扩展）

- [ ] 产品申请创建规则组功能
- [ ] 审核工作流引入
- [ ] 权限细化管理

## 6. 关键设计决策

### 6.1 为什么选择这个方案？

1. **职责单一**: Java管规则，Python管执行，职责清晰
2. **改动最小**: Python服务完全不需要改动  
3. **数据完整**: 基于Excel字段设计，覆盖所有业务需求
4. **兼容性好**: 保持现有API调用方式不变
5. **可靠性高**: 多级降级保障服务可用性

### 6.2 调整后的设计亮点

1. **规则码表**: 严格按照Excel字段映射，便于数据导入
2. **规则组设计**: 支持系统默认组和产品自定义组，统一管理
3. **冗余字段**: 规则组明细表包含rule_name和severity_level，便于前端编辑
4. **无外键约束**: 按要求去掉外键，通过应用层保证数据一致性
5. **简化权限**: 去掉审核流程，产品管理员直接管理

### 6.3 业务逻辑亮点

1. **降级策略**: 传递"default"或null给Python，利用其内置默认规则
2. **规则组优先级**: 产品规则组优先于系统默认组
3. **API完整性**: 支持规则的查看、修改、规则组的完整生命周期管理

## 7. 总结

本方案通过在Java微服务中引入规则码表管理，实现了：

- **零改动集成**: Python服务无需任何修改，利用其内置默认规则机制
- **灵活规则组**: 支持系统默认规则组和产品自定义规则组  
- **便捷编辑**: 规则组明细包含冗余字段，前端编辑友好
- **权限简化**: 产品管理员直接编辑，去掉复杂审核流程
- **架构清晰**: 无外键约束，应用层保证数据一致性
- **API完整**: 支持规则查看/修改、规则组完整生命周期管理

该方案满足第一阶段的所有调整需求，简化了复杂度，提高了开发效率。