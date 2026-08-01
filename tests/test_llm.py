# -*- coding: utf-8 -*-
"""LLM 叙事层测试(无网络:mock 调用 + 分隔符解析 + 降级)。"""
import datetime as dt
from src import llm, analyze


def _data():
    return {
        "overview": {"dow": {"pct": 0.5, "close": 40000, "source": "新浪财经"},
                     "nasdaq": {"pct": 1.0, "close": 17000, "source": "新浪财经"},
                     "sp500": {"pct": 0.7, "close": 5500, "source": "新浪财经"},
                     "us10y": {"yield": 4.2, "change_bp": 3.0, "source": "英为财情"},
                     "a50": {"pct": 0.2, "close": 12000, "source": "新浪财经"},
                     "oil": {"pct": 2.0, "close": 78.5, "source": "新浪财经"},
                     "gold": {"pct": -0.5, "close": 2400, "source": "新浪财经"}},
        "equity": {"hs300": {"pct": 0.85, "close": 4588, "source": "新浪财经"},
                   "zz1000": {"pct": 2.53, "close": 7076, "source": "新浪财经"},
                   "turnover": {"value": 2.5e12, "change_pct": 12.0, "source": "新浪财经"},
                   "advance_decline": {"advancing": 3500, "declining": 1500, "source": "东方财富"},
                   "style": "小盘相对占优(近似)", "style_source": "新浪财经"},
        "etf": {"groups": {"宽基": [{"name": "沪深300ETF", "code": "510300", "pct": 1.04, "pct_5d": 2.1,
                                      "premium": 0.1, "net_flow": 1.2e8, "scale": 5e10, "source": "东方财富"}],
                           "策略行业": [{"name": "半导体ETF", "code": "512480", "pct": 3.55, "pct_5d": 5.2,
                                        "premium": 0.3, "net_flow": 3e8, "scale": 1e10, "source": "东方财富"}]},
                "bond_etfs": [{"name": "国债ETF", "pct": 0.05, "source": "东方财富"}],
                "flow_top3": [{"name": "沪深300ETF"}], "premium_anomalies": [], "source": "东方财富"},
        "bond": {"gov": {"cn10y": 1.71, "cn1y": 1.15, "cn10y_chg_bp": -0.6, "cn1y_chg_bp": -1.1, "source": "中国债券信息网"},
                 "shibor": {"rate": 1.45, "change_bp": -0.2, "source": "中国货币网"},
                 "term_spread": 0.56, "term_spread_source": "中国债券信息网",
                 "bond_etfs": [{"name": "国债ETF", "pct": 0.05, "source": "东方财富"}]},
        "convertible": {"csi_index": {"pct": 0.3, "close": 400, "source": "新浪财经"},
                        "avg_price": 120.5, "avg_premium": 35.0, "premium_percentile_3y": 60.0,
                        "below_par": 30, "turnover": 5e8, "force_redeem": ["XX转债"],
                        "stats_source": "东方财富", "redeem_source": "集思录"},
    }


def test_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    data = _data()
    interp = analyze.analyze(data)
    assert llm.generate_narratives(data, interp, dt.date(2026, 8, 1)) == {}


def test_call_failure_returns_empty(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "gsk_test")
    monkeypatch.setattr(llm, "_call_groq", lambda *a, **k: None)
    data = _data()
    interp = analyze.analyze(data)
    assert llm.generate_narratives(data, interp, dt.date(2026, 8, 1)) == {}


def test_extract_sections_basic():
    txt = "===overview===\n**解读与判断**\n开盘偏强\n===equity===\n情绪偏暖"
    out = llm._extract_sections(txt)
    assert out == {"overview": "**解读与判断**\n开盘偏强", "equity": "情绪偏暖"}


def test_extract_sections_case_insensitive():
    out = llm._extract_sections("===OVERVIEW===\n开盘偏强")
    assert out == {"overview": "开盘偏强"}


def test_extract_sections_with_fence():
    txt = "```\n===overview===\n开盘偏强\n===equity===\n情绪偏暖\n```"
    out = llm._extract_sections(txt)
    assert out["overview"] == "开盘偏强" and out["equity"] == "情绪偏暖"


def test_extract_sections_ignores_leading_text():
    """标记前的闲聊文字应被忽略,中间板块按下一个标记干净切分。"""
    txt = "好的,以下是结果:\n===etf===\n资金流入\n===bond===\n利率平稳"
    assert llm._extract_sections(txt) == {"etf": "资金流入", "bond": "利率平稳"}


def test_extract_sections_no_markers_returns_empty():
    assert llm._extract_sections("没有任何标记的普通文本") == {}
    assert llm._extract_sections("") == {}


def test_generate_with_mocked_call(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "gsk_test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setattr(llm, "_call_groq", lambda *a, **k:
                        "===overview===\n开盘偏强\n===equity===\n情绪偏暖\n===etf===\n资金流入"
                        "\n===bond===\n利率平稳\n===convertible===\n估值中性")
    data = _data()
    interp = analyze.analyze(data)
    out = llm.generate_narratives(data, interp, dt.date(2026, 8, 1))
    assert set(out.keys()) == {"overview", "equity", "etf", "bond", "convertible"}
    assert out["overview"] == "开盘偏强"


def test_generate_partial_sections(monkeypatch):
    """模型只返回部分板块时,只保留已有部分,其余回退规则版。"""
    monkeypatch.setenv("LLM_API_KEY", "gsk_test")
    monkeypatch.setattr(llm, "_call_groq", lambda *a, **k:
                        "===overview===\n开盘偏强\n===equity===\n情绪偏暖")
    data = _data()
    interp = analyze.analyze(data)
    out = llm.generate_narratives(data, interp, dt.date(2026, 8, 1))
    assert set(out.keys()) == {"overview", "equity"}


def test_prompt_forbids_fabrication():
    """system prompt 必须含「严禁编造」红线。"""
    assert "严禁编造" in llm.SYSTEM_PROMPT


def test_prompt_uses_delimiter_protocol():
    """system prompt 必须声明分隔符协议。"""
    assert "===overview===" in llm.SYSTEM_PROMPT


def test_facts_text_contains_section_headers():
    """facts_text 应覆盖五个板块且复述真实数值(供 LLM 引用)。"""
    data = _data()
    interp = analyze.analyze(data)
    txt = analyze.facts_text(data, interp)
    for h in ["【一、", "【二、", "【三、", "【四、", "【五、"]:
        assert h in txt
    assert "沪深300ETF" in txt  # ETF 明细
    assert "1.71" in txt  # 国债10Y 真实数值
