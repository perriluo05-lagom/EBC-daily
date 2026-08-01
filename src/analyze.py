# -*- coding: utf-8 -*-
"""规则解读层:基于真实数据用透明规则推导"解读"与"参考思路"。

核心合规:所有判断由真实数值触发;任何关键数值缺失时输出"数据不足,暂不解读",
绝不臆造结论。措辞统一用"可关注/可以留意",禁绝对化指令。
"""
from __future__ import annotations

from .fetchers import base
from .config import (
    TH_VOLUME_UP, TH_VOLUME_DOWN, TH_INDEX_BIG, TH_INDEX_FLAT,
    TH_STYLE_DIFF, TH_YIELD_BP, TH_SHIBOR_BP, TH_CB_HIGH_PCT, TH_CB_LOW_PCT,
    POLICY_RATE_7D, POLICY_RATE_7D_SRC,
)


def _f(d, *path):
    """安全取嵌套数值;失败返回 None。"""
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return base.to_float(cur)


def opening_call(data: dict) -> str:
    """板块一开盘定调(基于隔夜外盘真实数据)。"""
    dow = _f(data, "overview", "dow", "pct")
    us10y_chg = _f(data, "overview", "us10y", "change_bp")
    a50 = _f(data, "overview", "a50", "pct")
    if dow is None and us10y_chg is None and a50 is None:
        return "数据不足,暂不解读"
    parts = []
    if dow is not None:
        parts.append("美股偏强" if dow > 0.5 else ("美股偏弱" if dow < -0.5 else "美股震荡"))
    if us10y_chg is not None:
        parts.append("美债利率上行" if us10y_chg > TH_YIELD_BP else ("美债利率下行" if us10y_chg < -TH_YIELD_BP else "美债利率变动不大"))
    bias = ""
    if a50 is not None:
        bias = f",A50夜盘{'走高' if a50 > 0.3 else ('走低' if a50 < -0.3 else '平稳')},A股或{'高开' if a50 > 0 else ('低开' if a50 < 0 else '平开')}概率偏大"
    return "、".join(parts) + bias if parts else (bias.lstrip(",") or "数据不足,暂不解读")


def market_temperature(data: dict) -> str:
    """板块二市场温度(沪深300涨幅 + 成交额环比 + 涨跌家数比)。"""
    hs = _f(data, "equity", "hs300", "pct")
    vol_chg = _f(data, "equity", "turnover", "change_pct")
    adv = _f(data, "equity", "advance_decline", "advancing")
    dec = _f(data, "equity", "advance_decline", "declining")
    if hs is None:
        return "数据不足,暂不解读"
    vol_word = ""
    if vol_chg is not None:
        vol_word = "放量" if vol_chg > TH_VOLUME_UP else ("缩量" if vol_chg < TH_VOLUME_DOWN else "成交平稳")
    ad_word = ""
    if adv is not None and dec is not None and (adv + dec) > 0:
        ratio = adv / (adv + dec)
        ad_word = "普涨" if ratio > 0.7 else ("普跌" if ratio < 0.3 else "涨跌互现")
    if hs > TH_INDEX_BIG and (vol_word in ("放量", "")):
        return f"沪深300 {hs:+.2f}%,{'量价齐升、情绪偏热' if vol_word == '放量' else '情绪偏暖'}{('、' + ad_word) if ad_word else ''}"
    if hs < -TH_INDEX_BIG:
        return f"沪深300 {hs:+.2f}%,{'放量下跌、情绪偏冷' if vol_word == '放量' else '情绪偏弱'}{('、' + ad_word) if ad_word else ''},观望为主"
    if abs(hs) <= TH_INDEX_FLAT:
        return f"沪深300 {hs:+.2f}%,窄幅震荡、方向待选{(',成交' + vol_word) if vol_word else ''}"
    return f"沪深300 {hs:+.2f}%,{vol_word or '情绪中性'}{('、' + ad_word) if ad_word else ''}"


def style_note(data: dict) -> str:
    return data.get("equity", {}).get("style", "数据暂缺")


def etf_flow_note(data: dict) -> str:
    """板块三资金集中方向。"""
    top = data.get("etf", {}).get("flow_top3") or []
    names = [t.get("name") for t in top if t.get("name")]
    if not names:
        return "数据不足,暂不解读"
    return f"资金净流入集中在 {('、'.join(names[:3]))},可关注相关赛道资金延续性"


def etf_premium_note(data: dict) -> str:
    """板块三溢价异常提示。"""
    anom = data.get("etf", {}).get("premium_anomalies") or []
    if not anom:
        return "无明显溢价异常"
    names = [f"{a.get('name')}({a.get('premium'):+.2f}%)" for a in anom if a.get("premium") is not None]
    return f"{'、'.join(names[:3])}溢价偏离较大,可留意申赎套利与折溢价回归"


def bond_view(data: dict) -> str:
    """板块四债市核心矛盾(长端利率 + 资金面 + 期限利差)。"""
    chg10 = _f(data, "bond", "gov", "cn10y_chg_bp")
    sh_chg = _f(data, "bond", "shibor", "change_bp")
    sh = _f(data, "bond", "shibor", "rate")
    spread = _f(data, "bond", "term_spread")
    if chg10 is None and sh_chg is None and spread is None:
        return "数据不足,暂不解读"
    parts = []
    if chg10 is not None:
        parts.append("长端利率上行" if chg10 > TH_YIELD_BP else ("长端利率下行" if chg10 < -TH_YIELD_BP else "长端利率窄幅波动"))
    if sh_chg is not None:
        parts.append("资金面边际收敛" if sh_chg > TH_SHIBOR_BP else ("资金面边际宽松" if sh_chg < -TH_SHIBOR_BP else "资金面平稳"))
    elif sh is not None:
        parts.append(f"Shibor 1周 {sh:.2f}%,高于7天逆回购利率{POLICY_RATE_7D}%(来源:{POLICY_RATE_7D_SRC})、资金面偏紧" if sh > POLICY_RATE_7D + 0.1 else "资金面接近政策利率、相对宽松")
    if spread is not None:
        if spread < 0.3:
            parts.append("期限利差极度平坦")
        elif spread > 1.2:
            parts.append("期限利差较陡")
    return "、".join(parts) if parts else "债市窄幅波动"


def bond_reference(data: dict) -> str:
    chg10 = _f(data, "bond", "gov", "cn10y_chg_bp")
    sh_chg = _f(data, "bond", "shibor", "change_bp")
    if chg10 is None and sh_chg is None:
        return "数据不足,可留意后续利率走势再行判断"
    tightening = (chg10 is not None and chg10 > TH_YIELD_BP) or (sh_chg is not None and sh_chg > TH_SHIBOR_BP)
    easing = (chg10 is not None and chg10 < -TH_YIELD_BP) or (sh_chg is not None and sh_chg < -TH_SHIBOR_BP)
    if tightening:
        return "利率上行叠加资金收敛,债市或承压,可以留意短久期、高等级品种的防御价值"
    if easing:
        return "利率下行叠加资金宽松,债市环境偏暖,可关注中长久期利率债的资本利得机会"
    return "利率与资金面变化不大,可以留意票息策略与适度杠杆的平衡"


def cb_valuation(data: dict) -> str:
    """板块五可转债估值(均价 + 溢价率分位)。"""
    prem = _f(data, "convertible", "avg_premium")
    pctile = _f(data, "convertible", "premium_percentile_3y")
    below = _f(data, "convertible", "below_par")
    if prem is None and pctile is None:
        return "数据不足,暂不解读"
    bits = []
    if pctile is not None:
        if pctile > TH_CB_HIGH_PCT:
            bits.append(f"转股溢价率处近3年 {pctile:.0f} 分位、估值偏高,注意回撤")
        elif pctile < TH_CB_LOW_PCT:
            bits.append(f"转股溢价率处近3年 {pctile:.0f} 分位、估值偏低,弹性较好")
        else:
            bits.append(f"转股溢价率处近3年 {pctile:.0f} 分位、估值中性")
    elif prem is not None:
        bits.append(f"平均转股溢价率 {prem:.1f}%")
    if below is not None and below > 100:
        bits.append(f"破面券 {below} 只、低价券增多,可留意下修博弈")
    return "、".join(bits) if bits else "数据不足,暂不解读"


def cb_event_note(data: dict) -> str:
    redeem = data.get("convertible", {}).get("force_redeem") or []
    if not redeem:
        return "当日无明显强赎事件提示"
    return f"强赎提示:{('、'.join(redeem[:5]))}等,持有者需关注最后转股/交易日,避免强赎损失"


def analyze(data: dict) -> dict:
    return {
        "opening_call": opening_call(data),
        "market_temperature": market_temperature(data),
        "style_note": style_note(data),
        "etf_flow_note": etf_flow_note(data),
        "etf_premium_note": etf_premium_note(data),
        "bond_view": bond_view(data),
        "bond_reference": bond_reference(data),
        "cb_valuation": cb_valuation(data),
        "cb_event_note": cb_event_note(data),
    }


# ---------------------------------------------------------------------------
# facts_text:导出结构化"数据事实 + 规则结论"摘要,供 LLM prompt 使用
# ---------------------------------------------------------------------------
# 仅复述真实采集数据与规则结论,不新增任何数值;LLM 只能引用此处出现的信息。

def _fs(d) -> str:
    return d.get("source", "") if isinstance(d, dict) else ""


def _fp(d) -> str:
    return base.pct(d.get("pct")) if isinstance(d, dict) else base.MISSING


def _fn(d, key, nd=2, unit="") -> str:
    return base.num(d.get(key), nd, unit) if isinstance(d, dict) else base.MISSING


def _fb(d, key) -> str:
    return base.bp(d.get(key)) if isinstance(d, dict) else base.MISSING


def _yi(v) -> str:
    """元 → 亿元展示;None → 数据暂缺。"""
    if v is None:
        return base.MISSING
    try:
        return f"{float(v) / 1e8:,.2f}亿元"
    except (TypeError, ValueError):
        return base.MISSING


def _facts_overview(data: dict, interp: dict) -> list[str]:
    ov = data.get("overview", {})
    dow, nas, sp = ov.get("dow", {}), ov.get("nasdaq", {}), ov.get("sp500", {})
    u10 = ov.get("us10y", {})
    a50, oil, gold = ov.get("a50", {}), ov.get("oil", {}), ov.get("gold", {})
    L = ["【一、昨夜今晨概览】"]
    L.append(f"- 道指:{_fp(dow)}({_fn(dow, 'close', 0, '点')})(来源:{_fs(dow)})")
    L.append(f"- 纳指:{_fp(nas)}({_fn(nas, 'close', 0, '点')})(来源:{_fs(nas)})")
    L.append(f"- 标普500:{_fp(sp)}({_fn(sp, 'close', 0, '点')})(来源:{_fs(sp)})")
    L.append(f"- 美债10Y收益率:{_fn(u10, 'yield', 2, '%')}(变动{_fb(u10, 'change_bp')})(来源:{_fs(u10)})")
    L.append(f"- 富时A50:{_fp(a50)}({_fn(a50, 'close', 0, '')})(来源:{_fs(a50)})")
    L.append(f"- 原油:{_fp(oil)}({_fn(oil, 'close', 2, '')})(来源:{_fs(oil)})")
    L.append(f"- 黄金:{_fp(gold)}({_fn(gold, 'close', 2, '')})(来源:{_fs(gold)})")
    L.append(f"- 规则结论·开盘定调:{interp.get('opening_call', '')}")
    return L


def _facts_equity(data: dict, interp: dict) -> list[str]:
    eq = data.get("equity", {})
    hs, zz = eq.get("hs300", {}), eq.get("zz1000", {})
    tv = eq.get("turnover", {})
    ad = eq.get("advance_decline", {})
    adv = ad.get("advancing") if isinstance(ad, dict) else None
    dec = ad.get("declining") if isinstance(ad, dict) else None
    ad_txt = f"涨{adv}/跌{dec}" if (adv is not None and dec is not None) else base.MISSING
    vol = base.yuan_billion(tv.get("value")) if isinstance(tv, dict) else base.MISSING
    chg = base.pct(tv.get("change_pct")) if isinstance(tv, dict) else base.MISSING
    L = ["【二、A股大盘温度】"]
    L.append(f"- 沪深300:{_fp(hs)}({_fn(hs, 'close', 0, '点')})(来源:{_fs(hs)})")
    L.append(f"- 中证1000:{_fp(zz)}({_fn(zz, 'close', 0, '点')})(来源:{_fs(zz)})")
    L.append(f"- 全市场成交额:{vol}(环比{chg})(来源:{_fs(tv)})")
    L.append(f"- 涨跌家数:{ad_txt}(来源:{_fs(ad)})")
    L.append(f"- 风格偏向:{eq.get('style', base.MISSING)}")
    L.append(f"- 规则结论·市场温度:{interp.get('market_temperature', '')}")
    return L


def _facts_etf(data: dict, interp: dict) -> list[str]:
    etf = data.get("etf", {})
    L = ["【三、ETF焦点】"]
    for gname, items in etf.get("groups", {}).items():
        L.append(f"- {gname}:")
        for it in items:
            prem = it.get("premium")
            prem_s = f"{prem:+.2f}%" if prem is not None else base.MISSING
            L.append(
                f"  · {it.get('name', '')}({it.get('code', '')}) 昨日{_fp(it)}、"
                f"5日{base.pct(it.get('pct_5d'))}、溢价{prem_s}、"
                f"资金净流入{_yi(it.get('net_flow'))}、规模{_yi(it.get('scale'))}"
            )
    top = etf.get("flow_top3") or []
    if top:
        names = "、".join(t.get("name", "") for t in top[:3])
        L.append(f"- 全市场资金净流入TOP3:{names}")
    L.append(f"- 规则结论·资金流向:{interp.get('etf_flow_note', '')}")
    L.append(f"- 规则结论·溢价提示:{interp.get('etf_premium_note', '')}")
    return L


def _facts_bond(data: dict, interp: dict) -> list[str]:
    bd = data.get("bond", {})
    gov = bd.get("gov", {})
    spread = bd.get("term_spread")
    spread_s = f"{spread:.2f}%" if spread is not None else base.MISSING
    dr = bd.get("shibor", {})
    L = ["【四、债券市场】"]
    L.append(f"- 国债10Y:{_fn(gov, 'cn10y', 2, '%')}(变动{_fb(gov, 'cn10y_chg_bp')})(来源:{_fs(gov)})")
    L.append(f"- 国债1Y:{_fn(gov, 'cn1y', 2, '%')}(变动{_fb(gov, 'cn1y_chg_bp')})(来源:{_fs(gov)})")
    L.append(f"- 期限利差(10Y-1Y):{spread_s}(来源:{bd.get('term_spread_source', '')})")
    L.append(f"- Shibor 1周:{_fn(dr, 'rate', 2, '%')}(变动{_fb(dr, 'change_bp')})(来源:{_fs(dr)})")
    for b in bd.get("bond_etfs", []):
        L.append(f"- {b.get('name', '')}:{base.pct(b.get('pct'))}(来源:{b.get('source', '')})")
    L.append(f"- 规则结论·债市核心矛盾:{interp.get('bond_view', '')}")
    L.append(f"- 规则结论·参考思路:{interp.get('bond_reference', '')}")
    return L


def _facts_cb(data: dict, interp: dict) -> list[str]:
    cb = data.get("convertible", {})
    csi = cb.get("csi_index", {})
    avg_p = cb.get("avg_price")
    avg_prem = cb.get("avg_premium")
    pctile = cb.get("premium_percentile_3y")
    below = cb.get("below_par")
    L = ["【五、可转债】"]
    L.append(f"- 中证转债指数:{_fp(csi)}({_fn(csi, 'close', 0, '点')})(来源:{_fs(csi)})")
    L.append(f"- 全市场均价:{f'{avg_p:.2f}元' if avg_p is not None else base.MISSING}(来源:{cb.get('stats_source', '')})")
    L.append(f"- 平均转股溢价率:{f'{avg_prem:.1f}%' if avg_prem is not None else base.MISSING}")
    L.append(f"- 溢价率近3年分位:{f'{pctile:.0f}%' if pctile is not None else base.MISSING}")
    L.append(f"- 破面只数:{f'{int(below)}只' if below is not None else base.MISSING}")
    L.append(f"- 成交额:{base.yuan_billion(cb.get('turnover'))}")
    redeem = cb.get("force_redeem") or []
    if redeem:
        L.append(f"- 强赎名单:{'、'.join(redeem[:5])}(来源:{cb.get('redeem_source', '')})")
    L.append(f"- 规则结论·估值:{interp.get('cb_valuation', '')}")
    L.append(f"- 规则结论·事件提示:{interp.get('cb_event_note', '')}")
    return L


def facts_text(data: dict, interp: dict | None = None) -> str:
    """导出五板块"数据事实 + 规则结论"摘要,供 LLM prompt 使用。

    LLM 只能引用此处出现的信息,以此守住"禁止编造"红线。
    """
    interp = interp or {}
    lines = []
    lines += _facts_overview(data, interp)
    lines += _facts_equity(data, interp)
    lines += _facts_etf(data, interp)
    lines += _facts_bond(data, interp)
    lines += _facts_cb(data, interp)
    return "\n".join(lines)
