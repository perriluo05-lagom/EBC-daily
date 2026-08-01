# -*- coding: utf-8 -*-
"""板块三:ETF焦点(宽基/策略行业涨跌、资金流向、溢价异常)。"""
from __future__ import annotations

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
    pct_v = base.to_float(r.get("涨跌幅"))
    price = base.to_float(r.get("最新价"))
    # 溢价:优先 IOPV,其次基金净值
    iopv = base.to_float(r.get("IOPV")) or base.to_float(r.get("基金净值")) or base.to_float(r.get("净值"))
    premium = (price / iopv - 1) * 100 if (price and iopv) else None
    return {"code": code, "name": name, "pct": pct_v, "price": price, "premium": premium, "source": SRC_EAST}


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
                items.append({"code": code, "name": name, "pct": None, "price": None, "premium": None, "source": SRC_EAST})
                continue
            item = _row_etf(r, code, name)
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
