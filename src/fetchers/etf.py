# -*- coding: utf-8 -*-
"""板块三:ETF焦点(宽基/策略行业涨跌、5日涨跌、资金净流入、规模、溢价异常)。"""
from __future__ import annotations

import datetime as dt
import logging

from . import base
from ..config import SRC_EAST, ETF_WATCH, ETF_BOND_CODES, ETF_ALL_CODES, TH_PREMIUM

log = logging.getLogger("ebc.fetchers.etf")


def _etf_spot_map() -> dict:
    """返回 {代码: row_dict} 来自 fund_etf_spot_em。"""
    df = base.safe(base.ak().fund_etf_spot_em)
    if df is None or len(df) == 0:
        return {}
    code_col = "代码" if "代码" in df.columns else df.columns[0]
    out = {}
    for _, r in df.iterrows():
        code = str(r[code_col]).zfill(6)
        out[code] = r
    return out


def _row_etf(r, code: str, name: str) -> dict:
    """从 spot 行抽取单只 ETF 字段(含资金净流入/规模)。"""
    pct_v = base.to_float(r.get("涨跌幅"))
    price = base.to_float(r.get("最新价"))
    # 溢价:优先 IOPV,其次基金净值
    iopv = base.to_float(r.get("IOPV实时估值")) or base.to_float(r.get("基金净值")) or base.to_float(r.get("净值"))
    premium = (price / iopv - 1) * 100 if (price and iopv) else None
    net_flow = base.to_float(r.get("主力净流入-净额"))  # 元
    scale = base.to_float(r.get("流通市值"))  # 元
    return {
        "code": code, "name": name, "pct": pct_v, "price": price,
        "premium": premium, "net_flow": net_flow, "scale": scale, "source": SRC_EAST,
    }


def _etf_5d_pct(code: str) -> float | None:
    """近5个交易日累计涨跌幅(前复权收盘价计算);不可得返回 None。

    用 fund_etf_hist_em 取最近约15个自然日的日K,取末值与倒数第6个交易日收盘比较。
    """
    end = dt.date.today()
    start = end - dt.timedelta(days=15)
    df = base.safe(
        base.ak().fund_etf_hist_em,
        symbol=code, period="daily",
        start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
        adjust="qfq", retries=1,
    )
    if df is None or len(df) < 6:
        return None
    close_col = "收盘" if "收盘" in df.columns else next(
        (c for c in df.columns if "收盘" in str(c) or "close" in str(c).lower()), None)
    if close_col is None:
        return None
    c0 = base.to_float(df.iloc[-1][close_col])
    c5 = base.to_float(df.iloc[-6][close_col])
    return (c0 / c5 - 1) * 100 if (c0 and c5) else None


def _flow_top3() -> list[dict]:
    """ETF 资金净流入 TOP3(全市场 fund_etf_fund_daily_em)。"""
    df = base.safe(base.ak().fund_etf_fund_daily_em)
    if df is None or len(df) == 0:
        return []
    code_col = "代码" if "代码" in df.columns else df.columns[0]
    name_col = next((c for c in df.columns if "名称" in str(c)), None)
    flow_col = next((c for c in df.columns if "净流入" in str(c) or "净流" in str(c)), None)
    if flow_col is None:
        return []
    df = df.copy()
    df["_f"] = df[flow_col].apply(base.to_float)
    df = df.dropna(subset=["_f"]).sort_values("_f", ascending=False).head(3)
    out = []
    for _, r in df.iterrows():
        out.append({
            "code": str(r[code_col]).zfill(6),
            "name": str(r[name_col]) if name_col else "",
            "net": float(r["_f"]),
            "source": SRC_EAST,
        })
    return out


def fetch_etf() -> dict:
    spot = base.safe(_etf_spot_map) or {}

    # 宽基 & 策略行业
    groups = {}
    anomalies = []
    for group, pairs in ETF_WATCH.items():
        items = []
        for code, name in pairs:
            r = spot.get(code)
            if r is None:
                items.append({
                    "code": code, "name": name, "pct": None, "pct_5d": None,
                    "price": None, "premium": None, "net_flow": None, "scale": None, "source": SRC_EAST,
                })
                continue
            item = _row_etf(r, code, name)
            item["pct_5d"] = base.safe(_etf_5d_pct, code, retries=1)
            items.append(item)
            p = item.get("premium")
            if p is not None and abs(p) > TH_PREMIUM:
                anomalies.append(item)
        groups[group] = items

    # 国债ETF(供债券板块引用)
    bond_etfs = []
    for code, name in ETF_BOND_CODES:
        r = spot.get(code)
        if r is None:
            bond_etfs.append({"code": code, "name": name, "pct": None, "source": SRC_EAST})
        else:
            bond_etfs.append({"code": code, "name": name, "pct": base.to_float(r.get("涨跌幅")), "source": SRC_EAST})

    flow = base.safe(_flow_top3) or []
    return {
        "groups": groups,            # {宽基:[...], 策略行业:[...]}
        "bond_etfs": bond_etfs,
        "flow_top3": flow,
        "premium_anomalies": anomalies,
        "source": SRC_EAST,
    }
