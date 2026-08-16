# -*- coding: utf-8 -*-
"""周报/月报生成模块：提供周期性深度分析。

周报定位：
- 每周五生成，总结一周市场表现
- 面向非专业投资者，用通俗易懂的语言
- 强调长期投资理念，不鼓励频繁交易
- 提供教育性内容，帮助投资者理解市场波动

月报定位：
- 每月最后一个周五生成
- 总结整月市场表现和趋势
- 提供更深入的市场分析和投资教育
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

from .fetchers import base
from .config import SRC_SINA, SRC_EAST, SRC_CBOND, SRC_CM, SRC_JSL
from . import llm

log = logging.getLogger("ebc.weekly")


def should_generate_weekly_report(report_date: dt.date, is_monthly: bool = False) -> bool:
    """判断是否应该生成周报/月报。
    
    Args:
        report_date: 报告日期
        is_monthly: 是否为月报（True=月报，False=周报）
    
    Returns:
        是否应该生成报告
    """
    # 只在周五生成
    if report_date.weekday() != 4:  # 4 = 周五
        return False
    
    if is_monthly:
        # 月报：每月最后一个周五
        # 检查当前周五是否是本月的最后一个周五
        next_friday = report_date + dt.timedelta(days=7)
        return next_friday.month != report_date.month
    else:
        # 周报：每周五
        return True


def _get_date_range(report_date: dt.date, days: int) -> tuple[dt.date, dt.date]:
    """获取日期范围。
    
    Args:
        report_date: 报告日期
        days: 回溯天数（7=一周，30=一月）
    
    Returns:
        (开始日期, 结束日期)
    """
    end_date = report_date
    start_date = end_date - dt.timedelta(days=days)
    return start_date, end_date


def _fetch_index_data_sina(symbol: str, start_date: dt.date, end_date: dt.date) -> dict | None:
    """使用新浪财经接口获取指数历史数据（备用数据源）。"""
    try:
        # 新浪接口格式：sh000300, sh000852 等
        ak = base.ak()
        df = base.safe(
            ak.stock_zh_index_daily,
            symbol=symbol
        )
        if df is None or len(df) == 0:
            return None
        
        # 筛选日期范围
        df['date'] = df['date'].astype(str)
        mask = (df['date'] >= start_date.strftime('%Y-%m-%d')) & (df['date'] <= end_date.strftime('%Y-%m-%d'))
        df = df[mask]
        
        if len(df) == 0:
            return None
        
        return {
            "start": float(df.iloc[0]["close"]),
            "end": float(df.iloc[-1]["close"]),
            "high": float(df["high"].max()),
            "low": float(df["low"].min()),
            "change_pct": (float(df.iloc[-1]["close"]) / float(df.iloc[0]["close"]) - 1) * 100,
        }
    except Exception as e:
        log.warning("新浪接口获取%s数据失败: %s", symbol, e)
        return None


def _fetch_index_data_em(symbol: str, start_date: dt.date, end_date: dt.date) -> dict | None:
    """使用东方财富接口获取指数历史数据。"""
    try:
        ak = base.ak()
        df = base.safe(
            ak.stock_zh_index_daily_em,
            symbol=symbol,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d")
        )
        if df is None or len(df) == 0:
            return None
        
        return {
            "start": float(df.iloc[0]["收盘"]),
            "end": float(df.iloc[-1]["收盘"]),
            "high": float(df["最高"].max()),
            "low": float(df["最低"].min()),
            "change_pct": (float(df.iloc[-1]["收盘"]) / float(df.iloc[0]["收盘"]) - 1) * 100,
        }
    except Exception as e:
        log.warning("东方财富接口获取%s数据失败: %s", symbol, e)
        return None


def _fetch_historical_data(start_date: dt.date, end_date: dt.date) -> dict:
    """获取历史数据（多数据源备用）。
    
    注意：
    - 指数数据：获取区间首尾的累计涨跌幅（周/月维度）
    - 国债收益率：获取区间首尾的变动（周/月维度）
    - 资金流向和行业板块：因无法获取周期累计数据，已删除
    """
    log.info("获取历史数据: %s 至 %s", start_date, end_date)
    
    data = {
        "start_date": start_date,
        "end_date": end_date,
        "indices": {},
        "bond_yields": {},
    }
    
    # 获取主要指数数据（优先东方财富，失败则用新浪）
    index_configs = [
        ("sh000300", "hs300", "沪深300"),
        ("sh000852", "zz1000", "中证1000"),
        ("sh000016", "sh50", "上证50"),
        ("sh000905", "zz500", "中证500"),
        ("sz399006", "cyb", "创业板指"),
    ]
    
    for symbol, key, name in index_configs:
        # 先尝试东方财富
        result = _fetch_index_data_em(symbol, start_date, end_date)
        # 失败则尝试新浪
        if result is None:
            result = _fetch_index_data_sina(symbol, start_date, end_date)
        
        if result is not None:
            data["indices"][key] = result
            log.info("成功获取%s数据", name)
    
    # 获取国债收益率历史数据
    try:
        ak = base.ak()
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
        log.warning("获取国债收益率数据失败: %s", e)
    
    return data


def _generate_facts_for_llm(data: dict, period_type: str) -> str:
    """生成供 LLM 分析的数据事实。
    
    注意：所有涨跌幅均为周期累计涨跌幅（本周/本月累计）
    """
    lines = []
    
    period_desc = "本周" if period_type == "周" else "本月"
    lines.append(f"【{period_type}报数据事实】")
    lines.append(f"报告周期：{data['start_date'].strftime('%Y-%m-%d')} 至 {data['end_date'].strftime('%Y-%m-%d')}")
    lines.append(f"说明：以下涨跌幅均为{period_desc}累计涨跌幅")
    lines.append("")
    
    # 指数表现
    if data.get("indices"):
        lines.append("【指数表现】（周期累计涨跌幅）")
        for key, info in data["indices"].items():
            name_map = {
                "hs300": "沪深300",
                "zz1000": "中证1000",
                "sh50": "上证50",
                "zz500": "中证500",
                "cyb": "创业板指",
            }
            name = name_map.get(key, key)
            lines.append(f"- {name}：{period_desc}累计{info['change_pct']:+.2f}%（区间最高{info['high']:.2f}，最低{info['low']:.2f}）")
        lines.append("")
    
    # 债券市场
    if data.get("bond_yields"):
        bond = data["bond_yields"]
        lines.append("【债券市场】（周期累计变动）")
        lines.append(f"- 10年期国债收益率：{bond['10y_start']:.2f}% → {bond['10y_end']:.2f}%（{period_desc}累计变动{bond['10y_change_bp']:+.1f}bp）")
        lines.append(f"- 1年期国债收益率：{bond['1y_start']:.2f}% → {bond['1y_end']:.2f}%（{period_desc}累计变动{bond['1y_change_bp']:+.1f}bp）")
        lines.append("")
    
    return "\n".join(lines)


def _generate_weekly_prompt(facts: str, period_type: str) -> str:
    """生成周报/月报的 LLM prompt。"""
    period_desc = "本周" if period_type == "周" else "本月"
    
    return f"""报告日期：{period_type}报
以下是本{period_type}的「数据事实」（均已标注来源，均为可查证真实数据）：

{facts}

请基于以上数据事实，撰写一份面向普通投资者的{period_type}市场深度分析报告。

**核心原则**：
1. **深度分析**：不要只罗列数据，要挖掘数据背后的逻辑、驱动因素和潜在趋势
2. **透彻归因**：每个关键数据变化都要解释"为什么"——是政策驱动、资金流向、情绪变化还是基本面因素
3. **洞察趋势**：基于数据分析潜在的市场趋势和投资机会，提供有前瞻性的观点
4. **时间维度明确**：所有涨跌幅均为{period_desc}累计涨跌幅，必须在报告中明确标注
5. **严禁敷衍**：绝对不要使用"数据暂缺"等表述，没有的数据直接删除章节

**分析深度要求**：
- **市场回顾**：不仅描述涨跌，要分析驱动因素（如：政策预期、资金面、情绪面、外部因素等）
- **风格轮动**：解释为什么会出现这种风格分化（如：风险偏好变化、估值差异、资金偏好转移等）
- **债券市场**：分析收益率变动的原因（如：经济预期、货币政策、资金面松紧等）
- **投资思考**：基于深度分析给出有洞察力的投资建议，而非泛泛而谈

**排版要求（微信公众号风格）**：
1. 使用 Markdown 格式，核心结论和关键洞察必须**加粗**突出
2. 表格：展示指数对比、债券收益率等数据，表格中必须标注"累计涨跌幅"或"累计变动"
3. 引用块：用于教育性内容或重要提示，用 > 标记
4. 每个章节 2-4 段，每段 100-150 字，确保分析有深度但不冗长
5. 使用短句，避免长句；使用主动语态，避免被动语态

**报告结构**：
## 一、本{period_type}市场回顾
（用表格展示主要指数{period_desc}累计表现）
（表格列：指数名称 | {period_desc}累计涨跌幅 | 区间最高 | 区间最低）
（**加粗**总结市场整体特征，并深入分析驱动因素：是什么力量主导了市场走势？政策面、资金面、情绪面各扮演什么角色？）

## 二、风格轮动分析
（对比大盘vs小盘、价值vs成长的{period_desc}累计表现差异）
（**加粗**风格特征结论）
（深入分析：为什么会出现这种风格分化？背后的驱动因素是什么？是风险偏好变化、估值修复、还是资金偏好转移？这种风格切换可能持续多久？）
（月报增加：**什么是风格轮动？** 用引用块解释这个概念，100字以内）

## 三、债券市场
（分析国债收益率{period_desc}累计变动，用表格展示数据）
（表格列：期限 | 期初收益率 | 期末收益率 | {period_desc}累计变动）
（**加粗**关键变动）
（深入分析：收益率变动的原因是什么？反映了对经济前景的什么预期？货币政策、资金面、通胀预期各有什么影响？期限利差变化意味着什么？）

## 四、投资思考
（基于深度分析，给出有洞察力的投资建议）
（**加粗**核心建议）
（建议要有针对性：基于当前市场特征，投资者应该如何调整策略？需要注意什么风险？有哪些潜在机会？）
（月报增加：用引用块给出"长期投资提醒"，50字以内）

**禁止**：
- 不要给出具体的买卖建议
- 不要预测短期走势
- 不要使用"建议买入/卖出"等绝对化表述
- 不要编造数据
- 不要重复表达相同的意思
- 不要使用"数据暂缺"、"未能提供"、"无法分析"等敷衍表述
- 不要添加"资金流向分析"和"行业板块表现"章节
- 不要写废话和套话
- 不要浅尝辄止，每个观点都要有深度支撑

**语言风格**：
- 高信息密度：每句话都要有信息量，但通俗易懂
- 深刻洞察：不仅描述现象，更要揭示本质
- 精炼与详实并重：语言凝练但分析有深度
- 从受众需求出发，提供真正有价值的投资洞察

请直接输出报告内容，不要前言和解释。"""


def generate_weekly_report(
    report_date: dt.date,
    is_monthly: bool = False
) -> str:
    """生成周报/月报。
    
    Args:
        report_date: 报告日期
        is_monthly: 是否为月报
    
    Returns:
        Markdown格式的周报内容
    """
    period_type = "月" if is_monthly else "周"
    days = 30 if is_monthly else 7
    
    log.info("生成%s报: %s", period_type, report_date)
    
    # 获取日期范围
    start_date, end_date = _get_date_range(report_date, days)
    
    # 获取历史数据
    data = _fetch_historical_data(start_date, end_date)
    
    # 生成数据事实
    facts = _generate_facts_for_llm(data, period_type)
    
    # 调用 LLM 生成深度分析
    narrative = ""
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    
    if api_key and base_url and model:
        log.info("调用 LLM 生成%s报分析", period_type)
        prompt = _generate_weekly_prompt(facts, period_type)
        narrative = llm._call_llm(api_key, base_url, model, prompt)
    
    # 生成报告
    lines = []
    
    # 标题
    title = f"【EBC {period_type}报】{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> 报告周期：{start_date.strftime('%Y年%m月%d日')} 至 {end_date.strftime('%Y年%m月%d日')}")
    lines.append("")
    
    # LLM 生成的分析
    if narrative:
        lines.append(narrative)
    else:
        # 降级：使用规则分析（已改进为深度分析）
        lines.append(_analyze_market_trend_simple(data, period_type))
        lines.append("")
        
        lines.append(_analyze_bond_market_simple(data, period_type))
        lines.append("")
        
        lines.append(_generate_investment_guidance_simple(data, period_type))
        lines.append("")
    
    # 免责声明
    lines.append("---")
    lines.append("> ⚠️ 以上内容基于公开数据整理，仅供学习参考，不构成投资建议。")
    lines.append("> 市场有风险，投资需谨慎。请根据自身风险承受能力独立判断。")
    if narrative:
        lines.append("> 以上内容由AI生成，仅供参考。")
    
    return "\n".join(lines)


def _analyze_market_trend_simple(data: dict, period_type: str) -> str:
    """市场趋势深度分析（降级方案）。"""
    period_desc = "本周" if period_type == "周" else "本月"
    lines = []
    
    # 表格展示指数表现
    lines.append("## 一、市场回顾")
    lines.append("")
    lines.append("| 指数名称 | 累计涨跌幅 | 区间最高 | 区间最低 |")
    lines.append("|---------|-----------|---------|---------|")
    
    indices = data.get("indices", {})
    index_names = {
        "sh50": "上证50",
        "hs300": "沪深300",
        "zz500": "中证500",
        "zz1000": "中证1000",
        "cyb": "创业板指"
    }
    
    for key, name in index_names.items():
        if key in indices:
            idx = indices[key]
            change = idx.get("change_pct", 0)
            high = idx.get("high", 0)
            low = idx.get("low", 0)
            lines.append(f"| {name} | {change:+.2f}% | {high:.2f} | {low:.2f} |")
    
    lines.append("")
    
    # 深度分析
    hs300 = indices.get("hs300", {})
    zz1000 = indices.get("zz1000", {})
    sh50 = indices.get("sh50", {})
    cyb = indices.get("cyb", {})
    
    if hs300:
        hs_change = hs300.get("change_pct", 0)
        zz_change = zz1000.get("change_pct", 0) if zz1000 else 0
        sh_change = sh50.get("change_pct", 0) if sh50 else 0
        cy_change = cyb.get("change_pct", 0) if cyb else 0
        
        # 判断市场整体走势
        if hs_change > 2:
            trend = "强劲上涨"
            reason = "市场情绪乐观，资金积极入场"
        elif hs_change > 0:
            trend = "小幅上涨"
            reason = "市场情绪谨慎乐观，资金选择性布局"
        elif hs_change > -2:
            trend = "小幅调整"
            reason = "市场情绪谨慎，资金观望情绪浓厚"
        else:
            trend = "明显下跌"
            reason = "市场情绪悲观，资金避险情绪升温"
        
        lines.append(f"**市场整体呈现{trend}态势，{reason}。**")
        lines.append("")
        
        # 风格分析
        style_diff = zz_change - sh_change
        if style_diff > 3:
            style_desc = "小盘股显著跑赢大盘股"
            style_reason = "资金偏好高风险高弹性品种，市场风险偏好明显提升"
        elif style_diff > 1:
            style_desc = "小盘股跑赢大盘股"
            style_reason = "资金开始向中小市值倾斜，市场风险偏好有所回升"
        elif style_diff > -1:
            style_desc = "大小盘表现相对均衡"
            style_reason = "资金在不同市值间均衡配置，市场风格中性"
        elif style_diff > -3:
            style_desc = "大盘股跑赢小盘股"
            style_reason = "资金偏好稳健品种，市场风险偏好有所下降"
        else:
            style_desc = "大盘股显著跑赢小盘股"
            style_reason = "资金集中流向大盘蓝筹，市场避险情绪浓厚"
        
        lines.append(f"**风格特征：{style_desc}，{style_reason}。**")
        lines.append("")
        
        # 成长价值分析
        growth_value_diff = cy_change - sh_change
        if growth_value_diff > 2:
            gv_desc = "成长风格显著跑赢价值风格"
            gv_reason = "市场对未来增长预期乐观，资金积极布局成长赛道"
        elif growth_value_diff > 0:
            gv_desc = "成长风格跑赢价值风格"
            gv_reason = "市场对成长性资产偏好提升，资金开始关注成长机会"
        elif growth_value_diff > -2:
            gv_desc = "价值风格跑赢成长风格"
            gv_reason = "市场更注重当期业绩确定性，资金偏好价值型资产"
        else:
            gv_desc = "价值风格显著跑赢成长风格"
            gv_reason = "市场对成长性预期悲观，资金集中流向低估值价值股"
        
        lines.append(f"**成长价值：{gv_desc}，{gv_reason}。**")
    
    return "\n".join(lines) if lines else "数据不足，暂不分析。"


def _analyze_bond_market_simple(data: dict, period_type: str) -> str:
    """债券市场深度分析（降级方案）。"""
    period_desc = "本周" if period_type == "周" else "本月"
    bond = data.get("bond_yields", {})
    
    if not bond:
        return "## 二、债券市场\n\n债券市场数据不足，暂不分析。"
    
    lines = []
    lines.append("## 二、债券市场")
    lines.append("")
    
    # 表格展示收益率变化
    lines.append("| 期限 | 期初收益率 | 期末收益率 | 累计变动 |")
    lines.append("|------|-----------|-----------|---------|")
    
    y1_start = bond.get("1y_start", 0)
    y1_end = bond.get("1y_end", 0)
    y1_change = bond.get("1y_change_bp", 0)
    
    y10_start = bond.get("10y_start", 0)
    y10_end = bond.get("10y_end", 0)
    y10_change = bond.get("10y_change_bp", 0)
    
    lines.append(f"| 1年期 | {y1_start:.2f}% | {y1_end:.2f}% | {y1_change:+.1f}bp |")
    lines.append(f"| 10年期 | {y10_start:.2f}% | {y10_end:.2f}% | {y10_change:+.1f}bp |")
    lines.append("")
    
    # 深度分析
    # 10年期收益率变化分析
    if y10_change > 5:
        y10_desc = "10年期国债收益率大幅上行"
        y10_reason = "市场对经济前景预期乐观，或通胀预期升温，资金从避险资产流出"
    elif y10_change > 0:
        y10_desc = "10年期国债收益率小幅上行"
        y10_reason = "市场对经济前景谨慎乐观，或资金面边际收紧"
    elif y10_change > -5:
        y10_desc = "10年期国债收益率小幅下行"
        y10_reason = "市场对经济前景谨慎，或资金面宽松，避险需求增加"
    else:
        y10_desc = "10年期国债收益率大幅下行"
        y10_reason = "市场对经济前景悲观，避险情绪浓厚，资金集中流向安全资产"
    
    lines.append(f"**{y10_desc}，{y10_reason}。**")
    lines.append("")
    
    # 期限利差分析
    spread_start = y10_start - y1_start
    spread_end = y10_end - y1_end
    spread_change = (spread_end - spread_start) * 100  # 转换为bp
    
    if spread_change > 5:
        spread_desc = "期限利差显著走阔"
        spread_reason = "长端利率上行幅度大于短端，反映市场对长期经济增长预期改善"
    elif spread_change > 0:
        spread_desc = "期限利差小幅走阔"
        spread_reason = "长端利率上行，市场对长期经济预期略有改善"
    elif spread_change > -5:
        spread_desc = "期限利差小幅收窄"
        spread_reason = "短端利率相对坚挺，长端利率下行，反映市场对短期经济仍有信心，但对长期前景谨慎"
    else:
        spread_desc = "期限利差显著收窄"
        spread_reason = "长端利率下行幅度大于短端，反映市场对长期经济增长预期悲观"
    
    lines.append(f"**期限利差{spread_desc}，{spread_reason}。**")
    lines.append("")
    
    # 对债券投资者的影响
    if y10_change < 0:
        bond_impact = "债券价格上涨，持有债券类资产的投资者获得资本利得"
    else:
        bond_impact = "债券价格下跌，持有债券类资产的投资者面临净值回撤"
    
    lines.append(f"**{bond_impact}。**")
    
    return "\n".join(lines)


def _generate_investment_guidance_simple(data: dict, period_type: str) -> str:
    """投资指导深度分析（降级方案）。"""
    period_desc = "本周" if period_type == "周" else "本月"
    lines = []
    
    lines.append("## 三、投资思考")
    lines.append("")
    
    indices = data.get("indices", {})
    bond = data.get("bond_yields", {})
    
    hs300 = indices.get("hs300", {})
    zz1000 = indices.get("zz1000", {})
    sh50 = indices.get("sh50", {})
    cyb = indices.get("cyb", {})
    
    hs_change = hs300.get("change_pct", 0) if hs300 else 0
    zz_change = zz1000.get("change_pct", 0) if zz1000 else 0
    sh_change = sh50.get("change_pct", 0) if sh50 else 0
    cy_change = cyb.get("change_pct", 0) if cyb else 0
    
    # 基于市场特征给出针对性建议
    style_diff = zz_change - sh_change
    growth_value_diff = cy_change - sh_change
    
    # 市场整体建议
    if hs_change > 3:
        lines.append("**市场大幅上涨，投资者需保持理性：**")
        lines.append("")
        lines.append("- 短期涨幅较大，追高风险增加，建议控制仓位")
        lines.append("- 可考虑逐步兑现部分盈利，锁定收益")
        lines.append("- 避免情绪化追涨，坚持既定投资策略")
    elif hs_change < -3:
        lines.append("**市场明显下跌，投资者需保持耐心：**")
        lines.append("")
        lines.append("- 短期跌幅较大，恐慌性抛售往往不是最佳选择")
        lines.append("- 可审视持仓质量，优质资产下跌可能是布局机会")
        lines.append("- 坚持长期投资理念，避免被短期波动影响")
    else:
        lines.append("**市场波动相对温和，投资者可从容应对：**")
        lines.append("")
        lines.append("- 利用平稳期审视投资组合，确保与风险承受能力匹配")
        lines.append("- 关注市场风格变化，适时调整配置结构")
        lines.append("- 坚持定投策略，在市场波动中积累筹码")
    
    lines.append("")
    
    # 风格配置建议
    if style_diff > 2:
        lines.append("**小盘股表现强势，但需警惕风格切换风险：**")
        lines.append("")
        lines.append("- 小盘股弹性大但波动也大，不宜过度集中配置")
        lines.append("- 可适当参与，但需设置止盈止损")
        lines.append("- 保持大盘小盘的均衡配置，避免单一风格暴露")
    elif style_diff < -2:
        lines.append("**大盘股表现稳健，但需关注估值合理性：**")
        lines.append("")
        lines.append("- 大盘股稳定性好，适合作为底仓配置")
        lines.append("- 关注估值水平，避免在高位过度集中")
        lines.append("- 可适当配置小盘股，分散风格风险")
    else:
        lines.append("**大小盘表现相对均衡，投资者可灵活配置：**")
        lines.append("")
        lines.append("- 市场风格中性，可根据个人偏好配置")
        lines.append("- 建议保持大盘小盘的均衡比例")
        lines.append("- 关注个股质量，而非单纯追逐风格")
    
    lines.append("")
    
    # 债券配置建议
    y10_change = bond.get("10y_change_bp", 0) if bond else 0
    
    if y10_change < -5:
        lines.append("**债券收益率大幅下行，债券投资者需注意：**")
        lines.append("")
        lines.append("- 已持有债券获得资本利得，但未来上涨空间可能有限")
        lines.append("- 可考虑适度降低久期，锁定收益")
        lines.append("- 关注利率反转风险，避免过度乐观")
    elif y10_change > 5:
        lines.append("**债券收益率大幅上行，债券投资者可关注：**")
        lines.append("")
        lines.append("- 收益率上行意味着债券价格下跌，但未来配置价值提升")
        lines.append("- 可逐步增加债券配置，锁定较高收益率")
        lines.append("- 关注经济基本面变化，判断利率走势")
    else:
        lines.append("**债券收益率波动温和，投资者可保持现有配置：**")
        lines.append("")
        lines.append("- 债券作为资产配置的稳定器，应保持合理比例")
        lines.append("- 关注收益率曲线变化，适时调整久期")
        lines.append("- 坚持股债平衡配置，降低组合波动")
    
    lines.append("")
    lines.append("> **长期投资提醒：** 市场短期波动难以预测，坚持长期投资、分散配置是应对不确定性的有效方式。")
    
    return "\n".join(lines)
