# -*- coding: utf-8 -*-
"""
backtest/etf_statarb.py — Avellaneda–Lee statistical arbitrage on the 11 Select Sector SPDR ETFs (Session 5, hypothesis H2).

Fully deterministic, no LLM, no randomness except a seeded bootstrap. Hard rules honoured here:
  * Point-in-time (rule 4): the signal at the close of day t uses closes/volumes up to and including t only (a trailing window of M returns).
    Decisions are executed at the close of t+lag (lag >= 1, default 1); the position earns the return of day t+lag+1.
  * Costs: harness cost model, 5 bps commission + 5 bps slippage per side, charged on turnover (sum of |change in ETF weight|).
  * Every number written to a report is tagged by backtest/etf_statarb_report.py (rule 5).

Pipeline per decision day t (all vectorised over days and ETFs):
  1. window of the last M simple returns of each *eligible* ETF (full M+1 bars, positive volume on every bar);
  2. time-series demean and volatility scaling:  Y = (R - mean) / std;
  3. factor removal:  eps = Y @ P  with the projection P = I - V V'
        xs  : V = flat vector 1/sqrt(n)  (cross-sectional demeaning of the standardised returns; the residuals sum to zero every day)
        pca : V = top-K eigenvectors of the window correlation matrix (Avellaneda–Lee eigenportfolios);
  4. cumulative residual X_s = sum_{j<=s} eps_j;  AR(1) fit  X_{s+1} = a + b X_s + zeta  by OLS over the window;
        kappa = -ln(b) * 252,  m = a/(1-b),  sigma_eq = sqrt(var(zeta)/(1-b^2)),  half-life = -ln2/ln(b) days;
  5. S-score  s = (X_M - m) / sigma_eq;
  6. state machine per ETF (see `run_state_machine`);
  7. weights: an active ETF holds the residual portfolio h_i (h_i . r = eps_i + const, i.e. long the ETF, short the factor);
        v_i = sign_i / std(eps_i)  (inverse residual volatility);  w = sum_i v_i h_i, normalised to gross exposure exactly 1.0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTOR_ETFS: List[str] = ["XLK", "XLF", "XLV", "XLE", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"]
TRADING_DAYS = 252


@dataclass(frozen=True)
class Params:
    window: int = 60            # M: lookback in daily returns (pre-registered)
    open_th: float = 1.25       # open when |s| > open_th
    close_th: float = 0.50      # close a long when s > -close_th, a short when s < +close_th
    stop_th: float = 3.5        # stop when the adverse |s| >= stop_th
    max_halflife: float = 30.0  # tradable only if 0 < b < 1 and half-life <= this (days)
    factor_model: str = "xs"    # "xs" (primary, pre-registered) | "pca" (exploratory)
    n_factors: int = 3          # pca only
    exec_lag: int = 1           # decision at close t, trade at close t+exec_lag
    cost_bps_side: float = 10.0  # 5 bps commission + 5 bps slippage per side (core.ai_hedge_fund.cost_model defaults)
    trading_time: bool = False  # exploratory: volume "trading time" returns  R * mean_vol_10d / vol
    vol_avg_days: int = 10

    def __post_init__(self) -> None:
        if self.exec_lag < 1:
            raise ValueError("exec_lag must be >= 1: trades never execute at the close that produced the signal (rule 2)")
        if self.factor_model not in ("xs", "pca"):
            raise ValueError("factor_model must be 'xs' or 'pca'")
        if self.window < 10:
            raise ValueError("window too short")


# ----------------------------------------------------------------------------------------------------------------------
# data


def load_prices(snapshot_root: str, tickers: Optional[List[str]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(close, volume) frames over the union of dates; `Close` is the snapshot's total-return-adjusted close."""
    tickers = tickers or SECTOR_ETFS
    cl, vo = {}, {}
    for t in tickers:
        p = os.path.join(snapshot_root, "prices", f"{t.replace('^', '_').replace('.', '_')}.csv")
        p = p if os.path.exists(p) else p + ".gz"
        df = pd.read_csv(p, index_col="date", parse_dates=True).sort_index()
        cl[t], vo[t] = df["Close"], df["Volume"]
    return pd.DataFrame(cl)[tickers], pd.DataFrame(vo)[tickers]


# ----------------------------------------------------------------------------------------------------------------------
# signals


def eligibility(close: pd.DataFrame, volume: pd.DataFrame, window: int) -> pd.DataFrame:
    """An ETF is in the universe on day t iff its last window+1 bars all exist with positive close and volume.
    This is how XLRE (2015-10) and XLC (2018-06) enter only once they have a full, clean lookback window."""
    ok = (close > 0) & (volume > 0)
    return ok.astype(float).rolling(window + 1, min_periods=window + 1).min().eq(1.0)


def _projection(Y: np.ndarray, p: Params) -> np.ndarray:
    """(B, M, n) standardised windows -> (B, n, n) projection removing the common factor(s)."""
    B, M, n = Y.shape
    eye = np.eye(n)[None]
    if p.factor_model == "xs":
        v = np.full((n, 1), 1.0 / math.sqrt(n))
        return eye - (v @ v.T)[None]
    C = np.einsum("bmi,bmj->bij", Y, Y) / (M - 1)
    _, vec = np.linalg.eigh(C)                       # ascending eigenvalues
    V = vec[:, :, -p.n_factors:]
    return eye - V @ np.swapaxes(V, 1, 2)


def _batch_signals(W: np.ndarray, p: Params) -> Dict[str, np.ndarray]:
    """W: (B, M, n) windows of raw (or trading-time) returns. Returns s, b, halflife, resid_std (B,n); G (B,n,n)."""
    B, M, n = W.shape
    sd_raw = W.std(axis=1, ddof=1)                                          # (B, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        Y = (W - W.mean(axis=1, keepdims=True)) / sd_raw[:, None, :]
        P = _projection(Y, p)
        E = Y @ P                                                           # residuals, (B, M, n)
        X = np.cumsum(E, axis=1)
        x0, x1 = X[:, :-1, :], X[:, 1:, :]
        mx, my = x0.mean(axis=1), x1.mean(axis=1)
        dx = x0 - mx[:, None, :]
        sxx = (dx ** 2).sum(axis=1)
        b = (dx * (x1 - my[:, None, :])).sum(axis=1) / sxx
        a = my - b * mx
        z = x1 - a[:, None, :] - b[:, None, :] * x0
        var_z = (z ** 2).sum(axis=1) / (M - 1 - 2)
        sig_eq = np.sqrt(var_z / (1.0 - b ** 2))
        m = a / (1.0 - b)
        s = (X[:, -1, :] - m) / sig_eq
        hl = -math.log(2.0) / np.log(b)
        std_e = E.std(axis=1, ddof=1)
        # weights matrix G[:, j, i] = P[j, i] / sd_raw[j] / std_e[i]: w = G @ sign gives sum_i sign_i/std_e_i * h_i, h_i[j] = P[j,i]/sd_raw[j]
        G = P / sd_raw[:, :, None] / std_e[:, None, :]
    tradable = (b > 0.0) & (b < 1.0) & (hl <= p.max_halflife) & np.isfinite(s) & (sxx > 1e-12) & (std_e > 1e-12) & np.isfinite(G).all(axis=1)
    return {"s": s, "b": b, "hl": hl, "std_e": std_e, "G": G, "tradable": tradable, "E": E, "kappa": -np.log(b) * TRADING_DAYS, "m": m, "sig_eq": sig_eq}


@dataclass
class Signals:
    dates: pd.DatetimeIndex
    tickers: List[str]
    s: np.ndarray          # (T, N)
    b: np.ndarray
    hl: np.ndarray
    kappa: np.ndarray
    tradable: np.ndarray   # bool (T, N); includes eligibility
    elig: np.ndarray       # bool (T, N)
    G: np.ndarray          # (T, N, N)
    returns: np.ndarray


def sig_returns(close: pd.DataFrame, volume: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Simple returns used by the signal (trading-time scaled if requested). Return of day t uses close t and close t-1 only."""
    R = close.pct_change(fill_method=None)
    if p.trading_time:
        vbar = volume.rolling(p.vol_avg_days, min_periods=p.vol_avg_days).mean()
        R = R * (vbar / volume)
    return R


def compute_signals(close: pd.DataFrame, volume: pd.DataFrame, p: Params = Params()) -> Signals:
    dates, tick = close.index, list(close.columns)
    T, N, M = len(dates), len(tick), p.window
    Rdf = sig_returns(close, volume, p)
    fin = np.isfinite(Rdf).astype(float).rolling(M, min_periods=M).min().eq(1.0)     # the M signal returns of the window are all defined
    elig = (eligibility(close, volume, M) & fin).to_numpy()
    R = Rdf.to_numpy(dtype=float)
    Rraw = close.pct_change(fill_method=None).to_numpy(dtype=float)
    s = np.full((T, N), np.nan); b = s.copy(); hl = s.copy(); kappa = s.copy()
    G = np.zeros((T, N, N))
    tradable = np.zeros((T, N), dtype=bool)
    # windows of the last M returns ending at t: R[t-M+1 .. t]  (needs t >= M; eligibility guarantees M+1 valid bars)
    from numpy.lib.stride_tricks import sliding_window_view
    if T > M:
        win = sliding_window_view(R, M, axis=0)           # (T-M+1, N, M), window k covers rows k..k+M-1
        win = np.swapaxes(win, 1, 2)                      # (T-M+1, M, N); k -> decision row t = k+M-1
        t_of = np.arange(M - 1, T)
        groups: Dict[bytes, List[int]] = {}
        for k, t in enumerate(t_of):
            e = elig[t]
            if e.sum() >= max(3, p.n_factors + 2 if p.factor_model == "pca" else 3):
                groups.setdefault(e.tobytes(), []).append(k)
        for key, ks in sorted(groups.items()):
            cols = np.flatnonzero(np.frombuffer(key, dtype=bool))
            ks = np.asarray(ks)
            Wk = win[ks][:, :, cols]
            if not np.isfinite(Wk).all():
                raise AssertionError("eligible windows must be finite")
            out = _batch_signals(Wk, p)
            rows = t_of[ks]
            for nm, arr in (("s", s), ("b", b), ("hl", hl), ("kappa", kappa)):
                arr[np.ix_(rows, cols)] = out[nm]
            tradable[np.ix_(rows, cols)] = out["tradable"]
            G[np.ix_(rows, cols, cols)] = np.nan_to_num(out["G"], nan=0.0, posinf=0.0, neginf=0.0)
    tradable &= elig
    return Signals(dates, tick, s, b, hl, kappa, tradable, elig, G, Rraw)


# ----------------------------------------------------------------------------------------------------------------------
# state machine and weights


def run_state_machine(s: np.ndarray, tradable: np.ndarray, p: Params = Params()) -> Tuple[np.ndarray, int]:
    """pos[t, i] in {-1, 0, +1} after the decision at the close of day t; also the number of entries.

    open : flat, tradable, not blocked, open_th < |s| < stop_th  ->  long if s < 0, short if s > 0
    close: long when s > -close_th, short when s < +close_th (includes |s| < close_th and overshoot through zero)
    stop : long when s <= -stop_th, short when s >= +stop_th  -> flat and blocked until |s| < open_th again
    forced close when the ETF is no longer tradable (b outside (0,1), half-life too long, or left the universe)."""
    T, N = s.shape
    pos = np.zeros((T, N), dtype=np.int8)
    state = np.zeros(N, dtype=np.int8)
    blocked = np.zeros(N, dtype=bool)
    entries = 0
    for t in range(T):
        st, tr = s[t], tradable[t]
        a = np.abs(st)
        with np.errstate(invalid="ignore"):
            blocked &= ~(a < p.open_th)
            held = state != 0
            stop = held & (((state > 0) & (st <= -p.stop_th)) | ((state < 0) & (st >= p.stop_th)))
            close = held & (((state > 0) & (st > -p.close_th)) | ((state < 0) & (st < p.close_th)))
            forced = held & ~tr
            state[stop | close | forced] = 0
            blocked |= stop
            can = (state == 0) & tr & ~blocked & (a > p.open_th) & (a < p.stop_th)
        state[can] = -np.sign(st[can]).astype(np.int8)
        entries += int(can.sum())
        pos[t] = state
    return pos, entries


def target_weights(sig: Signals, pos: np.ndarray) -> np.ndarray:
    """(T, N) decision-time target weights, gross exposure exactly 1 where any position is held, else 0."""
    w = np.einsum("tji,ti->tj", sig.G, pos.astype(float))
    gross = np.abs(w).sum(axis=1)
    out = np.zeros_like(w)
    nz = gross > 1e-12
    out[nz] = w[nz] / gross[nz, None]
    return out


def apply_execution(W: np.ndarray, R: np.ndarray, lag: int, cost_bps_side: float) -> Dict[str, np.ndarray]:
    """Held position after the close of day u is W[u-lag] (decision at the close of u-lag, trade at the close of u); it earns day u+1.
    Cost is charged on the trade date u: cost_bps_side * sum|H[u] - H[u-1]|.  lag=0 is the forbidden same-close variant (tests only)."""
    T, N = W.shape
    H = np.zeros_like(W)
    if lag < T:
        H[lag:] = W[: T - lag] if lag > 0 else W
    Rz = np.nan_to_num(R, nan=0.0)
    gross = np.zeros(T)
    gross[1:] = (H[:-1] * Rz[1:]).sum(axis=1)               # earned on u from the position held after close u-1
    turnover = np.zeros(T)
    turnover[0] = np.abs(H[0]).sum()
    turnover[1:] = np.abs(H[1:] - H[:-1]).sum(axis=1)
    cost = turnover * cost_bps_side / 10_000.0
    return {"H": H, "gross": gross, "turnover": turnover, "cost": cost, "net": gross - cost}


@dataclass
class Result:
    params: Params
    dates: pd.DatetimeIndex
    tickers: List[str]
    signals: Signals
    pos: np.ndarray
    W: np.ndarray
    H: np.ndarray
    gross: pd.Series
    cost: pd.Series
    net: pd.Series
    turnover: pd.Series
    entries: int
    start: pd.Timestamp        # first decision date (sample start)


def backtest(close: pd.DataFrame, volume: pd.DataFrame, p: Params = Params()) -> Result:
    sig = compute_signals(close, volume, p)
    pos, entries = run_state_machine(sig.s, sig.tradable, p)
    W = target_weights(sig, pos)
    ex = apply_execution(W, sig.returns, p.exec_lag, p.cost_bps_side)
    first = np.flatnonzero(sig.elig.sum(axis=1) >= 3)
    start = close.index[first[0]] if len(first) else close.index[0]
    mk = lambda a: pd.Series(a, index=close.index)  # noqa: E731
    return Result(p, close.index, list(close.columns), sig, pos, W, ex["H"], mk(ex["gross"]), mk(ex["cost"]), mk(ex["net"]), mk(ex["turnover"]), entries, start)


# ----------------------------------------------------------------------------------------------------------------------
# statistics


def stationary_bootstrap_means(x: np.ndarray, mean_block: float, n_boot: int, seed: int, chunk: int = 500) -> np.ndarray:
    """Politis–Romano stationary bootstrap of the sample mean: geometric block lengths (mean `mean_block`), circular wrap."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot)
    q = 1.0 / mean_block
    j = np.arange(n)[None, :]
    for lo in range(0, n_boot, chunk):
        B = min(chunk, n_boot - lo)
        start = rng.integers(0, n, size=(B, n))
        new = rng.random((B, n)) < q
        new[:, 0] = True
        pos_start = np.maximum.accumulate(np.where(new, j, 0), axis=1)           # column where the current block began
        base = np.take_along_axis(start, pos_start, axis=1)
        idx = (base + (j - pos_start)) % n
        out[lo:lo + B] = x[idx].mean(axis=1)
    return out


def h2_test(net: np.ndarray, mean_block: float = 20.0, n_boot: int = 10_000, seed: int = 20261105) -> Dict[str, Any]:
    """H2: mean daily net return > 0. Reject iff the one-sided 5th percentile of the bootstrap mean > 0."""
    net = np.asarray(net, dtype=float)
    bm = stationary_bootstrap_means(net, mean_block, n_boot, seed)
    mean, sd = float(net.mean()), float(net.std(ddof=1))
    return {
        "n_days": int(len(net)), "mean": mean, "std": sd,
        "p05": float(np.percentile(bm, 5)), "lo": float(np.percentile(bm, 2.5)), "hi": float(np.percentile(bm, 97.5)),
        "p_one_sided": float((bm <= 0).mean()), "boot_se": float(bm.std(ddof=1)),
        "reject_h0": bool(np.percentile(bm, 5) > 0),
        "sharpe_ann": float(mean / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else float("nan"),
        "mean_block": float(mean_block), "n_boot": int(n_boot), "seed": int(seed),
    }


def mde_mean(n_days: int, sigma_daily: float, inflation: float = 1.5) -> Dict[str, float]:
    """Minimum detectable mean daily return (one-sided 5%, 80% power) for an iid-like series with variance inflated by `inflation`
    (autocorrelation / vol clustering assumption). Pure arithmetic on assumptions; touches no data."""
    z = 1.6448536269514722 + 0.8416212335729143
    se = sigma_daily * math.sqrt(inflation / n_days)
    return {"se_mean": se, "mde_mean": z * se, "mde_sharpe_ann": z * math.sqrt(inflation * TRADING_DAYS / n_days)}


def summarise(res: Result, mean_block: float = 20.0, n_boot: int = 10_000, seed: int = 20261105) -> Dict[str, Any]:
    sel = res.net.index >= res.start
    net, gr, co, to = res.net[sel], res.gross[sel], res.cost[sel], res.turnover[sel]
    out = h2_test(net.to_numpy(), mean_block, n_boot, seed)
    gsd = float(gr.std(ddof=1))
    out.update({
        "sample_start": str(net.index[0].date()), "sample_end": str(net.index[-1].date()),
        "gross_mean": float(gr.mean()), "gross_sharpe_ann": float(gr.mean() / gsd * math.sqrt(TRADING_DAYS)) if gsd > 0 else float("nan"),
        "cost_mean": float(co.mean()), "cost_drag_ann": float(co.mean() * TRADING_DAYS),
        "turnover_mean_daily": float(to.mean()), "turnover_ann": float(to.mean() * TRADING_DAYS),
        "entries": int(res.entries), "days_in_market_frac": float((np.abs(res.H[sel.nonzero()[0]]).sum(axis=1) > 0).mean()),
        "net_ann_return": float(net.mean() * TRADING_DAYS), "max_drawdown": float(_max_dd(net.to_numpy())),
        "economic_threshold_daily": 1e-4, "meets_economic_threshold": bool(net.mean() >= 1e-4),
    })
    return out


def _max_dd(r: np.ndarray) -> float:
    eq = np.cumsum(r)                       # additive equity (gross exposure 1 capital base)
    return float((eq - np.maximum.accumulate(eq)).min())


# ----------------------------------------------------------------------------------------------------------------------
# CLI


def prereg_committed(path: str = os.path.join(ROOT, "HYPOTHESIS_H2.md")) -> bool:
    """The real-data run is refused unless HYPOTHESIS_H2.md is tracked and has no uncommitted changes (rule 6 / Phase C)."""
    try:
        subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=ROOT, check=True, capture_output=True)
        return subprocess.run(["git", "diff", "--quiet", "HEAD", "--", path], cwd=ROOT).returncode == 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _round(o: Any) -> Any:
    if isinstance(o, float):
        return float(f"{o:.10g}") if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _round(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v) for v in o]
    return o


def _write(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(_round(obj), fh, indent=2, sort_keys=True)
        fh.write("\n")


def write_daily_csv(path: str, res: Result) -> None:
    sel = res.net.index >= res.start
    df = pd.DataFrame({"gross": res.gross, "cost": res.cost, "net": res.net, "turnover": res.turnover})[sel]
    df.to_csv(path, float_format="%.10e", index_label="date", lineterminator="\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Avellaneda–Lee sector-ETF stat-arb (H2). Defaults are the pre-registered values.")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--factor", default="xs", choices=["xs", "pca"])
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--block", type=float, default=20.0)
    ap.add_argument("--reps", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=20261105)
    ap.add_argument("--tag", default="h2")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "results"))
    a = ap.parse_args(argv)
    if not prereg_committed():
        print("refusing to run on real data: HYPOTHESIS_H2.md must be committed first (Session 5, rule 6)", file=sys.stderr)
        return 2
    snap = a.snapshot if os.path.isabs(a.snapshot) else os.path.join(ROOT, a.snapshot)
    sid = os.path.basename(snap.rstrip("/"))
    close, volume = load_prices(snap)
    p = Params(window=a.window, factor_model=a.factor)
    res = backtest(close, volume, p)
    summ = summarise(res, a.block, a.reps, a.seed)
    summ["params"] = asdict(p)
    summ["snapshot"] = sid
    os.makedirs(a.out_dir, exist_ok=True)
    stem = os.path.join(a.out_dir, f"etf_statarb_{sid}_{a.tag}")
    write_daily_csv(stem + ".csv", res)
    _write(stem + "_summary.json", summ)
    h = hashlib.sha256()
    for f in (stem + ".csv", stem + "_summary.json"):
        with open(f, "rb") as fh:
            h.update(fh.read())
    print(f"digest sha256 {h.hexdigest()}")
    print(json.dumps(_round({k: summ[k] for k in ("mean", "p05", "lo", "hi", "p_one_sided", "sharpe_ann", "n_days", "entries", "reject_h0")}), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
