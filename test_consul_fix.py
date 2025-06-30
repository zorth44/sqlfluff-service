#!/usr/bin/env python3
"""
测试SQLFluffService修复的脚本
"""

import os
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.sqlfluff_service import SQLFluffService
from app.utils.file_utils import FileManager
from app.config.settings import get_settings

def test_sqlfluff_service():
    """测试SQLFluffService的修复"""
    print("开始测试SQLFluffService...")
    
    # 获取配置
    settings = get_settings()
    print(f"NFS根目录: {settings.NFS_SHARE_ROOT_PATH}")
    
    # 初始化文件管理器
    file_manager = FileManager()
    print(f"文件管理器NFS根目录: {file_manager.nfs_root}")
    
    # 创建测试SQL文件
    test_sql_content = """
SELECT user_id, username, email 
FROM users 
WHERE status = 'active' 
ORDER BY created_at DESC 
LIMIT 10;
"""
    
    # 保存测试文件
    test_file_path = "test_sql_file.sql"
    file_manager.write_text_file(test_file_path, test_sql_content)
    print(f"创建测试文件: {test_file_path}")
    
    # 获取绝对路径
    abs_path = file_manager.get_absolute_path(test_file_path)
    print(f"绝对路径: {abs_path}")
    
    # 测试SQLFluffService
    sqlfluff_service = SQLFluffService()
    
    try:
        # 测试相对路径
        print("\n测试相对路径...")
        result1 = sqlfluff_service.analyze_sql_file(test_file_path)
        print(f"相对路径测试成功，违规数: {result1['summary']['total_violations']}")
        
        # 测试绝对路径
        print("\n测试绝对路径...")
        result2 = sqlfluff_service.analyze_sql_file(str(abs_path))
        print(f"绝对路径测试成功，违规数: {result2['summary']['total_violations']}")
        
        print("\n✅ 所有测试通过！")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 清理测试文件
        try:
            file_manager.delete_file(test_file_path)
            print(f"清理测试文件: {test_file_path}")
        except:
            pass

if __name__ == "__main__":
    test_sqlfluff_service() 