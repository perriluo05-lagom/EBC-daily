# -*- coding: utf-8 -*-
"""板块五:可转债(中证转债指数/均价/溢价率及分位/破面/成交/强赎)。"""
from __future__ import annotations

import logging

from . import base
from ..config import SRC_EAST, SRC_SINA, SRC_JSL, INDEX_CODES

log = logging.getLogger("ebc.fetchers.convertible")


def _csi_bond_index(sina_df) -> dict:
    """中证转债指数涨跌幅(新浪指数表 sh000832)。"""
    src = SRC_SINA
    if sina_df is None or len(sina_df) == 0:
        return {"pct": None, "close": None, "source": src}
    col = "代码" if "代码" in sina_df.columns else sina_df.columns[0]
    rows = sina_df[sina_df[col].astype(str) == f"sh{INDEX_CODES['中证转债']}"]
    if len(rows) == 0:
        return {"pct": None, "close": None, "source": src}
    r = rows.iloc[0]
    return {"pct": base.to_float(r.get("涨跌幅")), "close": base.to_float(r.get("最新价")), "source": src}


def _market_stats() -> dict:
    """全市场均价/平均溢价率/破面数/成交额。使用缓存。"""
    src = SRC_EAST
    df = base.cached_call("bond_zh_hs_cov_spot", base.ak().bond_zh_hs_cov_spot)
    if df is None or len(df) == 0:
        return {"avg_price": None, "avg_premium": None, "below_par": None, "turnover": None, "source": src}
    
    # 列名映射（支持中英文列名）
    price_col = next((c for c in df.columns if "最新价" in str(c) or str(c).lower() in ["trade", "price"]), None)
    amount_col = next((c for c in df.columns if "成交额" in str(c) or str(c).lower() in ["amount", "turnover"]), None)
    prem_col = next((c for c in df.columns if ("溢价" in str(c) and "率" in str(c)) or str(c).lower() in ["premiumrate", "premium"]), None)
    
    if price_col is None:
        return {"avg_price": None, "avg_premium": None, "below_par": None, "turnover": None, "source": src}
    
    prices = df[price_col].apply(base.to_float).dropna()
    avg_price = float(prices.mean()) if len(prices) else None
    below_par = int((prices < 100).sum()) if len(prices) else None
    turnover = float(df[amount_col].apply(base.to_float).sum()) if amount_col else None
    avg_premium = None
    if prem_col:
        prems = df[prem_col].apply(base.to_float).dropna()
        avg_premium = float(prems.mean()) if len(prems) else None
    return {"avg_price": avg_price, "avg_premium": avg_premium, "below_par": below_par, "turnover": turnover, "source": src}


def _premium_percentile_3y(current_premium: float | None) -> float | None:
    """用集思录可转债指数历史平均溢价率算近3年分位;不可得返回 None。

    注:bond_cb_index_jsl 字段需实测;无历史溢价率列时返回 None(渲染为"数据暂缺")。
    """
    if current_premium is None:
        return None
    fn = getattr(base.ak(), "bond_cb_index_jsl", None)
    if not fn:
        return None
    df = base.safe(fn)
    if df is None or len(df) == 0:
        return None
    prem_col = next((c for c in df.columns if "溢价" in str(c)), None)
    if prem_col is None:
        return None
    series = df[prem_col].apply(base.to_float).dropna()
    series = series.tail(750)  # 近3年交易日
    if len(series) < 30:
        return None
    # 当前溢价率在历史序列中的分位
    rank = (series <= current_premium).sum()
    return round(rank / len(series) * 100, 1)


def _force_redeem() -> list[str]:
    """集思录强赎名单(取名称)。"""
    fn = getattr(base.ak(), "bond_cb_redeem_jsl", None)
    if not fn:
        return []
    df = base.safe(fn)
    if df is None or len(df) == 0:
        return []
    name_col = next((c for c in df.columns if "名称" in str(c) or "转债" in str(c)), None)
    if name_col is None:
        return []
    return [str(v) for v in df[name_col].head(10).tolist()]


def fetch_convertible(sina_df) -> dict:
    csi = base.safe(_csi_bond_index, sina_df) or {"pct": None, "close": None, "source": SRC_SINA}
    stats = base.safe(_market_stats) or {"avg_price": None, "avg_premium": None, "below_par": None, "turnover": None, "source": SRC_EAST}
    cur_prem = stats.get("avg_premium")
    pctile = base.safe(_premium_percentile_3y, cur_prem)
    redeem = base.safe(_force_redeem) or []
    return {
        "csi_index": csi,
        "avg_price": stats.get("avg_price"),
        "avg_premium": cur_prem,
        "premium_percentile_3y": pctile,
        "below_par": stats.get("below_par"),
        "turnover": stats.get("turnover"),
        "force_redeem": redeem,
        "stats_source": SRC_EAST,
        "redeem_source": SRC_JSL,
    }
