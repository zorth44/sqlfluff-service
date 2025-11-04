#!/bin/bash
# 日志清理脚本 - Log Cleanup Script
# 功能: 压缩旧日志、删除过期日志、释放磁盘空间

set -e

# ============= 配置区 =============
APP_DIR="/home/$(whoami)/sqlfluff-service"
LOG_DIR="$APP_DIR/logs"

# 日志保留策略
KEEP_DAYS=14              # 保留14天的日志
COMPRESS_DAYS=2           # 2天前的日志进行压缩

# 最大日志文件大小检查 (单位: MB)
MAX_SINGLE_FILE_SIZE=500  # 单个文件超过500MB时警告

# 是否执行清理 (true=真实执行, false=仅预览)
DRY_RUN=false

# ============= 颜色定义 =============
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============= 函数定义 =============

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查目录
check_directory() {
    if [ ! -d "$LOG_DIR" ]; then
        log_error "日志目录不存在: $LOG_DIR"
        exit 1
    fi
    log_success "日志目录: $LOG_DIR"
}

# 显示当前日志状态
show_log_status() {
    log_info "========== 当前日志状态 =========="

    # 未压缩日志文件
    UNCOMPRESSED_COUNT=$(find "$LOG_DIR" -name "*.log" -type f 2>/dev/null | wc -l | tr -d ' ')
    UNCOMPRESSED_SIZE=$(du -sh "$LOG_DIR"/*.log 2>/dev/null | awk '{sum+=$1} END {print sum}' || echo "0")

    # 已压缩日志文件
    COMPRESSED_COUNT=$(find "$LOG_DIR" -name "*.log.gz" -type f 2>/dev/null | wc -l | tr -d ' ')
    COMPRESSED_SIZE=$(du -sh "$LOG_DIR"/*.log.gz 2>/dev/null | awk '{sum+=$1} END {print sum}' || echo "0")

    # 总大小
    TOTAL_SIZE=$(du -sh "$LOG_DIR" 2>/dev/null | awk '{print $1}')

    echo "  未压缩日志: $UNCOMPRESSED_COUNT 个文件"
    echo "  已压缩日志: $COMPRESSED_COUNT 个文件"
    echo "  总大小: $TOTAL_SIZE"
    echo ""
}

# 检查超大日志文件
check_large_files() {
    log_info "========== 检查超大日志文件 =========="

    local found_large=false
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            size_mb=$(du -m "$file" | awk '{print $1}')
            if [ "$size_mb" -gt "$MAX_SINGLE_FILE_SIZE" ]; then
                log_warning "超大文件: $(basename "$file") - ${size_mb}MB"
                found_large=true
            fi
        fi
    done < <(find "$LOG_DIR" -name "*.log" -type f 2>/dev/null)

    if [ "$found_large" = false ]; then
        log_success "未发现超大日志文件"
    fi
    echo ""
}

# 压缩旧日志
compress_old_logs() {
    log_info "========== 压缩旧日志 (${COMPRESS_DAYS}天前) =========="

    local compressed_count=0
    local compressed_size=0

    # 查找需要压缩的日志文件 (超过COMPRESS_DAYS天，且未压缩)
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            filename=$(basename "$file")
            filesize=$(du -h "$file" | awk '{print $1}')

            if [ "$DRY_RUN" = true ]; then
                echo "  [预览] 将压缩: $filename ($filesize)"
            else
                echo "  压缩中: $filename ($filesize)"
                if gzip "$file" 2>/dev/null; then
                    compressed_count=$((compressed_count + 1))
                    log_success "  已压缩: $filename"
                else
                    log_error "  压缩失败: $filename"
                fi
            fi
        fi
    done < <(find "$LOG_DIR" -name "*.log" -type f -mtime +$COMPRESS_DAYS 2>/dev/null)

    if [ "$compressed_count" -eq 0 ]; then
        log_info "无需压缩的日志文件"
    else
        log_success "共压缩 $compressed_count 个文件"
    fi
    echo ""
}

# 删除过期日志
delete_old_logs() {
    log_info "========== 删除过期日志 (${KEEP_DAYS}天前) =========="

    local deleted_count=0
    local freed_space=0

    # 查找需要删除的压缩日志文件
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            filename=$(basename "$file")
            filesize=$(du -h "$file" | awk '{print $1}')

            if [ "$DRY_RUN" = true ]; then
                echo "  [预览] 将删除: $filename ($filesize)"
            else
                echo "  删除中: $filename ($filesize)"
                if rm -f "$file" 2>/dev/null; then
                    deleted_count=$((deleted_count + 1))
                    log_success "  已删除: $filename"
                else
                    log_error "  删除失败: $filename"
                fi
            fi
        fi
    done < <(find "$LOG_DIR" -name "*.log.gz" -type f -mtime +$KEEP_DAYS 2>/dev/null)

    if [ "$deleted_count" -eq 0 ]; then
        log_info "无需删除的过期日志"
    else
        log_success "共删除 $deleted_count 个过期日志"
    fi
    echo ""
}

# 显示清理结果
show_cleanup_result() {
    log_info "========== 清理后日志状态 =========="
    show_log_status
}

# 显示最近的日志文件
show_recent_logs() {
    log_info "========== 最近的日志文件 =========="
    echo "未压缩日志 (最近5个):"
    find "$LOG_DIR" -name "*.log" -type f 2>/dev/null | xargs ls -lh 2>/dev/null | tail -5 | awk '{print "  " $9 " - " $5}'
    echo ""
    echo "已压缩日志 (最近5个):"
    find "$LOG_DIR" -name "*.log.gz" -type f 2>/dev/null | xargs ls -lh 2>/dev/null | tail -5 | awk '{print "  " $9 " - " $5}'
    echo ""
}

# 显示使用帮助
show_help() {
    cat << EOF
日志清理脚本使用说明

用法:
  $0 [选项]

选项:
  -h, --help              显示此帮助信息
  -d, --dry-run           预览模式，不实际执行清理
  -k, --keep DAYS         保留天数 (默认: $KEEP_DAYS)
  -c, --compress DAYS     压缩天数 (默认: $COMPRESS_DAYS)
  -s, --status            仅显示日志状态，不执行清理

示例:
  $0                      # 执行清理（使用默认配置）
  $0 --dry-run            # 预览清理（不实际执行）
  $0 --keep 30            # 保留30天的日志
  $0 --status             # 仅查看当前状态

配置:
  日志目录: $LOG_DIR
  保留天数: $KEEP_DAYS 天
  压缩策略: $COMPRESS_DAYS 天前的日志
  最大文件: $MAX_SINGLE_FILE_SIZE MB

EOF
}

# ============= 主程序 =============

main() {
    echo -e "${GREEN}========== SQL核验服务 - 日志清理 ==========${NC}"
    echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    # 解析命令行参数
    local status_only=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -d|--dry-run)
                DRY_RUN=true
                log_warning "预览模式 - 不会实际执行清理操作"
                shift
                ;;
            -k|--keep)
                KEEP_DAYS="$2"
                shift 2
                ;;
            -c|--compress)
                COMPRESS_DAYS="$2"
                shift 2
                ;;
            -s|--status)
                status_only=true
                shift
                ;;
            *)
                log_error "未知选项: $1"
                show_help
                exit 1
                ;;
        esac
    done

    # 检查目录
    check_directory

    # 显示当前状态
    show_log_status

    if [ "$status_only" = true ]; then
        show_recent_logs
        exit 0
    fi

    # 检查超大文件
    check_large_files

    # 执行清理
    compress_old_logs
    delete_old_logs

    # 显示结果
    if [ "$DRY_RUN" = false ]; then
        show_cleanup_result
        log_success "日志清理完成!"
    else
        log_info "预览完成 - 使用不带 --dry-run 参数执行实际清理"
    fi
}

# 执行主程序
main "$@"
