# -*- coding: utf-8 -*-
"""板块五:可转债(均价/破面/成交/强赎)。"""
from __future__ import annotations

import logging

from . import base
from ..config import SRC_EAST, SRC_JSL

log = logging.getLogger("ebc.fetchers.convertible")


def _market_stats() -> dict:
    """全市场均价/破面数/成交额。使用缓存。"""
    src = SRC_EAST
    df = base.cached_call("bond_zh_hs_cov_spot", base.ak().bond_zh_hs_cov_spot)
    if df is None or len(df) == 0:
        return {"avg_price": None, "below_par": None, "turnover": None, "source": src}
    
    # 列名映射（支持中英文列名）
    price_col = next((c for c in df.columns if "最新价" in str(c) or str(c).lower() in ["trade", "price"]), None)
    amount_col = next((c for c in df.columns if "成交额" in str(c) or str(c).lower() in ["amount", "turnover"]), None)
    
    if price_col is None:
        return {"avg_price": None, "below_par": None, "turnover": None, "source": src}
    
    prices = df[price_col].apply(base.to_float).dropna()
    avg_price = float(prices.mean()) if len(prices) else None
    below_par = int((prices < 100).sum()) if len(prices) else None
    turnover = float(df[amount_col].apply(base.to_float).sum()) if amount_col else None
    
    return {"avg_price": avg_price, "below_par": below_par, "turnover": turnover, "source": src}


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
    stats = base.safe(_market_stats) or {"avg_price": None, "below_par": None, "turnover": None, "source": SRC_EAST}
    redeem = base.safe(_force_redeem) or []
    return {
        "avg_price": stats.get("avg_price"),
        "below_par": stats.get("below_par"),
        "turnover": stats.get("turnover"),
        "force_redeem": redeem,
        "stats_source": SRC_EAST,
        "redeem_source": SRC_JSL,
    }
