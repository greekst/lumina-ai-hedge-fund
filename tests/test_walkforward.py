"""Walk-forward harness: determinism, point-in-time guarantees, event alignment, TTM math."""
import os

import numpy as np
import pandas as pd
import pytest

from backtest import walkforward as wf
from backtest.pit import Snapshot, _ttm, decision_session, pit_fundamentals

SNAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest", "snapshots", "2026-11-04")
needs_snap = pytest.mark.skipif(not os.path.exists(SNAP), reason="snapshot not present")


def test_decision_session_alignment():
    s = pd.bdate_range("2024-01-01", "2024-01-31")
    # after close on Wed 10th -> decide at Wed 10th close
    assert decision_session(s, "2024-01-10 16:05") == pd.Timestamp("2024-01-10")
    assert decision_session(s, "2024-01-10 16:00") == pd.Timestamp("2024-01-10")
    # pre-open / intraday -> previous session
    assert decision_session(s, "2024-01-10 06:00") == pd.Timestamp("2024-01-09")
    assert decision_session(s, "2024-01-10 12:00") == pd.Timestamp("2024-01-09")
    # Monday pre-open -> Friday
    assert decision_session(s, "2024-01-15 07:00") == pd.Timestamp("2024-01-12")


def _f(start, end, acc, **v):
    return dict(start=start, end=end, accepted_at=acc, form="10-Q", **v)


def test_ttm_and_point_in_time_filings():
    filings = [
        _f("2022-01-01", "2022-12-31", "2023-02-01 16:00", net_income=100.0),
        _f("2022-01-01", "2022-06-30", "2022-08-01 16:00", net_income=40.0),
        _f("2023-01-01", "2023-06-30", "2023-08-01 16:00", net_income=60.0),
        # restatement of FY2022 accepted later: must be ignored before its acceptance
        _f("2022-01-01", "2022-12-31", "2023-09-01 16:00", net_income=999.0),
    ]
    from backtest.pit import _available
    ttm = _ttm(_available(filings, pd.Timestamp("2023-08-15")), "net_income")
    assert ttm["value"] == pytest.approx(100 + 60 - 40)
    assert _ttm(_available(filings, pd.Timestamp("2023-08-01 15:59")), "net_income")["value"] == 100.0  # 10-Q not yet accepted
    assert _ttm(_available(filings, pd.Timestamp("2023-10-01")), "net_income")["value"] == pytest.approx(999 + 60 - 40)


def test_eps_split_normalisation():
    filings = [_f("2023-01-01", "2023-12-31", "2024-02-01 16:00", net_income=1000.0, diluted_shares=100.0, equity=5000.0)]
    pre = pit_fundamentals(filings, pd.Timestamp("2024-03-01"), price=20.0, splits=[{"date": "2024-06-10", "ratio": 10.0}])
    # 100 shares pre-split -> 1000 post-split; EPS 1.0 -> P/E 20
    assert pre["pe_trailing"] == pytest.approx(20.0)
    assert pre["roe"] == pytest.approx(20.0)
    assert pre["_tags"]["pe_trailing"]["as_of"] == "2024-02-01"


@needs_snap
def test_future_data_cannot_change_a_decision():
    """Poison every bar after features_through and every filing after the announcement: decisions must not move."""
    snap = Snapshot.load(SNAP)
    t = "AAPL"
    ev = snap.events[t][-6]
    D = decision_session(snap.sessions(t), ev["announced_at_et"])
    base = wf.build_inputs(snap, t, D, ev["announced_at_et"])
    ref = {s: wf.DECIDERS[s](base) for s in wf.STRATEGIES}

    # Independent cutoff: nothing from the decision session D onward may be used.
    rng = np.random.default_rng(0)
    for k in (t, "SPY", "^VIX"):
        df = snap.prices[k].copy()
        fut = df.index >= D
        df.loc[fut, ["Open", "High", "Low", "Close", "CloseSplitAdj"]] *= rng.uniform(0.2, 5.0, (fut.sum(), 1))
        snap.prices[k] = df
    snap.fundamentals[t] = snap.fundamentals[t] + [
        _f("2000-01-01", "2030-12-31", "2030-01-01 00:00", net_income=-1e15, equity=1.0, revenue=1e18, diluted_shares=1.0),
        # accepted after the close of D (the decision time) but before the announcement
        _f("2000-01-01", D.strftime("%Y-%m-%d"), f"{D.date()} 16:01:00", net_income=-1e15, equity=1.0, revenue=1e18,
           diluted_shares=1.0)]
    poisoned = wf.build_inputs(snap, t, D, ev["announced_at_et"])
    assert poisoned["stock"] == base["stock"]
    for s in wf.STRATEGIES:
        assert wf.DECIDERS[s](poisoned) == ref[s], s


@needs_snap
def test_rerun_is_byte_identical(tmp_path):
    kw = dict(n_events=3, tickers=["AAPL", "JPM"])
    a = wf.run(SNAP, out_dir=str(tmp_path / "a"), **kw)
    b = wf.run(SNAP, out_dir=str(tmp_path / "b"), **kw)
    assert wf.digest(a["paths"]) == wf.digest(b["paths"])
    rows = a["rows"]
    assert set(rows.strategy) == set(wf.STRATEGIES) and len(rows) == 2 * 3 * len(wf.STRATEGIES)
    assert (pd.to_datetime(rows.features_through) < pd.to_datetime(rows.decision_date)).all()
    assert (pd.to_datetime(rows.decision_date) <= pd.to_datetime(rows.announced_at_et)).all()


@needs_snap
def test_snapshot_hashes_match_manifest():
    from backtest.snapshot import verify
    assert verify(SNAP) == []


# ---------------------------------------------------------------- Session 2: EDGAR / S&P 100 snapshot
SNAP2 = os.path.join(os.path.dirname(SNAP), "2026-11-04-sp100")
needs_snap2 = pytest.mark.skipif(not os.path.exists(os.path.join(SNAP2, "manifest.json")), reason="sp100 snapshot not present")


@needs_snap2
@pytest.mark.parametrize("t", ["JPM", "XOM", "NVDA"])
def test_edgar_snapshot_future_poison_cannot_change_a_decision(t):
    """EDGAR fundamentals + 8-K event times + sector ETF: poison everything from D on, decisions must not move."""
    snap = Snapshot.load(SNAP2)
    ev = snap.events[t][-5]
    D = decision_session(snap.sessions(t), ev["announced_at_et"])
    base = wf.build_inputs(snap, t, D, ev["announced_at_et"])
    ref = {s: wf.DECIDERS[s](base) for s in wf.STRATEGIES}
    rng = np.random.default_rng(3)
    etf = snap.universe[t]["sector_etf"]
    for k in (t, "SPY", "^VIX", etf):
        df = snap.prices[k].copy()
        fut = df.index >= D
        df.loc[fut, ["Open", "High", "Low", "Close", "CloseSplitAdj"]] *= rng.uniform(0.2, 5.0, (fut.sum(), 1))
        snap.prices[k] = df
    # a filing accepted one minute after the close of D (before a pre-market release, after the decision)
    # and a far-future restatement
    acc = pd.Timestamp(f"{D.date()} 16:01:00")
    snap.fundamentals[t] = snap.fundamentals[t] + [
        _f("2000-01-01", "2030-12-31", "2030-01-01 00:00", net_income=-1e15, equity=1.0, revenue=1e18, diluted_shares=1.0),
        _f("2000-01-01", D.strftime("%Y-%m-%d"), acc.strftime("%Y-%m-%d %H:%M:%S"), net_income=-1e15, equity=1.0,
           revenue=1e18, diluted_shares=1.0)]
    poisoned = wf.build_inputs(snap, t, D, ev["announced_at_et"])
    assert poisoned["stock"] == base["stock"]
    for s in wf.STRATEGIES:
        assert wf.DECIDERS[s](poisoned) == ref[s], s


@needs_snap2
def test_edgar_snapshot_rerun_identical_and_sector_benchmark(tmp_path):
    kw = dict(n_events=3, tickers=["AAPL", "JPM", "XOM"])
    a = wf.run(SNAP2, out_dir=str(tmp_path / "a"), **kw)
    b = wf.run(SNAP2, out_dir=str(tmp_path / "b"), **kw)
    assert wf.digest(a["paths"]) == wf.digest(b["paths"])
    r = a["rows"]
    assert set(r.sector_etf) == {"XLK", "XLF", "XLE"}
    assert r.filter(like="sector_ret_").notna().all().all()
    assert (pd.to_datetime(r.features_through) < pd.to_datetime(r.decision_date)).all()
    assert "cells" in a["summary"]


@needs_snap2
def test_edgar_snapshot_hashes_match_manifest():
    from backtest.snapshot import verify
    assert verify(SNAP2) == []


@needs_snap
def test_overnight_filing_before_premarket_release_is_excluded():
    """Pre-market release on day X -> D = X-1, entry at the close of D. A filing accepted at 16:01 on D is
    public before the release but AFTER the decision: it must not be used (cutoff = min(release, close of D))."""
    snap = Snapshot.load(SNAP)
    t = "JPM"
    ev = snap.events[t][-6]
    sessions = snap.sessions(t)
    D = decision_session(sessions, ev["announced_at_et"])
    nxt = sessions[sessions.get_loc(D) + 1]
    release = f"{nxt.date()} 07:00"
    assert decision_session(sessions, release) == D
    base = wf.build_inputs(snap, t, D, release)
    snap.fundamentals[t] = snap.fundamentals[t] + [
        _f("2000-01-01", D.strftime("%Y-%m-%d"), f"{D.date()} 16:01:00", net_income=-1e15, equity=1.0, revenue=1e18,
           diluted_shares=1.0)]
    assert wf.build_inputs(snap, t, D, release)["stock"] == base["stock"]
