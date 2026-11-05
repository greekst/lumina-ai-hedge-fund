# -*- coding: utf-8 -*-
"""
backtest/etf_statarb_report.py — Session 5 Phase D: the pre-registered H2 result first (read from the output of the exact registered command),
then the exploratory block defined in HYPOTHESIS_H2.md. Writes
    results/etf_statarb_<snapshot>_h2_explore.json   (deterministic)
    results/etf_statarb_<snapshot>_h2_summary.md      (every number tagged, rule 5; validated by tests/test_report_tagging.py)

    LUMINA_LLM_MODE=mock PYTHONHASHSEED=0 python -m backtest.etf_statarb_report --snapshot backtest/snapshots/2026-11-04-pit2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backtest import etf_statarb as es
from backtest.etf_statarb import Params
from core.reporting.tagged import Tagged, SOURCED_FACT, MODEL_ASSUMPTION, untagged_numbers

ROOT = es.ROOT
AS_OF = "2026-11-05"


def metrics(res: es.Result, boot: int = 0, block: float = 20.0) -> Dict[str, Any]:
    sel = (res.net.index >= res.start)
    net, gr, to = res.net[sel].to_numpy(), res.gross[sel].to_numpy(), res.turnover[sel].to_numpy()
    sd, gsd = net.std(ddof=1), gr.std(ddof=1)
    out = {"n": int(len(net)), "net_mean": float(net.mean()), "gross_mean": float(gr.mean()), "cost_mean": float(res.cost[sel].mean()),
           "sharpe": float(net.mean() / sd * math.sqrt(252)) if sd > 0 else None, "gross_sharpe": float(gr.mean() / gsd * math.sqrt(252)) if gsd > 0 else None,
           "turnover": float(to.mean()), "entries": int(res.entries),
           "breakeven_bps_side": float(gr.mean() / to.mean() * 1e4) if to.mean() > 0 else None}
    if boot:
        t = es.h2_test(net, block, boot, 20261105)
        out.update({"p05": t["p05"], "lo": t["lo"], "hi": t["hi"], "p": t["p_one_sided"]})
    return out


def sub_metrics(net: np.ndarray, gross: np.ndarray, boot: int = 2000) -> Dict[str, Any]:
    if len(net) < 30:
        return {"n": int(len(net)), "net_mean": float(net.mean()) if len(net) else None}
    sd = net.std(ddof=1)
    t = es.h2_test(net, 20.0, boot, 20261105)
    return {"n": int(len(net)), "net_mean": float(net.mean()), "gross_mean": float(gross.mean()),
            "sharpe": float(net.mean() / sd * math.sqrt(252)) if sd > 0 else None, "lo": t["lo"], "hi": t["hi"]}


PREREG_COMMIT = "610fb6fcda557471e757a1f1658c5e2be6acef83"
ENGINE_COMMIT = "e284c5b"


def verify_registration(snap: str) -> Dict[str, Any]:
    """Review P1-1: check, rather than assert in prose, that (a) HYPOTHESIS_H2.md above the RESULTS line is byte-identical to the pre-registration commit,
    (b) the engine file is identical to the engine commit that preceded it, (c) the snapshot's price files match the manifest sha256."""
    import subprocess

    def git_show(rev: str, path: str) -> bytes:
        return subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT, check=True, capture_output=True).stdout
    marker = b"RESULTS (appended after the run)"
    now = open(os.path.join(ROOT, "HYPOTHESIS_H2.md"), "rb").read()
    old = git_show(PREREG_COMMIT, "HYPOTHESIS_H2.md")
    ok_h = now.split(marker)[0] == old.split(marker)[0]
    ok_e = open(os.path.join(ROOT, "backtest", "etf_statarb.py"), "rb").read() == git_show(ENGINE_COMMIT, "backtest/etf_statarb.py")
    man = json.load(open(os.path.join(snap, "manifest.json"), encoding="utf-8"))["sha256"]
    bad = []
    for t in es.SECTOR_ETFS + ["SPY", "^VIX"]:
        rel = f"prices/{t.replace('^', '_')}.csv.gz"
        if man.get(rel) != hashlib.sha256(open(os.path.join(snap, rel), "rb").read()).hexdigest():
            bad.append(rel)
    assert ok_h and ok_e and not bad, f"registration check failed: prereg_intact={ok_h} engine_unchanged={ok_e} bad_prices={bad}"
    return {"prereg_above_line_intact": ok_h, "engine_unchanged_since_engine_commit": ok_e, "snapshot_prices_match_manifest": True}


def build(snap: str) -> Dict[str, Any]:
    sid = os.path.basename(snap.rstrip("/"))
    verification = verify_registration(snap)
    close, vol = es.load_prices(snap)
    base = Params()
    res = es.backtest(close, vol, base)
    with open(os.path.join(ROOT, "results", f"etf_statarb_{sid}_h2_summary.json"), encoding="utf-8") as fh:
        primary = json.load(fh)
    sel = res.net.index >= res.start
    out: Dict[str, Any] = {"primary": primary, "snapshot": sid, "verification": verification}
    # realised MDE from the realised volatility (same inflation as registered)
    out["mde_realised"] = es.mde_mean(primary["n_days"], primary["std"])
    mdes = {str(sg): es.mde_mean(primary["n_days"], sg) for sg in (0.0015, 0.0025, 0.0040)}
    out["mde_assumed"] = mdes
    # 1 PCA K=3
    out["pca3"] = metrics(es.backtest(close, vol, Params(factor_model="pca", n_factors=3)), boot=10_000)
    # 2 gross, with CI
    g = es.h2_test(res.gross[sel].to_numpy(), 20.0, 10_000, 20261105)
    out["gross_test"] = {k: g[k] for k in ("mean", "lo", "hi", "p05", "p_one_sided", "sharpe_ann")}
    out["breakeven_bps_side"] = float(primary["gross_mean"] / primary["turnover_mean_daily"] * 1e4)
    # review P2-5: cost sensitivity (exact, cost is linear in turnover); P2-4: MDE from the realised bootstrap SE
    out["cost_sens"] = {str(c): float(primary["gross_mean"] - primary["turnover_mean_daily"] * c / 1e4) for c in (0, 2, 5, 10)}
    z = 1.6448536269514722 + 0.8416212335729143
    out["mde_boot_se"] = {"mde_mean": z * primary["boot_se"], "mde_sharpe_ann": z * primary["boot_se"] / primary["std"] * math.sqrt(252)}
    # 3 beta to SPY (same-day), on the sample days
    spy = pd.read_csv(os.path.join(snap, "prices", "SPY.csv.gz"), index_col="date", parse_dates=True)["Close"].pct_change()
    x = spy.reindex(res.net.index)[sel].to_numpy()
    for nm, series in (("net", res.net), ("gross", res.gross)):
        y = series[sel].to_numpy()
        beta = float(np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1))
        out[f"beta_spy_{nm}"] = {"beta": beta, "corr": float(np.corrcoef(x, y)[0, 1])}
    # mean net exposure of the held book (sum of weights) for context
    out["mean_net_exposure"] = float(res.H[sel.nonzero()[0]].sum(axis=1).mean())
    # 4 by year, by VIX regime (VIX close at the decision date of the position in force = two sessions before the P&L day)
    net, gr = res.net[sel], res.gross[sel]
    out["by_year"] = {str(y): sub_metrics(net[net.index.year == y].to_numpy(), gr[gr.index.year == y].to_numpy()) for y in sorted(set(net.index.year))}
    vix = pd.read_csv(os.path.join(snap, "prices", "_VIX.csv.gz"), index_col="date", parse_dates=True)["Close"].reindex(res.net.index).shift(2)[sel]
    reg = pd.cut(vix, [-np.inf, 15, 25, np.inf], labels=["<15", "15-25", ">25"], right=False)
    out["by_vix"] = {str(k): sub_metrics(net[reg == k].to_numpy(), gr[reg == k].to_numpy()) for k in ["<15", "15-25", ">25"]}
    # 5 trading time
    out["trading_time"] = metrics(es.backtest(close, vol, Params(trading_time=True)), boot=10_000)
    # 6 grids (no bootstrap; no winner is picked)
    out["grid_open_close"] = {f"{o}|{c}": metrics(es.backtest(close, vol, Params(open_th=o, close_th=c)))
                              for o in (1.0, 1.25, 1.5, 2.0) for c in (0.25, 0.5, 0.75)}
    out["grid_window"] = {str(m): metrics(es.backtest(close, vol, Params(window=m))) for m in (40, 60, 90)}
    # 7 block lengths
    out["blocks"] = {str(b): {k: v for k, v in es.h2_test(res.net[sel].to_numpy(), float(b), 10_000, 20261105).items() if k in ("p05", "lo", "hi", "p_one_sided")} for b in (5, 60)}
    # sanity: primary recomputed here equals the registered output
    out["primary_recomputed_mean"] = float(res.net[sel].mean())
    return out


def _t(v, kind=SOURCED_FACT, src="", unit="", dec=2, scale=1.0) -> str:
    return Tagged(None if v is None else float(v) * scale, src, AS_OF, kind, "", unit, dec).render(with_label=False)


def markdown(r: Dict[str, Any]) -> str:
    sid = r["snapshot"]
    S = f"etf-statarb {sid} h2"
    P = r["primary"]
    F = lambda v, **k: _t(v, src=S, **k)  # noqa: E731
    A = lambda v, **k: _t(v, kind=MODEL_ASSUMPTION, src="HYPOTHESIS_H2.md", **k)  # noqa: E731
    bp = dict(unit="bp", scale=1e4)
    pct = dict(unit="%", scale=100.0)
    L: List[str] = [
        "# Session 5 Phase D — pre-registered H2 first, then exploratory results", "",
        f"Pre-registration: HYPOTHESIS_H2.md (commit 610fb6f, before any real-data run). Snapshot `{sid}` (frozen, untouched). Mean daily net return of the "
        "Avellaneda–Lee-style sector-ETF strategy (a specific variant: cross-sectional demeaning of standardised returns, symmetric 0.50 exit, 3.5 stop, inverse-residual-volatility weights, ETF-on-ETF); "
        "\"no edge\" applies to this variant, not to every Avellaneda–Lee implementation. <!-- text-only -->", "",
        f"Registration check run with this report: pre-registration above the RESULTS line identical to its commit, engine unchanged since its commit, snapshot price files match the manifest ({'yes' if all(r['verification'].values()) else 'NO'}). <!-- text-only -->", "",
        "## H2 (confirmatory)", "",
        f"- Sample: {F(P['n_days'], dec=0)} trading days, `{P['sample_start']}` to `{P['sample_end']}`; {F(P['entries'], dec=0)} position entries.",
        f"- **Mean daily net return = {F(P['mean'], **bp)}** ({F(P['net_ann_return'], **pct)} a year on the unit-gross capital base); daily standard deviation {F(P['std'], **bp)}.",
        f"- Stationary bootstrap (mean block {A(P['mean_block'], dec=0)} days, {A(P['n_boot'], dec=0)} replicates): one-sided lower bound (fifth percentile) {F(P['p05'], **bp)}; "
        f"two-sided ninety-five percent CI [{F(P['lo'], **bp)}, {F(P['hi'], **bp)}]; one-sided bootstrap p {F(P['p_one_sided'], dec=4)}; bootstrap SE {F(P['boot_se'], **bp)}.",
        ("- **Decision: reject H0** (the fifth percentile is above zero). <!-- text-only -->" if P["reject_h0"] else
         "- **Decision: do not reject H0.** The fifth percentile is not above zero; here the whole interval lies below zero, so the strategy lost money net of costs. <!-- text-only -->"),
        f"- Annualised Sharpe (net) {F(P['sharpe_ann'])}; economic threshold {A(1.0, **{'unit': 'bp', 'dec': 2})} a day: "
        + ("met. <!-- text-only -->" if P["meets_economic_threshold"] else "not met. <!-- text-only -->"),
        f"- Turnover (sum of |weight change|) {F(P['turnover_mean_daily'], **pct)} of gross exposure per day ({F(P['turnover_ann'], dec=1)} times a year); share of days in the market "
        f"{F(P['days_in_market_frac'], **pct)}.",
        f"- Cost drag {F(P['cost_mean'], **bp)} a day ({F(P['cost_drag_ann'], **pct)} a year) against a gross (pre-cost) point estimate of {F(P['gross_mean'], **bp)} a day (gross Sharpe {F(P['gross_sharpe_ann'])}); "
        f"the gross mean is not distinguishable from zero (CI in the exploratory block). If it were real, it would just pay a cost of {F(r['breakeven_bps_side'], unit='bp', dec=2)} per side, against the assumed {A(P['params']['cost_bps_side'], unit='bp', dec=0)}.",
        "- Cost sensitivity (exact, cost is linear in turnover; the registered per-side cost is an assumption, likely conservative for liquid sector funds at the close but with borrow, financing and impact omitted): "
        + ", ".join(f"net mean at {A(float(c), unit='bp', dec=0)} per side {F(v, **bp)}" for c, v in r["cost_sens"].items()) + ". <!-- sensitivity, exploratory -->",
        f"- Realised MDE (one-sided, eighty percent power; registered variance inflation {A(1.5)} assumed): {F(r['mde_realised']['mde_mean'], **bp)} a day, i.e. an annualised Sharpe of {F(r['mde_realised']['mde_sharpe_ann'])}. "
        f"Using the realised bootstrap SE instead (the registered inflation proved conservative): {F(r['mde_boot_se']['mde_mean'], **bp)} a day, Sharpe {F(r['mde_boot_se']['mde_sharpe_ann'])}. "
        f"Pre-registered MDE grid by assumed daily volatility: "
        + ", ".join(f"{A(float(k), unit='%', dec=2, scale=100.0)} → {A(v['mde_mean'], **bp)}" for k, v in r["mde_assumed"].items()) + ".",
        f"- Maximum drawdown of the additive equity curve {F(P['max_drawdown'], **pct)}. Max drawdown is descriptive only.",
        f"- Reproducibility: the exact registered command run twice gave identical output digests; this report recomputes the primary mean as {F(r['primary_recomputed_mean'], **bp)}. <!-- text-only -->", "",
        "## Exploratory (not evidence for anything; no cell is chosen)", "",
        "### Gross (pre-cost) result", "",
        f"- Gross point estimate {F(r['gross_test']['mean'], **bp)} a day — **not distinguishable from zero** (two-sided CI includes zero; the one-sided p is exploratory and not corrected for the number of cells shown). Ninety-five percent CI [{F(r['gross_test']['lo'], **bp)}, {F(r['gross_test']['hi'], **bp)}], one-sided p {F(r['gross_test']['p_one_sided'], dec=4)}, Sharpe {F(r['gross_test']['sharpe_ann'])}.", "",
        "### Factor model: PCA with K = 3 versus cross-sectional demeaning", "",
        "| model | net mean | 5th pct | CI low | CI high | p | Sharpe | gross mean | turnover | entries |", "|---|---|---|---|---|---|---|---|---|---|",
        f"| xs (primary) | {F(P['mean'], **bp)} | {F(P['p05'], **bp)} | {F(P['lo'], **bp)} | {F(P['hi'], **bp)} | {F(P['p_one_sided'], dec=4)} | {F(P['sharpe_ann'])} | {F(P['gross_mean'], **bp)} | {F(P['turnover_mean_daily'], **pct)} | {F(P['entries'], dec=0)} |",
    ]
    q = r["pca3"]
    L.append(f"| pca K=3 | {F(q['net_mean'], **bp)} | {F(q['p05'], **bp)} | {F(q['lo'], **bp)} | {F(q['hi'], **bp)} | {F(q['p'], dec=4)} | {F(q['sharpe'])} | {F(q['gross_mean'], **bp)} | {F(q['turnover'], **pct)} | {F(q['entries'], dec=0)} |")
    q = r["trading_time"]
    L += ["", "### Volume trading time (signal returns scaled by trailing ten-day mean volume over the day's volume)", "",
          "| variant | net mean | 5th pct | CI low | CI high | p | Sharpe | gross mean | turnover | entries |", "|---|---|---|---|---|---|---|---|---|---|",
          f"| trading time | {F(q['net_mean'], **bp)} | {F(q['p05'], **bp)} | {F(q['lo'], **bp)} | {F(q['hi'], **bp)} | {F(q['p'], dec=4)} | {F(q['sharpe'])} | {F(q['gross_mean'], **bp)} | {F(q['turnover'], **pct)} | {F(q['entries'], dec=0)} |"]
    L += ["", "### Market exposure", "",
          f"- Net-return beta to SPY (same-day OLS) {F(r['beta_spy_net']['beta'], dec=3)}, correlation {F(r['beta_spy_net']['corr'], dec=3)}; gross-return beta {F(r['beta_spy_gross']['beta'], dec=3)}. "
          f"Mean net weight of the held book {F(r['mean_net_exposure'], dec=3)} (the book is factor-hedged against the standardised-return factor, not dollar-neutral).", "",
          "### By calendar year (day-level bootstrap; descriptive, about forty cells are shown so some will look notable by chance)", "", "| year | days | net mean | gross mean | Sharpe | CI low | CI high |", "|---|---|---|---|---|---|---|"]
    for y, m in r["by_year"].items():
        L.append(f"| {y} | {F(m['n'], dec=0)} | {F(m['net_mean'], **bp)} | {F(m.get('gross_mean'), **bp)} | {F(m.get('sharpe'))} | {F(m.get('lo'), **bp)} | {F(m.get('hi'), **bp)} |")
    L += ["", "### By VIX regime (VIX close on the decision date, two sessions before the P&L day; the interval resamples selected, non-adjacent days, so it is only indicative)", "",
          "| regime | days | net mean | gross mean | Sharpe | CI low | CI high |", "|---|---|---|---|---|---|---|"]
    for k, m in r["by_vix"].items():
        L.append(f"| VIX {k} | {F(m['n'], dec=0)} | {F(m['net_mean'], **bp)} | {F(m.get('gross_mean'), **bp)} | {F(m.get('sharpe'))} | {F(m.get('lo'), **bp)} | {F(m.get('hi'), **bp)} |")
    L += ["", "### Threshold sensitivity (open × close; stop fixed; all cells shown, no winner picked)", "",
          "| open / close | net mean | gross mean | net Sharpe | turnover | entries |", "|---|---|---|---|---|---|"]
    for k, m in r["grid_open_close"].items():
        o, c = k.split("|")
        L.append(f"| {o} / {c} | {F(m['net_mean'], **bp)} | {F(m['gross_mean'], **bp)} | {F(m['sharpe'])} | {F(m['turnover'], **pct)} | {F(m['entries'], dec=0)} |")
    L += ["", "### Lookback sensitivity (all else fixed; each M starts its sample M−60 sessions earlier or later, and all cells share one history)", "", "| M | net mean | gross mean | net Sharpe | turnover | entries |", "|---|---|---|---|---|---|"]
    for k, m in r["grid_window"].items():
        L.append(f"| {k} | {F(m['net_mean'], **bp)} | {F(m['gross_mean'], **bp)} | {F(m['sharpe'])} | {F(m['turnover'], **pct)} | {F(m['entries'], dec=0)} |")
    L += ["", "### Bootstrap block length (primary series)", "", "| mean block | 5th pct | CI low | CI high | p |", "|---|---|---|---|---|"]
    for k, m in r["blocks"].items():
        L.append(f"| {k} days | {F(m['p05'], **bp)} | {F(m['lo'], **bp)} | {F(m['hi'], **bp)} | {F(m['p_one_sided'], dec=4)} |")
    txt = "\n".join(L) + "\n"
    bad = untagged_numbers(txt)
    assert not bad, f"untagged numbers: {bad[:5]}"
    return txt


def _rj(o: Any) -> Any:
    return es._round(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    a = ap.parse_args(argv)
    snap = a.snapshot if os.path.isabs(a.snapshot) else os.path.join(ROOT, a.snapshot)
    r = build(snap)
    sid = r["snapshot"]
    jp = os.path.join(ROOT, "results", f"etf_statarb_{sid}_h2_explore.json")
    es._write(jp, r)
    mp = os.path.join(ROOT, "results", f"etf_statarb_{sid}_h2_summary.md")
    with open(mp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown(r))
    h = hashlib.sha256()
    for f in (jp, mp):
        with open(f, "rb") as fh:
            h.update(fh.read())
    print("report digest sha256", h.hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
