#!/usr/bin/env python3
"""
数据库初始化脚本

用于初始化数据库结构，创建表、索引等。
支持数据库的创建、升级和重置操作。
"""

import os
import sys
import logging
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config.settings import get_settings
from app.core.database import Base, engine, test_database_connection
from app.models.database import LintingJob, LintingTask

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_database_connection():
    """检查数据库连接"""
    logger.info("检查数据库连接...")
    if test_database_connection():
        logger.info("✅ 数据库连接正常")
        return True
    else:
        logger.error("❌ 数据库连接失败")
        return False


def create_database_if_not_exists():
    """创建数据库（如果不存在）"""
    settings = get_settings()
    db_url = settings.get_database_url()
    
    # 解析数据库URL获取数据库名
    try:
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        db_name = parsed.path.lstrip('/')
        
        # 创建连接到MySQL服务器的URL（不包含数据库名）
        server_url = f"{parsed.scheme}://{parsed.netloc}"
        
        logger.info(f"检查数据库 '{db_name}' 是否存在...")
        
        # 连接到MySQL服务器
        server_engine = create_engine(server_url, echo=False)
        
        with server_engine.connect() as conn:
            # 检查数据库是否存在
            result = conn.execute(
                text("SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = :db_name"),
                {"db_name": db_name}
            )
            
            if result.fetchone() is None:
                logger.info(f"数据库 '{db_name}' 不存在，正在创建...")
                conn.execute(text(f"CREATE DATABASE {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
                conn.commit()
                logger.info(f"✅ 数据库 '{db_name}' 创建成功")
            else:
                logger.info(f"✅ 数据库 '{db_name}' 已存在")
        
        server_engine.dispose()
        
    except Exception as e:
        logger.error(f"❌ 创建数据库失败: {e}")
        return False
    
    return True


def init_alembic():
    """初始化Alembic配置"""
    logger.info("初始化Alembic配置...")
    
    try:
        alembic_cfg = Config(str(project_root / "alembic.ini"))
        
        # 检查versions目录是否存在迁移文件
        versions_dir = project_root / "alembic" / "versions"
        migration_files = list(versions_dir.glob("*.py"))
        
        if not migration_files:
            logger.info("未找到迁移文件，创建初始迁移...")
            command.revision(
                alembic_cfg, 
                autogenerate=True, 
                message="Create initial tables"
            )
            logger.info("✅ 初始迁移文件创建成功")
        else:
            logger.info(f"✅ 找到 {len(migration_files)} 个迁移文件")
        
        return alembic_cfg
        
    except Exception as e:
        logger.error(f"❌ 初始化Alembic配置失败: {e}")
        return None


def run_migrations(alembic_cfg):
    """执行数据库迁移"""
    logger.info("执行数据库迁移...")
    
    try:
        # 升级到最新版本
        command.upgrade(alembic_cfg, "head")
        logger.info("✅ 数据库迁移完成")
        return True
        
    except Exception as e:
        logger.error(f"❌ 数据库迁移失败: {e}")
        return False


def verify_tables():
    """验证表是否正确创建"""
    logger.info("验证数据库表结构...")
    
    try:
        with engine.connect() as conn:
            # 检查表是否存在
            tables_to_check = ['linting_jobs', 'linting_tasks']
            
            for table_name in tables_to_check:
                result = conn.execute(
                    text("""
                        SELECT COUNT(*) 
                        FROM INFORMATION_SCHEMA.TABLES 
                        WHERE TABLE_SCHEMA = DATABASE() 
                        AND TABLE_NAME = :table_name
                    """),
                    {"table_name": table_name}
                )
                
                count = result.scalar()
                if count > 0:
                    logger.info(f"✅ 表 '{table_name}' 存在")
                else:
                    logger.error(f"❌ 表 '{table_name}' 不存在")
                    return False
            
            # 检查索引是否存在
            indexes_to_check = [
                ('linting_jobs', 'job_id'),
                ('linting_tasks', 'task_id'),
                ('linting_tasks', 'job_id')
            ]
            
            for table_name, index_column in indexes_to_check:
                result = conn.execute(
                    text("""
                        SELECT COUNT(*) 
                        FROM INFORMATION_SCHEMA.STATISTICS 
                        WHERE TABLE_SCHEMA = DATABASE() 
                        AND TABLE_NAME = :table_name 
                        AND COLUMN_NAME = :column_name
                    """),
                    {"table_name": table_name, "column_name": index_column}
                )
                
                count = result.scalar()
                if count > 0:
                    logger.info(f"✅ 索引 '{table_name}.{index_column}' 存在")
                else:
                    logger.warning(f"⚠️ 索引 '{table_name}.{index_column}' 不存在")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 验证表结构失败: {e}")
        return False


def create_test_data():
    """创建测试数据（可选）"""
    logger.info("是否创建测试数据? (y/N): ")
    
    try:
        response = input().strip().lower()
        if response in ['y', 'yes']:
            logger.info("创建测试数据...")
            
            from app.core.database import create_database_session
            from app.utils.uuid_utils import generate_job_id, generate_task_id
            
            session = create_database_session()
            
            try:
                # 创建测试Job
                test_job = LintingJob(
                    job_id=generate_job_id(),
                    status='COMPLETED',
                    submission_type='SINGLE_FILE',
                    source_path='test/sample.sql'
                )
                session.add(test_job)
                session.commit()
                
                # 创建测试Task
                test_task = LintingTask(
                    task_id=generate_task_id(),
                    job_id=test_job.job_id,
                    status='SUCCESS',
                    source_file_path='test/sample.sql',
                    result_file_path='test/results/sample.json'
                )
                session.add(test_task)
                session.commit()
                
                logger.info("✅ 测试数据创建成功")
                logger.info(f"测试Job ID: {test_job.job_id}")
                logger.info(f"测试Task ID: {test_task.task_id}")
                
            except Exception as e:
                session.rollback()
                logger.error(f"❌ 创建测试数据失败: {e}")
            finally:
                session.close()
        else:
            logger.info("跳过创建测试数据")
            
    except KeyboardInterrupt:
        logger.info("\n操作被用户取消")


def reset_database():
    """重置数据库（危险操作）"""
    logger.warning("⚠️ 这将删除所有数据并重新创建数据库结构!")
    logger.warning("确定要继续吗? 输入 'RESET' 确认: ")
    
    try:
        response = input().strip()
        if response == 'RESET':
            logger.info("重置数据库...")
            
            # 删除所有表
            Base.metadata.drop_all(bind=engine)
            logger.info("✅ 已删除所有表")
            
            # 重新创建表
            Base.metadata.create_all(bind=engine)
            logger.info("✅ 已重新创建表结构")
            
            # 重新运行Alembic标记
            alembic_cfg = Config(str(project_root / "alembic.ini"))
            command.stamp(alembic_cfg, "head")
            logger.info("✅ 已更新Alembic版本标记")
            
            return True
        else:
            logger.info("取消重置操作")
            return False
            
    except KeyboardInterrupt:
        logger.info("\n操作被用户取消")
        return False


def main():
    """主函数"""
    logger.info("🚀 开始初始化数据库...")
    
    # 先尝试创建数据库（如果不存在）
    if not create_database_if_not_exists():
        logger.error("❌ 数据库创建失败")
        return False
    
    # 然后检查数据库连接
    if not check_database_connection():
        logger.error("❌ 数据库连接失败，请检查配置")
        return False
    
    # 初始化Alembic
    alembic_cfg = init_alembic()
    if not alembic_cfg:
        logger.error("❌ Alembic初始化失败")
        return False
    
    # 执行迁移
    if not run_migrations(alembic_cfg):
        logger.error("❌ 数据库迁移失败")
        return False
    
    # 验证表结构
    if not verify_tables():
        logger.error("❌ 表结构验证失败")
        return False
    
    logger.info("🎉 数据库初始化完成!")
    
    # 询问是否创建测试数据
    create_test_data()
    
    return True


def show_help():
    """显示帮助信息"""
    print("""
数据库初始化脚本

用法:
    python scripts/init_db.py [选项]

选项:
    --help, -h      显示此帮助信息
    --reset         重置数据库（删除所有数据）
    --check         仅检查数据库连接
    --migrate       仅执行迁移
    --verify        仅验证表结构

示例:
    python scripts/init_db.py              # 完整初始化
    python scripts/init_db.py --check      # 检查连接
    python scripts/init_db.py --reset      # 重置数据库
    """)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            arg = sys.argv[1]
            
            if arg in ['--help', '-h']:
                show_help()
            elif arg == '--reset':
                if reset_database():
                    logger.info("✅ 数据库重置完成")
                else:
                    logger.error("❌ 数据库重置失败")
            elif arg == '--check':
                if check_database_connection():
                    logger.info("✅ 数据库连接正常")
                else:
                    logger.error("❌ 数据库连接失败")
            elif arg == '--migrate':
                alembic_cfg = Config(str(project_root / "alembic.ini"))
                if run_migrations(alembic_cfg):
                    logger.info("✅ 迁移完成")
                else:
                    logger.error("❌ 迁移失败")
            elif arg == '--verify':
                if verify_tables():
                    logger.info("✅ 表结构正常")
                else:
                    logger.error("❌ 表结构异常")
            else:
                logger.error(f"未知选项: {arg}")
                show_help()
        else:
            # 执行完整初始化
            success = main()
            if not success:
                sys.exit(1)
                
    except KeyboardInterrupt:
        logger.info("\n操作被用户取消")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 脚本执行失败: {e}")
        sys.exit(1) 