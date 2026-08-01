# -*- coding: utf-8 -*-
"""规则解读层测试(纯逻辑,无网络)。"""
import datetime as dt
from src import analyze


def _data(hs=0.8, vol_chg=15.0, adv=3000, dec=2000, dow=0.6, us10y_chg=4.0,
          a50=0.4, chg10=4.0, dr_chg=12.0, spread=0.6, prem=40.0, pctile=85.0,
          below=120):
    return {
        "overview": {"dow": {"pct": dow}, "us10y": {"change_bp": us10y_chg}, "a50": {"pct": a50}},
        "equity": {
            "hs300": {"pct": hs}, "zz1000": {"pct": hs - 0.8},
            "turnover": {"change_pct": vol_chg},
            "advance_decline": {"advancing": adv, "declining": dec},
            "style": "小盘相对占优(近似)",
        },
        "etf": {"flow_top3": [{"name": "沪深300ETF"}], "premium_anomalies": [{"name": "券商ETF", "premium": 1.5}]},
        "bond": {"gov": {"cn10y_chg_bp": chg10}, "shibor": {"change_bp": dr_chg, "rate": 1.55}, "term_spread": spread},
        "convertible": {"avg_premium": prem, "premium_percentile_3y": pctile, "below_par": below,
                        "force_redeem": ["XX转债"]},
    }


def test_opening_call_up():
    r = analyze.analyze(_data(dow=1.2, us10y_chg=6.0, a50=0.5))
    assert "美股偏强" in r["opening_call"]
    assert "高开" in r["opening_call"]


def test_market_temperature_hot():
    r = analyze.analyze(_data(hs=1.2, vol_chg=15.0, adv=3500, dec=1500))
    assert "情绪偏热" in r["market_temperature"] or "情绪偏暖" in r["market_temperature"]


def test_market_temperature_cold():
    r = analyze.analyze(_data(hs=-1.2, vol_chg=15.0, adv=1000, dec=4000))
    assert "情绪偏弱" in r["market_temperature"] or "情绪偏冷" in r["market_temperature"]


def test_bond_reference_tightening():
    r = analyze.analyze(_data(chg10=5.0, dr_chg=12.0))
    assert "短久期" in r["bond_reference"]


def test_cb_valuation_high():
    r = analyze.analyze(_data(prem=45.0, pctile=90.0, below=150))
    assert "估值偏高" in r["cb_valuation"]
    assert "下修博弈" in r["cb_valuation"]


def test_missing_data_no_fabrication():
    """关键数值缺失时应输出'数据不足,暂不解读',绝不臆造。"""
    d = _data()
    d["equity"]["hs300"]["pct"] = None
    r = analyze.analyze(d)
    assert "数据不足" in r["market_temperature"]
