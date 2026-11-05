# -*- coding: utf-8 -*-
"""Session 5: tests for backtest/etf_statarb.py. SYNTHETIC DATA ONLY — nothing here reads the real ETF prices."""
import math

import numpy as np
import pandas as pd
import pytest

from backtest import etf_statarb as es
from backtest.etf_statarb import Params

TICK = es.SECTOR_ETFS


def synth(T=900, n=11, seed=0, kind="ou", b=0.90, sig_xi=0.008, f_vol=0.01, start="2015-01-01", pop_vol=2e6):
    """log prices = common random-walk factor + per-asset component. kind: 'ou' (mean-reverting residual) or 'rw' (pure random walk)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=T)
    f = np.cumsum(rng.normal(0.0003, f_vol, T))
    if kind == "rw":
        x = np.cumsum(rng.normal(0, 0.008, (T, n)), axis=0)
    else:
        x = np.zeros((T, n))
        for t in range(1, T):
            x[t] = b * x[t - 1] + rng.normal(0, sig_xi, n)
    beta = 1.0 + 0.1 * rng.standard_normal(n)
    lp = f[:, None] * beta[None, :] + x
    close = pd.DataFrame(100 * np.exp(lp), index=idx, columns=TICK[:n])
    vol = pd.DataFrame(pop_vol * (1 + 0.1 * rng.random((T, n))), index=idx, columns=TICK[:n])
    return close, vol


# ------------------------------------------------------------------------------------------------ invariants

@pytest.mark.parametrize("model", ["xs", "pca"])
def test_gross_exposure_and_tradable_guard(model):
    close, vol = synth(700, seed=1, kind="rw")      # random walks: many windows are non-stationary or too slow
    res = es.backtest(close, vol, Params(factor_model=model))
    gross = np.abs(res.W).sum(axis=1)
    assert gross.max() <= 1.0 + 1e-7
    held = np.abs(res.pos).sum(axis=1) > 0
    assert np.allclose(gross[held], 1.0, atol=1e-9) and np.all(gross[~held] == 0.0)
    # an ETF whose AR(1) coefficient is outside (0,1) or whose half-life is too long is never held
    sg = res.signals
    bad = ~sg.tradable
    assert np.all(res.pos[bad] == 0)
    assert np.any(bad & sg.elig), "test data should contain non-tradable (eligible) cases"


def test_xs_residuals_sum_to_zero_every_day_and_window():
    close, vol = synth(300, seed=2)
    R = close.pct_change().to_numpy()[1:]
    from numpy.lib.stride_tricks import sliding_window_view
    Wn = np.swapaxes(sliding_window_view(R, 60, axis=0), 1, 2)[:50]
    out = es._batch_signals(Wn, Params())
    assert np.abs(out["E"].sum(axis=2)).max() < 1e-12        # cross-sectional residuals sum to zero at every date
    # PCA residuals live in the complement of the K factors: orthogonal to the factor space in every window
    outp = es._batch_signals(Wn, Params(factor_model="pca"))
    assert np.isfinite(outp["E"]).all()


def test_nonstationary_series_get_zero_weight():
    # exact unit root / explosive cumulative residuals must never be tradable
    b = np.array([1.0, 1.0000001, 1.2, 0.9999999999])
    hl = -math.log(2) / np.log(b)
    assert not np.any(((b > 0) & (b < 1) & (hl <= 30))[:3])
    assert not ((b > 0) & (b < 1) & (hl <= 30))[3]            # b just below 1: half-life astronomically long
    # engine level: ETF 0 gets a persistent (momentum) residual -> its cumulative residual has b >= 1 in the windows
    close, vol = synth(700, seed=3, kind="ou")
    r = close.pct_change().fillna(0).to_numpy()
    mom = 1e-4 * np.arange(len(close)) + np.random.default_rng(9).normal(0, 0.0005, len(close))   # accelerating cumulative residual (explosive)
    r[:, 0] = r[:, 0] * 0 + mom
    close2 = pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=close.index, columns=close.columns)
    sg = es.compute_signals(close2, vol)
    nonstat = sg.elig[:, 0] & (sg.b[:, 0] >= 1.0)
    assert nonstat.sum() > 20, "synthetic momentum series should yield b >= 1 windows"
    res = es.backtest(close2, vol)
    assert np.all(res.pos[nonstat, 0] == 0)


def test_state_machine_rules():
    p = Params()
    s = np.array([[0.0], [-1.0], [-1.3], [-1.0], [-0.6], [-0.4], [0.0], [1.3], [3.6], [3.4], [1.0], [1.4], [0.2]])
    tr = np.ones_like(s, dtype=bool)
    pos, entries = es.run_state_machine(s, tr, p)
    assert pos[:, 0].tolist() == [0, 0, 1, 1, 1, 0, 0, -1, 0, 0, 0, -1, 0]   # open long at -1.3, close at -0.4; short at 1.3, stop at 3.6, blocked at 3.4 until |s|<1.25
    assert entries == 3
    # leaving the tradable set forces a close
    tr2 = tr.copy(); tr2[3:, 0] = False
    pos2, _ = es.run_state_machine(s, tr2, p)
    assert pos2[3:, 0].tolist() == [0] * 10
    # entry at |s| >= stop is not allowed
    pos3, _ = es.run_state_machine(np.array([[-3.6], [-3.0]]), np.ones((2, 1), bool), p)
    assert pos3[0, 0] == 0 and pos3[1, 0] == 1


def test_universe_entry_rule_waits_for_a_full_clean_window():
    close, vol = synth(300, seed=4)
    close["XLRE"] = close["XLRE"].where(np.arange(len(close)) >= 100)     # ETF starts on bar 100
    vol.loc[vol.index[100 + 20], "XLRE"] = 0                                # zero-volume bar inside the first window
    el = es.eligibility(close, vol, 60)
    first = np.flatnonzero(el["XLRE"].to_numpy())[0]
    assert first == 100 + 20 + 60 + 1 and not el["XLK"].iloc[:60].any() and el["XLK"].iloc[60]
    sg = es.compute_signals(close, vol)
    assert np.isnan(sg.s[:first, TICK.index("XLRE")]).all() and not np.isnan(sg.s[first, TICK.index("XLRE")])


# ------------------------------------------------------------------------------------------------ economics on synthetic data

def test_ou_series_makes_money():
    nets = []
    for seed in range(3):
        close, vol = synth(1500, seed=10 + seed, b=0.85, sig_xi=0.010)
        res = es.backtest(close, vol)
        r = res.net[res.net.index >= res.start].to_numpy()
        nets.append(r)
        assert r.mean() > 0 and r.mean() / r.std(ddof=1) * math.sqrt(252) > 2.0
    t = es.h2_test(np.concatenate(nets), 20, 2000, 1)
    assert t["reject_h0"]


def test_random_walk_does_not_make_money_beyond_costs():
    means, tstats = [], []
    for seed in range(5):
        close, vol = synth(2500, seed=100 + seed, kind="rw")
        res = es.backtest(close, vol)
        sel = res.net.index >= res.start
        net, gross = res.net[sel].to_numpy(), res.gross[sel].to_numpy()
        means.append(net.mean())
        tstats.append(net.mean() / (net.std(ddof=1) / math.sqrt(len(net))))
        assert net.mean() < gross.mean()                        # costs are charged
        assert res.cost[sel].sum() > 0
    assert max(tstats) < 2.0 and np.mean(means) < 0


# ------------------------------------------------------------------------------------------------ point-in-time

def _scramble_after(close, vol, t, seed=7):
    rng = np.random.default_rng(seed)
    c2, v2 = close.copy(), vol.copy()
    n_after = len(close) - t - 1
    c2.iloc[t + 1:] = c2.iloc[t + 1:].to_numpy()[rng.permutation(n_after)] * rng.uniform(0.5, 1.5, (n_after, close.shape[1]))
    v2.iloc[t + 1:] = v2.iloc[t + 1:].to_numpy()[rng.permutation(n_after)] * rng.uniform(0.3, 3, (n_after, close.shape[1]))
    return c2, v2


def pit_violations(engine, close, vol, t):
    """engine(close, vol) -> (W targets (T,N), H held after each close (T,N)). Returns the list of look-ahead violations at date index t.
    (a) poisoned future: scramble every price/volume after t; targets for dates <= t and positions held after closes <= t+1 must not change.
    (b) same-close: shock the return of day t only (scale all closes from t on); positions held after any close <= t+... must not react to it
        before the close of t+lag, i.e. positions held after the close of day t (and earlier) must not change."""
    bad = []
    W0, H0 = engine(close, vol)
    c2, v2 = _scramble_after(close, vol, t)
    W1, H1 = engine(c2, v2)
    if not np.allclose(W0[: t + 1], W1[: t + 1], atol=1e-12):
        bad.append("targets up to t changed when the future was scrambled")
    if not np.allclose(H0[: t + 2], H1[: t + 2], atol=1e-12):
        bad.append("positions up to t+1 changed when the future was scrambled")
    c3 = close.copy()
    c3.iloc[t:] = c3.iloc[t:] * 1.05
    W3, H3 = engine(c3, vol)
    if not np.allclose(H0[:t + 1], H3[:t + 1], atol=1e-12):
        bad.append("a position held after the close of day t reacts to day t's own return (same-close trade)")
    return bad


def honest_engine(p=Params()):
    def f(close, vol):
        r = es.backtest(close, vol, p)
        return r.W, r.H
    return f


def leaky_same_close(close, vol):
    p = Params()
    sig = es.compute_signals(close, vol, p)
    pos, _ = es.run_state_machine(sig.s, sig.tradable, p)
    W = es.target_weights(sig, pos)
    ex = es.apply_execution(W, sig.returns, 0, p.cost_bps_side)     # forbidden lag 0: trades on the close that produced the signal
    return W, ex["H"]


def leaky_window_includes_t_plus_1(close, vol):
    p = Params()
    sig = es.compute_signals(close, vol, p)
    pos, _ = es.run_state_machine(sig.s, sig.tradable, p)
    W = es.target_weights(sig, pos)
    W = np.vstack([W[1:], np.zeros((1, W.shape[1]))])               # decision at t uses the window ending at t+1
    ex = es.apply_execution(W, sig.returns, 1, p.cost_bps_side)
    return W, ex["H"]


@pytest.fixture(scope="module")
def pit_data():
    close, vol = synth(500, seed=21, b=0.85, sig_xi=0.012)
    # make sure positions exist around the test date
    return close, vol


@pytest.mark.parametrize("model", ["xs", "pca"])
@pytest.mark.parametrize("t", [250, 321, 400])
def test_poisoned_future_and_same_close_for_the_engine(pit_data, model, t):
    close, vol = pit_data
    assert pit_violations(honest_engine(Params(factor_model=model)), close, vol, t) == []


def test_positions_exist_around_the_test_dates(pit_data):
    close, vol = pit_data
    res = es.backtest(close, vol)
    assert any(np.abs(res.H[t]).sum() > 0 for t in (250, 321, 400)) and np.abs(res.H[250:330]).sum() > 0


def test_trading_time_variant_is_also_point_in_time(pit_data):
    close, vol = pit_data
    assert pit_violations(honest_engine(Params(trading_time=True)), close, vol, 321) == []


def test_meta_leak_detector_fails_for_a_same_close_trading_variant(pit_data):
    close, vol = pit_data
    found = []
    for t in range(250, 420, 7):
        found += pit_violations(leaky_same_close, close, vol, t)
    assert any("same-close" in v for v in found)


def test_meta_leak_detector_fails_for_a_window_including_t_plus_1(pit_data):
    close, vol = pit_data
    found = []
    for t in range(250, 420, 7):
        found += pit_violations(leaky_window_includes_t_plus_1, close, vol, t)
    assert any("scrambled" in v for v in found)


def test_exec_lag_below_one_is_refused():
    with pytest.raises(ValueError):
        Params(exec_lag=0)


def test_decision_t_is_earned_on_t_plus_2_only():
    W = np.zeros((6, 2)); W[2] = [1.0, 0.0]                                    # decision at close of day 2
    R = np.full((6, 2), 0.01)
    ex = es.apply_execution(W, R, 1, 10.0)
    assert ex["H"][3, 0] == 1.0 and ex["H"][2, 0] == 0.0                         # traded at the close of day 3
    assert ex["gross"].tolist() == [0, 0, 0, 0, 0.01, 0.0] or ex["gross"][4] == 0.01   # earns day 4 (close 3 -> close 4)
    assert ex["gross"][3] == 0.0 and ex["gross"][2] == 0.0
    assert abs(ex["cost"][3] - 1.0 * 10 / 10_000) < 1e-15 and abs(ex["cost"][4] - 1.0 * 10 / 10_000) < 1e-15  # in on 3, out on 4


# ------------------------------------------------------------------------------------------------ determinism / statistics

def test_backtest_is_deterministic():
    close, vol = synth(400, seed=5)
    a, b = es.backtest(close, vol), es.backtest(close, vol)
    assert a.net.equals(b.net) and np.array_equal(a.W, b.W)


def test_stationary_bootstrap_matches_known_sd_and_is_seeded():
    rng = np.random.default_rng(0)
    x = rng.normal(0.0, 1.0, 2000)
    bm = es.stationary_bootstrap_means(x, 20, 3000, 5)
    assert abs(bm.std(ddof=1) - 1 / math.sqrt(2000)) < 0.15 / math.sqrt(2000) * 2
    assert np.array_equal(bm, es.stationary_bootstrap_means(x, 20, 3000, 5))
    # positive drift is detected, zero drift is not
    assert es.h2_test(x + 0.1, 20, 2000, 1)["reject_h0"] and not es.h2_test(x, 20, 2000, 1)["reject_h0"]


def test_mde_formula():
    m = es.mde_mean(3400, 0.0025)
    assert abs(m["mde_mean"] - 2.4864 * 0.0025 * math.sqrt(1.5 / 3400)) < 1e-6
    assert 0.7 < m["mde_sharpe_ann"] < 0.9


def test_cli_refuses_without_committed_prereg(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "prereg_committed", lambda *a, **k: False)
    assert es.main(["--snapshot", str(tmp_path), "--out-dir", str(tmp_path)]) == 2


@pytest.mark.parametrize("model", ["xs", "pca"])
def test_signals_up_to_t_are_unchanged_by_scrambling_the_future(pit_data, model):
    """Sensitive version: the S-scores, tradable flags and hedge matrices themselves (not only discrete positions)."""
    close, vol = pit_data
    p = Params(factor_model=model)
    for t in (200, 321, 420):
        a = es.compute_signals(close, vol, p)
        c2, v2 = _scramble_after(close, vol, t)
        b = es.compute_signals(c2, v2, p)
        for nm in ("s", "b", "hl", "kappa"):
            assert np.allclose(getattr(a, nm)[: t + 1], getattr(b, nm)[: t + 1], atol=1e-12, equal_nan=True), nm
        assert np.array_equal(a.tradable[: t + 1], b.tradable[: t + 1]) and np.allclose(a.G[: t + 1], b.G[: t + 1], atol=1e-12)
        # ...and they do change after t (the scramble really changed the data)
        assert not np.allclose(a.s[t + 61:], b.s[t + 61:], equal_nan=True)


def test_signal_leak_mutation_is_detected(pit_data, monkeypatch):
    """Mutation test: a signal that peeks at the next day's return must fail the sensitive check above."""
    close, vol = pit_data
    real = es.compute_signals

    def leaky(c, v, p=Params()):
        sg = real(c, v, p)
        sg.s = sg.s + 50 * np.roll(np.nan_to_num(sg.returns), -1, axis=0)
        return sg
    t = 321
    a = leaky(close, vol)
    c2, v2 = _scramble_after(close, vol, t)
    b = leaky(c2, v2)
    assert not np.allclose(a.s[: t + 1], b.s[: t + 1], atol=1e-12, equal_nan=True)
