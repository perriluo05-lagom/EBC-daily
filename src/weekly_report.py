# -*- coding: utf-8 -*-
"""周报生成模块：每周五生成市场周报，提供周期性深度分析。

周报定位：
- 面向非专业投资者，用通俗易懂的语言总结一周市场表现
- 强调长期投资理念，不鼓励频繁交易
- 提供教育性内容，帮助投资者理解市场波动
- 每周五生成，如果周五是节假日则顺延到下一个交易日
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from .fetchers import base
from .config import SRC_SINA, SRC_EAST, SRC_CBOND, SRC_CM, SRC_JSL

log = logging.getLogger("ebc.weekly")


def should_generate_weekly_report(report_date: dt.date, is_biweekly: bool = False) -> bool:
    """判断是否应该生成周报/双周报。
    
    Args:
        report_date: 报告日期
        is_biweekly: 是否为双周报（True=双周报，False=周报）
    
    Returns:
        是否应该生成报告
    """
    # 只在周五生成
    if report_date.weekday() != 4:  # 4 = 周五
        return False
    
    if is_biweekly:
        # 双周报：每两周的周五（ISO周数为偶数）
        iso_week = report_date.isocalendar()[1]
        return iso_week % 2 == 0
    else:
        # 周报：每周五
        return True


def _get_date_range(report_date: dt.date, days: int) -> tuple[dt.date, dt.date]:
    """获取日期范围。
    
    Args:
        report_date: 报告日期
        days: 回溯天数（7=一周，14=两周）
    
    Returns:
        (开始日期, 结束日期)
    """
    end_date = report_date
    start_date = end_date - dt.timedelta(days=days)
    return start_date, end_date


def _fetch_historical_data(start_date: dt.date, end_date: dt.date) -> dict:
    """获取历史数据。
    
    注意：akshare 的历史数据接口可能有限，这里尽力获取可用数据。
    如果某些数据无法获取，会降级为"数据暂缺"。
    """
    log.info("获取历史数据: %s 至 %s", start_date, end_date)
    
    data = {
        "start_date": start_date,
        "end_date": end_date,
        "indices": {},
        "etf_flows": {},
        "bond_yields": {},
        "convertible_stats": {},
    }
    
    # 尝试获取主要指数的历史数据
    try:
        ak = base.ak()
        
        # 沪深300历史数据
        hs300_df = base.safe(
            ak.stock_zh_index_daily_em,
            symbol="sh000300",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d")
        )
        if hs300_df is not None and len(hs300_df) > 0:
            data["indices"]["hs300"] = {
                "start": float(hs300_df.iloc[0]["收盘"]),
                "end": float(hs300_df.iloc[-1]["收盘"]),
                "high": float(hs300_df["最高"].max()),
                "low": float(hs300_df["最低"].min()),
                "change_pct": (float(hs300_df.iloc[-1]["收盘"]) / float(hs300_df.iloc[0]["收盘"]) - 1) * 100,
            }
        
        # 中证1000历史数据
        zz1000_df = base.safe(
            ak.stock_zh_index_daily_em,
            symbol="sh000852",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d")
        )
        if zz1000_df is not None and len(zz1000_df) > 0:
            data["indices"]["zz1000"] = {
                "start": float(zz1000_df.iloc[0]["收盘"]),
                "end": float(zz1000_df.iloc[-1]["收盘"]),
                "high": float(zz1000_df["最高"].max()),
                "low": float(zz1000_df["最低"].min()),
                "change_pct": (float(zz1000_df.iloc[-1]["收盘"]) / float(zz1000_df.iloc[0]["收盘"]) - 1) * 100,
            }
        
        # 国债收益率历史数据
        bond_df = base.safe(
            ak.bond_china_yield,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d")
        )
        if bond_df is not None and len(bond_df) > 0:
            # 筛选国债曲线
            gov_df = bond_df[bond_df["曲线名称"].str.contains("国债")]
            if len(gov_df) > 0:
                data["bond_yields"] = {
                    "10y_start": float(gov_df.iloc[0]["10年"]),
                    "10y_end": float(gov_df.iloc[-1]["10年"]),
                    "10y_change_bp": (float(gov_df.iloc[-1]["10年"]) - float(gov_df.iloc[0]["10年"])) * 100,
                    "1y_start": float(gov_df.iloc[0]["1年"]),
                    "1y_end": float(gov_df.iloc[-1]["1年"]),
                    "1y_change_bp": (float(gov_df.iloc[-1]["1年"]) - float(gov_df.iloc[0]["1年"])) * 100,
                }
    
    except Exception as e:
        log.warning("获取历史数据失败: %s", e)
    
    return data


def _analyze_market_trend(data: dict) -> str:
    """分析市场趋势。"""
    lines = []
    
    # 沪深300分析
    hs300 = data.get("indices", {}).get("hs300")
    if hs300:
        change = hs300["change_pct"]
        if change > 2:
            lines.append(f"沪深300指数上涨{change:.2f}%，市场表现强劲，投资者信心较足。")
        elif change > 0:
            lines.append(f"沪深300指数小幅上涨{change:.2f}%，市场整体平稳。")
        elif change > -2:
            lines.append(f"沪深300指数小幅下跌{change:.2f}%，市场有所调整。")
        else:
            lines.append(f"沪深300指数下跌{change:.2f}%，市场情绪偏弱，投资者需谨慎。")
        
        # 波动性分析
        volatility = hs300["high"] - hs300["low"]
        volatility_pct = volatility / hs300["start"] * 100
        if volatility_pct > 5:
            lines.append(f"期间指数波动幅度达{volatility_pct:.1f}%，市场波动较大。")
    
    # 中证1000分析（小盘股）
    zz1000 = data.get("indices", {}).get("zz1000")
    if zz1000 and hs300:
        zz_change = zz1000["change_pct"]
        hs_change = hs300["change_pct"]
        diff = zz_change - hs_change
        if diff > 1:
            lines.append(f"中证1000涨幅({zz_change:.2f}%)超过沪深300({hs_change:.2f}%)，小盘股表现相对活跃。")
        elif diff < -1:
            lines.append(f"中证1000涨幅({zz_change:.2f}%)落后于沪深300({hs_change:.2f}%)，大盘股相对强势。")
    
    return "\n".join(lines) if lines else "数据不足，暂不分析。"


def _analyze_bond_market(data: dict) -> str:
    """分析债券市场。"""
    lines = []
    
    bond = data.get("bond_yields", {})
    if bond:
        # 10年期国债收益率变化
        change_10y = bond.get("10y_change_bp", 0)
        if change_10y > 5:
            lines.append(f"10年期国债收益率上升{change_10y:.1f}个基点，债券价格下跌，市场利率上行。")
        elif change_10y > 0:
            lines.append(f"10年期国债收益率小幅上升{change_10y:.1f}个基点，债券市场略有承压。")
        elif change_10y > -5:
            lines.append(f"10年期国债收益率小幅下降{abs(change_10y):.1f}个基点，债券价格略有上涨。")
        else:
            lines.append(f"10年期国债收益率下降{abs(change_10y):.1f}个基点，债券价格上涨，市场利率下行。")
        
        # 期限利差分析
        spread_start = bond.get("10y_start", 0) - bond.get("1y_start", 0)
        spread_end = bond.get("10y_end", 0) - bond.get("1y_end", 0)
        spread_change = (spread_end - spread_start) * 100
        
        if spread_change > 5:
            lines.append(f"期限利差扩大{spread_change:.1f}个基点，市场对长期经济前景预期改善。")
        elif spread_change < -5:
            lines.append(f"期限利差收窄{abs(spread_change):.1f}个基点，市场对短期经济前景更为关注。")
    
    return "\n".join(lines) if lines else "数据不足，暂不分析。"


def _generate_investment_guidance(data: dict, period_type: str) -> str:
    """生成投资指导意见（教育性，非推荐）。"""
    lines = []
    
    lines.append(f"**本期{period_type}市场总结**")
    lines.append("")
    
    # 基于市场表现给出教育性提示
    hs300 = data.get("indices", {}).get("hs300")
    if hs300:
        change = hs300["change_pct"]
        if change > 3:
            lines.append("市场上涨较多，但请注意：")
            lines.append("- 过去的表现不代表未来收益")
            lines.append("- 不建议因为短期上涨就追高买入")
            lines.append("- 可以借此机会审视自己的投资组合是否均衡")
        elif change < -3:
            lines.append("市场下跌较多，但请理解：")
            lines.append("- 市场波动是正常现象，长期投资需要承受短期波动")
            lines.append("- 不建议因为短期下跌就恐慌卖出")
            lines.append("- 可以借此机会学习如何在市场低迷时保持理性")
        else:
            lines.append("市场波动不大，这是投资的好时机：")
            lines.append("- 可以利用平稳市场学习投资知识")
            lines.append("- 审视自己的投资目标是否清晰")
            lines.append("- 确保投资组合符合自己的风险承受能力")
    
    lines.append("")
    lines.append("**重要提醒**：投资有风险，入市需谨慎。本报告仅供学习参考，不构成投资建议。")
    
    return "\n".join(lines)


def generate_weekly_report(
    report_date: dt.date,
    is_biweekly: bool = False
) -> str:
    """生成周报/双周报。
    
    Args:
        report_date: 报告日期
        is_biweekly: 是否为双周报
    
    Returns:
        Markdown格式的周报内容
    """
    period_type = "双周" if is_biweekly else "周"
    days = 14 if is_biweekly else 7
    
    log.info("生成%s报: %s", period_type, report_date)
    
    # 获取日期范围
    start_date, end_date = _get_date_range(report_date, days)
    
    # 获取历史数据
    data = _fetch_historical_data(start_date, end_date)
    
    # 生成报告内容
    lines = []
    
    # 标题
    title = f"【EBC {period_type}报】{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> 报告周期：{start_date.strftime('%Y年%m月%d日')} 至 {end_date.strftime('%Y年%m月%d日')}")
    lines.append("")
    
    # 一、市场概览
    lines.append("## 一、市场概览")
    lines.append("")
    lines.append(_analyze_market_trend(data))
    lines.append("")
    
    # 二、债券市场
    lines.append("## 二、债券市场")
    lines.append("")
    lines.append(_analyze_bond_market(data))
    lines.append("")
    
    # 三、投资参考
    lines.append("## 三、投资参考")
    lines.append("")
    lines.append(_generate_investment_guidance(data, period_type))
    lines.append("")
    
    # 免责声明
    lines.append("---")
    lines.append("> ⚠️ 以上内容基于公开数据整理，仅供学习参考，不构成投资建议。")
    lines.append("> 市场有风险，投资需谨慎。请根据自身风险承受能力独立判断。")
    lines.append("> 以上内容由AI生成，仅供参考。")
    
    return "\n".join(lines)
