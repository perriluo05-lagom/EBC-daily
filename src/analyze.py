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
