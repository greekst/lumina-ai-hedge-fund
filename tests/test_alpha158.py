"""Alpha158 factor values vs hand-computed references, and point-in-time invariance."""
import numpy as np
import pandas as pd
import pytest

from core.ai_hedge_fund.alpha158_engine import Alpha158Engine, EPS


def test_exactly_158_factors(ohlcv):
    f = Alpha158Engine.calculate_alpha158(ohlcv)
    assert f.shape == (len(ohlcv), 158)


def test_hand_computed_reference_last_row(ohlcv):
    f = Alpha158Engine.calculate_alpha158(ohlcv).iloc[-1]
    o, h, l, c, v = (ohlcv[k].to_numpy() for k in ["Open", "High", "Low", "Close", "Volume"])
    # KBAR
    assert f["KMID"] == pytest.approx((c[-1] - o[-1]) / o[-1], rel=1e-12)
    assert f["KLEN"] == pytest.approx((h[-1] - l[-1]) / o[-1], rel=1e-12)
    assert f["KSFT"] == pytest.approx((2 * c[-1] - h[-1] - l[-1]) / o[-1], rel=1e-12)
    assert f["OPEN0"] == pytest.approx((o[-1] - c[-2]) / (c[-2] + EPS), rel=1e-12)
    # Momentum / moments (window 5)
    w = c[-5:]
    assert f["ROC5"] == pytest.approx(c[-1] / c[-6] - 1.0, rel=1e-12)
    assert f["MA5"] == pytest.approx(w.mean() / c[-1] - 1.0, rel=1e-12)
    assert f["STD5"] == pytest.approx(np.std(w, ddof=1) / c[-1], rel=1e-10)
    assert f["MAX5"] == pytest.approx(h[-5:].max() / c[-1] - 1.0, rel=1e-12)
    assert f["RSV5"] == pytest.approx((c[-1] - l[-5:].min()) / (h[-5:].max() - l[-5:].min() + EPS), rel=1e-10)
    assert f["VWAP5"] == pytest.approx((c[-5:] * v[-5:]).sum() / (v[-5:].sum() + EPS) / c[-1] - 1.0, rel=1e-10)
    # Regression: slope / r^2 via numpy.polyfit
    t = np.arange(5)
    slope, icpt = np.polyfit(t, w, 1)
    pred = slope * t + icpt
    r2 = 1 - ((w - pred) ** 2).sum() / ((w - w.mean()) ** 2).sum()
    assert f["BETA5"] == pytest.approx(slope / c[-1], rel=1e-8)
    assert f["RSQR5"] == pytest.approx(r2, rel=1e-6)
    assert f["RESI5"] == pytest.approx((w[-1] - pred[-1]) / c[-1], rel=1e-6, abs=1e-12)
    # Timing: argmax position of high within window, normalised to [0,1]
    assert f["IMAX5"] == pytest.approx(np.argmax(h[-5:]) / 4.0)
    # Correlation of close with log volume
    assert f["CORR5"] == pytest.approx(np.corrcoef(w, np.log(v[-5:] + 1.0))[0, 1], rel=1e-8)


def test_point_in_time_invariance(ohlcv):
    """Factors at date t must not change when future rows are appended (no look-ahead).
    This fails on the upstream code because of `.bfill()` in the warm-up period."""
    full = Alpha158Engine.calculate_alpha158(ohlcv)
    for t in (3, 10, 40, 61, 90):
        trunc = Alpha158Engine.calculate_alpha158(ohlcv.iloc[: t + 1])
        pd.testing.assert_series_equal(trunc.iloc[-1], full.iloc[t], check_names=False, rtol=1e-9, atol=1e-12)


def test_compute_symbol_summary_offline(ohlcv):
    s = Alpha158Engine.compute_symbol_summary("TEST", df=ohlcv)
    assert s["status"] == "SUCCESS" and s["factor_count"] == 158
    assert s["as_of"] == str(ohlcv.index[-1])[:10]
