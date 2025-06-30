#!/usr/bin/env python3
"""
测试运行脚本
执行所有测试并生成报告
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def run_tests():
    """运行所有测试"""
    print("🧪 开始执行SQL核验服务测试套件")
    print("=" * 60)
    
    # 确保在项目根目录
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # 测试命令
    test_commands = [
        # 单元测试
        ["python", "-m", "pytest", "tests/services/", "-v", "--tb=short"],
        # API集成测试
        ["python", "-m", "pytest", "tests/api/", "-v", "--tb=short"],
        # Celery任务测试
        ["python", "-m", "pytest", "tests/celery_app/", "-v", "--tb=short"],
        # 覆盖率测试
        ["python", "-m", "pytest", "tests/", "--cov=app", "--cov-report=html", "--cov-report=term-missing"]
    ]
    
    results = []
    
    for i, cmd in enumerate(test_commands, 1):
        print(f"\n📋 执行测试 {i}/{len(test_commands)}: {' '.join(cmd)}")
        print("-" * 60)
        
        start_time = time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            end_time = time.time()
            
            print(f"✅ 测试完成 (耗时: {end_time - start_time:.2f}秒)")
            print(f"返回码: {result.returncode}")
            
            if result.stdout:
                print("输出:")
                print(result.stdout)
            
            if result.stderr:
                print("错误:")
                print(result.stderr)
            
            results.append({
                "command": cmd,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration": end_time - start_time
            })
            
        except subprocess.TimeoutExpired:
            print("❌ 测试超时")
            results.append({
                "command": cmd,
                "returncode": -1,
                "stdout": "",
                "stderr": "Timeout",
                "duration": 300
            })
        except Exception as e:
            print(f"❌ 测试执行失败: {e}")
            results.append({
                "command": cmd,
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "duration": 0
            })
    
    # 生成测试报告
    print("\n" + "=" * 60)
    print("📊 测试结果总结")
    print("=" * 60)
    
    total_tests = len(results)
    passed_tests = sum(1 for r in results if r["returncode"] == 0)
    failed_tests = total_tests - passed_tests
    
    print(f"总测试套件: {total_tests}")
    print(f"通过: {passed_tests} ✅")
    print(f"失败: {failed_tests} ❌")
    print(f"成功率: {(passed_tests/total_tests)*100:.1f}%")
    
    if failed_tests > 0:
        print("\n❌ 失败的测试:")
        for i, result in enumerate(results):
            if result["returncode"] != 0:
                print(f"  {i+1}. {' '.join(result['command'])}")
                if result["stderr"]:
                    print(f"     错误: {result['stderr'][:100]}...")
    
    # 检查覆盖率报告
    coverage_dir = project_root / "htmlcov"
    if coverage_dir.exists():
        print(f"\n📈 覆盖率报告已生成: {coverage_dir}")
        print("   打开 htmlcov/index.html 查看详细报告")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1) 