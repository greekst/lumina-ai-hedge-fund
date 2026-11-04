"""Fee/slippage deduction and SQLite ledger integrity for the paper trader."""
import sqlite3
import time

import pytest

from core.ai_hedge_fund.cost_model import CostModel


def test_cost_model_buy_sell_math():
    cm = CostModel(commission_bps=10.0, commission_min=1.0, slippage_bps=20.0)
    b = cm.execute(100.0, 50, "BUY")
    assert b["fill_price"] == pytest.approx(100.2)
    assert b["gross_notional"] == pytest.approx(5010.0)
    assert b["commission"] == pytest.approx(5.01)
    assert b["slippage_cost"] == pytest.approx(10.0)
    assert b["net_cash_flow"] == pytest.approx(-5015.01)
    s = cm.execute(100.0, 50, "SELL")
    assert s["fill_price"] == pytest.approx(99.8)
    assert s["net_cash_flow"] == pytest.approx(4990.0 - 4.99)


def test_minimum_commission_and_round_trip():
    cm = CostModel(commission_bps=5.0, commission_min=1.0, slippage_bps=5.0)
    assert cm.commission(100.0) == 1.0  # 0.05 < min
    rt = cm.round_trip_return(100.0, 100.0)
    assert rt < 0  # flat price round trip loses costs
    assert rt == pytest.approx((100 * 0.9995 * 0.9995) / (100 * 1.0005 * 1.0005) - 1)


def test_invalid_inputs_rejected():
    cm = CostModel()
    with pytest.raises(ValueError):
        cm.execute(0.0, 10, "BUY")
    with pytest.raises(ValueError):
        cm.execute(10.0, 10, "HOLD")


def _usd_cash(eng):
    return float(eng.get_account_balance().get("USD", 0.0))


def _orders(eng):
    with sqlite3.connect(eng.db_path) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM orders ORDER BY order_id")]


def test_paper_trade_deducts_fees_and_slippage(paper_engine, monkeypatch):
    monkeypatch.setenv("LUMINA_COMMISSION_BPS", "10")
    monkeypatch.setenv("LUMINA_COMMISSION_MIN", "1")
    monkeypatch.setenv("LUMINA_SLIPPAGE_BPS", "20")
    eng = paper_engine
    cash0 = _usd_cash(eng)
    r = eng.place_order("AAPL", "BUY", 10, price=100.0, enforce_market_hours=False, signal_timestamp=time.time())
    assert r["success"], r
    assert r["executed_price"] == pytest.approx(100.2)
    assert r["commission"] == pytest.approx(1.002)
    assert _usd_cash(eng) == pytest.approx(cash0 - 1002.0 - 1.002)
    pos = {p["symbol"]: p for p in eng.get_positions()}["AAPL"]
    # avg entry = slipped fill price; commission is charged to cash, not the basis
    assert pos["avg_entry_price"] == pytest.approx(100.2)

    r2 = eng.place_order("AAPL", "SELL", 10, price=100.0, enforce_market_hours=False, signal_timestamp=time.time())
    assert r2["success"], r2
    # Flat price round trip must lose exactly the modelled costs
    expected_loss = (1002.0 + 1.002) - (998.0 - 1.0)
    assert _usd_cash(eng) == pytest.approx(cash0 - expected_loss)
    orders = _orders(eng)
    assert [o["side"] for o in orders] == ["BUY", "SELL"]
    assert orders[0]["quote_price"] == pytest.approx(100.0)
    assert orders[0]["commission"] == pytest.approx(1.002)
    assert orders[1]["slippage_cost"] == pytest.approx(2.0)


def test_ledger_integrity_rejections_do_not_mutate_state(paper_engine):
    eng = paper_engine
    cash0 = _usd_cash(eng)
    # Oversell with no position
    r = eng.place_order("MSFT", "SELL", 5, price=50.0, enforce_market_hours=False, signal_timestamp=time.time())
    assert not r["success"]
    # Insufficient cash
    r = eng.place_order("MSFT", "BUY", 10_000_000, price=50.0, enforce_market_hours=False, signal_timestamp=time.time())
    assert not r["success"]
    assert _usd_cash(eng) == pytest.approx(cash0)
    assert eng.get_positions() == []
    assert _orders(eng) == []
    # Idempotency reservation released (audit P1-4): a valid retry goes through
    r = eng.place_order("MSFT", "BUY", 1, price=50.0, enforce_market_hours=False, signal_timestamp=time.time())
    assert r["success"], r


def test_ledger_conservation_over_many_trades(paper_engine, monkeypatch):
    """Cash after a trade sequence equals initial cash plus the cost model's net cash flows."""
    from core.ai_hedge_fund.idempotency_guard import OrderIdempotencyGuard
    monkeypatch.setattr(OrderIdempotencyGuard, "COOLDOWN_WINDOW_SECONDS", 0)
    eng = paper_engine
    cm = CostModel.from_env()
    cash0 = _usd_cash(eng)
    trades = [("BUY", 3, 100.0), ("BUY", 2, 110.0), ("SELL", 4, 120.0), ("BUY", 1, 90.0), ("SELL", 2, 95.0)]
    expected_cash = cash0
    for i, (side, q, px) in enumerate(trades):
        r = eng.place_order("NVDA", side, q, price=px, enforce_market_hours=False, signal_timestamp=time.time())
        assert r["success"], r
        expected_cash += cm.execute(px, q, side)["net_cash_flow"]
    assert _usd_cash(eng) == pytest.approx(expected_cash)
    assert eng.get_positions() == []
    assert len(_orders(eng)) == len(trades)
