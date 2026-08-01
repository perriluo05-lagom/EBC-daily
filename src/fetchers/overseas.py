# -*- coding: utf-8 -*-
"""板块一:昨夜今晨概览(美股/美债/A50/原油/黄金)。"""
from __future__ import annotations

import logging

from . import base
from ..config import SRC_SINA, SRC_INVESTING

log = logging.getLogger("ebc.fetchers.overseas")


def _col(df, *keywords):
    """在 DataFrame 列名中按包含的关键词匹配(大小写不敏感)。"""
    if df is None or len(df) == 0:
        return None
    cols = list(df.columns)
    for kw in keywords:
        for c in cols:
            if kw.lower() in str(c).lower():
                return c
    return None


def _us_index(symbol: str, source: str) -> dict:
    """美股指数:取最近一行涨跌幅与收盘。"""
    df = base.safe(base.ak().index_us_stock_sina, symbol=symbol)
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


def fetch_overview() -> dict:
    """采集隔夜外盘。每个字段失败均降级为 None(渲染时显示"数据暂缺")。"""
    out: dict = {"source": SRC_SINA}

    out["dow"] = base.safe(_us_index, ".DJI", SRC_SINA) or {"pct": None, "close": None, "source": SRC_SINA}
    out["nasdaq"] = base.safe(_us_index, ".IXIC", SRC_SINA) or {"pct": None, "close": None, "source": SRC_SINA}
    out["sp500"] = base.safe(_us_index, ".INX", SRC_SINA) or {"pct": None, "close": None, "source": SRC_SINA}

    # 美债10Y(bond_zh_us_rate:英为财情)
    us10y = {"yield": None, "change_bp": None, "source": SRC_INVESTING}
    df = base.safe(base.ak().bond_zh_us_rate)
    col = _col(df, "美国", "10")
    if df is not None and len(df) >= 1 and col:
        last = base.to_float(df.iloc[-1][col])
        prev = base.to_float(df.iloc[-2][col]) if len(df) > 1 else None
        us10y["yield"] = last
        if last is not None and prev is not None:
            us10y["change_bp"] = (last - prev) * 100
    out["us10y"] = us10y

    # 富时A50期货:优先 akshare,失败用新浪 CHA50CFD 兜底
    out["a50"] = _fetch_a50()

    # 原油(WTI CL)/黄金(COMEX GC):futures_foreign_hist 取最近两日收盘算涨幅
    out["oil"] = _fetch_foreign_future("CL", "原油")
    out["gold"] = _fetch_foreign_future("GC", "黄金")
    return out


def _fetch_a50() -> dict:
    src = SRC_SINA
    # 方式1:akshare 外盘期货实时(若存在该符号)
    fn = getattr(base.ak(), "futures_foreign_commodity_realtime", None)
    if fn:
        df = base.safe(fn, symbol="A50")
        if df is not None and len(df) > 0:
            # 字段不确定,尽力取价格与涨跌幅
            p = base.to_float(df.iloc[0].get("最新价") or df.iloc[0].get("price"))
            chg = base.to_float(df.iloc[0].get("涨跌幅") or df.iloc[0].get("change_pct"))
            if p is not None or chg is not None:
                return {"pct": chg, "close": p, "source": src}
    # 方式2:新浪 hq.sinajs.cn 兜底(CHA50CFD)
    txt = base.http_get("https://hq.sinajs.cn/list=CHA50CFD", headers=base.SINA_REFERER)
    if txt and "hq_str_CHA50CFD" in txt:
        try:
            payload = txt.split('"', 2)[1]
            parts = payload.split(",")
            # 新浪外盘期货字段:0名称 1开盘 2昨结 3最新 ... 涨跌幅位置不固定,用 (最新-昨结)/昨结
            if len(parts) >= 4:
                last = base.to_float(parts[3])
                prev = base.to_float(parts[2])
                pct_v = (last / prev - 1) * 100 if last and prev else None
                return {"pct": pct_v, "close": last, "source": src}
        except Exception as e:  # noqa: BLE001
            log.warning("A50 新浪解析失败: %s", e)
    return {"pct": None, "close": None, "source": src}


def _fetch_foreign_future(symbol: str, name: str) -> dict:
    src = SRC_SINA
    fn = getattr(base.ak(), "futures_foreign_hist", None)
    if fn:
        df = base.safe(fn, symbol=symbol)
        if df is not None and len(df) >= 2:
            close_col = _col(df, "收盘") or _col(df, "close")
            if close_col:
                c0 = base.to_float(df.iloc[-1][close_col])
                c1 = base.to_float(df.iloc[-2][close_col])
                pct_v = (c0 / c1 - 1) * 100 if c0 and c1 else None
                return {"pct": pct_v, "close": c0, "name": name, "source": src}
    return {"pct": None, "close": None, "name": name, "source": src}
