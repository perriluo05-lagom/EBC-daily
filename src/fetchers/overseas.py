# -*- coding: utf-8 -*-
"""板块一:全球市场概览。

数据维度：
- 美股：道指、纳指、标普500
- 美债：10Y/2Y收益率
- 商品：WTI原油、黄金
- 汇率：在岸人民币
"""
from __future__ import annotations

import logging

from . import base
from ..config import SRC_SINA, SRC_INVESTING, SRC_EAST

log = logging.getLogger("ebc.fetchers.overseas")


def _col(df, *keywords):
    """在 DataFrame 列名中按包含的关键词匹配。"""
    if df is None or len(df) == 0:
        return None
    cols = list(df.columns)
    for kw in keywords:
        for c in cols:
            if kw.lower() in str(c).lower():
                return c
    return None


def _us_index(symbol: str, source: str) -> dict:
    """美股指数。"""
    cache_key = f"us_index_{symbol}"
    df = base.cached_call(cache_key, base.ak().index_us_stock_sina, symbol=symbol)
    if df is None or len(df) == 0:
        return {"pct": None, "close": None, "source": source}
    pct_col = _col(df, "涨跌幅") or _col(df, "change_pct")
    close_col = _col(df, "收盘") or _col(df, "close")
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    pct_v = base.to_float(last[pct_col]) if pct_col else None
    if pct_v is None and prev is not None and close_col:
        c0, c1 = base.to_float(last[close_col]), base.to_float(prev[close_col])
        pct_v = (c0 / c1 - 1) * 100 if c0 and c1 else None
    return {"pct": pct_v, "close": base.to_float(last[close_col]) if close_col else None, "source": source}


def _fetch_foreign_future(symbol: str, name: str) -> dict:
    """外盘期货。"""
    src = SRC_SINA
    fn = getattr(base.ak(), "futures_foreign_hist", None)
    if fn:
        cache_key = f"foreign_future_{symbol}"
        df = base.cached_call(cache_key, fn, symbol=symbol)
        if df is not None and len(df) >= 2:
            close_col = _col(df, "收盘") or _col(df, "close")
            if close_col:
                c0 = base.to_float(df.iloc[-1][close_col])
                c1 = base.to_float(df.iloc[-2][close_col])
                pct_v = (c0 / c1 - 1) * 100 if c0 and c1 else None
                return {"pct": pct_v, "close": c0, "name": name, "source": src}
    return {"pct": None, "close": None, "name": name, "source": src}


def _us_treasury_yields() -> dict:
    """美债收益率（10Y/2Y）。"""
    src = SRC_INVESTING
    result = {"10y": None, "2y": None, "10y_chg_bp": None, "2y_chg_bp": None, "source": src}
    
    df = base.cached_call("bond_zh_us_rate", base.ak().bond_zh_us_rate)
    if df is not None and len(df) >= 2:
        # 10Y
        col_10y = _col(df, "美国", "10")
        if col_10y:
            last = base.to_float(df.iloc[-1][col_10y])
            prev = base.to_float(df.iloc[-2][col_10y])
            result["10y"] = last
            if last is not None and prev is not None:
                result["10y_chg_bp"] = (last - prev) * 100
        
        # 2Y
        col_2y = _col(df, "美国", "2")
        if col_2y:
            last = base.to_float(df.iloc[-1][col_2y])
            prev = base.to_float(df.iloc[-2][col_2y])
            result["2y"] = last
            if last is not None and prev is not None:
                result["2y_chg_bp"] = (last - prev) * 100
    
    return result


# VIX恐慌指数和美元指数对国内ETF投资者参考意义不大，已删除


def _usd_cny() -> dict:
    """在岸人民币汇率（USD/CNY）。"""
    src = SRC_SINA
    # 使用中国银行外汇牌价接口
    try:
        fn = getattr(base.ak(), "currency_boc_sina", None)
        if fn:
            import datetime
            # 查询最近3天的数据，确保周末也能获取到周五的数据
            today = datetime.date.today()
            start_date = (today - datetime.timedelta(days=3)).strftime("%Y%m%d")
            end_date = today.strftime("%Y%m%d")
            df = base.cached_call("usd_cny", fn, symbol="美元", start_date=start_date, end_date=end_date)
            if df is not None and len(df) > 0:
                # 取最新一天的数据（第一行是最新的）
                # 优先取央行中间价，其次取中行折算价
                rate = base.to_float(df.iloc[0].get("央行中间价") or df.iloc[0].get("中行折算价"))
                if rate is not None:
                    return {"rate": rate, "source": src}
    except Exception as e:
        log.warning("在岸人民币获取失败: %s", e)
    return {"rate": None, "source": src}


def fetch_overview() -> dict:
    """采集全球市场数据（仅保留对国内ETF投资者重要的指标）。"""
    out: dict = {"source": SRC_SINA}

    # 美股三大指数 - 对A股开盘有指引作用
    out["dow"] = base.safe(_us_index, ".DJI", SRC_SINA) or {"pct": None, "close": None, "source": SRC_SINA}
    out["nasdaq"] = base.safe(_us_index, ".IXIC", SRC_SINA) or {"pct": None, "close": None, "source": SRC_SINA}
    out["sp500"] = base.safe(_us_index, ".INX", SRC_SINA) or {"pct": None, "close": None, "source": SRC_SINA}

    # 美债收益率 - 影响全球资金流向
    out["us_treasury"] = base.safe(_us_treasury_yields) or {
        "10y": None, "2y": None, "10y_chg_bp": None, "2y_chg_bp": None, "source": SRC_INVESTING
    }

    # 大宗商品 - 影响相关ETF
    out["oil_wti"] = _fetch_foreign_future("CL", "WTI原油")
    out["gold"] = _fetch_foreign_future("GC", "黄金")

    # 在岸人民币 - 影响A股资金流向
    out["usd_cny"] = base.safe(_usd_cny) or {"rate": None, "source": SRC_SINA}

    return out
