# -*- coding: utf-8 -*-
"""渲染层测试:结构完整、来源标注、缺失降级、免责声明。"""
import datetime as dt
from src import render


def _data_all_missing():
    return {
        "overview": {"dow": {"pct": None, "close": None, "source": "新浪财经"},
                     "nasdaq": {"pct": None, "source": "新浪财经"},
                     "sp500": {"pct": None, "source": "新浪财经"},
                     "us10y": {"yield": None, "change_bp": None, "source": "英为财情"},
                     "a50": {"pct": None, "source": "新浪财经"},
                     "oil": {"pct": None, "source": "新浪财经"},
                     "gold": {"pct": None, "source": "新浪财经"}},
        "equity": {"hs300": {"pct": None, "close": None, "source": "东方财富"},
                   "zz1000": {"pct": None, "close": None, "source": "东方财富"},
                   "turnover": {"value": None, "change_pct": None, "source": "东方财富"},
                   "advance_decline": {"advancing": None, "declining": None, "source": "东方财富"},
                   "style": "数据暂缺", "style_source": "东方财富"},
        "etf": {"groups": {"宽基": [{"name": "沪深300ETF", "pct": None, "premium": None}],
                           "策略行业": [{"name": "券商ETF", "pct": None, "premium": None}]},
                "bond_etfs": [{"name": "国债ETF", "pct": None, "source": "东方财富"}],
                "flow_top3": [], "premium_anomalies": [], "source": "东方财富"},
        "bond": {"gov": {"cn10y": None, "cn1y": None, "cn10y_chg_bp": None, "cn1y_chg_bp": None, "source": "中国债券信息网"},
                 "shibor": {"rate": None, "change_bp": None, "source": "中国货币网"},
                 "term_spread": None, "term_spread_source": "中国债券信息网",
                 "bond_etfs": [{"name": "国债ETF", "pct": None, "source": "东方财富"}]},
        "convertible": {"csi_index": {"pct": None, "close": None, "source": "东方财富"},
                        "avg_price": None, "avg_premium": None, "premium_percentile_3y": None,
                        "below_par": None, "turnover": None, "force_redeem": [],
                        "stats_source": "东方财富", "redeem_source": "集思录"},
    }


def _interp_all_missing():
    return {k: "数据不足,暂不解读" for k in [
        "opening_call", "market_temperature", "style_note", "etf_flow_note",
        "etf_premium_note", "bond_view", "bond_reference", "cb_valuation", "cb_event_note"]}


def test_render_has_five_sections():
    md = render.render(_data_all_missing(), _interp_all_missing(), dt.date(2026, 8, 1), "2026-07-31")
    for h in ["## 一、", "## 二、", "## 三、", "## 四、", "## 五、"]:
        assert h in md


def test_render_has_disclaimer():
    md = render.render(_data_all_missing(), _interp_all_missing(), dt.date(2026, 8, 1), "2026-07-31")
    assert "不构成投资建议" in md  # 用户给定免责声明正文
    assert "AI生成" in md


def test_render_missing_fields_no_crash():
    md = render.render(_data_all_missing(), _interp_all_missing(), dt.date(2026, 8, 1), "2026-07-31")
    assert "数据暂缺" in md
    assert "（来源：" in md  # 来源标注存在


def test_render_has_tables():
    """各板块应输出 Markdown 表格(表头分隔线)。"""
    md = render.render(_data_all_missing(), _interp_all_missing(), dt.date(2026, 8, 1), "2026-07-31")
    assert "| 品种 | 涨跌 | 数值 | 来源 |" in md  # 概览表头
    assert "| --- |" in md  # 表头分隔线


def test_render_falls_back_without_narrative():
    """无 narrative 时回退规则版标签。"""
    md = render.render(_data_all_missing(), _interp_all_missing(), dt.date(2026, 8, 1), "2026-07-31")
    assert "**开盘定调**" in md or "**解读**" in md


def test_render_uses_narrative_when_present():
    """有 narrative 时使用 LLM 叙事,对应板块不再出现回退标签。"""
    narrative = {"overview": "LLM测试叙事内容XYZ_UNIQUE"}
    md = render.render(_data_all_missing(), _interp_all_missing(), dt.date(2026, 8, 1),
                       "2026-07-31", narrative=narrative)
    assert "LLM测试叙事内容XYZ_UNIQUE" in md
    assert "**开盘定调**" not in md  # 概览已用叙事,不再回退


def test_render_etf_table_has_new_fields():
    """ETF 表应含 5日涨跌/资金净流入/规模 列。"""
    md = render.render(_data_all_missing(), _interp_all_missing(), dt.date(2026, 8, 1), "2026-07-31")
    assert "5日涨跌" in md
    assert "当日资金净流入" in md
    assert "规模" in md


def test_subject_format():
    assert render.subject(dt.date(2026, 8, 1)) == "【EBC Daily】2026-08-01"
