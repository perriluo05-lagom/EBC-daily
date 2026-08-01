# -*- coding: utf-8 -*-
"""板块四:债券市场(国债收益率/期限利差/Shibor 1周/国债ETF)。

资金面指标采用 Shibor 1周(上海银行间同业拆放利率),经 akshare rate_interbank
取"上海银行同业拆借市场/Shibor人民币/1周";取不到时"数据暂缺",绝不以其他利率冒充。
"""
from __future__ import annotations

import datetime as dt
import logging

from . import base
from ..config import SRC_CBOND, SRC_CM

log = logging.getLogger("ebc.fetchers.bond")


def _gov_yields() -> dict:
    """取中债国债收益率曲线最近两日的 1Y/10Y。"""
    src = SRC_CBOND
    end = dt.date.today()
    start = end - dt.timedelta(days=30)
    df = base.safe(
        base.ak().bond_china_yield,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if df is None or len(df) == 0:
        return {"cn10y": None, "cn1y": None, "cn10y_chg_bp": None, "cn1y_chg_bp": None, "source": src}
    name_col = next((c for c in df.columns if "曲线" in str(c) or "名称" in str(c)), None)
    date_col = next((c for c in df.columns if "日期" in str(c) or "date" in str(c).lower()), df.columns[1])
    y1_col = next((c for c in df.columns if str(c).strip() == "1年"), None)
    y10_col = next((c for c in df.columns if str(c).strip() == "10年"), None)
    if name_col is None or y1_col is None or y10_col is None:
        return {"cn10y": None, "cn1y": None, "cn10y_chg_bp": None, "cn1y_chg_bp": None, "source": src}
    # 仅国债曲线
    gov = df[df[name_col].astype(str).str.contains("国债")]
    if len(gov) == 0:
        gov = df
    gov = gov.sort_values(date_col)
    last = gov.iloc[-1]
    prev = gov.iloc[-2] if len(gov) > 1 else None
    c10 = base.to_float(last[y10_col])
    c1 = base.to_float(last[y1_col])
    c10p = base.to_float(prev[y10_col]) if prev is not None else None
    c1p = base.to_float(prev[y1_col]) if prev is not None else None
    return {
        "cn10y": c10, "cn1y": c1,
        "cn10y_chg_bp": (c10 - c10p) * 100 if (c10 is not None and c10p is not None) else None,
        "cn1y_chg_bp": (c1 - c1p) * 100 if (c1 is not None and c1p is not None) else None,
        "date": str(last[date_col])[:10],
        "source": src,
    }


def _shibor_1w() -> dict:
    """Shibor 1周(上海银行间同业拆放利率),作为资金面指标。

    akshare 的 rate_interbank 接口取"上海银行同业拆借市场/Shibor人民币/1周";
    取不到时返回"数据暂缺",绝不以其他利率冒充。
    """
    src = SRC_CM
    fn = getattr(base.ak(), "rate_interbank", None)
    if not fn:
        return {"rate": None, "change_bp": None, "source": src}
    df = base.safe(fn, market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="1周")
    if df is None or len(df) == 0:
        return {"rate": None, "change_bp": None, "source": src}
    date_col = next((c for c in df.columns if "日期" in str(c) or "date" in str(c).lower()), df.columns[0])
    rate_col = next((c for c in df.columns if c != date_col and ("利率" in str(c) or "Shibor" in str(c))), None)
    if rate_col is None:
        rate_col = next((c for c in df.columns if c != date_col), None)
    if rate_col is None:
        return {"rate": None, "change_bp": None, "source": src}
    df = df.sort_values(date_col)
    last = base.to_float(df.iloc[-1][rate_col])
    prev = base.to_float(df.iloc[-2][rate_col]) if len(df) > 1 else None
    chg = (last - prev) * 100 if (last is not None and prev is not None) else None
    return {"rate": last, "change_bp": chg, "source": src}


def fetch_bond(etf_bonds: list[dict] | None = None) -> dict:
    gov = base.safe(_gov_yields) or {"cn10y": None, "cn1y": None, "cn10y_chg_bp": None, "cn1y_chg_bp": None, "source": SRC_CBOND}
    sh = base.safe(_shibor_1w) or {"rate": None, "change_bp": None, "source": SRC_CM}
    c10, c1 = gov.get("cn10y"), gov.get("cn1y")
    term_spread = (c10 - c1) if (c10 is not None and c1 is not None) else None
    return {
        "gov": gov,
        "shibor": sh,
        "term_spread": term_spread,
        "term_spread_source": SRC_CBOND,
        "bond_etfs": etf_bonds or [],
    }
