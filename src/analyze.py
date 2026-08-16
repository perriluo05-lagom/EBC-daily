# -*- coding: utf-8 -*-
"""规则层：只提取数据事实，不做判断。深度分析交给 LLM。

核心原则：
- 规则层只负责数据提取和格式化，输出"数据事实"
- 所有解读、判断、教育性内容都由 LLM 生成
- 未配置 LLM 时，只展示数据表格，不做简单判断
"""
from __future__ import annotations

from .fetchers import base


def _f(d, *path):
    """安全取嵌套数值;失败返回 None。"""
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return base.to_float(cur)


def analyze(data: dict) -> dict:
    """规则层：只提取关键事实，不做判断。"""
    return {
        "data_facts": extract_all_facts(data),
    }


def _fs(d) -> str:
    return d.get("source", "") if isinstance(d, dict) else ""


def _fp(d) -> str:
    return base.pct(d.get("pct")) if isinstance(d, dict) else base.MISSING


def _fn(d, key, nd=2, unit="") -> str:
    return base.num(d.get(key), nd, unit) if isinstance(d, dict) else base.MISSING


def _fb(d, key) -> str:
    return base.bp(d.get(key)) if isinstance(d, dict) else base.MISSING


def _yi(v) -> str:
    """元 → 亿元展示；None → 数据暂缺。"""
    if v is None:
        return base.MISSING
    try:
        return f"{float(v) / 1e8:,.2f}亿元"
    except (TypeError, ValueError):
        return base.MISSING


def _wan(v) -> str:
    """元 → 万元展示；None → 数据暂缺。"""
    if v is None:
        return base.MISSING
    try:
        return f"{float(v) / 1e4:,.2f}万元"
    except (TypeError, ValueError):
        return base.MISSING


def extract_all_facts(data: dict) -> str:
    """提取所有数据事实，供 LLM 分析。"""
    lines = []
    lines += _facts_global_market(data)
    lines += _facts_a_share_market(data)
    lines += _facts_etf(data)
    lines += _facts_bond(data)
    lines += _facts_convertible(data)
    return "\n".join(lines)


def _facts_global_market(data: dict) -> list[str]:
    """全球市场数据事实（仅保留对ETF投资者重要的指标）。"""
    ov = data.get("overview", {})
    L = ["【一、全球市场概览】"]
    
    # 美股
    dow, nas, sp = ov.get("dow", {}), ov.get("nasdaq", {}), ov.get("sp500", {})
    L.append(f"- 道指：{_fp(dow)}（{_fn(dow, 'close', 0, '点')}）（来源：{_fs(dow)}）")
    L.append(f"- 纳指：{_fp(nas)}（{_fn(nas, 'close', 0, '点')}）（来源：{_fs(nas)}）")
    L.append(f"- 标普500：{_fp(sp)}（{_fn(sp, 'close', 0, '点')}）（来源：{_fs(sp)}）")
    
    # 美债
    treasury = ov.get("us_treasury", {})
    L.append(f"- 美债10Y收益率：{_fn(treasury, '10y', 2, '%')}（变动{_fb(treasury, '10y_chg_bp')}）（来源：{_fs(treasury)}）")
    L.append(f"- 美债2Y收益率：{_fn(treasury, '2y', 2, '%')}（变动{_fb(treasury, '2y_chg_bp')}）（来源：{_fs(treasury)}）")
    
    # 大宗商品（仅保留原油和黄金）
    oil_wti = ov.get("oil_wti", {})
    gold = ov.get("gold", {})
    L.append(f"- WTI原油：{_fp(oil_wti)}（{_fn(oil_wti, 'close', 2, '美元/桶')}）（来源：{_fs(oil_wti)}）")
    L.append(f"- 黄金：{_fp(gold)}（{_fn(gold, 'close', 2, '美元/盎司')}）（来源：{_fs(gold)}）")
    
    # 汇率（仅保留在岸人民币）
    usd_cny = ov.get("usd_cny", {})
    L.append(f"- 在岸人民币(USD/CNY)：{_fn(usd_cny, 'rate', 4, '')}（来源：{_fs(usd_cny)}）")
    
    return L


def _facts_a_share_market(data: dict) -> list[str]:
    """A股市场数据事实。"""
    eq = data.get("equity", {})
    indices = eq.get("indices", {})
    L = ["【二、A股市场】"]
    
    # 核心指数
    sh50 = indices.get("sh50", {})
    hs300 = indices.get("hs300", {})
    zz500 = indices.get("zz500", {})
    zz1000 = indices.get("zz1000", {})
    cyb = indices.get("cyb", {})
    kc50 = indices.get("kc50", {})
    
    L.append(f"- 上证50：{_fp(sh50)}（{_fn(sh50, 'close', 0, '点')}）（来源：{_fs(sh50)}）")
    L.append(f"- 沪深300：{_fp(hs300)}（{_fn(hs300, 'close', 0, '点')}）（来源：{_fs(hs300)}）")
    L.append(f"- 中证500：{_fp(zz500)}（{_fn(zz500, 'close', 0, '点')}）（来源：{_fs(zz500)}）")
    L.append(f"- 中证1000：{_fp(zz1000)}（{_fn(zz1000, 'close', 0, '点')}）（来源：{_fs(zz1000)}）")
    L.append(f"- 创业板指：{_fp(cyb)}（{_fn(cyb, 'close', 0, '点')}）（来源：{_fs(cyb)}）")
    L.append(f"- 科创50：{_fp(kc50)}（{_fn(kc50, 'close', 0, '点')}）（来源：{_fs(kc50)}）")
    
    # 成交额（仅绝对值）
    tv = eq.get("turnover", {})
    vol = base.yuan_billion(tv.get("value")) if isinstance(tv, dict) else base.MISSING
    L.append(f"- 全市场成交额：{vol}（来源：{_fs(tv)}）")
    
    # 行业板块
    sectors = eq.get("sectors", [])
    if sectors:
        top_sectors = [s for s in sectors if s.get("rank") == "top"][:5]
        bottom_sectors = [s for s in sectors if s.get("rank") == "bottom"][:5]
        if top_sectors:
            top_txt = "、".join([f"{s.get('name', '')}({s.get('pct', 0):+.2f}%)" for s in top_sectors])
            L.append(f"- 涨幅前5行业：{top_txt}（来源：东方财富）")
        if bottom_sectors:
            bottom_txt = "、".join([f"{s.get('name', '')}({s.get('pct', 0):+.2f}%)" for s in bottom_sectors])
            L.append(f"- 跌幅前5行业：{bottom_txt}（来源：东方财富）")
    
    # 风格判断
    style_notes = eq.get("style_notes", [])
    if style_notes:
        L.append(f"- 风格特征：{'；'.join(style_notes)}")
    
    return L


def _facts_etf(data: dict) -> list[str]:
    """ETF数据事实。"""
    etf = data.get("etf", {})
    L = ["【三、ETF焦点】"]
    
    # 观察池ETF
    for gname, items in etf.get("groups", {}).items():
        L.append(f"- {gname}：")
        for it in items:
            prem = it.get("premium")
            prem_s = f"{prem:+.2f}%" if prem is not None else base.MISSING
            L.append(
                f"  · {it.get('name', '')}（{it.get('code', '')}） 昨日{_fp(it)}、"
                f"成交额{_yi(it.get('turnover'))}、溢价{prem_s}、"
                f"资金净流入{_yi(it.get('net_flow'))}、规模{_yi(it.get('scale'))}"
            )
    
    # 资金流向TOP3
    top = etf.get("flow_top3") or []
    if top:
        names = "、".join(t.get("name", "") for t in top[:3])
        L.append(f"- 全市场资金净流入TOP3：{names}")
    
    # 溢价异常
    anomalies = etf.get("premium_anomalies") or []
    if anomalies:
        anom_names = [f"{a.get('name', '')}({a.get('premium', 0):+.2f}%)" for a in anomalies[:3]]
        L.append(f"- 溢价异常ETF：{'、'.join(anom_names)}")
    
    return L


def _facts_bond(data: dict) -> list[str]:
    """债券市场数据事实。"""
    bd = data.get("bond", {})
    gov = bd.get("gov", {})
    spread = bd.get("term_spread")
    spread_s = f"{spread:.2f}%" if spread is not None else base.MISSING
    dr = bd.get("shibor", {})
    L = ["【四、债券市场】"]
    L.append(f"- 国债10Y：{_fn(gov, 'cn10y', 2, '%')}（变动{_fb(gov, 'cn10y_chg_bp')}）（来源：{_fs(gov)}）")
    L.append(f"- 国债1Y：{_fn(gov, 'cn1y', 2, '%')}（变动{_fb(gov, 'cn1y_chg_bp')}）（来源：{_fs(gov)}）")
    L.append(f"- 期限利差（10Y-1Y）：{spread_s}（来源：{bd.get('term_spread_source', '')}）")
    L.append(f"- Shibor 1周：{_fn(dr, 'rate', 2, '%')}（变动{_fb(dr, 'change_bp')}）（来源：{_fs(dr)}）")
    
    # 国债ETF
    for b in bd.get("bond_etfs", []):
        L.append(f"- {b.get('name', '')}：{base.pct(b.get('pct'))}（来源：{b.get('source', '')}）")
    
    return L


def _facts_convertible(data: dict) -> list[str]:
    """可转债数据事实。"""
    cb = data.get("convertible", {})
    avg_p = cb.get("avg_price")
    below = cb.get("below_par")
    L = ["【五、可转债】"]
    L.append(f"- 全市场均价：{f'{avg_p:.2f}元' if avg_p is not None else base.MISSING}（来源：{cb.get('stats_source', '')}）")
    L.append(f"- 破面只数：{f'{int(below)}只' if below is not None else base.MISSING}")
    L.append(f"- 成交额：{base.yuan_billion(cb.get('turnover'))}")
    
    redeem = cb.get("force_redeem") or []
    if redeem:
        L.append(f"- 强赎名单：{'、'.join(redeem[:5])}（来源：{cb.get('redeem_source', '')}）")
    
    return L


# 兼容旧接口
def facts_text(data: dict, interp: dict | None = None) -> str:
    """导出所有数据事实，供 LLM prompt 使用。"""
    return extract_all_facts(data)
