# -*- coding: utf-8 -*-
"""数据采集基座:统一安全调用、数值转换、HTTP 兜底、来源标注。

核心原则:
- 任何采集异常都降级为"数据暂缺",绝不抛出中断流程,绝不填默认值或臆测。
- 所有返回结构都携带 source 字段,供渲染时附 (来源:XX)。
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable

log = logging.getLogger("ebc.fetchers")

MISSING = "数据暂缺"

# 浏览器 UA / Referer(新浪 hq.sinajs.cn 必须带 Referer 否则 403)
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
SINA_REFERER = {"Referer": "https://finance.sina.com.cn/"}


def ak():
    """延迟导入 akshare,避免无网络/未安装时整体崩溃。"""
    import akshare as ak  # noqa: WPS433
    return ak


def safe(fn: Callable, *args, retries: int = 2, sleep: float = 1.0, **kwargs) -> Any:
    """安全调用:失败重试,最终失败返回 None(不抛出)。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries:
                time.sleep(sleep * (attempt + 1))
    log.warning("采集失败(%s): %s", getattr(fn, "__name__", fn), last_err)
    return None


def http_get(url: str, *, headers: dict | None = None, timeout: int = 15) -> str | None:
    """HTTP GET 兜底,返回文本或 None。"""
    import requests  # noqa: WPS433
    hdr = dict(HTTP_HEADERS)
    if headers:
        hdr.update(headers)
    try:
        r = requests.get(url, headers=hdr, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:  # noqa: BLE001
        log.warning("HTTP 兜底失败 %s: %s", url, e)
        return None


def to_float(x: Any) -> float | None:
    """安全转 float;失败、NaN、空值返回 None。"""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def pct(x: float | None) -> str:
    """格式化百分比,如 +1.23%;None → MISSING。"""
    if x is None:
        return MISSING
    return f"{x:+.2f}%"


def num(x: float | None, ndigits: int = 2, unit: str = "") -> str:
    """格式化数值;None → MISSING。"""
    if x is None:
        return MISSING
    return f"{round(x, ndigits):.{ndigits}f}{unit}"


def bp(x: float | None) -> str:
    """格式化 bp 变动,如 +3.2bp;None → MISSING。"""
    if x is None:
        return MISSING
    return f"{x:+.1f}bp"


def yuan_billion(x: float | None) -> str:
    """成交额由元转为亿元展示;None → MISSING。"""
    if x is None:
        return MISSING
    return f"{x / 1e8:,.0f}亿元"


def tag(source: str) -> str:
    """来源标注。"""
    return f"(来源:{source})"
