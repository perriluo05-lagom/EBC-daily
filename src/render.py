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
# 一、昨夜今晨概览
# ---------------------------------------------------------------------------
def _section_overview(data: dict, interp: dict, narrative: dict) -> list[str]:
    ov = data.get("overview", {})
    dow, nas, sp = ov.get("dow", {}), ov.get("nasdaq", {}), ov.get("sp500", {})
    u10 = ov.get("us10y", {})
    a50, oil, gold = ov.get("a50", {}), ov.get("oil", {}), ov.get("gold", {})
    rows = [
        ["道指", _pct(dow), _num(dow, "close", 0, "点"), _src(dow)],
        ["纳指", _pct(nas), _num(nas, "close", 0, "点"), _src(nas)],
        ["标普500", _pct(sp), _num(sp, "close", 0, "点"), _src(sp)],
        ["美债10Y", _bp(u10, "change_bp"), _num(u10, "yield", 2, "%"), _src(u10)],
        ["富时A50", _pct(a50), _num(a50, "close", 0, ""), _src(a50)],
        ["原油", _pct(oil), _num(oil, "close", 2, ""), _src(oil)],
        ["黄金", _pct(gold), _num(gold, "close", 2, ""), _src(gold)],
    ]
    lines = [T.SECTION_OVERVIEW, *_table(["品种", "涨跌", "数值", "来源"], rows)]
    fallback = [T.LABEL_ANALYSIS, "", f"开盘定调：{interp.get('opening_call', '')}"]
    lines += _narrative_block(narrative, "overview", fallback)
    return lines


# ---------------------------------------------------------------------------
# 二、A股大盘温度
# ---------------------------------------------------------------------------
def _section_equity(data: dict, interp: dict, narrative: dict) -> list[str]:
    eq = data.get("equity", {})
    hs, zz = eq.get("hs300", {}), eq.get("zz1000", {})
    rows = [
        ["沪深300", _pct(hs), _num(hs, "close", 0, "点"), _src(hs)],
        ["中证1000", _pct(zz), _num(zz, "close", 0, "点"), _src(zz)],
    ]
    lines = [T.SECTION_EQUITY, *_table(["指数", "昨日涨跌", "收盘", "来源"], rows)]
    tv = eq.get("turnover", {})
    vol_str = base.yuan_billion(tv.get("value")) if isinstance(tv, dict) else base.MISSING
    chg_str = base.pct(tv.get("change_pct")) if isinstance(tv, dict) else base.MISSING
    lines.append(_line("全市场成交额", f"{vol_str}、环比 {chg_str}", _src(tv)))
    ad = eq.get("advance_decline", {})
    adv = ad.get("advancing") if isinstance(ad, dict) else None
    dec = ad.get("declining") if isinstance(ad, dict) else None
    ad_txt = f"涨 {adv} / 跌 {dec}" if (adv is not None and dec is not None) else base.MISSING
    lines.append(_line("涨跌家数", ad_txt, _src(ad)))
    lines.append(_line("风格偏向", eq.get("style", base.MISSING), eq.get("style_source", "")))
    fallback = [T.LABEL_ANALYSIS, "", f"解读：{interp.get('market_temperature', '')}"]
    lines += _narrative_block(narrative, "equity", fallback)
    return lines


# ---------------------------------------------------------------------------
# 三、ETF焦点
# ---------------------------------------------------------------------------
def _etf_table(etf: dict) -> list[str]:
    """ETF 合并表：宽基/策略行业合为一张表，带「组别」列，精简为 6 列。

    用「成交额」替代原「5日涨跌」——成交额直接来自 fund_etf_spot_em 一次全量返回，
    可靠不缺失；5日涨跌需逐只拉历史K线，本地代理环境下常缺失。保留核心的涨跌 /
    成交额（流动性）/ 资金净流入。
    """
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
    fb = []
    if interp.get("etf_flow_note"):
        fb.append(f"资金流向：{interp['etf_flow_note']}")
    if interp.get("etf_premium_note"):
        fb.append(f"溢价提示：{interp['etf_premium_note']}")
    fallback = [T.LABEL_ANALYSIS, "", *fb] if fb else []
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
    fallback = [T.LABEL_ANALYSIS, "", f"解读：{interp.get('bond_view', '')}"]
    lines += _narrative_block(narrative, "bond", fallback)
    return lines


# ---------------------------------------------------------------------------
# 五、可转债
# ---------------------------------------------------------------------------
def _section_cb(data: dict, interp: dict, narrative: dict) -> list[str]:
    cb = data.get("convertible", {})
    csi = cb.get("csi_index", {})
    avg_p = cb.get("avg_price")
    avg_prem = cb.get("avg_premium")
    pctile = cb.get("premium_percentile_3y")
    below = cb.get("below_par")
    rows = [
        ["中证转债指数", f"{_pct(csi)}（{_num(csi, 'close', 0, '点')}）", _src(csi)],
        ["全市场均价", f"{avg_p:.2f}元" if avg_p is not None else base.MISSING, cb.get("stats_source", "")],
        ["平均转股溢价率", f"{avg_prem:.1f}%" if avg_prem is not None else base.MISSING, cb.get("stats_source", "")],
        ["溢价率近3年分位", f"{pctile:.0f}%" if pctile is not None else base.MISSING, cb.get("stats_source", "")],
        ["破面只数", f"{int(below)}只" if below is not None else base.MISSING, cb.get("stats_source", "")],
        ["成交额", base.yuan_billion(cb.get("turnover")), cb.get("stats_source", "")],
    ]
    lines = [T.SECTION_CB, *_table(["指标", "数值", "来源"], rows)]
    fallback = [T.LABEL_ANALYSIS, "", f"解读：{interp.get('cb_valuation', '')}"]
    lines += _narrative_block(narrative, "convertible", fallback)
    event = interp.get("cb_event_note", "")
    if event:
        ev_src = cb.get("redeem_source", "")
        lines.append("")
        lines.append(f"事件提示：{event}（来源：{ev_src}）" if ev_src else f"事件提示：{event}")
    return lines


def render(data: dict, interp: dict, report_date: dt.date, trade_date, narrative: dict | None = None) -> str:
    narrative = narrative or {}
    sections = [
        f"# 【EBC Daily】{report_date.strftime('%Y-%m-%d')}",
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
