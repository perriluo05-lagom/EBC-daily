# -*- coding: utf-8 -*-
"""Markdown 渲染层:拼装五大板块,每数值附 (来源:XX),文末加免责声明。

所有格式化均对 None/缺失做降级处理为"数据暂缺",绝不填默认值。
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
    return f"- {label}:{value}（来源：{source}）" if source else f"- {label}:{value}"


def _pair(label: str, value: str, source: str) -> str:
    return _line(label, value, source)


def _section_overview(data: dict, interp: dict) -> list[str]:
    ov = data.get("overview", {})
    lines = [T.SECTION_OVERVIEW]
    dow, nas, sp = ov.get("dow", {}), ov.get("nasdaq", {}), ov.get("sp500", {})
    lines.append(_line(
        "美股",
        f"道指 {_pct(dow)}（{_num(dow, 'close', 0, '点')}）、纳指 {_pct(nas)}、标普500 {_pct(sp)}",
        _src(dow) or _src(nas),
    ))
    u10 = ov.get("us10y", {})
    u10y_v = _num(u10, "yield", 2, "%")
    u10y_c = _bp(u10, "change_bp")
    u10y_txt = f"{u10y_v}（{u10y_c}）" if u10y_v != base.MISSING else base.MISSING
    lines.append(_line("美债10Y收益率", u10y_txt, _src(u10)))
    a50, oil, gold = ov.get("a50", {}), ov.get("oil", {}), ov.get("gold", {})
    lines.append(_line("外盘期货", f"富时A50 {_pct(a50)}、原油 {_pct(oil)}、黄金 {_pct(gold)}", _src(a50)))
    lines.append(f"{T.LABEL_OPENING}:{interp.get('opening_call', '')}")
    return lines


def _section_equity(data: dict, interp: dict) -> list[str]:
    eq = data.get("equity", {})
    hs, zz = eq.get("hs300", {}), eq.get("zz1000", {})
    lines = [T.SECTION_EQUITY]
    lines.append(_line(
        "核心指数",
        f"沪深300 {_pct(hs)}（{_num(hs, 'close', 0, '点')}）、中证1000 {_pct(zz)}（{_num(zz, 'close', 0, '点')}）",
        _src(hs),
    ))
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
    lines.append(f"{T.LABEL_INTERPRET}:{interp.get('market_temperature', '')}")
    return lines


def _section_etf(data: dict, interp: dict) -> list[str]:
    etf = data.get("etf", {})
    lines = [T.SECTION_ETF]
    for gname, items in etf.get("groups", {}).items():
        parts = []
        for it in items:
            p = base.pct(it.get("pct"))
            prem = it.get("premium")
            prem_s = f"（溢价{prem:+.2f}%）" if prem is not None else ""
            parts.append(f"{it.get('name', '')}{p}{prem_s}")
        lines.append(_line(gname, "、".join(parts) if parts else base.MISSING, etf.get("source", "")))
    lines.append(_line("资金流向", interp.get("etf_flow_note", ""), etf.get("source", "")))
    lines.append(_line("溢价提示", interp.get("etf_premium_note", ""), etf.get("source", "")))
    return lines


def _section_bond(data: dict, interp: dict) -> list[str]:
    bd = data.get("bond", {})
    gov = bd.get("gov", {})
    lines = [T.SECTION_BOND]
    spread = bd.get("term_spread")
    spread_s = f"{spread:.2f}%" if spread is not None else base.MISSING
    lines.append(_line(
        "国债收益率",
        f"10Y {_num(gov, 'cn10y', 2, '%')}（{_bp(gov, 'cn10y_chg_bp')}）、"
        f"1Y {_num(gov, 'cn1y', 2, '%')}（{_bp(gov, 'cn1y_chg_bp')}）、期限利差 {spread_s}",
        _src(gov),
    ))
    dr = bd.get("shibor", {})
    lines.append(_line("Shibor 1周", f"{_num(dr, 'rate', 2, '%')}（{_bp(dr, 'change_bp')}）", _src(dr)))
    betfs = bd.get("bond_etfs", [])
    if betfs:
        parts = [f"{b.get('name', '')}{base.pct(b.get('pct'))}" for b in betfs]
        lines.append(_line("国债ETF", "、".join(parts), betfs[0].get("source", "")))
    lines.append(f"{T.LABEL_INTERPRET}:{interp.get('bond_view', '')}")
    lines.append(f"{T.LABEL_REFERENCE}:{interp.get('bond_reference', '')}")
    return lines


def _section_cb(data: dict, interp: dict) -> list[str]:
    cb = data.get("convertible", {})
    lines = [T.SECTION_CB]
    csi = cb.get("csi_index", {})
    lines.append(_line("中证转债指数", f"{_pct(csi)}（{_num(csi, 'close', 0, '点')}）", _src(csi)))
    avg_p = cb.get("avg_price")
    avg_prem = cb.get("avg_premium")
    pctile = cb.get("premium_percentile_3y")
    avg_p_s = f"{avg_p:.2f}元" if avg_p is not None else base.MISSING
    prem_s = f"{avg_prem:.1f}%" if avg_prem is not None else base.MISSING
    pctile_s = f"、近3年分位 {pctile:.0f}%" if pctile is not None else ""
    lines.append(_line("估值指标", f"均价 {avg_p_s}、平均转股溢价率 {prem_s}{pctile_s}", cb.get("stats_source", "")))
    below = cb.get("below_par")
    turnover = cb.get("turnover")
    below_s = f"{int(below)}只" if below is not None else base.MISSING
    turn_s = base.yuan_billion(turnover)
    lines.append(_line("破面与成交", f"破面 {below_s}、成交额 {turn_s}", cb.get("stats_source", "")))
    lines.append(f"{T.LABEL_INTERPRET}:{interp.get('cb_valuation', '')}")
    lines.append(_line("事件提示", interp.get("cb_event_note", ""), cb.get("redeem_source", "")))
    return lines


def render(data: dict, interp: dict, report_date: dt.date, trade_date) -> str:
    sections = [
        f"# 【EBC Daily】{report_date.strftime('%Y-%m-%d')}",
        f"> 数据基准日:{trade_date}（A股为前一交易日收盘,外盘为隔夜收盘,利率为最近更新交易日）。",
        *_section_overview(data, interp),
        *_section_equity(data, interp),
        *_section_etf(data, interp),
        *_section_bond(data, interp),
        *_section_cb(data, interp),
        "",
        "---",
        DISCLAIMER,
    ]
    body = "\n".join(sections)
    if len(body) < WORD_MIN:
        # 不编造内容补字数;仅如实说明
        body += "\n\n> 注:本期部分字段数据暂缺,正文偏短,接口稳定后将自动充实。"
    return body


def subject(report_date: dt.date) -> str:
    return f"【EBC Daily】{report_date.strftime('%Y-%m-%d')}"
