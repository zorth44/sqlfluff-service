#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQL质量检查报告生成器（CSV格式）

从SQLFluff服务API获取检查结果，生成CSV格式报告，便于团队协作追踪问题。
"""

import requests
import argparse
import sys
import csv
from datetime import datetime
import os


class CSVReportGenerator:
    """CSV报告生成器"""
    
    def __init__(self, base_url, timeout=30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        
    def get_task_ids(self, job_id):
        """获取Job下的所有Task IDs"""
        url = f"{self.base_url}/api/v1/jobs/tasks"
        params = {"job_id": job_id}
        
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return data.get("task_ids", [])
        except Exception as e:
            print(f"❌ 获取任务列表失败: {e}", file=sys.stderr)
            raise
    
    def get_task_detail(self, task_id):
        """获取Task的详细信息（用于获取元数据）"""
        url = f"{self.base_url}/api/v1/tasks"
        params = {"task_id": task_id}
        
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"⚠️  获取任务详情失败 {task_id}: {e}", file=sys.stderr)
            return None
    
    def get_task_lint_result(self, task_id):
        """获取Task的Lint结果（包含sql_line）"""
        url = f"{self.base_url}/api/v1/tasks/result/lint"
        params = {"task_id": task_id}
        
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            if response.status_code == 409:
                # 任务还在处理中或失败
                return None
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"⚠️  获取任务Lint结果失败 {task_id}: {e}", file=sys.stderr)
            return None
    
    def parse_task_data(self, task_id, task_detail, lint_result):
        """解析Task数据"""
        if not task_detail:
            return None
        
        source_file_path = task_detail.get("source_file_path", "")
        file_name = os.path.basename(source_file_path) if source_file_path else "unknown.sql"
        sql_lines = task_detail.get("sql_lines", 0)
        updated_at = task_detail.get("updated_at", "")
        
        # 格式化时间
        try:
            dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            formatted_time = updated_at
        
        violations = []
        if lint_result:
            violations = lint_result.get("violations", [])
        
        return {
            "task_id": task_id,
            "source_file_path": source_file_path,
            "file_name": file_name,
            "sql_lines": sql_lines,
            "updated_at": formatted_time,
            "violations": violations
        }
    
    def generate_csv_rows(self, all_tasks):
        """生成CSV行数据"""
        rows = []
        
        for task_data in all_tasks:
            source_file_path = task_data["source_file_path"]
            file_name = task_data["file_name"]
            sql_lines = task_data["sql_lines"]
            updated_at = task_data["updated_at"]
            violations = task_data["violations"]
            
            if violations:
                # 有问题：每个violation一行
                for violation in violations:
                    line_no = violation.get("line_no", "")
                    line_pos = violation.get("line_pos", "")
                    severity_level = violation.get("severity_level", "UNKNOWN")
                    code = violation.get("code", "")
                    rule = violation.get("rule", "")
                    description = violation.get("description", "")
                    sql_line = violation.get("sql_line", "")
                    
                    row = [
                        source_file_path,      # 文件路径
                        file_name,             # 文件名
                        sql_lines,             # 文件行数
                        line_no,               # 问题行号
                        line_pos,              # 问题列号
                        severity_level,        # 严重级别
                        code,                  # 规则代码
                        rule,                  # 规则名称
                        description,           # 问题描述
                        sql_line,              # SQL代码
                        updated_at,            # 检查时间
                        "",                    # 跟踪人（空白）
                        "待处理",              # 状态
                        ""                     # 备注（空白）
                    ]
                    rows.append(row)
            else:
                # 无问题：文件占一行
                row = [
                    source_file_path,      # 文件路径
                    file_name,             # 文件名
                    sql_lines,             # 文件行数
                    "-",                   # 问题行号
                    "-",                   # 问题列号
                    "-",                   # 严重级别
                    "-",                   # 规则代码
                    "-",                   # 规则名称
                    "无问题",              # 问题描述
                    "-",                   # SQL代码
                    updated_at,            # 检查时间
                    "",                    # 跟踪人（空白）
                    "无问题",              # 状态
                    ""                     # 备注（空白）
                ]
                rows.append(row)
        
        return rows
    
    def write_csv_file(self, rows, output_file, job_id):
        """写入CSV文件"""
        # CSV表头
        headers = [
            "文件路径",
            "文件名",
            "文件行数",
            "问题行号",
            "问题列号",
            "严重级别",
            "规则代码",
            "规则名称",
            "问题描述",
            "SQL代码",
            "检查时间",
            "跟踪人",
            "状态",
            "备注"
        ]
        
        with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            
            # 写入表头
            writer.writerow(headers)
            
            # 写入数据行
            writer.writerows(rows)
        
        print(f"\n✅ CSV报告已生成: {output_file}")
        print(f"   总行数: {len(rows)} 行（不含表头）")
    
    def generate_statistics(self, all_tasks):
        """生成统计信息"""
        total_files = len(all_tasks)
        files_with_issues = 0
        total_violations = 0
        severity_counts = {
            "BLOCKER": 0,
            "CRITICAL": 0,
            "MAJOR": 0,
            "MINOR": 0,
            "INFO": 0,
            "UNKNOWN": 0
        }
        
        for task_data in all_tasks:
            violations = task_data["violations"]
            if violations:
                files_with_issues += 1
                total_violations += len(violations)
                
                for violation in violations:
                    severity = violation.get("severity_level", "UNKNOWN").upper()
                    if severity in severity_counts:
                        severity_counts[severity] += 1
                    else:
                        severity_counts["UNKNOWN"] += 1
        
        return {
            "total_files": total_files,
            "files_with_issues": files_with_issues,
            "files_without_issues": total_files - files_with_issues,
            "total_violations": total_violations,
            "severity_counts": severity_counts,
            "critical_violations": severity_counts["BLOCKER"] + severity_counts["CRITICAL"]
        }
    
    def print_statistics(self, stats):
        """打印统计信息"""
        print(f"\n📊 统计摘要:")
        print(f"  • 总文件数: {stats['total_files']}")
        print(f"  • 有问题文件: {stats['files_with_issues']}")
        print(f"  • 无问题文件: {stats['files_without_issues']}")
        print(f"  • 总问题数: {stats['total_violations']}")
        print(f"  • 阻断问题: {stats['critical_violations']} (BLOCKER + CRITICAL)")
        print(f"\n  问题分布:")
        for severity, count in stats['severity_counts'].items():
            if count > 0:
                print(f"    - {severity}: {count}")
    
    def generate_report(self, job_id, output_file=None):
        """生成报告的主函数"""
        print(f"📊 开始生成CSV报告...")
        print(f"🆔 Job ID: {job_id}")
        
        # 1. 获取Task IDs
        print(f"\n📋 正在获取任务列表...")
        task_ids = self.get_task_ids(job_id)
        print(f"✓ 找到 {len(task_ids)} 个任务")
        
        if not task_ids:
            print("⚠️  没有找到任何任务")
            return
        
        # 2. 获取每个Task的详情和结果
        print(f"\n🔍 正在获取任务结果...")
        all_tasks = []
        success_count = 0
        
        for i, task_id in enumerate(task_ids, 1):
            print(f"  [{i}/{len(task_ids)}] {task_id}", end="")
            
            # 获取任务详情
            task_detail = self.get_task_detail(task_id)
            if not task_detail:
                print(" ❌ 获取详情失败")
                continue
            
            # 检查状态
            task_status = task_detail.get("status")
            if task_status != "SUCCESS":
                print(f" ⏭️  跳过 (状态: {task_status})")
                continue
            
            # 获取Lint结果（包含sql_line）
            lint_result = self.get_task_lint_result(task_id)
            if lint_result is None:
                print(" ❌ 获取Lint结果失败")
                continue
            
            # 解析数据
            task_data = self.parse_task_data(task_id, task_detail, lint_result)
            if task_data:
                all_tasks.append(task_data)
                success_count += 1
                
                violations_count = len(task_data["violations"])
                if violations_count > 0:
                    print(f" ✓ ({violations_count} 个问题)")
                else:
                    print(f" ✓ (无问题)")
            else:
                print(" ❌ 解析失败")
        
        print(f"\n✓ 成功获取 {success_count}/{len(task_ids)} 个任务的结果")
        
        if not all_tasks:
            print("⚠️  没有可用的任务数据")
            return
        
        # 3. 生成统计信息
        print(f"\n📊 正在计算统计信息...")
        statistics = self.generate_statistics(all_tasks)
        self.print_statistics(statistics)
        
        # 4. 生成CSV行数据
        print(f"\n📝 正在生成CSV数据...")
        csv_rows = self.generate_csv_rows(all_tasks)
        
        # 5. 写入CSV文件
        if not output_file:
            output_file = f"sql_report_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        self.write_csv_file(csv_rows, output_file, job_id)
        
        # 6. 输出使用提示
        print(f"\n💡 使用提示:")
        print(f"  1. 使用Excel/WPS打开 {output_file}")
        print(f"  2. 可以按「严重级别」列筛选，优先处理BLOCKER和CRITICAL")
        print(f"  3. 在「跟踪人」列填写负责人姓名")
        print(f"  4. 在「状态」列更新处理状态（待处理/进行中/已完成/已忽略）")
        print(f"  5. 在「备注」列记录修复说明或问题原因")


def main():
    parser = argparse.ArgumentParser(
        description="SQL质量检查报告生成器（CSV格式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 生成CSV报告到文件
  python generate_sql_report_csv.py --job-id job-abc123 --output report.csv
  
  # 使用自定义API地址
  python generate_sql_report_csv.py --job-id job-abc123 --api-url http://192.168.1.100:8000
  
  # 不指定输出文件（自动生成文件名）
  python generate_sql_report_csv.py --job-id job-abc123
        """
    )
    
    parser.add_argument(
        "--job-id",
        required=True,
        help="Job ID（必需）"
    )
    
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="API地址（默认: http://localhost:8000）"
    )
    
    parser.add_argument(
        "--output",
        help="输出文件路径（不指定则自动生成文件名）"
    )
    
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="API请求超时时间（秒，默认: 30）"
    )
    
    args = parser.parse_args()
    
    try:
        generator = CSVReportGenerator(args.api_url, args.timeout)
        generator.generate_report(args.job_id, args.output)
    except KeyboardInterrupt:
        print("\n\n⚠️  操作已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


