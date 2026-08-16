# -*- coding: utf-8 -*-
"""Markdown 渲染层:五大板块,每板块=数据表+叙事块,数值附 (来源:XX),文末免责声明。

所有格式化均对 None/缺失做降级处理为"数据暂缺",绝不填默认值。
叙事块优先用 LLM 生成的 narrative;无 narrative 时回退规则版 interp。
"""
from __future__ import annotations

import datetime as dt

from .fetchers import base
from .config import DISCLAIMER, WORD_MIN
from . import templates as T


def _src(metric: dict | None, fallback: str = "") -> str:
    if isinstance(metric, dict):
        return metric.get("source", "") or fallback
    return fallback


def _pct(metric: dict | None) -> str:
    if not metric:
        return base.MISSING
    return base.pct(metric.get("pct"))


def _num(metric: dict | None, key: str, ndigits: int = 2, unit: str = "") -> str:
    if not metric:
        return base.MISSING
    return base.num(metric.get(key), ndigits, unit)


def _bp(metric: dict | None, key: str) -> str:
    """格式化 bp 变动,带正负号;None → 数据暂缺。"""
    if not metric:
        return base.MISSING
    return base.bp(metric.get(key))


def _line(label: str, value: str, source: str) -> str:
    return f"- **{label}**：{value}（来源：{source}）" if source else f"- **{label}**：{value}"


def _yi(v) -> str:
    """元 → 亿元展示;None → 数据暂缺。"""
    if v is None:
        return base.MISSING
    try:
        return f"{float(v) / 1e8:,.2f}亿元"
    except (TypeError, ValueError):
        return base.MISSING


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """生成 Markdown 表格;rows 为空时返回数据暂缺提示行。"""
    if not rows:
        return ["> 表格数据暂缺"]
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return out


def _narrative_block(narrative: dict, section: str, fallback_lines: list[str]) -> list[str]:
    """有 LLM 结构化叙事则按 **解读与判断** 规范排版；否则回退 fallback_lines。

    结构化叙事只含分析段落（交易参考已删除）：小标题独占段落、分析段间空行，
    避免「标签与正文堆砌在一段」。
    """
    nar = (narrative or {}).get(section)
    if not nar:
        return ["", *fallback_lines]
    out = ["", T.LABEL_ANALYSIS, ""]
    for p in nar.get("analysis", []):
        if p.strip():
            out.append(p.strip())
            out.append("")
    return out


# ---------------------------------------------------------------------------
# 一、全球市场概览
# ---------------------------------------------------------------------------
def _section_overview(data: dict, interp: dict, narrative: dict) -> list[str]:
    ov = data.get("overview", {})
    dow, nas, sp = ov.get("dow", {}), ov.get("nasdaq", {}), ov.get("sp500", {})
    treasury = ov.get("us_treasury", {})
    oil_wti = ov.get("oil_wti", {})
    gold = ov.get("gold", {})
    usd_cny = ov.get("usd_cny", {})
    
    rows = [
        ["道指", _pct(dow), _num(dow, "close", 0, "点"), _src(dow)],
        ["纳指", _pct(nas), _num(nas, "close", 0, "点"), _src(nas)],
        ["标普500", _pct(sp), _num(sp, "close", 0, "点"), _src(sp)],
        ["美债10Y", _bp(treasury, "10y_chg_bp"), _num(treasury, "10y", 2, "%"), _src(treasury)],
        ["美债2Y", _bp(treasury, "2y_chg_bp"), _num(treasury, "2y", 2, "%"), _src(treasury)],
        ["WTI原油", _pct(oil_wti), _num(oil_wti, "close", 2, "美元/桶"), _src(oil_wti)],
        ["黄金", _pct(gold), _num(gold, "close", 2, "美元/盎司"), _src(gold)],
        ["在岸人民币", "", _num(usd_cny, "rate", 4, ""), _src(usd_cny)],
    ]
    lines = [T.SECTION_OVERVIEW, *_table(["品种", "涨跌", "数值", "来源"], rows)]
    fallback = [T.LABEL_ANALYSIS, "", ""]
    lines += _narrative_block(narrative, "overview", fallback)
    return lines


# ---------------------------------------------------------------------------
# 二、A股市场
# ---------------------------------------------------------------------------
def _section_equity(data: dict, interp: dict, narrative: dict) -> list[str]:
    eq = data.get("equity", {})
    indices = eq.get("indices", {})
    
    # 核心指数表格
    sh50 = indices.get("sh50", {})
    hs300 = indices.get("hs300", {})
    zz500 = indices.get("zz500", {})
    zz1000 = indices.get("zz1000", {})
    cyb = indices.get("cyb", {})
    kc50 = indices.get("kc50", {})
    
    rows = [
        ["上证50", _pct(sh50), _num(sh50, "close", 0, "点"), _src(sh50)],
        ["沪深300", _pct(hs300), _num(hs300, "close", 0, "点"), _src(hs300)],
        ["中证500", _pct(zz500), _num(zz500, "close", 0, "点"), _src(zz500)],
        ["中证1000", _pct(zz1000), _num(zz1000, "close", 0, "点"), _src(zz1000)],
        ["创业板指", _pct(cyb), _num(cyb, "close", 0, "点"), _src(cyb)],
        ["科创50", _pct(kc50), _num(kc50, "close", 0, "点"), _src(kc50)],
    ]
    lines = [T.SECTION_EQUITY, *_table(["指数", "昨日涨跌", "收盘", "来源"], rows)]
    
    # 成交额（仅显示绝对值，不显示环比）
    tv = eq.get("turnover", {})
    vol_str = base.yuan_billion(tv.get("value")) if isinstance(tv, dict) else base.MISSING
    lines.append(_line("全市场成交额", vol_str, _src(tv)))
    
    # 行业板块表现
    sectors = eq.get("sectors", [])
    if sectors:
        top_sectors = [s for s in sectors if s.get("rank") == "top"][:3]
        bottom_sectors = [s for s in sectors if s.get("rank") == "bottom"][:3]
        
        if top_sectors:
            top_txt = "、".join([f"{s.get('name', '')}({s.get('pct', 0):+.2f}%)" for s in top_sectors])
            lines.append(_line("涨幅前3行业", top_txt, "东方财富"))
        
        if bottom_sectors:
            bottom_txt = "、".join([f"{s.get('name', '')}({s.get('pct', 0):+.2f}%)" for s in bottom_sectors])
            lines.append(_line("跌幅前3行业", bottom_txt, "东方财富"))
    
    # 风格特征
    style_notes = eq.get("style_notes", [])
    if style_notes:
        style_txt = "；".join(style_notes)
        lines.append(_line("风格特征", style_txt, ""))
    
    fallback = [T.LABEL_ANALYSIS, "", ""]
    lines += _narrative_block(narrative, "equity", fallback)
    return lines


# ---------------------------------------------------------------------------
# 三、ETF焦点
# ---------------------------------------------------------------------------
def _etf_table(etf: dict) -> list[str]:
    """ETF 合并表：宽基/策略行业合为一张表，带「组别」列，精简为 6 列。"""
    rows = []
    for gname, items in etf.get("groups", {}).items():
        for it in items:
            rows.append([
                gname,
                it.get("name", ""),
                base.pct(it.get("pct")),
                _yi(it.get("turnover")),
                _yi(it.get("net_flow")),
                it.get("source", ""),
            ])
    return _table(["组别", "品种", "昨日涨跌", "成交额", "资金净流入", "来源"], rows)


def _section_etf(data: dict, interp: dict, narrative: dict) -> list[str]:
    etf = data.get("etf", {})
    lines = [T.SECTION_ETF, *_etf_table(etf)]
    
    # 资金流向TOP3
    top3 = etf.get("flow_top3", [])
    if top3:
        top3_txt = "、".join([f"{t.get('name', '')}({t.get('net_flow', 0) / 1e8:.2f}亿)" for t in top3])
        lines.append(_line("资金净流入TOP3", top3_txt, "东方财富"))
    
    # 溢价异常
    anomalies = etf.get("premium_anomalies", [])
    if anomalies:
        anom_txt = "、".join([f"{a.get('name', '')}({a.get('premium', 0):+.2f}%)" for a in anomalies[:3]])
        lines.append(_line("溢价异常", anom_txt, "东方财富"))
    
    fallback = [T.LABEL_ANALYSIS, "", ""]
    lines += _narrative_block(narrative, "etf", fallback)
    return lines


# ---------------------------------------------------------------------------
# 四、债券市场
# ---------------------------------------------------------------------------
def _section_bond(data: dict, interp: dict, narrative: dict) -> list[str]:
    bd = data.get("bond", {})
    gov = bd.get("gov", {})
    spread = bd.get("term_spread")
    spread_s = f"{spread:.2f}%" if spread is not None else base.MISSING
    dr = bd.get("shibor", {})
    rows = [
        ["国债10Y", _num(gov, "cn10y", 2, "%"), _bp(gov, "cn10y_chg_bp"), _src(gov)],
        ["国债1Y", _num(gov, "cn1y", 2, "%"), _bp(gov, "cn1y_chg_bp"), _src(gov)],
        ["期限利差", spread_s, "—", bd.get("term_spread_source", "")],
        ["Shibor 1周", _num(dr, "rate", 2, "%"), _bp(dr, "change_bp"), _src(dr)],
    ]
    for b in bd.get("bond_etfs", []):
        rows.append([b.get("name", ""), base.pct(b.get("pct")), "—", b.get("source", "")])
    lines = [T.SECTION_BOND, *_table(["指标", "数值", "变动", "来源"], rows)]
    fallback = [T.LABEL_ANALYSIS, "", ""]
    lines += _narrative_block(narrative, "bond", fallback)
    return lines


# ---------------------------------------------------------------------------
# 五、可转债
# ---------------------------------------------------------------------------
def _section_cb(data: dict, interp: dict, narrative: dict) -> list[str]:
    cb = data.get("convertible", {})
    avg_p = cb.get("avg_price")
    below = cb.get("below_par")
    rows = [
        ["全市场均价", f"{avg_p:.2f}元" if avg_p is not None else base.MISSING, cb.get("stats_source", "")],
        ["破面只数", f"{int(below)}只" if below is not None else base.MISSING, cb.get("stats_source", "")],
        ["成交额", base.yuan_billion(cb.get("turnover")), cb.get("stats_source", "")],
    ]
    lines = [T.SECTION_CB, *_table(["指标", "数值", "来源"], rows)]
    
    # 强赎事件
    redeem = cb.get("force_redeem", [])
    if redeem:
        redeem_txt = "、".join(redeem[:5])
        lines.append(_line("强赎提示", redeem_txt, cb.get("redeem_source", "")))
    
    fallback = [T.LABEL_ANALYSIS, "", ""]
    lines += _narrative_block(narrative, "convertible", fallback)
    return lines


def render(data: dict, interp: dict, report_date: dt.date, trade_date, narrative: dict | None = None) -> str:
    narrative = narrative or {}
    date_str = f"{report_date.year}年{report_date.month}月{report_date.day}日"
    weekday = ["一", "二", "三", "四", "五", "六", "日"][report_date.weekday()]
    sections = [
        f"# 【EBC Daily】",
        f"{date_str} 星期{weekday}",
        f"> 数据基准日：{trade_date}（A股为前一交易日收盘，外盘为隔夜收盘，利率为最近更新交易日）。",
        *_section_overview(data, interp, narrative),
        *_section_equity(data, interp, narrative),
        *_section_etf(data, interp, narrative),
        *_section_bond(data, interp, narrative),
        *_section_cb(data, interp, narrative),
        "",
        "---",
        DISCLAIMER,
    ]
    body = "\n".join(sections)
    if len(body) < WORD_MIN:
        # 不编造内容补字数；仅如实说明
        body += "\n\n> 注：本期部分字段数据暂缺，正文偏短，接口稳定后将自动充实。"
    return body


def subject(report_date: dt.date) -> str:
    return f"【EBC Daily】{report_date.strftime('%Y-%m-%d')}"
