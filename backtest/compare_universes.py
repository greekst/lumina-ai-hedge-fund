# -*- coding: utf-8 -*-
"""
backtest/compare_universes.py — Session 3 Phase B: survivorship-biased vs point-in-time universe, side by side.

Columns (same decision-date window as Session 2, 2023-10-09 .. 2026-09-30):
  A  Session 2 as published: S&P 100 proxy (today's 100 largest), snapshot 2026-11-04-sp100, last 12 events/ticker
  B  today's 100 largest, recomputed on the Session 3 data (snapshot 2026-11-04-pit, universe static_top at the
     last session): isolates the universe effect from data/candidate differences
  C  point-in-time universe: an event counts only if its company was in the top 100 at the close of D-1

  python -m backtest.compare_universes            # writes results/pit_vs_biased_2026-11-04.md/.json
  python -m backtest.compare_universes --snapshot 2026-11-04-pit2   # Session 4: B and C on the new base snapshot
                                                  # -> results/pit_vs_biased_2026-11-04-pit2.md/.json
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import numpy as np

from backtest import walkforward as wf
from backtest.pit import Snapshot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW = ("2023-10-09", "2026-09-30")


def _snap_id() -> str:
    import sys
    return sys.argv[sys.argv.index("--snapshot") + 1] if "--snapshot" in sys.argv else "2026-11-04-pit"


def _root(sid: str) -> str:
    return os.path.join(ROOT, "backtest", "snapshots", sid)


def runs(out_dir: str = wf.RESULTS_DIR, sid: str = "2026-11-04-pit") -> Dict[str, Any]:
    PIT = _root(sid)
    snap = Snapshot.load(PIT)
    last = str(snap.sessions("SPY")[-1].date())
    res = {}
    res["B"] = wf.run(PIT, None, out_dir=out_dir, universe=f"static_top:{last}", d_from=WINDOW[0], d_to=WINDOW[1],
                      tag="biased_today_top100", two_way=True, snap=snap)
    res["C"] = wf.run(PIT, None, out_dir=out_dir, universe="pit", d_from=WINDOW[0], d_to=WINDOW[1],
                      tag="pit_s2window", two_way=True, snap=snap)
    with open(os.path.join(ROOT, "results", "walkforward_2026-11-04-sp100_summary.json"), encoding="utf-8") as fh:
        res["A"] = {"summary": json.load(fh), "rows": None}
    res["_last_session"] = last
    res["_sid"] = sid
    return res


ROWS = [  # (label, cell key, kind)
    ("buy-and-hold excess vs sector ETF", "buy_and_hold|{h}|excess_sector", "cell"),
    ("buy-and-hold excess vs SPY", "buy_and_hold|{h}|excess_ret", "cell"),
    ("council excess vs sector ETF", "council|{h}|excess_sector", "cell"),
    ("factors-only excess vs sector ETF", "factors_only|{h}|excess_sector", "cell"),
    ("council − factors-only (paired)", "council_minus_factors|{h}", "cell"),
    ("council selection skill, within ticker", "council|{h}|selection_skill_fe", "skill"),
    ("factors-only selection skill, within ticker", "factors_only|{h}|selection_skill_fe", "skill"),
]


def markdown(res: Dict[str, Any]) -> str:
    from core.reporting.tagged import untagged_numbers
    sid = res.get("_sid", "2026-11-04-pit")
    srcs = {"A": "wf-backtest 2026-11-04-sp100", "B": f"wf-backtest {sid}_biased_today_top100",
            "C": f"wf-backtest {sid}_pit_s2window"}

    def F(x, k, pct=True, dec=2):
        return wf._fmt(x, pct, srcs[k], "2026-11-04", decimals=dec)

    def cell(k, m, kind):
        if m is None or m.get("mean") is None:
            return "n/a"
        if kind == "skill":
            return f"{F(m['mean'], k)} [{F(m['lo'], k)} … {F(m['hi'], k)}]"
        c = m.get("cluster") or {}
        return f"{F(m['mean'], k)} [{F(c.get('lo'), k)} … {F(c.get('hi'), k)}]"

    L = ["# Survivorship-biased vs point-in-time universe — Session 2 window", "",
         "Same harness, same decision-date window (`2023-10-09` to `2026-09-30`, twelve earnings seasons), council in "
         "LUMINA_LLM_MODE=mock. Each cell: mean, then the 95% bootstrap CI clustered by earnings season in brackets. "
         "Column A is Session 2 as published (S&P 100 proxy: today's hundred largest S&P 500 members, Session 2 data, last "
         "twelve events per ticker). Column B is today's hundred largest recomputed on the Session 3 data (point-in-time "
         "candidate pool, EDGAR shares x close on the last session), every event in the window. Column C is the point-in-time "
         "universe: an event counts only if its company was in the top hundred by market cap at the close of D-1. "
         "B versus C isolates the universe effect on identical data. <!-- text-only -->", "",
         "| | A: Session 2 (biased) | B: today's top hundred, Session 3 data (biased) | C: point-in-time |", "|---|---|---|---|"]
    if sid != "2026-11-04-pit":
        L[0] += f" (snapshot {sid})"
        L.insert(3, f"Session 4: columns B and C use snapshot `{sid}` (ranking rules v2 and event rules v2 in the base; same prices as "
                    "`2026-11-04-pit`). Column A is unchanged. <!-- text-only -->")
        L.insert(4, "")
    ov = {k: res[k]["summary"]["cells"]["overall"] for k in "ABC"}
    L.append("| events | " + " | ".join(wf._fmt(ov[k]["n_events"], False, srcs[k], "2026-11-04", decimals=0) for k in "ABC") + " |")
    L.append("| tickers with events | " + " | ".join(
        wf._fmt(res[k]["summary"].get("run", {}).get("n_tickers_with_events", 100) if k != "A" else 100, False, srcs[k],
                "2026-11-04", decimals=0) for k in "ABC") + " |")
    for k_ in ("council", "factors_only"):
        L.append(f"| {k_} long rate | " + " | ".join(F(ov[k][f'{k_}|long_rate'], k) for k in "ABC") + " |")
    for h in wf.HORIZONS:
        L += [f"| **T+{h}** | | | |"]
        for label, key, kind in ROWS:
            L.append(f"| {label} | " + " | ".join(cell(k, ov[k].get(key.format(h=h)), kind) for k in "ABC") + " |")
    bh = {k: ov[k]["buy_and_hold|20|excess_sector"]["mean"] for k in "ABC"}
    surv = bh["C"] / bh["B"] if bh["B"] else float("nan")
    L += ["", "## How much of the buy-and-hold excess survives", "",
          f"- Buy-and-hold excess vs sector ETF at the twenty-session horizon: biased universe on this session's data (B) {F(bh['B'], 'B')}, "
          f"point-in-time universe (C) {F(bh['C'], 'C')}. Share that survives (C / B): "
          f"{wf._fmt(surv, False, 'derived: C / B', '2026-11-04', decimals=2)}. "
          f"Previous session as published (A): {F(bh['A'], 'A')}.",
          "- The point-in-time universe still excludes companies that were delisted after acquisition and have no price "
          "history in this sandbox (see results/pit_universe_2026-11-04.md, known gaps). The DIRECTION of that bias is "
          "unknown: several were long decliners before they left (Walgreens, Allergan, Celgene, Express Scripts), and a "
          "takeover premium lands on one announcement day, rarely inside an earnings window (corrected after the "
          "independent review, P1-5; it was first stated as a downward bias). <!-- text-only -->", ""]
    md = "\n".join(L) + "\n"
    bad = untagged_numbers(md)
    if bad:
        raise ValueError(f"untagged numbers: {bad[:5]}")
    return md


def from_files(sid: str = "2026-11-04-pit") -> Dict[str, Any]:
    res = {"_sid": sid}
    for k, name in (("A", "2026-11-04-sp100"), ("B", f"{sid}_biased_today_top100"), ("C", f"{sid}_pit_s2window")):
        with open(os.path.join(ROOT, "results", f"walkforward_{name}_summary.json"), encoding="utf-8") as fh:
            res[k] = {"summary": json.load(fh)}
    res["_last_session"] = str(Snapshot.load(_root(sid)).sessions("SPY")[-1].date())
    return res


def main() -> None:
    import sys
    sid = _snap_id()
    res = from_files(sid) if "--from-files" in sys.argv else runs(sid=sid)
    md = markdown(res)
    out = os.path.join(ROOT, "results", "pit_vs_biased_2026-11-04" + ("" if sid == "2026-11-04-pit" else f"-{sid.split('-')[-1]}") + ".md")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)
    with open(out.replace(".md", ".json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({k: res[k]["summary"]["cells"]["overall"] for k in "ABC"} | {"last_session": res["_last_session"]},
                  fh, indent=1, sort_keys=True, default=lambda x: None if isinstance(x, float) and not np.isfinite(x) else x)
    for k in "BC":
        if "paths" in res[k]:
            print(k, json.dumps(res[k]["paths"]), "sha256", wf.digest(res[k]["paths"]))
    print("written", out)


if __name__ == "__main__":
    main()
