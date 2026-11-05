# -*- coding: utf-8 -*-
"""
backtest/h1_report.py — Session 3 Phase D: the pre-registered H1 result first, then exploratory cells.

Reads only the outputs of the pre-registered command (HYPOTHESIS.md):
  results/walkforward_2026-11-04-pit_phaseD.csv and _summary.json
Writes results/h1_phaseD_2026-11-04.md / .json.

  python -m backtest.h1_report
  python -m backtest.h1_report --snapshot 2026-11-04-pit2   # Session 4 Phase C rerun -> results/h1_rerun_2026-11-04-pit2.md
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import numpy as np
import pandas as pd

from backtest import walkforward as wf
from backtest.stats import cluster_diff, cluster_diff_2way

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = "2026-11-04-pit_phaseD"
SRC = f"wf-backtest {TAG}"
AS_OF = "2026-11-04"
SEEN_FROM = "2023-10-09"   # Phase B window start (seen before pre-registration)
BASE_SID = "2026-11-04-pit"
SID = BASE_SID


def configure(sid: str) -> None:
    """Session 4: the same report for the pre-registered command run on another snapshot (only the id changes)."""
    global TAG, SRC, SID
    SID, TAG, SRC = sid, f"{sid}_phaseD", f"wf-backtest {sid}_phaseD"


def skill(df: pd.DataFrame, strat: str, h: int) -> Dict[str, Any]:
    """Within-ticker selection skill on a subset, demeaned within ticker on that subset (as in the harness)."""
    s = df[df.strategy == strat]
    y = s[f"underlying_ret_{h}"] - s[f"sector_ret_{h}"]
    yd = y - y.groupby(s["ticker"]).transform("mean")
    seas = pd.to_datetime(s["decision_date"]).dt.to_period("Q").astype(str).to_numpy()
    return {"two_way": cluster_diff_2way(yd.to_numpy(), s["long"].to_numpy() == 1, seas, s["ticker"].to_numpy()),
            "season": cluster_diff(yd.to_numpy(), s["long"].to_numpy() == 1, seas)}


def fe_slope(df: pd.DataFrame, strat: str = "council", h: int = 5) -> Dict[str, float]:
    """Review P1-4 (exploratory): the ticker fixed-effects slope of y on the long indicator, and the weight sum W that
    links it to the pre-registered S (S = W x a weighted average of within-ticker long-flat gaps; W < 1 attenuates S,
    and tickers that are all-long or all-flat add only to the denominators)."""
    s = df[df.strategy == strat]
    y = s[f"underlying_ret_{h}"] - s[f"sector_ret_{h}"]
    g = s["long"].astype(float)
    yd = y - y.groupby(s["ticker"]).transform("mean")
    gd = g - g.groupby(s["ticker"]).transform("mean")
    n_l, n_f = float(g.sum()), float((1 - g).sum())
    per = s.assign(g=g).groupby("ticker")["g"].agg(["sum", "count"])
    w = (1 / n_l + 1 / n_f) * float((per["sum"] * (per["count"] - per["sum"]) / per["count"]).sum())
    mixed = per[(per["sum"] > 0) & (per["sum"] < per["count"])]
    return {"slope": float((gd * yd).sum() / (gd * gd).sum()), "W": w, "tickers_mixed": int(len(mixed)),
            "tickers_all_one_side": int(len(per) - len(mixed))}


def build() -> Dict[str, Any]:
    with open(os.path.join(ROOT, "results", f"walkforward_{TAG}_summary.json"), encoding="utf-8") as fh:
        summ = json.load(fh)
    df = pd.read_csv(os.path.join(ROOT, "results", f"walkforward_{TAG}.csv"))
    o = summ["cells"]["overall"]
    out: Dict[str, Any] = {"h1": o["council|5|selection_skill_fe_2way"], "h1_season_only": o["council|5|selection_skill_fe"],
                           "run": summ["run"], "n_events": o["n_events"]}
    c = df[df.strategy == "council"]
    out["date_range"] = [str(c.decision_date.min()), str(c.decision_date.max())]
    out["n_seasons"] = int(pd.to_datetime(c.decision_date).dt.to_period("Q").nunique())
    pre = df[df.decision_date < SEEN_FROM]
    out["pre_seen"] = {f"{s}|{h}": skill(pre, s, h) for s in ("council", "factors_only") for h in wf.HORIZONS}
    out["pre_seen_n"] = int((pre.strategy == "council").sum())
    out["overall"] = o
    out["fe"] = fe_slope(df)
    if SID != BASE_SID:   # Session 4: the Session 3 pre-registered run, for the comparison table
        with open(os.path.join(ROOT, "results", f"walkforward_{BASE_SID}_phaseD_summary.json"), encoding="utf-8") as fh:
            ps = json.load(fh)["cells"]["overall"]
        out["prev"] = {"h1": ps["council|5|selection_skill_fe_2way"],
                       "fe": fe_slope(pd.read_csv(os.path.join(ROOT, "results", f"walkforward_{BASE_SID}_phaseD.csv")))}
    out["by_regime"] = summ["cells"]["by_regime"]
    out["by_sector"] = summ["cells"]["by_sector"]
    return out


def markdown(r: Dict[str, Any]) -> str:
    from core.reporting.tagged import untagged_numbers

    def F(x, pct=True, dec=2, src=SRC):
        return wf._fmt(x, pct, src, AS_OF, decimals=dec)

    def N(x, src=SRC):
        return wf._fmt(x, False, src, AS_OF, decimals=0)

    h = r["h1"]
    reject = h["p05"] is not None and h["p05"] > 0
    L = ["# Phase D — pre-registered H1 first, then exploratory results", "",
         "Pre-registration: HYPOTHESIS.md (committed before this run). Snapshot `2026-11-04-pit`, point-in-time top-hundred "
         "universe, mock council, YoY growth from the same filing's prior-year comparative. <!-- text-only -->", ""]
    if SID != BASE_SID:
        L = [f"# Session 4 Phase C — H1 rerun on snapshot `{SID}`, pre-registered command unchanged except the snapshot id", "",
             "Pre-registration: HYPOTHESIS.md (Session 3; nothing above its RESULTS line changed). Snapshot `" + SID + "`: ranking rules v2 "
             "and event rules v2 folded into a new base (results/pit2_changes_2026-11-04.md). Same prices as the Session 3 run. "
             "<!-- text-only -->", ""]
    L += [
         "## H1 (confirmatory): within-ticker selection skill of the council at T+5", "",
         f"- Sample: {N(r['n_events'])} events, decision dates `{r['date_range'][0]}` to `{r['date_range'][1]}`, "
         f"{N(h['n_c1'])} earnings seasons, {N(h['n_c2'])} tickers; council long on {N(h['n_in'])}, flat on {N(h['n_out'])}.",
         f"- **S = {F(h['mean'])}** (long-event minus flat-event sector-relative five-session return, demeaned within ticker).",
         f"- Two-way (season x ticker) bootstrap: one-sided lower bound (fifth percentile) {F(h['p05'])}; "
         f"two-sided ninety-five percent CI [{F(h['lo'])}, {F(h['hi'])}]; one-sided bootstrap p {F(h['p_one_sided'], False, 3)}; "
         f"SE {F(h['se'])}; MDE (one-sided, eighty percent power) {F(h['mde80_one_sided'])}.",
         ("- **Decision: reject H0** (the fifth percentile is above zero). <!-- text-only -->" if reject else
          "- **Decision: do not reject H0.** The fifth percentile is not above zero: no evidence that the council picks better "
          "earnings events within a ticker than it skips, at the pre-registered horizon. <!-- text-only -->"),
         ("- Economic check: the pre-registered threshold is twenty basis points (one round trip); see HYPOTHESIS.md. <!-- text-only -->"),
         f"- Season-only clustering (robustness, not the test): CI [{F(r['h1_season_only']['lo'])}, {F(r['h1_season_only']['hi'])}].",
         f"- Added after the independent review (attenuation finding; exploratory, does not change the decision): S is attenuated. It equals "
         f"W x (a weighted average of within-ticker long-minus-flat gaps) with W = {F(r['fe']['W'], False, 2, 'derived from ' + SRC)}; "
         f"{N(r['fe']['tickers_all_one_side'], 'derived from ' + SRC)} tickers are all-long or all-flat. The ticker fixed-effects "
         f"slope is {F(r['fe']['slope'], src='derived from ' + SRC)}. In those effect units the MDE is about the reported MDE "
         f"divided by W, i.e. close to one percent, not the reported figure.",
         ]
    if SID != BASE_SID:   # Session 4 (review P1-4): MDE in effect units, stated next to S's own MDE
        L.append(f"- MDE in within-ticker effect units (MDE / W): "
                 f"{F(h['mde80_one_sided'] / r['fe']['W'] if r['fe']['W'] else None, src='derived from ' + SRC)}.")
    if SID != BASE_SID and r.get("prev"):
        p, pf = r["prev"]["h1"], r["prev"]["fe"]
        ps = "wf-backtest 2026-11-04-pit_phaseD"
        L += ["", "## Compared with the Session 3 pre-registered run (snapshot `2026-11-04-pit`)", "",
              "| | Session 3 (`2026-11-04-pit`) | Session 4 (`" + SID + "`) |", "|---|---|---|",
              f"| events / seasons / tickers | {N(p['n_in'] + p['n_out'], ps)} / {N(p['n_c1'], ps)} / {N(p['n_c2'], ps)} | "
              f"{N(h['n_in'] + h['n_out'])} / {N(h['n_c1'])} / {N(h['n_c2'])} |",
              f"| S | {F(p['mean'], src=ps)} | {F(h['mean'])} |",
              f"| one-sided lower bound (p05) | {F(p['p05'], src=ps)} | {F(h['p05'])} |",
              f"| two-sided 95% CI | [{F(p['lo'], src=ps)}, {F(p['hi'], src=ps)}] | [{F(h['lo'])}, {F(h['hi'])}] |",
              f"| one-sided p | {F(p['p_one_sided'], False, 3, ps)} | {F(h['p_one_sided'], False, 3)} |",
              f"| decision | {'reject' if (p['p05'] or 0) > 0 else 'not rejected'} | {'reject' if reject else 'not rejected'} |",
              f"| fixed-effects slope (exploratory) | {F(pf['slope'], src='derived from ' + ps)} | {F(r['fe']['slope'], src='derived from ' + SRC)} |",
              f"| W | {F(pf['W'], False, 2, 'derived from ' + ps)} | {F(r['fe']['W'], False, 2, 'derived from ' + SRC)} |",
              f"| MDE, S units / effect units | {F(p['mde80_one_sided'], src=ps)} / {F(p['mde80_one_sided'] / pf['W'], src='derived from ' + ps)} | "
              f"{F(h['mde80_one_sided'])} / {F(h['mde80_one_sided'] / r['fe']['W'] if r['fe']['W'] else None, src='derived from ' + SRC)} |"]
    L += ["", "## Exploratory (not confirmatory; many cells, expect some false positives)", "",
         "### Within-ticker selection skill, all horizons (two-way clustered)", "",
         "| strategy / horizon | S | 95% CI low | 95% CI high | one-sided lower bound | longs | flats |", "|---|---|---|---|---|---|---|"]
    o = r["overall"]
    for s in ("council", "factors_only"):
        for hh in wf.HORIZONS:
            w = o[f"{s}|{hh}|selection_skill_fe_2way"]
            L.append(f"| {s} T+{hh} | {F(w['mean'])} | {F(w['lo'])} | {F(w['hi'])} | {F(w['p05'])} | {N(w['n_in'])} | {N(w['n_out'])} |")
    L += ["", f"### Unseen subsample: decision dates before `{SEEN_FROM}` (not looked at before pre-registration)", "",
          f"Events: {N(r['pre_seen_n'], 'derived from ' + SRC)}. Demeaned within ticker on the subsample. <!-- text-only -->", "",
          "| strategy / horizon | S | two-way 95% CI low | two-way 95% CI high | one-sided lower bound |", "|---|---|---|---|---|"]
    for s in ("council", "factors_only"):
        for hh in wf.HORIZONS:
            w = r["pre_seen"][f"{s}|{hh}"]["two_way"]
            src = "derived from " + SRC
            L.append(f"| {s} T+{hh} | {F(w['mean'], src=src)} | {F(w['lo'], src=src)} | {F(w['hi'], src=src)} | {F(w['p05'], src=src)} |")
    L += ["", "### Returns (season-clustered CIs)", "",
          "| strategy / horizon | events | avg net | excess vs SPY | excess vs sector ETF |", "|---|---|---|---|---|"]
    for s in wf.STRATEGIES:
        for hh in wf.HORIZONS:
            ms = o[f"{s}|{hh}|excess_sector"]
            L.append(f"| {s} T+{hh} | {N(ms['n'])} | {wf._ci(F, o[f'{s}|{hh}|net_ret'])} | {wf._ci(F, o[f'{s}|{hh}|excess_ret'])} | {wf._ci(F, ms)} |")
    L += ["", "| council − factors-only (paired) | mean [season-clustered CI] |", "|---|---|"]
    for hh in wf.HORIZONS:
        L.append(f"| T+{hh} | {wf._ci(F, o[f'council_minus_factors|{hh}'])} |")
    for title, key in (("By VIX regime (close on D-1)", "by_regime"), ("By GICS sector", "by_sector")):
        L += ["", f"### {title} — council within-ticker selection skill, two-way clustered", "",
              "| cell | events | T+1 | T+5 | T+20 |", "|---|---|---|---|---|"]
        for name, cc in r[key].items():
            cells = []
            for hh in wf.HORIZONS:
                w = cc.get(f"council|{hh}|selection_skill_fe_2way") or {}
                ok = (w.get("n_c1") or 0) >= wf.MIN_CLUSTERS and w.get("mean") is not None
                cells.append(f"{F(w['mean'])} [{F(w['lo'])} … {F(w['hi'])}]" if ok else "n/a (too few seasons)")
            L.append(f"| {name} | {N(cc['n_events'])} | " + " | ".join(cells) + " |")
    md = "\n".join(L) + "\n"
    bad = untagged_numbers(md)
    if bad:
        raise ValueError(f"untagged numbers: {bad[:6]}")
    return md


def main() -> None:
    import sys
    if "--snapshot" in sys.argv:
        configure(sys.argv[sys.argv.index("--snapshot") + 1])
    r = build()
    out = os.path.join(ROOT, "results", "h1_phaseD_2026-11-04" if SID == BASE_SID else f"h1_rerun_{SID}")
    with open(out + ".md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown(r))
    with open(out + ".json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump({k: r[k] for k in ("h1", "h1_season_only", "run", "n_events", "date_range", "n_seasons", "pre_seen", "pre_seen_n")
                   + (("fe", "prev") if SID != BASE_SID else ())},
                  fh, indent=1, sort_keys=True, default=lambda x: None if isinstance(x, float) and not np.isfinite(x) else x)
    print("written", out + ".md")


if __name__ == "__main__":
    main()
