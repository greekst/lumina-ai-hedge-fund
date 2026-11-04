# -*- coding: utf-8 -*-
"""Session 3: point-in-time universe (shares rule, ranking, P1-5 comparatives, two-way clustering)."""

import numpy as np
import pandas as pd

from backtest import pit_universe as PU
from backtest.edgar import fundamentals_from_companyfacts
from backtest.pit import _yoy_growth
from backtest.stats import cluster_diff_2way


def test_shares_rule_prefers_consistent_cover_value_and_rejects_partial_class():
    # single class: cover value consistent with the weighted count -> cover value
    assert PU.shares_from_filing(1.02e9, 1.0e9, None, None, None) == (1.02e9, "dei cover shares")
    # multi-class filer reporting one class on the cover (FOXA reported 1) -> weighted count
    v, m = PU.shares_from_filing(1.0, 4.3e8, None, None, None)
    assert v == 4.3e8 and m == "weighted diluted"
    # no weighted count (Visa): NI / EPS of the same filing
    v, m = PU.shares_from_filing(None, None, None, 5.0e9, 2.5)
    assert v == 2.0e9 and m.startswith("net income")
    # unit error (shares in millions) caught by NI / EPS
    v, m = PU.shares_from_filing(None, 718.2, None, 8.0e9, 11.0)
    assert abs(v - 8.0e9 / 11.0) < 1 and "sanity" in m


def test_shares_series_is_keyed_by_acceptance_and_picks_quarter():
    facts = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2024-04-20", "val": 1.0e9, "accn": "A1", "form": "10-Q", "filed": "2024-05-01"}]}}},
        "us-gaap": {"WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
            {"start": "2024-01-01", "end": "2024-03-31", "val": 1.01e9, "accn": "A1", "form": "10-Q", "filed": "2024-05-01"},
            {"start": "2023-01-01", "end": "2023-03-31", "val": 0.9e9, "accn": "A1", "form": "10-Q", "filed": "2024-05-01"}]}}}}}
    subs = [{"accessionNumber": "A1", "acceptanceDateTime": "2024-05-01T20:05:00.000Z", "form": "10-Q"}]
    s = PU.shares_series(facts, subs)
    assert s == [{"accepted_at": "2024-05-01 16:05:00", "as_of": "2024-04-20", "shares": 1.0e9,
                  "method": "dei cover shares", "form": "10-Q", "accn": "A1", "assets": None}]
    # strictly before the cutoff
    assert PU.shares_at(s, pd.Timestamp("2024-05-01 16:05:00")) is None
    assert PU.shares_at(s, pd.Timestamp("2024-05-01 16:05:01"))["shares"] == 1.0e9


class _Snap:
    def __init__(self):
        idx = pd.to_datetime(["2024-05-01", "2024-05-02"])
        self.prices = {"A": pd.DataFrame({"CloseSplitAdj": [10.0, 10.0]}, index=idx),
                       "B": pd.DataFrame({"CloseSplitAdj": [30.0, 30.0]}, index=idx),
                       "BRK.B": pd.DataFrame({"CloseSplitAdj": [400.0, 400.0]}, index=idx)}
        self.shares = {"A": [{"accepted_at": "2024-01-01 08:00:00", "as_of": "2023-12-31", "shares": 100.0}],
                       "B": [{"accepted_at": "2024-01-01 08:00:00", "as_of": "2023-12-31", "shares": 100.0},
                             {"accepted_at": "2024-05-01 17:00:00", "as_of": "2024-05-01", "shares": 50.0}],
                       "BRK.B": [{"accepted_at": "2024-01-01 08:00:00", "as_of": "2023-12-31", "shares": 1.0}]}
        # A split 2:1 after its share date: 100 shares then = 200 on today's (price) basis
        self.splits = {"A": [{"date": "2024-03-01", "ratio": 2.0}]}
        self.manifest = {"tickers": ["A", "B", "BRK.B"]}
        self.universe, self.floats = {}, {}


def test_market_cap_uses_split_basis_class_multiplier_and_pit_shares():
    snap = _Snap()
    caps = PU.market_caps_on(snap, pd.Timestamp("2024-05-01"))
    assert caps == {"A": 2000.0, "B": 3000.0, "BRK.B": 600000.0}   # B's 17:00 filing is not yet public at 16:00
    assert PU.rank_on(snap, pd.Timestamp("2024-05-01")) == {"BRK.B": 1, "B": 2, "A": 3}
    assert PU.rank_on(snap, pd.Timestamp("2024-05-02"))["B"] == 3   # now the new (small) share count applies


def test_prior_year_comparative_comes_from_the_same_filing():
    rows = [  # restated prior year inside the 2025 10-Q (spin-off): 60, while the old filing said 100
        {"start": "2025-01-01", "end": "2025-03-31", "val": 66.0, "accn": "N", "form": "10-Q", "filed": "2025-05-01", "fp": "Q1"},
        {"start": "2024-01-01", "end": "2024-03-31", "val": 60.0, "accn": "N", "form": "10-Q", "filed": "2025-05-01", "fp": "Q1"},
        {"start": "2024-01-01", "end": "2024-03-31", "val": 100.0, "accn": "O", "form": "10-Q", "filed": "2024-05-01", "fp": "Q1"}]
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
    subs = [{"accessionNumber": "N", "acceptanceDateTime": "2025-05-01T20:00:00.000Z", "form": "10-Q", "filingDate": "2025-05-01"},
            {"accessionNumber": "O", "acceptanceDateTime": "2024-05-01T20:00:00.000Z", "form": "10-Q", "filingDate": "2024-05-01"}]
    recs = fundamentals_from_companyfacts(facts, subs, since="2020-01-01", comparatives=True)
    new = [r for r in recs if r["access_number"] == "N"][0]
    assert new["revenue"] == 66.0 and new["revenue_prior"] == 60.0
    assert round(_yoy_growth(recs, "revenue", "comparative")["value"], 6) == 10.0     # restated basis
    assert round(_yoy_growth(recs, "revenue", "legacy")["value"], 6) == -34.0         # spin-off artefact


def test_two_way_bootstrap_detects_effect_and_is_wider_than_one_way():
    rng = np.random.default_rng(0)
    n_t, n_s = 40, 20
    tick = np.repeat(np.arange(n_t), n_s)
    seas = np.tile(np.arange(n_s), n_t)
    g = rng.random(n_t * n_s) < 0.5
    y = rng.normal(0, 1, n_t * n_s) + rng.normal(0, 1, n_s)[seas] + 0.0 * g
    null = cluster_diff_2way(y, g, seas, tick, n_boot=500)
    assert null["lo"] < 0 < null["hi"] and null["p_one_sided"] > 0.05
    eff = cluster_diff_2way(y + 0.5 * g, g, seas, tick, n_boot=500)
    assert eff["p05"] > 0 and eff["p_one_sided"] < 0.05
    assert eff["n_c1"] == n_s and eff["n_c2"] == n_t


def test_unconfirmed_share_jump_is_held_back_until_confirmed():
    ser = [{"accepted_at": "2020-01-01 08:00:00", "as_of": "2019-12-31", "shares": 100.0},
           {"accepted_at": "2020-04-01 08:00:00", "as_of": "2020-03-31", "shares": 1e5},     # one-off tagging error
           {"accepted_at": "2020-07-01 08:00:00", "as_of": "2020-06-30", "shares": 101.0},
           {"accepted_at": "2020-10-01 08:00:00", "as_of": "2020-09-30", "shares": 400.0},   # real (stock merger)...
           {"accepted_at": "2021-01-01 08:00:00", "as_of": "2020-12-31", "shares": 410.0}]   # ...confirmed next filing
    kept = [r["shares"] for r in PU.accepted_series(ser, [])]
    assert kept == [100.0, 101.0, 410.0]
    # a split is not a jump: 100 shares then = 400 today after a 4:1 split
    ser2 = [{"accepted_at": "2020-01-01 08:00:00", "as_of": "2019-12-31", "shares": 100.0},
            {"accepted_at": "2020-07-01 08:00:00", "as_of": "2020-06-30", "shares": 400.0}]
    assert len(PU.accepted_series(ser2, [{"date": "2020-03-01", "ratio": 4.0}])) == 2


def test_float_cross_check():
    assert PU.float_check_ok(100.0, 50.0) and PU.float_check_ok(100.0, None)
    assert not PU.float_check_ok(1e12, 1e7)            # cap 1e5 x the float: ADS-ratio / unit junk
    assert PU.float_check_ok(1e12, 0.9e9, shares_confirmed=True)   # float tagged in thousands, shares confirmed
    assert not PU.float_check_ok(1e12, 0.9e9)                       # same signature, single-tag share count


def test_v2_unit_band_and_v1_unchanged():
    # COP-style: weighted count tagged exactly x1/1000 -> v1 (inclusive bounds, as pre-registered) keeps it, v2 replaces it
    v1, _ = PU.shares_from_filing(None, 1.24e6, None, 2.48e9, 2.0)
    v2, m2 = PU.shares_from_filing(None, 1.24e6, None, 2.48e9, 2.0, unit_band=200.0)
    assert v1 == 1.24e6 and abs(v2 - 1.24e9) < 1 and "unit" in m2
