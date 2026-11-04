# -*- coding: utf-8 -*-
"""Session 3: poisoned-future tests for the point-in-time universe snapshot (hard rule 4).

Every data path that can influence WHICH events are traded or WHAT is decided is poisoned after the
decision cut-off: prices of every candidate and benchmark from D on, share counts accepted at or after
16:00 on D-1, and filings accepted at or after the announcement. Membership (rank at D-1), the event set and
every decision-time column must be unchanged. The meta-tests check that the detector FAILS for two
deliberately leaky harness variants (rank one session late; share counts visible one day early).
"""

import copy
import os

import numpy as np
import pandas as pd
import pytest

from backtest import pit_universe as PU
from backtest import walkforward as wf
from backtest.pit import Snapshot

SNAP = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backtest", "snapshots", "2026-11-04-pit")
pytestmark = pytest.mark.skipif(not os.path.exists(os.path.join(SNAP, "manifest.json")), reason="PIT snapshot not built")

DECISION_COLS = ["ticker", "decision_date", "features_through", "strategy", "action", "long", "allocation_pct",
                 "confidence", "cro_veto", "pe_trailing", "roe", "revenue_growth", "vix_d1", "pit_rank_d1"]
DAYS = ["2016-04-25", "2020-07-27", "2024-10-29"]   # busy earnings sessions in three different regimes


@pytest.fixture(scope="module")
def snap():
    return Snapshot.load(SNAP)


def poisoned(snap: Snapshot, D: pd.Timestamp, seed: int = 7) -> Snapshot:
    s = copy.copy(snap)
    rng = np.random.default_rng(seed)
    s.prices = {}
    for t, df in snap.prices.items():
        df = df.copy()
        fut = df.index >= D
        df.loc[fut, ["Open", "High", "Low", "Close", "CloseSplitAdj"]] *= rng.uniform(0.2, 5.0, (int(fut.sum()), 1))
        s.prices[t] = df
    prev = str(snap.sessions("SPY")[snap.sessions("SPY") < D][-1].date())
    s.shares = {}
    for t, ser in snap.shares.items():
        bad = [{"accepted_at": f"{prev} 16:00:00", "as_of": prev, "shares": 1e15, "method": "poison"},
               {"accepted_at": f"{D.date()} 09:00:00", "as_of": str(D.date()), "shares": 1.0, "method": "poison"}]
        s.shares[t] = sorted(ser + bad, key=lambda r: r["accepted_at"])
    s.fundamentals = {t: f + [dict(start="2000-01-01", end="2030-12-31", accepted_at="2099-01-01 00:00:00", form="10-K",
                                   net_income=-1e15, equity=1.0, revenue=1e18, diluted_shares=1.0)]
                      for t, f in snap.fundamentals.items()}
    return s


def _decisions(s: Snapshot, day: str) -> pd.DataFrame:
    r = wf.run(SNAP, None, universe="pit", d_from=day, d_to=day, write=False, snap=s)
    return r["rows"][DECISION_COLS].reset_index(drop=True)


def _detects_leak(snap: Snapshot, day: str) -> bool:
    D = pd.Timestamp(day)
    a, b = _decisions(snap, day), _decisions(poisoned(snap, D), day)
    return not a.equals(b)


@pytest.mark.parametrize("day", DAYS)
def test_membership_rank_ignores_the_future(snap, day):
    D = pd.Timestamp(day)
    prev = snap.sessions("SPY")[snap.sessions("SPY") < D][-1]
    clean = PU.rank_on(snap, prev)
    assert len(clean) >= PU.TOP_N
    assert PU.rank_on(poisoned(snap, D), prev) == clean


@pytest.mark.parametrize("day", DAYS)
def test_pit_universe_decisions_ignore_the_future(snap, day):
    a = _decisions(snap, day)
    assert len(a) > 0 and a["pit_rank_d1"].max() <= PU.TOP_N
    assert not _detects_leak(snap, day)


def test_detector_fails_if_rank_uses_session_d(snap, monkeypatch):
    """Leaky variant 1: membership ranked at the close of D (one session late) instead of D-1."""
    orig = PU.rank_on
    spy = snap.sessions("SPY")

    def late(s, day):
        return orig(s, spy[spy > day][0])
    monkeypatch.setattr(PU, "rank_on", late)
    assert _detects_leak(snap, DAYS[-1])


def test_detector_fails_if_shares_are_visible_early(snap, monkeypatch):
    """Leaky variant 2: share counts accepted up to the next morning are used for the D-1 rank."""
    orig = PU.shares_at

    def early(series, cutoff):
        return orig(series, cutoff + pd.Timedelta(hours=18))
    monkeypatch.setattr(PU, "shares_at", early)
    assert _detects_leak(snap, DAYS[-1])
