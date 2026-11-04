"""Phase C: anonymisation, budget/cache discipline and point-in-time invariance of the LLM data path."""
import json
import os
import re

import numpy as np
import pytest

from backtest import anonymise as A
from backtest import llm_client as LC
from backtest import walkforward as wf
from backtest.pit import Snapshot, decision_session

SNAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest", "snapshots", "2026-11-04")
needs_snap = pytest.mark.skipif(not os.path.exists(SNAP), reason="snapshot not present")


def _inp():
    snap = Snapshot.load(SNAP)
    ev = snap.events["AAPL"][-4]
    D = decision_session(snap.sessions("AAPL"), ev["announced_at_et"])
    return snap, ev, D, wf.build_inputs(snap, "AAPL", D, ev["announced_at_et"])


@needs_snap
@pytest.mark.parametrize("level", [1, 2])
def test_block_contains_no_identifiers(level):
    snap, ev, D, inp = _inp()
    block = A.data_block(inp, A.company_code("AAPL", snap.manifest["tickers"]), "Information Technology", level)
    assert "AAPL" not in block and "Apple" not in block and "iPhone" not in block
    assert not re.search(r"\b(19|20)\d{2}\b", block), "no years / absolute dates"
    assert not re.search(r"\bQ[1-4]\b", block), "no calendar quarters"
    price = inp["stock"]["current_price"]
    assert f"{price:.0f}" not in re.findall(r"\d+", block) or price < 100, "no absolute price level"
    assert "CO-" in block


def test_company_code_is_stable_and_not_alphabetical():
    u = ["AAPL", "AMZN", "MSFT", "NVDA", "XOM"]
    codes = [A.company_code(t, u) for t in u]
    assert len(set(codes)) == len(u) and codes == [A.company_code(t, list(reversed(u))) for t in u]
    assert codes != sorted(codes)


@needs_snap
@pytest.mark.parametrize("level", [1, 2])
def test_poisoned_future_cannot_change_the_llm_prompt(level):
    """Every bar from D onward and every post-dated filing poisoned -> identical anonymised prompt."""
    snap, ev, D, inp = _inp()
    code = A.company_code("AAPL", snap.manifest["tickers"])
    ref = A.data_block(inp, code, "Information Technology", level)
    rng = np.random.default_rng(1)
    for k in ("AAPL", "SPY", "^VIX"):
        df = snap.prices[k].copy()
        fut = df.index >= D
        df.loc[fut, ["Open", "High", "Low", "Close", "CloseSplitAdj"]] *= rng.uniform(0.2, 5.0, (fut.sum(), 1))
        snap.prices[k] = df
    snap.fundamentals["AAPL"] = snap.fundamentals["AAPL"] + [dict(
        start="2000-01-01", end="2030-12-31", accepted_at="2030-01-01 00:00", form="10-K",
        net_income=-1e15, equity=1.0, revenue=1e18, diluted_shares=1.0)]
    poisoned = wf.build_inputs(snap, "AAPL", D, ev["announced_at_et"])
    assert A.data_block(poisoned, code, "Information Technology", level) == ref
    assert A.persona_prompt(A.data_block(poisoned, code, "Information Technology", level)) == A.persona_prompt(ref)


def test_cache_replays_offline_and_budget_cap_is_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(LC, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(LC, "BUDGET_FILE", str(tmp_path / "budget.json"))
    g = LC.GeminiCached(allow_live=False)
    key = LC._key(g.model, "sys", "prompt", g.cfg)
    p = g._path(key)
    os.makedirs(os.path.dirname(p))
    with open(p, "w") as fh:
        json.dump({"key": key, "text": "{\"stance\": \"BULLISH\"}", "json": {"stance": "BULLISH"}}, fh)
    assert g.generate("sys", "prompt", "t")["json"]["stance"] == "BULLISH"   # cache hit, no network
    with pytest.raises(RuntimeError):
        g.generate("sys", "other prompt", "t")                                # not cached, live not allowed
    with open(tmp_path / "budget.json", "w") as fh:
        json.dump({"cap": 3, "requests_sent": 3, "ok": 3, "errors": 0, "by_purpose": {}}, fh)
    live = LC.GeminiCached(allow_live=True)
    with pytest.raises(LC.BudgetExceeded):
        live._call("sys", "x", "t")


def test_live_numbers_cannot_reach_the_decision():
    """Hard rule 3: an LLM-returned score is discarded; only the stance maps to a number."""
    from core.ai_hedge_fund.llm_guard import STANCE_SCORE, sanitize_agent_output
    r = sanitize_agent_output({"stance": "bullish", "score": 3})
    assert r["score"] == STANCE_SCORE["BULLISH"] and r["llm_raw_score"] == 3
    assert sanitize_agent_output({"stance": "TO THE MOON", "score": 100})["score"] == STANCE_SCORE["NEUTRAL"]
