#!/usr/bin/env python3
"""
历史数据迁移脚本（独立运行）

将历史Job的violations数据从JSON文件迁移到数据库表中。
这是一个独立的脚本，不依赖API或Celery，可以直接运行。

使用方法:
    # 迁移所有历史数据
    python scripts/migrate_violations_to_database.py --all
    
    # 迁移最近7天
    python scripts/migrate_violations_to_database.py --recent-days 7
    
    # 迁移指定时间范围
    python scripts/migrate_violations_to_database.py --start 2025-10-01 --end 2025-10-21
    
    # 强制刷新指定Job
    python scripts/migrate_violations_to_database.py --job-ids job-xxx job-yyy --force
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

# 添加项目路径到sys.path
# 脚本位于 ~/sqlfluff-service/scripts/
# 项目根目录是脚本的父目录
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

# 导入项目模块
from app.core.database import SessionLocal
from app.models.database import LintingJob, LintingTask, LintingViolation
from app.utils.file_utils import FileManager
from app.schemas.common import JobStatusEnum, TaskStatusEnum


class ViolationsMigrator:
    """Violations数据迁移器"""
    
    def __init__(self):
        self.db = SessionLocal()
        self.file_manager = FileManager()
        self.stats = {
            'total_jobs': 0,
            'success_jobs': 0,
            'failed_jobs': 0,
            'skipped_jobs': 0,
            'total_violations': 0,
            'errors': []
        }
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()
    
    def migrate(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        job_ids: Optional[List[str]] = None,
        force_refresh: bool = False,
        batch_size: int = 100,
        show_progress: bool = True
    ) -> Dict:
        """
        执行迁移
        
        Args:
            start_date: 开始时间
            end_date: 结束时间
            job_ids: Job ID列表
            force_refresh: 是否强制刷新
            batch_size: 批量处理大小
            show_progress: 是否显示进度
            
        Returns:
            dict: 迁移统计结果
        """
        print("\n" + "="*70)
        print("  📦 Violations 历史数据迁移工具")
        print("="*70)
        
        # 构建查询条件
        query = self.db.query(LintingJob)
        
        # 时间范围过滤
        if start_date:
            query = query.filter(LintingJob.created_at >= start_date)
            print(f"  📅 开始时间: {start_date.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print(f"  📅 开始时间: 无限制")
        
        if end_date:
            query = query.filter(LintingJob.created_at <= end_date)
            print(f"  📅 结束时间: {end_date.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print(f"  📅 结束时间: 无限制")
        
        # Job ID过滤
        if job_ids:
            query = query.filter(LintingJob.job_id.in_(job_ids))
            print(f"  🎯 指定Job: {len(job_ids)}个")
        
        # 只处理已完成的Job
        query = query.filter(
            LintingJob.status.in_(['COMPLETED', 'PARTIALLY_COMPLETED'])
        )
        
        # 获取需要处理的Job
        jobs = query.order_by(LintingJob.created_at.desc()).all()
        self.stats['total_jobs'] = len(jobs)
        
        print(f"  📊 找到 {self.stats['total_jobs']} 个Job需要迁移")
        print(f"  🔄 强制刷新: {'是' if force_refresh else '否'}")
        print(f"  📦 批量大小: {batch_size}")
        print("="*70 + "\n")
        
        if self.stats['total_jobs'] == 0:
            print("⚠️  没有找到符合条件的Job\n")
            return self.stats
        
        # 开始迁移
        start_time = time.time()
        
        for idx, job in enumerate(jobs, 1):
            try:
                if show_progress:
                    print(f"[{idx}/{self.stats['total_jobs']}] 处理Job: {job.job_id}", end=" ")
                
                # 检查是否需要跳过
                if not force_refresh:
                    existing_count = self.db.query(LintingViolation).filter(
                        LintingViolation.job_id == job.job_id
                    ).count()
                    
                    if existing_count > 0:
                        print(f"⏭️  跳过 (已有{existing_count}条数据)")
                        self.stats['skipped_jobs'] += 1
                        continue
                
                # 强制刷新：删除旧数据
                if force_refresh:
                    deleted_count = self.db.query(LintingViolation).filter(
                        LintingViolation.job_id == job.job_id
                    ).delete()
                    if deleted_count > 0:
                        print(f"🗑️  删除{deleted_count}条旧数据", end=" ")
                    self.db.commit()
                
                # 迁移Job的violations
                violations_count = self._migrate_job(job, batch_size)
                
                if violations_count > 0:
                    print(f"✅ {violations_count}条")
                    self.stats['success_jobs'] += 1
                    self.stats['total_violations'] += violations_count
                else:
                    print(f"⏭️  无数据")
                    self.stats['skipped_jobs'] += 1
                
            except Exception as e:
                print(f"❌ 失败: {str(e)[:50]}")
                self.stats['failed_jobs'] += 1
                self.stats['errors'].append({
                    'job_id': job.job_id,
                    'error': str(e)
                })
                # 继续处理下一个Job
                continue
        
        # 统计结果
        elapsed = time.time() - start_time
        self._print_summary(elapsed)
        
        return self.stats
    
    def _migrate_job(self, job: LintingJob, batch_size: int) -> int:
        """
        迁移单个Job的violations
        
        Args:
            job: Job对象
            batch_size: 批量大小
            
        Returns:
            int: 迁移的violations数量
        """
        # 获取Job下的所有成功的Task
        tasks = self.db.query(LintingTask).filter(
            LintingTask.job_id == job.job_id,
            LintingTask.status == TaskStatusEnum.SUCCESS,
            LintingTask.result_file_path.isnot(None)
        ).all()
        
        if not tasks:
            return 0
        
        job_violations_count = 0
        
        # 处理每个Task
        for task in tasks:
            try:
                # 读取JSON文件
                json_file_path = self.file_manager.get_absolute_path(task.result_file_path)
                
                if not json_file_path.exists():
                    # 文件不存在，跳过（容错）
                    continue
                
                # 解析JSON
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    result_data = json.load(f)
                
                violations = result_data.get("violations", [])
                
                if not violations:
                    continue
                
                # 读取源文件内容，用于填充sql_line字段
                sql_lines_dict = {}  # {line_no: sql_line}
                try:
                    source_file_path = self.file_manager.get_absolute_path(task.source_file_path)
                    if source_file_path.exists():
                        with open(source_file_path, 'r', encoding='utf-8') as f:
                            sql_content_lines = f.readlines()
                            for idx, line in enumerate(sql_content_lines, start=1):
                                sql_lines_dict[idx] = line.rstrip('\r\n')
                except Exception:
                    # 源文件读取失败，sql_line将为空（容错）
                    pass
                
                # 准备批量插入数据
                violation_records = []
                for v in violations:
                    line_no = v.get('line_no')
                    # 从源文件中获取对应行的SQL代码
                    sql_line = sql_lines_dict.get(line_no, '') if line_no else ''
                    
                    # 容错处理：缺少字段时使用默认值
                    violation_records.append({
                        'task_id': task.task_id,
                        'job_id': job.job_id,
                        'rule_code': v.get('code', 'UNKNOWN'),
                        'rule_name': v.get('rule'),  # 可以为None
                        'severity': v.get('severity'),  # 可以为None
                        'severity_level': v.get('severity_level'),  # 可以为None
                        'line_no': line_no,
                        'line_pos': v.get('line_pos'),
                        'description': v.get('description'),
                        'sql_line': sql_line,  # 从源文件读取的SQL行内容
                        'fixable': v.get('fixable', False),
                    })
                
                # 批量插入
                if violation_records:
                    self.db.bulk_insert_mappings(LintingViolation, violation_records)
                    job_violations_count += len(violation_records)
            
            except json.JSONDecodeError:
                # JSON解析失败，跳过（容错）
                continue
            except Exception:
                # 其他错误，跳过（容错）
                continue
        
        # 提交当前Job的数据
        if job_violations_count > 0:
            self.db.commit()
        
        return job_violations_count
    
    def _print_summary(self, elapsed: float):
        """打印统计摘要"""
        print("\n" + "="*70)
        print("  📊 迁移完成统计")
        print("="*70)
        print(f"  ⏱️  总耗时: {elapsed:.1f}秒")
        print(f"  📦 总Job数: {self.stats['total_jobs']}")
        print(f"  ✅ 成功: {self.stats['success_jobs']}")
        print(f"  ❌ 失败: {self.stats['failed_jobs']}")
        print(f"  ⏭️  跳过: {self.stats['skipped_jobs']}")
        print(f"  📝 迁移violations: {self.stats['total_violations']}")
        
        if self.stats['total_jobs'] > 0:
            success_rate = self.stats['success_jobs'] / self.stats['total_jobs'] * 100
            print(f"  📈 成功率: {success_rate:.1f}%")
        
        # 显示错误
        if self.stats['errors']:
            print(f"\n  ⚠️  错误列表 (共{len(self.stats['errors'])}个，显示前10个):")
            for error in self.stats['errors'][:10]:
                print(f"     - {error['job_id']}: {error['error'][:60]}")
        
        print("="*70 + "\n")


def parse_date(date_str: str) -> datetime:
    """解析日期字符串"""
    try:
        # 尝试解析 YYYY-MM-DD 格式
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        try:
            # 尝试解析 YYYY-MM-DD HH:MM:SS 格式
            return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            # 尝试解析 ISO 格式
            return datetime.fromisoformat(date_str)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='Violations历史数据迁移工具（独立运行）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 迁移所有历史数据
  python scripts/migrate_violations_to_database.py --all
  
  # 迁移最近7天的数据
  python scripts/migrate_violations_to_database.py --recent-days 7
  
  # 迁移指定时间范围
  python scripts/migrate_violations_to_database.py --start 2025-10-01 --end 2025-10-21
  
  # 迁移指定Job（强制刷新）
  python scripts/migrate_violations_to_database.py --job-ids job-xxx job-yyy --force
  
  # 静默模式（不显示进度）
  python scripts/migrate_violations_to_database.py --all --quiet
        """
    )
    
    # 时间范围参数
    time_group = parser.add_mutually_exclusive_group()
    time_group.add_argument('--all', action='store_true',
                           help='迁移所有历史数据')
    time_group.add_argument('--recent-days', type=int,
                           help='迁移最近N天的数据')
    time_group.add_argument('--start', type=str,
                           help='开始日期 (格式: 2025-10-01 或 2025-10-01 10:00:00)')
    
    parser.add_argument('--end', type=str,
                       help='结束日期 (格式: 2025-10-21 或 2025-10-21 23:59:59)')
    
    # Job过滤参数
    parser.add_argument('--job-ids', type=str, nargs='+',
                       help='指定要迁移的Job ID列表')
    
    # 其他参数
    parser.add_argument('--force', action='store_true',
                       help='强制刷新已存在的数据（会先删除旧数据）')
    parser.add_argument('--batch-size', type=int, default=100,
                       help='批量处理大小 (默认: 100)')
    parser.add_argument('--quiet', action='store_true',
                       help='静默模式，不显示详细进度')
    parser.add_argument('--dry-run', action='store_true',
                       help='试运行，只统计不实际迁移')
    
    args = parser.parse_args()
    
    # 检查互斥参数
    if args.end and not args.start:
        parser.error("--end 必须与 --start 一起使用")
    
    # 计算时间范围
    start_date = None
    end_date = None
    
    if args.all:
        print("📅 将迁移所有历史数据")
    elif args.recent_days:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.recent_days)
        print(f"📅 将迁移最近 {args.recent_days} 天的数据")
    elif args.start:
        start_date = parse_date(args.start)
        if args.end:
            end_date = parse_date(args.end)
        else:
            end_date = datetime.now()
        print(f"📅 将迁移时间范围: {args.start} ~ {args.end or '现在'}")
    
    # 试运行模式
    if args.dry_run:
        print("⚠️  试运行模式：只统计，不实际迁移\n")
    
    try:
        # 执行迁移
        with ViolationsMigrator() as migrator:
            # 试运行：只统计
            if args.dry_run:
                # 构建查询
                query = migrator.db.query(LintingJob)
                if start_date:
                    query = query.filter(LintingJob.created_at >= start_date)
                if end_date:
                    query = query.filter(LintingJob.created_at <= end_date)
                if args.job_ids:
                    query = query.filter(LintingJob.job_id.in_(args.job_ids))
                query = query.filter(
                    LintingJob.status.in_(['COMPLETED', 'PARTIALLY_COMPLETED'])
                )
                
                total = query.count()
                print(f"📊 统计结果: 找到 {total} 个符合条件的Job")
                
                if not args.force:
                    # 统计已迁移的Job
                    existing_jobs = migrator.db.query(LintingViolation.job_id).distinct().count()
                    print(f"📊 已迁移: {existing_jobs} 个Job")
                    print(f"📊 需要迁移: ~{total - existing_jobs} 个Job")
                
                print("\n提示: 移除 --dry-run 参数以实际执行迁移\n")
                sys.exit(0)
            
            # 实际迁移
            stats = migrator.migrate(
                start_date=start_date,
                end_date=end_date,
                job_ids=args.job_ids,
                force_refresh=args.force,
                batch_size=args.batch_size,
                show_progress=not args.quiet
            )
            
            # 返回退出码
            if stats['failed_jobs'] > 0:
                sys.exit(1)
            else:
                sys.exit(0)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断操作\n")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 错误: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

