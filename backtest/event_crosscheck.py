# -*- coding: utf-8 -*-
"""
backtest/event_crosscheck.py — 8-K Item 2.02 acceptance vs yfinance earnings dates, whole universe.

  python -m backtest.event_crosscheck --snapshot backtest/snapshots/2026-11-04-sp100

Offline (reads the snapshot's event_crosscheck.json). Writes results/events_8k_vs_yfinance_<id>.md/.json.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

import pandas as pd

from backtest.pit import Snapshot, decision_session
from backtest.sec_crosscheck import RESULTS, _c, match_8k, trading_day_gap


def run(snapshot_root: str) -> Dict[str, Any]:
    snap = Snapshot.load(snapshot_root)
    with open(os.path.join(snapshot_root, "event_crosscheck.json"), encoding="utf-8") as fh:
        xc = json.load(fh)
    start = snap.sessions("SPY")[0]
    rows = []
    for t in snap.manifest["tickers"]:
        evs = snap.events.get(t, [])
        if not evs or not str(evs[0].get("source", "")).startswith("SEC"):
            continue
        k8 = [{"accepted_at_et": e["announced_at_et"], "accession": e.get("accession")} for e in evs]
        sessions = snap.sessions(t)
        for y in xc.get(t, {}).get("yfinance", []):
            if pd.Timestamp(y) < start or y[:10] >= snap.manifest["price_end_exclusive"]:
                continue
            m = match_8k(y, k8)
            dv = decision_session(sessions, y)
            d8 = decision_session(sessions, m["accepted_at_et"]) if m else None
            rows.append({"ticker": t, "yfinance_et": y, "edgar_8k_et": m["accepted_at_et"] if m else None,
                         "D_yfinance": str(dv.date()) if dv is not None else None,
                         "D_8k": str(d8.date()) if d8 is not None else None,
                         "gap": trading_day_gap(sessions, dv, d8)})
    return {"rows": rows, "fallback_tickers": sorted(t for t in snap.manifest["tickers"]
                                                     if snap.events.get(t) and not str(snap.events[t][0]["source"]).startswith("SEC"))}


def markdown(res: Dict[str, Any], sid: str, run_date: str) -> str:
    from core.reporting.tagged import fact, untagged_numbers
    n = lambda x: fact(x, "event_crosscheck count", run_date, decimals=0).render()  # noqa: E731
    rows = res["rows"]
    same = [r for r in rows if r["gap"] == 0]
    one = [r for r in rows if r["gap"] is not None and abs(r["gap"]) == 1]
    far = [r for r in rows if r["gap"] is not None and abs(r["gap"]) > 1]
    unm = [r for r in rows if r["edgar_8k_et"] is None]
    L = [f"# Earnings timestamps: 8-K Item 2.02 vs yfinance — snapshot {sid}", "",
         "The harness uses the 8-K acceptance time; yfinance is shown only as a cross-check. A yfinance event "
         "without an 8-K within ten days is listed as unmatched. Tickers whose events had to come from yfinance "
         "(no 8-K Item 2.02 furnished) are listed at the end. <!-- text-only -->", "",
         f"- yfinance events in the price window: {n(len(rows))}",
         f"- same decision session: {n(len(same))}",
         f"- off by one trading day: {n(len(one))}",
         f"- off by more than one trading day: {n(len(far))}",
         f"- no matching `8-K`: {n(len(unm))}", ""]
    for title, rr in (("Off by more than one trading day", far), ("Off by one trading day", one), ("Unmatched", unm)):
        L += [f"## {title}", ""]
        if not rr:
            L += ["None. <!-- text-only -->", ""]
            continue
        L += ["| ticker | yfinance (ET) | 8-K accepted (ET) | D yfinance | D 8-K | gap (sessions) |", "|---|---|---|---|---|---|"]
        for r in rr:
            L.append(f"| {r['ticker']} | `{r['yfinance_et']}` | {_c(r['edgar_8k_et'])} | {_c(r['D_yfinance'])} | "
                     f"{_c(r['D_8k'])} | {n(r['gap']) if r['gap'] is not None else 'n/a'} |")
        L.append("")
    L += ["## Tickers with yfinance-sourced events (no 8-K Item 2.02)", "",
          (", ".join(res["fallback_tickers"]) or "None.") + " <!-- text-only -->", ""]
    md = "\n".join(L)
    bad = untagged_numbers(md)
    if bad:
        raise ValueError(f"untagged numbers: {bad[:5]}")
    return md


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    a = ap.parse_args()
    res = run(a.snapshot)
    sid = os.path.basename(os.path.normpath(a.snapshot))
    with open(os.path.join(RESULTS, f"events_8k_vs_yfinance_{sid}.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    with open(os.path.join(RESULTS, f"events_8k_vs_yfinance_{sid}.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown(res, sid, sid[:10]))
    g = [r["gap"] for r in res["rows"]]
    print(f"rows={len(g)} same={g.count(0)} unmatched={sum(r['edgar_8k_et'] is None for r in res['rows'])} "
          f"fallback={res['fallback_tickers']}")


if __name__ == "__main__":
    main()
