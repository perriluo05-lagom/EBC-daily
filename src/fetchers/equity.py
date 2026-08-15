# -*- coding: utf-8 -*-
"""板块二:A股大盘温度（大幅扩展版）。

数据维度：
- 核心指数：上证50、沪深300、中证500、中证1000、创业板指、科创50、北证50
- 市场情绪：涨跌家数、涨跌停统计、成交额及环比
- 资金流向：北向资金净流入
- 风格判断：大小盘对比、价值成长对比
"""
from __future__ import annotations

import logging

from . import base
from ..config import SRC_SINA, SRC_EAST, INDEX_CODES, INDEX_SYMBOL_PREFIX

log = logging.getLogger("ebc.fetchers.equity")


def _sina_row(sina_df, code: str):
    """在新浪指数表中按 sh/sz/bj+code 精确匹配一行。"""
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
    """用东方财富 index_daily_em 取上一交易日成交额。"""
    total = 0.0
    got = 0
    for code in (INDEX_CODES["上证综指"], INDEX_CODES["深证综指"]):
        prefix = INDEX_SYMBOL_PREFIX.get(code, "sh")
        cache_key = f"index_daily_em_{prefix}{code}"
        df = base.cached_call(cache_key, base.ak().stock_zh_index_daily_em, symbol=f"{prefix}{code}")
        if df is None or len(df) < 2:
            continue
        col = "成交额" if "成交额" in df.columns else next((c for c in df.columns if "成交额" in str(c)), None)
        if col is None:
            continue
        v = base.to_float(df.iloc[-2][col])
        if v is not None:
            total += v
            got += 1
    if got < 2:
        return None
    return total


def _market_turnover(sina_df) -> dict:
    """全市场成交额 = 上证综指 + 深证综指 成交额。"""
    sh = _sina_row(sina_df, INDEX_CODES["上证综指"])
    sz = _sina_row(sina_df, INDEX_CODES["深证综指"])
    t_sh = base.to_float(sh.get("成交额")) if sh is not None else None
    t_sz = base.to_float(sz.get("成交额")) if sz is not None else None
    today = (t_sh + t_sz) if (t_sh is not None and t_sz is not None) else None
    prev = base.safe(_prev_turnover_from_em)
    change = (today / prev - 1) * 100 if (today and prev) else None
    return {"value": today, "prev": prev, "change_pct": change, "source": SRC_SINA}


def _advance_decline() -> dict:
    """全市场涨跌家数、涨跌停统计。"""
    df = base.cached_call("stock_zh_a_spot_em", base.ak().stock_zh_a_spot_em)
    if df is None or len(df) == 0:
        return {
            "advancing": None, "declining": None, "unchanged": None,
            "limit_up": None, "limit_down": None, "source": SRC_EAST
        }
    
    col = "涨跌幅" if "涨跌幅" in df.columns else None
    if col is None:
        return {
            "advancing": None, "declining": None, "unchanged": None,
            "limit_up": None, "limit_down": None, "source": SRC_EAST
        }
    
    pcts = df[col].apply(base.to_float)
    adv = int((pcts > 0).sum())
    dec = int((pcts < 0).sum())
    unch = int((pcts == 0).sum())
    
    # 涨跌停统计（A股主板10%，创业板/科创板20%）
    # 简化处理：涨幅>=9.8%视为涨停，跌幅<=-9.8%视为跌停
    limit_up = int((pcts >= 9.8).sum())
    limit_down = int((pcts <= -9.8).sum())
    
    return {
        "advancing": adv, "declining": dec, "unchanged": unch,
        "limit_up": limit_up, "limit_down": limit_down, "source": SRC_EAST
    }


# 北向资金数据源已失效（akshare 返回 NaN），已删除


def _sector_performance() -> list[dict]:
    """获取行业板块涨跌排行（前5涨、前5跌）。"""
    try:
        fn = getattr(base.ak(), "stock_board_industry_name_em", None)
        if fn:
            df = base.cached_call("sector_performance", fn)
            if df is not None and len(df) > 0:
                pct_col = next((c for c in df.columns if "涨跌幅" in str(c)), None)
                name_col = next((c for c in df.columns if "板块名称" in str(c) or "名称" in str(c)), None)
                
                if pct_col and name_col:
                    df = df.copy()
                    df["_pct"] = df[pct_col].apply(base.to_float)
                    df = df.dropna(subset=["_pct"])
                    
                    # 涨幅前5
                    top5 = df.nlargest(5, "_pct")
                    # 跌幅前5
                    bottom5 = df.nsmallest(5, "_pct")
                    
                    result = []
                    for _, r in top5.iterrows():
                        result.append({
                            "name": str(r[name_col]),
                            "pct": float(r["_pct"]),
                            "rank": "top"
                        })
                    for _, r in bottom5.iterrows():
                        result.append({
                            "name": str(r[name_col]),
                            "pct": float(r["_pct"]),
                            "rank": "bottom"
                        })
                    
                    return result
    except Exception as e:
        log.warning("行业板块数据获取失败: %s", e)
    
    return []


def fetch_equity(sina_df) -> dict:
    """获取A股大盘数据（仅保留主流指数）。"""
    # 核心指数（删除北证50，北交所流动性差，大部分ETF投资者不关注）
    indices = {
        "sh50": _index_spot(sina_df, INDEX_CODES["上证50"]),
        "hs300": _index_spot(sina_df, INDEX_CODES["沪深300"]),
        "zz500": _index_spot(sina_df, INDEX_CODES["中证500"]),
        "zz1000": _index_spot(sina_df, INDEX_CODES["中证1000"]),
        "cyb": _index_spot(sina_df, INDEX_CODES["创业板指"]),
        "kc50": _index_spot(sina_df, INDEX_CODES["科创50"]),
    }
    
    # 市场成交
    turnover = _market_turnover(sina_df)
    
    # 涨跌家数
    ad = base.safe(_advance_decline) or {
        "advancing": None, "declining": None, "unchanged": None,
        "limit_up": None, "limit_down": None, "source": SRC_EAST
    }
    
    # 行业板块
    sectors = base.safe(_sector_performance) or []
    
    # 风格判断
    hs300_pct = indices["hs300"].get("pct")
    zz1000_pct = indices["zz1000"].get("pct")
    sh50_pct = indices["sh50"].get("pct")
    cyb_pct = indices["cyb"].get("pct")
    
    style_notes = []
    if hs300_pct is not None and zz1000_pct is not None:
        diff = zz1000_pct - hs300_pct
        if diff > 0.5:
            style_notes.append("小盘股明显强于大盘股")
        elif diff < -0.5:
            style_notes.append("大盘股明显强于小盘股")
        else:
            style_notes.append("大小盘表现相对均衡")
    
    if sh50_pct is not None and cyb_pct is not None:
        diff = cyb_pct - sh50_pct
        if diff > 1.0:
            style_notes.append("成长风格（创业板）显著强于价值风格（上证50）")
        elif diff < -1.0:
            style_notes.append("价值风格（上证50）显著强于成长风格（创业板）")
    
    return {
        "indices": indices,
        "turnover": turnover,
        "advance_decline": ad,
        "sectors": sectors,
        "style_notes": style_notes,
    }
