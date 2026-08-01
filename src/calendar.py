# -*- coding: utf-8 -*-
"""交易日判断。

优先用 akshare ``tool_trade_date_hist_sina`` 获取沪深交易所历史交易日;
接口失败时降级为"周一至五且非周末"的粗判(并告警),宁可漏发不乱发。
"""
from __future__ import annotations

import datetime as dt
import logging
from functools import lru_cache

log = logging.getLogger("ebc.calendar")

_TRADE_DATES: set[str] | None = None


def _load_trade_dates() -> set[str]:
    """加载交易日集合(YYYY-MM-DD)。失败返回空集。"""
    global _TRADE_DATES
    if _TRADE_DATES is not None:
        return _TRADE_DATES
    try:
        import akshare as ak  # 延迟导入,避免 dry-run 无网络时整体崩溃
        df = ak.tool_trade_date_hist_sina()
        # 列名通常为 trade_date,做容错
        col = "trade_date" if "trade_date" in df.columns else df.columns[0]
        dates = set()
        for v in df[col]:
            dates.add(_norm_date(v))
        _TRADE_DATES = dates
        log.info("交易日历加载成功,共 %d 个交易日", len(dates))
    except Exception as e:  # noqa: BLE001
        log.warning("交易日历接口失败,降级为周末粗判: %s", e)
        _TRADE_DATES = set()
    return _TRADE_DATES


def _norm_date(v) -> str:
    """把各种日期类型统一成 YYYY-MM-DD 字符串。"""
    if isinstance(v, str):
        return v[:10]
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    # pandas Timestamp
    try:
        return str(v)[:10]
    except Exception:  # noqa: BLE001
        return ""


def is_trading_day(d: dt.date) -> bool:
    """判断 d 是否为 A 股交易日。"""
    ds = d.strftime("%Y-%m-%d")
    dates = _load_trade_dates()
    if dates:
        return ds in dates
    # 降级:仅排除周末(无法识别节假日,已告警)
    return d.weekday() < 5


def latest_trade_day_on_or_before(d: dt.date) -> dt.date:
    """返回 <= d 的最近一个交易日(A 股数据基准日)。"""
    cur = d
    # 向前最多回溯 15 天,覆盖长假
    for _ in range(20):
        if is_trading_day(cur):
            return cur
        cur -= dt.timedelta(days=1)
    # 兜底:返回 d 本身(已告警)
    return d


def previous_trade_day(d: dt.date) -> dt.date:
    """返回严格 < d 的最近一个交易日(用于环比)。"""
    cur = d - dt.timedelta(days=1)
    for _ in range(20):
        if is_trading_day(cur):
            return cur
        cur -= dt.timedelta(days=1)
    return cur
