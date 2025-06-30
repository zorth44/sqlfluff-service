#!/usr/bin/env python3
"""
SQLFluff方言功能演示脚本

展示如何为不同的SQL方言创建Job并进行分析。
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sqlfluff_service import SQLFluffService
from app.schemas.job import JobCreateRequest
from app.core.logging import service_logger

# 不同方言的SQL示例
SQL_EXAMPLES = {
    "mysql": """
        SELECT u.id, u.name, COUNT(o.id) as order_count
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        WHERE u.status = 'active'
        GROUP BY u.id, u.name
        HAVING COUNT(o.id) > 0
        ORDER BY order_count DESC
        LIMIT 10;
    """,
    
    "postgres": """
        SELECT u.id, u.name, COUNT(o.id) as order_count
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        WHERE u.status = 'active'
        GROUP BY u.id, u.name
        HAVING COUNT(o.id) > 0
        ORDER BY order_count DESC
        LIMIT 10;
    """,
    
    "bigquery": """
        SELECT 
            u.id,
            u.name,
            COUNT(o.id) as order_count
        FROM `project.dataset.users` u
        LEFT JOIN `project.dataset.orders` o 
            ON u.id = o.user_id
        WHERE u.status = 'active'
        GROUP BY u.id, u.name
        HAVING COUNT(o.id) > 0
        ORDER BY order_count DESC
        LIMIT 10;
    """,
    
    "snowflake": """
        SELECT u.id, u.name, COUNT(o.id) as order_count
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        WHERE u.status = 'active'
        GROUP BY u.id, u.name
        HAVING COUNT(o.id) > 0
        ORDER BY order_count DESC
        LIMIT 10;
    """
}


async def demo_dialect_analysis():
    """演示不同方言的SQL分析"""
    print("=== SQLFluff方言功能演示 ===\n")
    
    # 初始化SQLFluff服务
    sqlfluff_service = SQLFluffService()
    
    # 显示支持的方言
    print("支持的方言列表:")
    dialects = sqlfluff_service.get_supported_dialects()
    for dialect in sorted(dialects)[:10]:  # 只显示前10个
        print(f"  - {dialect}")
    print(f"  ... 总共支持 {len(dialects)} 种方言\n")
    
    # 对每种方言进行分析
    for dialect, sql_content in SQL_EXAMPLES.items():
        print(f"--- 分析 {dialect.upper()} 方言 ---")
        print(f"SQL内容:\n{sql_content.strip()}\n")
        
        try:
            # 分析SQL内容
            result = sqlfluff_service.analyze_sql_content(
                sql_content=sql_content,
                file_name=f"demo_{dialect}.sql",
                dialect=dialect
            )
            
            # 显示分析结果
            summary = result.get('summary', {})
            print(f"分析结果:")
            print(f"  - 总违规数: {summary.get('total_violations', 0)}")
            print(f"  - 严重违规: {summary.get('critical_violations', 0)}")
            print(f"  - 警告违规: {summary.get('warning_violations', 0)}")
            print(f"  - 文件通过: {summary.get('file_passed', False)}")
            
            # 显示违规详情（如果有）
            violations = result.get('violations', [])
            if violations:
                print(f"  违规详情:")
                for violation in violations[:3]:  # 只显示前3个
                    print(f"    - 第{violation['line_no']}行: {violation['description']}")
                if len(violations) > 3:
                    print(f"    ... 还有 {len(violations) - 3} 个违规")
            
            # 显示分析元数据
            metadata = result.get('analysis_metadata', {})
            print(f"  分析元数据:")
            print(f"    - 使用方言: {metadata.get('dialect', 'unknown')}")
            print(f"    - 应用规则数: {metadata.get('rules_applied', 0)}")
            print(f"    - SQLFluff版本: {metadata.get('sqlfluff_version', 'unknown')}")
            
        except Exception as e:
            print(f"分析失败: {e}")
        
        print("\n" + "="*50 + "\n")


def demo_job_creation():
    """演示如何创建不同方言的Job请求"""
    print("=== Job创建请求示例 ===\n")
    
    # 创建不同方言的Job请求示例
    for dialect in ['mysql', 'postgres', 'bigquery']:
        print(f"--- {dialect.upper()} 方言Job请求 ---")
        
        # 创建Job请求
        job_request = JobCreateRequest(
            sql_content=SQL_EXAMPLES[dialect],
            dialect=dialect
        )
        
        print(f"请求数据:")
        print(f"  - 方言: {job_request.dialect}")
        print(f"  - SQL内容长度: {len(job_request.sql_content)} 字符")
        print(f"  - 提交类型: 单SQL文件")
        
        # 验证请求
        try:
            job_request.model_validate(job_request.model_dump())
            print(f"  - 请求验证: ✓ 通过")
        except Exception as e:
            print(f"  - 请求验证: ✗ 失败 - {e}")
        
        print()


def demo_config_validation():
    """演示配置验证功能"""
    print("=== 配置验证演示 ===\n")
    
    sqlfluff_service = SQLFluffService()
    
    # 测试不同方言的配置验证
    test_dialects = ['mysql', 'postgres', 'invalid_dialect', 'bigquery']
    
    for dialect in test_dialects:
        print(f"验证方言: {dialect}")
        try:
            result = sqlfluff_service.validate_config(dialect)
            print(f"  - 配置有效: {result['is_valid']}")
            print(f"  - 使用方言: {result['dialect']}")
            print(f"  - 启用规则数: {result['rules_enabled']}")
            
            if result.get('errors'):
                print(f"  - 错误信息: {result['errors']}")
        except Exception as e:
            print(f"  - 验证失败: {e}")
        print()


async def main():
    """主函数"""
    print("SQLFluff方言功能演示")
    print("="*50)
    
    # 演示直接SQL分析
    await demo_dialect_analysis()
    
    # 演示Job创建
    demo_job_creation()
    
    # 演示配置验证
    demo_config_validation()
    
    print("演示完成！")


if __name__ == "__main__":
    asyncio.run(main()) 