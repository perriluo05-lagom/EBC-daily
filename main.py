# -*- coding: utf-8 -*-
"""EBC Daily 主流程。

用法:
  python main.py                # 交易日判定后采集并发送邮件
  python main.py --dry-run      # 不判交易日、不发邮件,打印 Markdown 并写入 output/
  python main.py --dry-run --date 2026-07-31   # 指定报告日期
  python main.py --weekly       # 生成周报（周五时）
  python main.py --monthly      # 生成月报（每月最后一个周五）
  python main.py --clean        # 清理旧的输出文件
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

# 确保能 import src.*
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import calendar as cal
from src.fetchers import base, overseas, equity, etf as etf_mod, bond, convertible
from src import analyze, render, emailer, llm, weekly_report, cleaner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ebc.main")


def _load_dotenv() -> None:
    """极简 .env 加载(无 python-dotenv 依赖)。"""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parse_date(s: str | None) -> dt.date:
    if not s:
        s = os.environ.get("FORCE_DATE", "").strip()
    if s:
        return dt.datetime.strptime(s, "%Y-%m-%d").date()
    return dt.date.today()


def collect_all() -> dict:
    """采集五大板块数据(失败字段内部已降级为"数据暂缺")。"""
    log.info("开始采集数据...")
    # 清理过期缓存，释放内存
    base.clear_cache()
    # 新浪指数表一次性取回,供 A 股指数 / 成交额 / 中证转债 共用
    sina_df = base.cached_call("stock_zh_index_spot_sina", base.ak().stock_zh_index_spot_sina)
    if sina_df is None:
        log.warning("新浪指数表取数失败,A 股指数/成交额将显示数据暂缺")
    etf_data = etf_mod.fetch_etf()
    data = {
        "overview": overseas.fetch_overview(),
        "equity": equity.fetch_equity(sina_df),
        "etf": etf_data,
        "bond": bond.fetch_bond(etf_bonds=etf_data.get("bond_etfs")),
        "convertible": convertible.fetch_convertible(sina_df),
    }
    # 采集完成后清理所有缓存，释放内存
    base.clear_all_cache()
    return data


def _summarize(data: dict) -> None:
    """简要统计各板块数据可得性,便于排查采集失败。"""
    miss = 0
    total = 0
    for sec in ("overview", "equity", "etf", "bond", "convertible"):
        block = data.get(sec, {})
        if not isinstance(block, dict):
            continue
        for v in _iter_leaves(block):
            total += 1
            if v is None or (isinstance(v, str) and "数据暂缺" in v):
                miss += 1
    log.info("采集完成:数据点 %d 个,其中数据暂缺 %d 个(生产环境通常为 0)", total, miss)


def _iter_leaves(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_leaves(v)
    else:
        yield obj


def main() -> int:
    parser = argparse.ArgumentParser(description="EBC Daily 每日资讯邮件")
    parser.add_argument("--dry-run", action="store_true", help="不发邮件,输出到 stdout 与 output/")
    parser.add_argument("--date", help="报告日期 YYYY-MM-DD(默认今天)")
    parser.add_argument("--weekly", action="store_true", help="生成周报（周五时）")
    parser.add_argument("--monthly", action="store_true", help="生成月报（每月最后一个周五）")
    parser.add_argument("--clean", action="store_true", help="清理旧的输出文件")
    args = parser.parse_args()

    _load_dotenv()
    report_date = _parse_date(args.date)

    try:
        import akshare  # noqa: F401
    except ImportError:
        log.error("未安装 akshare,请先运行: pip install -r requirements.txt")
        return 1

    # 处理文件清理
    if args.clean:
        log.info("开始清理旧的输出文件...")
        stats = cleaner.run_cleanup(dry_run=args.dry_run)
        log.info("清理完成: 删除 %d 个文件, 保留 %d 个文件", stats["deleted"], stats["kept"])
        return 0

    # 处理周报/月报
    if args.weekly or args.monthly:
        is_monthly = args.monthly
        if not weekly_report.should_generate_weekly_report(report_date, is_monthly):
            if is_monthly:
                log.info("%s 不是生成月报的时间（需要是每月最后一个周五）", report_date)
            else:
                log.info("%s 不是生成周报的时间（需要是周五）", report_date)
            return 0
        
        log.info("生成%s报: %s", "月" if is_monthly else "周", report_date)
        md = weekly_report.generate_weekly_report(report_date, is_monthly)
        
        if args.dry_run:
            out_dir = Path(__file__).resolve().parent / "output"
            out_dir.mkdir(exist_ok=True)
            period = "monthly" if is_monthly else "weekly"
            stem = f"EBC-{period}-{report_date.strftime('%Y-%m-%d')}"
            md_file = out_dir / f"{stem}.md"
            html_file = out_dir / f"{stem}.html"
            md_file.write_text(md, encoding="utf-8")
            html_file.write_text(emailer.md_to_html(md), encoding="utf-8")
            print(md)
            print(f"\n[dry-run] 已写入 {md_file} 与 {html_file}", file=sys.stderr)
            return 0
        
        subject = f"【EBC {'月' if is_monthly else '周'}报】{report_date.strftime('%Y-%m-%d')}"
        ok = emailer.send(subject, md)
        return 0 if ok else 1

    # 日常推送
    if not args.dry_run:
        if not cal.is_trading_day(report_date):
            log.info("%s 非交易日,跳过推送。", report_date)
            return 0

    # 数据基准日:最近一个已收盘的交易日(早8点未开盘,取前一交易日)
    trade_date = cal.previous_trade_day(report_date)
    log.info("报告日期=%s,数据基准日=%s, dry_run=%s", report_date, trade_date, args.dry_run)

    data = collect_all()
    _summarize(data)
    interp = analyze.analyze(data)
    narrative = llm.generate_narratives(data, interp, report_date)
    md = render.render(data, interp, report_date, trade_date, narrative)

    if args.dry_run:
        out_dir = Path(__file__).resolve().parent / "output"
        out_dir.mkdir(exist_ok=True)
        stem = f"EBC-Daily-{report_date.strftime('%Y-%m-%d')}"
        md_file = out_dir / f"{stem}.md"
        html_file = out_dir / f"{stem}.html"
        md_file.write_text(md, encoding="utf-8")
        html_file.write_text(emailer.md_to_html(md), encoding="utf-8")
        print(md)
        print(f"\n[dry-run] 已写入 {md_file} 与 {html_file}(浏览器打开 .html 可预览邮件效果)", file=sys.stderr)
        return 0

    ok = emailer.send(render.subject(report_date), md)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
