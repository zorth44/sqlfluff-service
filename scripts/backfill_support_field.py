#!/usr/bin/env python3
"""
历史数据回填脚本：从JSON文件读取support字段并更新数据库

将历史Job的violations数据中的support字段从JSON文件回填到数据库表中。
这个脚本用于修复在添加support字段之前的历史数据。

使用方法:
    # 回填所有历史数据
    python scripts/backfill_support_field.py --all
    
    # 回填最近7天
    python scripts/backfill_support_field.py --recent-days 7
    
    # 回填指定时间范围
    python scripts/backfill_support_field.py --start 2025-10-01 --end 2025-10-21
    
    # 强制刷新指定Job
    python scripts/backfill_support_field.py --job-ids job-xxx job-yyy --force
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
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

# 导入项目模块
from app.core.database import SessionLocal
from app.models.database import LintingJob, LintingTask, LintingViolation
from app.utils.file_utils import FileManager
from app.schemas.common import TaskStatusEnum


class SupportFieldBackfiller:
    """Support字段回填器"""
    
    def __init__(self):
        self.db = SessionLocal()
        self.file_manager = FileManager()
        self.stats = {
            'total_jobs': 0,
            'success_jobs': 0,
            'failed_jobs': 0,
            'skipped_jobs': 0,
            'total_violations': 0,
            'updated_violations': 0,
            'errors': []
        }
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()
    
    def backfill(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        job_ids: Optional[List[str]] = None,
        force_refresh: bool = False,
        batch_size: int = 100,
        show_progress: bool = True,
        verbose: bool = False
    ) -> Dict:
        """
        执行回填
        
        Args:
            start_date: 开始时间
            end_date: 结束时间
            job_ids: Job ID列表
            force_refresh: 是否强制刷新（即使已有support字段也更新）
            batch_size: 批量处理大小
            show_progress: 是否显示进度
            
        Returns:
            dict: 回填统计结果
        """
        print("\n" + "="*70)
        print("  🔄 Support字段历史数据回填工具")
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
        
        print(f"  📊 找到 {self.stats['total_jobs']} 个Job需要回填")
        print(f"  🔄 强制刷新: {'是' if force_refresh else '否'}")
        print(f"  📦 批量大小: {batch_size}")
        print("="*70 + "\n")
        
        if self.stats['total_jobs'] == 0:
            print("⚠️  没有找到符合条件的Job\n")
            return self.stats
        
        # 开始回填
        start_time = time.time()
        
        for idx, job in enumerate(jobs, 1):
            try:
                if show_progress:
                    print(f"[{idx}/{self.stats['total_jobs']}] 处理Job: {job.job_id}", end=" ")
                
                # 检查是否需要跳过
                if not force_refresh:
                    # 检查是否所有violations都有support字段
                    violations_without_support = self.db.query(LintingViolation).filter(
                        LintingViolation.job_id == job.job_id,
                        (
                            (LintingViolation.support.is_(None)) |
                            (LintingViolation.support == '')
                        )
                    ).count()
                    
                    if violations_without_support == 0:
                        print(f"⏭️  跳过 (所有violations已有support字段)")
                        self.stats['skipped_jobs'] += 1
                        continue
                
                # 回填Job的violations
                self._verbose = getattr(self, '_verbose', False)
                updated_count = self._backfill_job(job, force_refresh, batch_size)
                
                if updated_count > 0:
                    print(f"✅ 更新{updated_count}条")
                    self.stats['success_jobs'] += 1
                    self.stats['updated_violations'] += updated_count
                else:
                    # 检查是否有violations但没有更新
                    violations_count = self.db.query(LintingViolation).filter(
                        LintingViolation.job_id == job.job_id
                    ).count()
                    
                    if violations_count == 0:
                        print(f"⏭️  无violations数据")
                    else:
                        print(f"⏭️  无数据需要更新 (已有{violations_count}条violations)")
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
    
    def _backfill_job(self, job: LintingJob, force_refresh: bool, batch_size: int) -> int:
        """
        回填单个Job的violations的support字段
        
        Args:
            job: Job对象
            force_refresh: 是否强制刷新
            batch_size: 批量大小
            
        Returns:
            int: 更新的violations数量
        """
        # 获取Job下的所有成功的Task
        tasks = self.db.query(LintingTask).filter(
            LintingTask.job_id == job.job_id,
            LintingTask.status == TaskStatusEnum.SUCCESS,
            LintingTask.result_file_path.isnot(None)
        ).all()
        
        if not tasks:
            return 0
        
        # 获取verbose标志（从实例变量或参数传递）
        verbose = getattr(self, '_verbose', False)
        
        updated_count = 0
        
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
                    if verbose:
                        print(f"      [DEBUG] Task {task.task_id}: JSON中没有violations")
                    continue
                
                # 检查JSON中是否有support字段
                has_support_field = any('support' in v for v in violations)
                
                if not has_support_field:
                    if verbose:
                        print(f"      [DEBUG] Task {task.task_id}: JSON中的violations没有support字段（历史数据）")
                    continue
                
                # 构建violations的映射表，用于快速查找
                # 使用多种键组合以提高匹配成功率
                violations_map_exact = {}  # (line_no, line_pos, rule_code) - 精确匹配
                violations_map_no_pos = {}  # (line_no, rule_code) - 无位置匹配
                
                for v in violations:
                    line_no = v.get('line_no')
                    line_pos = v.get('line_pos') or 0
                    rule_code = v.get('code', '')
                    support = v.get('support', '')
                    
                    if not line_no or not rule_code:
                        continue
                    
                    # 精确匹配键
                    key_exact = (line_no, line_pos, rule_code)
                    violations_map_exact[key_exact] = support
                    
                    # 无位置匹配键（fallback）
                    key_no_pos = (line_no, rule_code)
                    if key_no_pos not in violations_map_no_pos:
                        violations_map_no_pos[key_no_pos] = support
                
                # 查询该task的所有violations
                db_violations = self.db.query(LintingViolation).filter(
                    LintingViolation.task_id == task.task_id
                ).all()
                
                if not db_violations:
                    if verbose:
                        print(f"      [DEBUG] Task {task.task_id}: 数据库中没有violations")
                    continue
                
                if verbose:
                    print(f"      [DEBUG] Task {task.task_id}: JSON中有{len(violations)}条violations, 数据库中有{len(db_violations)}条")
                
                # 更新每个violation的support字段
                for db_violation in db_violations:
                    # 检查是否需要更新
                    if not force_refresh and db_violation.support and db_violation.support != '':
                        continue
                    
                    line_no = db_violation.line_no
                    line_pos = db_violation.line_pos or 0
                    rule_code = db_violation.rule_code or ''
                    
                    if not line_no or not rule_code:
                        continue
                    
                    # 尝试精确匹配
                    key_exact = (line_no, line_pos, rule_code)
                    support_value = violations_map_exact.get(key_exact)
                    
                    # 如果精确匹配失败，尝试无位置匹配
                    if support_value is None:
                        key_no_pos = (line_no, rule_code)
                        support_value = violations_map_no_pos.get(key_no_pos, '')
                    
                    # 更新字段
                    if support_value != db_violation.support:
                        db_violation.support = support_value
                        updated_count += 1
                
                # 批量提交
                if updated_count > 0 and updated_count % batch_size == 0:
                    self.db.commit()
            
            except json.JSONDecodeError as e:
                # JSON解析失败，跳过（容错）
                continue
            except Exception as e:
                # 其他错误，跳过（容错）
                continue
        
        # 提交当前Job的数据
        if updated_count > 0:
            self.db.commit()
        
        return updated_count
    
    def _print_summary(self, elapsed: float):
        """打印统计摘要"""
        print("\n" + "="*70)
        print("  📊 回填完成统计")
        print("="*70)
        print(f"  ⏱️  总耗时: {elapsed:.1f}秒")
        print(f"  📦 总Job数: {self.stats['total_jobs']}")
        print(f"  ✅ 成功: {self.stats['success_jobs']}")
        print(f"  ❌ 失败: {self.stats['failed_jobs']}")
        print(f"  ⏭️  跳过: {self.stats['skipped_jobs']}")
        print(f"  🔄 更新violations: {self.stats['updated_violations']}")
        
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
        description='Support字段历史数据回填工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 回填所有历史数据
  python scripts/backfill_support_field.py --all
  
  # 回填最近7天的数据
  python scripts/backfill_support_field.py --recent-days 7
  
  # 回填指定时间范围
  python scripts/backfill_support_field.py --start 2025-10-01 --end 2025-10-21
  
  # 回填指定Job（强制刷新）
  python scripts/backfill_support_field.py --job-ids job-xxx job-yyy --force
  
  # 静默模式（不显示进度）
  python scripts/backfill_support_field.py --all --quiet
        """
    )
    
    # 时间范围参数
    time_group = parser.add_mutually_exclusive_group()
    time_group.add_argument('--all', action='store_true',
                           help='回填所有历史数据')
    time_group.add_argument('--recent-days', type=int,
                           help='回填最近N天的数据')
    time_group.add_argument('--start', type=str,
                           help='开始日期 (格式: 2025-10-01 或 2025-10-01 10:00:00)')
    
    parser.add_argument('--end', type=str,
                       help='结束日期 (格式: 2025-10-21 或 2025-10-21 23:59:59)')
    
    # Job过滤参数
    parser.add_argument('--job-ids', type=str, nargs='+',
                       help='指定要回填的Job ID列表')
    
    # 其他参数
    parser.add_argument('--force', action='store_true',
                       help='强制刷新已存在的数据（即使已有support字段也更新）')
    parser.add_argument('--batch-size', type=int, default=100,
                       help='批量处理大小 (默认: 100)')
    parser.add_argument('--quiet', action='store_true',
                       help='静默模式，不显示详细进度')
    parser.add_argument('--verbose', action='store_true',
                       help='详细模式，显示调试信息')
    parser.add_argument('--dry-run', action='store_true',
                       help='试运行，只统计不实际回填')
    
    args = parser.parse_args()
    
    # 检查互斥参数
    if args.end and not args.start:
        parser.error("--end 必须与 --start 一起使用")
    
    # 计算时间范围
    start_date = None
    end_date = None
    
    if args.all:
        print("📅 将回填所有历史数据")
    elif args.recent_days:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.recent_days)
        print(f"📅 将回填最近 {args.recent_days} 天的数据")
    elif args.start:
        start_date = parse_date(args.start)
        if args.end:
            end_date = parse_date(args.end)
        else:
            end_date = datetime.now()
        print(f"📅 将回填时间范围: {args.start} ~ {args.end or '现在'}")
    
    # 试运行模式
    if args.dry_run:
        print("⚠️  试运行模式：只统计，不实际回填\n")
    
    try:
        # 执行回填
        with SupportFieldBackfiller() as backfiller:
            # 试运行：只统计
            if args.dry_run:
                # 构建查询
                query = backfiller.db.query(LintingJob)
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
                    # 统计需要回填的violations数量
                    violations_query = backfiller.db.query(LintingViolation)
                    if start_date:
                        jobs = backfiller.db.query(LintingJob.job_id).filter(
                            LintingJob.created_at >= start_date
                        ).subquery()
                        violations_query = violations_query.filter(
                            LintingViolation.job_id.in_(jobs)
                        )
                    if end_date:
                        jobs = backfiller.db.query(LintingJob.job_id).filter(
                            LintingJob.created_at <= end_date
                        ).subquery()
                        violations_query = violations_query.filter(
                            LintingViolation.job_id.in_(jobs)
                        )
                    if args.job_ids:
                        violations_query = violations_query.filter(
                            LintingViolation.job_id.in_(args.job_ids)
                        )
                    
                    violations_without_support = violations_query.filter(
                        (LintingViolation.support.is_(None)) |
                        (LintingViolation.support == '')
                    ).count()
                    
                    print(f"📊 需要回填的violations: ~{violations_without_support} 条")
                
                print("\n提示: 移除 --dry-run 参数以实际执行回填\n")
                sys.exit(0)
            
            # 实际回填
            backfiller._verbose = args.verbose if hasattr(args, 'verbose') else False
            stats = backfiller.backfill(
                start_date=start_date,
                end_date=end_date,
                job_ids=args.job_ids,
                force_refresh=args.force,
                batch_size=args.batch_size,
                show_progress=not args.quiet,
                verbose=backfiller._verbose
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

