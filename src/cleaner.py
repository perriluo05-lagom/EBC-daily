# -*- coding: utf-8 -*-
"""文件清理模块：定期清理旧的输出文件，避免磁盘空间占用过大。

清理策略：
- 保留最近 7 天的日报文件
- 保留最近 4 周的周报文件
- 保留最近 2 个月的双周报文件
- 每次运行时自动清理过期文件
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

log = logging.getLogger("ebc.cleaner")

# 保留策略（天数）
RETENTION_DAILY = 7        # 日报保留 7 天
RETENTION_WEEKLY = 28      # 周报保留 4 周
RETENTION_BIWEEKLY = 60    # 双周报保留 2 个月


def clean_old_files(output_dir: Path, dry_run: bool = False) -> dict:
    """清理旧的输出文件。
    
    Args:
        output_dir: 输出目录
        dry_run: 是否为试运行（不实际删除文件）
    
    Returns:
        清理统计信息
    """
    if not output_dir.exists():
        log.info("输出目录不存在: %s", output_dir)
        return {"deleted": 0, "kept": 0, "errors": 0}
    
    now = dt.datetime.now()
    stats = {"deleted": 0, "kept": 0, "errors": 0}
    
    # 遍历所有文件
    for file_path in output_dir.iterdir():
        if not file_path.is_file():
            continue
        
        # 根据文件名判断类型和保留期限
        file_name = file_path.name
        retention_days = None
        
        if "EBC-Daily-" in file_name:
            retention_days = RETENTION_DAILY
        elif "EBC-biweekly-" in file_name:
            retention_days = RETENTION_BIWEEKLY
        elif "EBC-weekly-" in file_name:
            retention_days = RETENTION_WEEKLY
        else:
            # 未知文件类型，保留
            stats["kept"] += 1
            continue
        
        # 获取文件修改时间
        try:
            mtime = dt.datetime.fromtimestamp(file_path.stat().st_mtime)
            age_days = (now - mtime).days
            
            if age_days > retention_days:
                if dry_run:
                    log.info("[试运行] 将删除过期文件: %s (已存在 %d 天)", file_name, age_days)
                else:
                    file_path.unlink()
                    log.info("已删除过期文件: %s (已存在 %d 天)", file_name, age_days)
                stats["deleted"] += 1
            else:
                stats["kept"] += 1
        except Exception as e:
            log.warning("处理文件失败 %s: %s", file_name, e)
            stats["errors"] += 1
    
    log.info(
        "文件清理完成: 删除 %d 个, 保留 %d 个, 错误 %d 个",
        stats["deleted"],
        stats["kept"],
        stats["errors"]
    )
    
    return stats


def get_output_dir() -> Path:
    """获取输出目录路径。"""
    return Path(__file__).resolve().parent.parent / "output"


def run_cleanup(dry_run: bool = False) -> dict:
    """运行文件清理。
    
    Args:
        dry_run: 是否为试运行
    
    Returns:
        清理统计信息
    """
    output_dir = get_output_dir()
    return clean_old_files(output_dir, dry_run)
