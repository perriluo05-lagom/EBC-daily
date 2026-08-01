# -*- coding: utf-8 -*-
"""板块二:A股大盘温度。

数据源:以新浪 stock_zh_index_spot_sina 为主(本地/生产均稳定,含成交额),
东方财富 stock_zh_a_spot_em 用于涨跌家数(生产可用)。
"""
from __future__ import annotations

import logging

from . import base
from ..config import SRC_SINA, SRC_EAST, INDEX_CODES, INDEX_SYMBOL_PREFIX

log = logging.getLogger("ebc.fetchers.equity")


def _sina_row(sina_df, code: str):
    """在新浪指数表中按 sh/sz+code 精确匹配一行。"""
    if sina_df is None or len(sina_df) == 0:
        return None
    prefix = INDEX_SYMBOL_PREFIX.get(code, "sh")
    symbol = f"{prefix}{code}"
    col = "代码" if "代码" in sina_df.columns else sina_df.columns[0]
    rows = sina_df[sina_df[col].astype(str) == symbol]
    return rows.iloc[0] if len(rows) else None


def _index_spot(sina_df, code: str) -> dict:
    r = _sina_row(sina_df, code)
    if r is None:
        return {"pct": None, "close": None, "source": SRC_SINA}
    return {
        "pct": base.to_float(r.get("涨跌幅")),
        "close": base.to_float(r.get("最新价")),
        "source": SRC_SINA,
    }


def _prev_turnover_from_em() -> float | None:
    """用东方财富 index_daily_em 取上一交易日成交额(生产可用;本地被代理屏蔽则返回 None)。"""
    total = 0.0
    got = 0
    for code in (INDEX_CODES["上证综指"], INDEX_CODES["深证综指"]):
        prefix = INDEX_SYMBOL_PREFIX.get(code, "sh")
        df = base.safe(base.ak().stock_zh_index_daily_em, symbol=f"{prefix}{code}")
        if df is None or len(df) < 2:
            continue
        col = "成交额" if "成交额" in df.columns else next((c for c in df.columns if "成交额" in str(c)), None)
        if col is None:
            continue
        v = base.to_float(df.iloc[-2][col])  # 上一交易日
        if v is not None:
            total += v
            got += 1
    if got < 2:
        return None
    return total


def _market_turnover(sina_df) -> dict:
    """全市场成交额 = 上证综指 + 深证综指 成交额;环比需上一交易日(东方财富)。"""
    sh = _sina_row(sina_df, INDEX_CODES["上证综指"])
    sz = _sina_row(sina_df, INDEX_CODES["深证综指"])
    t_sh = base.to_float(sh.get("成交额")) if sh is not None else None
    t_sz = base.to_float(sz.get("成交额")) if sz is not None else None
    today = (t_sh + t_sz) if (t_sh is not None and t_sz is not None) else None
    prev = base.safe(_prev_turnover_from_em)
    change = (today / prev - 1) * 100 if (today and prev) else None
    return {"value": today, "prev": prev, "change_pct": change, "source": SRC_SINA}


def _advance_decline() -> dict:
    """全市场涨跌家数(东方财富 stock_zh_a_spot_em;生产可用)。"""
    df = base.safe(base.ak().stock_zh_a_spot_em)
    if df is None or len(df) == 0:
        return {"advancing": None, "declining": None, "source": SRC_EAST}
    col = "涨跌幅" if "涨跌幅" in df.columns else None
    if col is None:
        return {"advancing": None, "declining": None, "source": SRC_EAST}
    adv = int((df[col].apply(base.to_float) > 0).sum())
    dec = int((df[col].apply(base.to_float) < 0).sum())
    return {"advancing": adv, "declining": dec, "source": SRC_EAST}


def fetch_equity(sina_df) -> dict:
    hs300 = _index_spot(sina_df, INDEX_CODES["沪深300"])
    zz1000 = _index_spot(sina_df, INDEX_CODES["中证1000"])
    turnover = _market_turnover(sina_df)
    ad = base.safe(_advance_decline) or {"advancing": None, "declining": None, "source": SRC_EAST}

    # 风格偏向(近似):中证1000 与 沪深300 真实涨跌幅差
    h, z = hs300.get("pct"), zz1000.get("pct")
    if h is not None and z is not None:
        diff = z - h
        style = "小盘相对占优(近似)" if diff > 0.5 else ("大盘相对占优(近似)" if diff < -0.5 else "大小盘相对均衡(近似)")
    else:
        style = "数据暂缺"
    return {
        "hs300": hs300,
        "zz1000": zz1000,
        "turnover": turnover,
        "advance_decline": ad,
        "style": style,
        "style_source": SRC_SINA,
    }
