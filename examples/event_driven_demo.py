#!/usr/bin/env python3
"""
事件驱动架构演示脚本

演示如何使用新的事件驱动架构和动态规则配置功能。
注意：Python Worker只处理单文件事件，不涉及ZIP解压（那是Java服务的职责）。
"""

import json
import time
import redis
import uuid
import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Redis连接配置 - 从环境变量读取
def get_redis_url():
    """从环境变量构建Redis连接URL"""
    host = os.getenv('REDIS_HOST', 'localhost')
    port = os.getenv('REDIS_PORT', '6379')
    password = os.getenv('REDIS_PASSWORD')
    
    if password:
        return f"redis://:{password}@{host}:{port}/0"
    else:
        return f"redis://{host}:{port}/0"

REDIS_URL = get_redis_url()

class SqlCheckEventDemo:
    """SQL检查事件演示类"""
    
    def __init__(self, redis_url: str = REDIS_URL):
        print(f"🔗 连接Redis服务器: {redis_url.replace(':' + os.getenv('REDIS_PASSWORD', ''), ':***') if os.getenv('REDIS_PASSWORD') else redis_url}")
        try:
            self.redis_client = redis.Redis.from_url(redis_url)
            # 测试连接
            self.redis_client.ping()
            print("✅ Redis连接成功")
        except Exception as e:
            print(f"❌ Redis连接失败: {e}")
            raise
            
        self.demo_sql_content = """
-- 示例SQL查询
SELECT 
  user_id,
  user_name,
  email
FROM users 
WHERE status = 'active'
  AND created_at > '2024-01-01';
"""
    
    def create_sql_check_event(self,
                              job_id: str,
                              sql_file_path: str,
                              file_name: str,
                              dialect: str = "mysql",
                              user_id: str = "demo_user",
                              product_name: str = "Demo App",
                              rules: Optional[List[str]] = None,
                              exclude_rules: Optional[List[str]] = None,
                              config_overrides: Optional[Dict[str, Any]] = None,
                              batch_id: str = None,
                              file_index: int = None,
                              total_files: int = None) -> Dict[str, Any]:
        """创建SQL检查请求事件（统一单文件格式）"""
        
        payload = {
            "job_id": job_id,
            "sql_file_path": sql_file_path,
            "file_name": file_name,
            "dialect": dialect,
            "user_id": user_id,
            "product_name": product_name
        }
        
        # 添加动态规则配置
        if rules:
            payload["rules"] = rules
        if exclude_rules:
            payload["exclude_rules"] = exclude_rules
        if config_overrides:
            payload["config_overrides"] = config_overrides
            
        # 添加批量处理信息（仅当来自Java服务的ZIP解压时）
        if batch_id:
            payload["batch_id"] = batch_id
        if file_index is not None:
            payload["file_index"] = file_index
        if total_files is not None:
            payload["total_files"] = total_files
        
        event_data = {
            "event_id": str(uuid.uuid4()),
            "event_type": "SqlCheckRequested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(uuid.uuid4()),
            "payload": payload
        }
        
        return event_data
    
    def demo_single_sql_check(self):
        """演示单SQL检查（使用默认规则）"""
        print("\n=== 演示1: 单SQL文件检查（默认规则） ===")
        
        job_id = f"demo-single-{int(time.time())}"
        
        # 创建事件
        event = self.create_sql_check_event(
            job_id=job_id,
            sql_file_path="demo/single_query.sql",
            file_name="single_query.sql",
            dialect="mysql"
        )
        
        # 发布事件
        self.publish_event(event)
        print(f"✅ 已发布单SQL检查事件，Job ID: {job_id}")
    
    def demo_dynamic_rules_check(self):
        """演示动态规则配置"""
        print("\n=== 演示2: 动态规则配置 ===")
        
        job_id = f"demo-rules-{int(time.time())}"
        
        # 创建带有自定义规则的事件
        event = self.create_sql_check_event(
            job_id=job_id,
            sql_file_path="demo/rules_demo.sql",
            file_name="rules_demo.sql",
            dialect="mysql",
            rules=["L001", "L032", "LT01"],  # 只启用特定规则
            exclude_rules=["L016", "L034"],   # 排除某些规则
            config_overrides={
                "max_line_length": 120,
                "capitalisation_policy": "lower"
            }
        )
        
        # 发布事件
        self.publish_event(event)
        print(f"✅ 已发布动态规则检查事件，Job ID: {job_id}")
        print(f"   启用规则: {event['payload']['rules']}")
        print(f"   排除规则: {event['payload']['exclude_rules']}")
        print(f"   配置覆盖: {event['payload']['config_overrides']}")
    
    def demo_simulated_batch_from_java(self):
        """演示模拟来自Java服务的单文件事件（包含批量信息）"""
        print("\n=== 演示3: 模拟Java服务发送的单文件事件（含批量信息） ===")
        print("说明：Java服务解压ZIP后，会为每个SQL文件发送独立的单文件事件")
        
        job_id = f"demo-from-java-{int(time.time())}"
        batch_id = f"batch-{int(time.time())}"
        
        # 模拟Java服务已解压ZIP，现在使用demo目录下已存在的SQL文件发送3个独立事件
        sql_files = [
            {"file_name": "mysql_query.sql", "file_path": "demo/mysql_query.sql"},
            {"file_name": "postgres_query.sql", "file_path": "demo/postgres_query.sql"},
            {"file_name": "sqlite_query.sql", "file_path": "demo/sqlite_query.sql"}
        ]
        
        total_files = len(sql_files)
        
        for index, sql_file in enumerate(sql_files):
            event = self.create_sql_check_event(
                job_id=job_id,
                sql_file_path=sql_file["file_path"],
                file_name=sql_file["file_name"],
                dialect="mysql",  # 简化演示，统一使用mysql方言
                batch_id=batch_id,      # 批量标识，用于Java服务结果聚合
                file_index=index + 1,   # 文件索引
                total_files=total_files # 总文件数
            )
            
            # 发布事件
            self.publish_event(event)
            print(f"   📄 处理文件: {sql_file['file_name']} ({index + 1}/{total_files})")
        
        print(f"✅ 模拟完成，Job ID: {job_id}, Batch ID: {batch_id}")
        print(f"   📝 说明：Worker处理每个文件后会返回批量信息供Java服务聚合")
    
    def demo_different_dialects(self):
        """演示不同SQL方言"""
        print("\n=== 演示4: 不同SQL方言支持 ===")
        
        dialects = ["mysql", "postgres", "sqlite", "bigquery", "snowflake"]
        
        for dialect in dialects:
            job_id = f"demo-{dialect}-{int(time.time())}"
            
            event = self.create_sql_check_event(
                job_id=job_id,
                sql_file_path=f"demo/{dialect}_query.sql",
                file_name=f"{dialect}_query.sql",
                dialect=dialect
            )
            
            self.publish_event(event)
            print(f"   🗄️  已发布 {dialect.upper()} 方言检查事件，Job ID: {job_id}")
        
        print(f"✅ 已发布 {len(dialects)} 个不同方言的检查事件")
    
    def publish_event(self, event_data: Dict[str, Any]):
        """发布事件到Redis"""
        try:
            self.redis_client.publish(
                "sql_check_requests", 
                json.dumps(event_data)
            )
        except Exception as e:
            print(f"❌ 发布事件失败: {e}")
    
    def listen_results(self, timeout: int = 60):
        """监听处理结果事件"""
        print(f"\n=== 监听处理结果（{timeout}秒超时） ===")
        
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe("sql_check_events")
        
        start_time = time.time()
        
        try:
            for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        event_data = json.loads(message['data'])
                        event_type = event_data.get('event_type')
                        payload = event_data.get('payload', {})
                        
                        # 打印完整的JSON消息
                        print(f"\n📨 收到事件: {event_type}")
                        print("=" * 50)
                        print(json.dumps(event_data, ensure_ascii=False, indent=2))
                        print("=" * 50)
                        
                        if event_type == "SqlCheckCompleted":
                            job_id = payload.get('job_id')
                            file_name = payload.get('file_name', 'unknown')
                            duration = payload.get('processing_duration', 0)
                            violations = payload.get('result', {}).get('summary', {}).get('total_violations', 0)
                            
                            batch_info = ""
                            if payload.get('batch_id'):
                                batch_info = f" (批量: {payload.get('file_index')}/{payload.get('total_files')})"
                            
                            print(f"✅ 完成: {file_name}{batch_info} (Job: {job_id})")
                            print(f"   处理时间: {duration}秒, 违规数: {violations}")
                            
                        elif event_type == "SqlCheckFailed":
                            job_id = payload.get('job_id')
                            file_name = payload.get('file_name', 'unknown')
                            error_msg = payload.get('error', {}).get('error_message', 'Unknown error')
                            
                            batch_info = ""
                            if payload.get('batch_id'):
                                batch_info = f" (批量: {payload.get('file_index')}/{payload.get('total_files')})"
                            
                            print(f"❌ 失败: {file_name}{batch_info} (Job: {job_id})")
                            print(f"   错误: {error_msg}")
                            
                        # 检查超时
                        if time.time() - start_time > timeout:
                            print(f"\n⏰ 监听超时（{timeout}秒）")
                            break
                            
                    except Exception as e:
                        print(f"❌ 处理结果事件失败: {e}")
                        
        except KeyboardInterrupt:
            print("\n⏹️  监听被用户中断")
        finally:
            pubsub.unsubscribe("sql_check_events")
            pubsub.close()


def main():
    """主演示函数"""
    print("=" * 70)
    print("SQLFluff 事件驱动架构演示")
    print("=" * 70)
    print("📋 功能特性:")
    print("  • 完全事件驱动架构，无数据库依赖")
    print("  • 统一的单文件处理模式")
    print("  • 动态规则配置支持")
    print("  • 支持Java服务批量结果聚合")
    print("  • 多SQL方言支持")
    print("=" * 70)
    print("📝 架构说明:")
    print("  • Python Worker: 只处理单文件事件")
    print("  • Java服务: 负责ZIP解压、文件保存、结果聚合")
    print("  • 批量处理: Java解压→多个单文件事件→Worker并行处理")
    print("=" * 70)
    
    demo = SqlCheckEventDemo()
    
    # 运行各种演示
    demo.demo_single_sql_check()
    time.sleep(1)
    
    demo.demo_dynamic_rules_check()
    time.sleep(1)
    
    demo.demo_simulated_batch_from_java()
    time.sleep(1)
    
    demo.demo_different_dialects()
    
    # 监听结果
    demo.listen_results(timeout=30)
    
    print("\n" + "=" * 70)
    print("🎉 演示完成！")
    print("💡 要查看Worker处理日志，请运行: python -m app.worker_main")
    print("=" * 70)


if __name__ == "__main__":
    main() 