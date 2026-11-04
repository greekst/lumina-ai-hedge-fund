"""CRO veto (0% allocation), ATR stop floor, LLM-number guard, mock mode, kill switches."""
import json

import pytest

from core.ai_hedge_fund.agents import ALL_ANALYST_AGENTS, PortfolioManagerAgent, RiskManagerAgent
from core.ai_hedge_fund.options_gex_feed import OptionsGexFeed


@pytest.fixture
def calm_market(monkeypatch):
    monkeypatch.setattr(OptionsGexFeed, "get_market_turbulence_warning", classmethod(lambda cls: {"is_turbulence": False}))


@pytest.fixture
def turbulent_market(monkeypatch):
    monkeypatch.setattr(OptionsGexFeed, "get_market_turbulence_warning", classmethod(lambda cls: {"is_turbulence": True}))


def _stock(vol=20.0, atr_pct=2.0, dynamic_sl=None, **kw):
    d = {"symbol": "TEST", "name": "Test Co", "current_price": 100.0, "currency": "USD",
         "roe": 20.0, "pb_ratio": 2.0, "piotroski_f_score": 8,
         "history_metrics": {"volatility_annualized_pct": vol, "atr_pct": atr_pct, "sma_200": 90.0}}
    if dynamic_sl is not None:
        d["history_metrics"]["dynamic_stop_loss_price"] = dynamic_sl
    d.update(kw)
    return d


def _bulls(n=5):
    return [{"agent_id": f"a{i}", "name": f"A{i}", "stance": "BULLISH", "score": 85} for i in range(n)]


# ---------------- CRO veto ----------------
@pytest.mark.parametrize("vol,turb,ctx,expect_veto", [
    (65.0, False, {}, True),                                              # extreme volatility
    (35.0, True, {}, True),                                               # gamma flip + vol >= 30
    (20.0, True, {"macro_liquidity": {"liquidity_crunch": True}}, True),  # gamma flip + liquidity crunch
    (20.0, False, {"news_intelligence": {"is_quarantined": True}}, True), # quarantined news
    (20.0, False, {}, False),
])
def test_cro_veto_paths(monkeypatch, vol, turb, ctx, expect_veto):
    monkeypatch.setattr(OptionsGexFeed, "get_market_turbulence_warning", classmethod(lambda cls: {"is_turbulence": turb}))
    r = RiskManagerAgent.evaluate_risk(_stock(vol=vol), _bulls(), dict(ctx, lang="en"))
    assert r["veto_triggered"] is expect_veto
    if expect_veto:
        assert r["max_allocation_pct"] == 0.0 and r["stance"] == "VETO"


def test_cro_ood_veto_when_forecast_bullish_but_fundamentals_broken(calm_market):
    ctx = {"quantum_forecast": {"consensus_status": "DOUBLE_BULLISH", "ensemble_expected_return_pct": 4.0}}
    r = RiskManagerAgent.evaluate_risk(_stock(roe=5.0), _bulls(), ctx)
    assert r["veto_triggered"] and r["max_allocation_pct"] == 0.0


def test_veto_forces_zero_allocation_in_final_verdict(monkeypatch):
    monkeypatch.setattr(OptionsGexFeed, "get_market_turbulence_warning", classmethod(lambda cls: {"is_turbulence": False}))
    stock = _stock(vol=70.0)
    risk = RiskManagerAgent.evaluate_risk(stock, _bulls(7), {})
    v = PortfolioManagerAgent.synthesize_verdict(stock, _bulls(7), risk, {})["verdict"]
    assert v["action"] == "HOLD" and v["allocation_pct"] == 0.0 and v["confidence_score"] <= 30


# ---------------- ATR stop floor ----------------
@pytest.mark.parametrize("atr_pct,expected_stop", [
    (1.0, 95.0),    # 2*ATR = 2%  -> floor at 5%
    (4.0, 92.0),    # 2*ATR = 8%
    (10.0, 84.0),   # 2*ATR = 20% -> cap at 16%
])
def test_atr_breathing_floor(calm_market, atr_pct, expected_stop):
    r = RiskManagerAgent.evaluate_risk(_stock(atr_pct=atr_pct), _bulls(3), {})
    assert r["stop_loss_price"] == pytest.approx(expected_stop)


def test_dynamic_stop_takes_precedence(calm_market):
    r = RiskManagerAgent.evaluate_risk(_stock(dynamic_sl=91.234), _bulls(3), {})
    assert r["stop_loss_price"] == pytest.approx(91.23)


def test_patrol_exits_position_below_stop(paper_engine, monkeypatch):
    """A SWING position trading below its stop is liquidated by the patrol."""
    from core.ai_hedge_fund.auto_trader import AutoTrader
    eng = paper_engine
    assert eng.place_order("AAPL", "BUY", 10, price=100.0, enforce_market_hours=False,
                           stop_loss_price=92.0, signal_timestamp=__import__("time").time())["success"]
    pos = dict(eng.get_positions()[0])
    pos.update(current_price=90.0, currency="USD",
               unrealized_pnl_pct=(90.0 / pos["avg_entry_price"] - 1.0) * 100.0)
    monkeypatch.setattr(eng, "get_portfolio_summary", lambda: {"positions": [pos]})
    AutoTrader.patrol_positions(eng, enforce_market_hours=False)
    assert eng.get_positions() == []


# ---------------- LLM guard / mock mode ----------------
def test_guard_replaces_llm_score_with_stance_score():
    from core.ai_hedge_fund.llm_guard import sanitize_agent_output, STANCE_SCORE
    out = sanitize_agent_output({"stance": "bullish", "score": 99})
    assert out["score"] == STANCE_SCORE["BULLISH"] and out["llm_raw_score"] == 99
    assert sanitize_agent_output({"stance": "nonsense", "score": 3})["score"] == STANCE_SCORE["NEUTRAL"]


def test_guard_cro_cio_numbers_are_deterministic():
    from core.ai_hedge_fund.llm_guard import sanitize_cio_verdict, sanitize_cro_verdict
    det = {"verdict": "APPROVED", "risk_level": "MODERATE", "max_position_size_pct": 5.0, "stop_loss_pct": -4.0}
    cro = sanitize_cro_verdict({"verdict": "REQUIRE_REDEBATE", "max_position_size_pct": 10.0, "stop_loss_pct": -20}, det)
    assert cro["verdict"] == "REQUIRE_REDEBATE" and cro["max_position_size_pct"] == 5.0 and cro["stop_loss_pct"] == -4.0
    cio = sanitize_cio_verdict({"conviction_score": 99, "target_allocation_pct": 10, "executive_summary": "x"},
                               {"conviction_score": 55, "target_allocation_pct": 0.0, "stop_loss_pct": -4.0})
    assert cio["conviction_score"] == 55 and cio["target_allocation_pct"] == 0.0 and cio["executive_summary"] == "x"


def test_mock_mode_agents_are_deterministic_and_not_degraded():
    from core.llm_mode import get_llm_mode
    assert get_llm_mode() == "mock"
    stock = _stock()
    a = [ag.evaluate(stock, {}) for ag in ALL_ANALYST_AGENTS]
    b = [ag.evaluate(stock, {}) for ag in ALL_ANALYST_AGENTS]
    assert json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)
    assert not any(x["is_degraded_fallback"] for x in a)
    assert all(x["llm_mode"] == "mock" for x in a)


def test_mock_client_returns_template_json():
    from core.llm_mode import make_genai_client
    c = make_genai_client("ignored")
    prompt = '出力は以下のJSONのみ: {"verdict": "APPROVED", "max_position_size_pct": 2.0から10.0の数値, "comment": "..."}'
    t1 = json.loads(c.models.generate_content(model="m", contents=prompt).text)
    t2 = json.loads(c.models.generate_content(model="m", contents=prompt).text)
    assert t1 == t2 and t1["verdict"] == "APPROVED" and t1["max_position_size_pct"] == 0


def test_llm_key_bug_fixed(monkeypatch):
    import core.llm_mode as lm
    monkeypatch.setenv("LUMINA_LLM_MODE", "")
    monkeypatch.setattr(lm, "_settings_key", lambda: "")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-not-a-real-key")
    assert lm.get_llm_mode() == "live" and lm.get_llm_api_key() == "dummy-not-a-real-key"
    monkeypatch.setenv("LUMINA_LLM_MODE", "off")
    assert lm.get_llm_api_key() == ""


# ---------------- Kill switches (hard rule 1) ----------------
def test_live_brokers_refuse_orders():
    from core.ai_hedge_fund.broker_client import IBKRClient, KabuStationClient
    assert IBKRClient().place_order("AAPL", "BUY", 1)["live_broker_blocked"]
    k = KabuStationClient(api_password="x")
    assert k.authenticate() is False
    assert k.place_order("7203.T", "BUY", 100)["live_broker_blocked"]


def test_social_posting_disabled():
    from x_publisher import XPublisher
    pub = XPublisher(api_key="a", api_secret="b", access_token="c", access_token_secret="d")
    assert pub.post_tweet("hello")["posting_disabled"] is True
    from core.ai_hedge_fund.hedge_fund_notifier import HedgeFundNotifier
    assert HedgeFundNotifier._send_payload({"content": "x"}) is False


def test_lightgbm_gate_labelled_as_assumption():
    from core.ai_hedge_fund.lightgbm_gatekeeper import LightGBMGatekeeper
    g = LightGBMGatekeeper.evaluate_gate("TEST", {"models": {}, "consensus_status": "NEUTRAL"})
    assert g["is_empirical"] is False and g["evidence_label"] == "MODEL ASSUMPTION"
    g2 = LightGBMGatekeeper.evaluate_gate("TEST", {"models": {}, "consensus_status": "NEUTRAL"})
    assert g["win_probability"] == g2["win_probability"]


def test_tear_sheet_has_no_fabricated_kpis(paper_engine):
    from core.ai_hedge_fund.fund_tear_sheet import FundTearSheet
    k = FundTearSheet.generate_tear_sheet(paper_engine, save_image=False)
    for key in ("sharpe_ratio", "sortino_ratio", "max_drawdown_pct", "win_rate_pct", "profit_factor"):
        assert k[key] is None, key
    curve = [(i, 100.0 * (1.001 ** i)) for i in range(30)]
    risk = FundTearSheet.compute_risk_kpis(curve)
    assert risk["max_drawdown_pct"] == 0.0 and risk["annualized_volatility_pct"] == pytest.approx(0.0, abs=1e-6)
