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
    rows, extra = [], []
    for t in snap.manifest["tickers"]:
        sessions = snap.sessions(t)
        used = set()
        for e in snap.events.get(t, []):
            if pd.Timestamp(e["vendor_et"]) < start:
                continue
            dv = decision_session(sessions, e["vendor_et"])
            d8 = decision_session(sessions, e["edgar_8k_et"]) if e.get("edgar_8k_et") else None
            du = decision_session(sessions, e["announced_at_et"])
            used.add(e.get("accession"))
            rows.append({"ticker": t, "yfinance_et": e["vendor_et"], "edgar_8k_et": e.get("edgar_8k_et"),
                         "D_yfinance": str(dv.date()) if dv is not None else None,
                         "D_8k": str(d8.date()) if d8 is not None else None,
                         "D_used": str(du.date()) if du is not None else None, "rule": e["rule"],
                         "gap": trading_day_gap(sessions, dv, d8)})
        for k in xc.get(t, {}).get("edgar_2_02", []):
            if k["accession"] not in used and pd.Timestamp(k["accepted_at_et"]) >= start:
                extra.append({"ticker": t, "edgar_8k_et": k["accepted_at_et"][:16], "accession": k["accession"]})
    return {"rows": rows, "extra_8k": extra, "fallback_tickers": []}


def markdown(res: Dict[str, Any], sid: str, run_date: str) -> str:
    from core.reporting.tagged import fact, untagged_numbers
    n = lambda x: fact(x, "event_crosscheck count", run_date, decimals=0).render()  # noqa: E731
    rows = res["rows"]
    same = [r for r in rows if r["gap"] == 0]
    one = [r for r in rows if r["gap"] is not None and abs(r["gap"]) == 1]
    far = [r for r in rows if r["gap"] is not None and abs(r["gap"]) > 1]
    unm = [r for r in rows if r["edgar_8k_et"] is None]
    L = [f"# Earnings timestamps: 8-K Item 2.02 vs yfinance — snapshot {sid}", "",
         "yfinance identifies which dates are earnings releases; each is matched to an `8-K` Item 2.02 within three "
         "calendar days, and the harness uses the EARLIER of the two timestamps (column D used). An `8-K` can be "
         "accepted after the press release (look-ahead if used alone); a vendor placeholder time can only move D "
         "earlier. Item 2.02 filings that match no earnings date (delivery reports, monthly sales, preliminary "
         "results, pre-announcements) are listed and are NOT events. <!-- text-only -->", "",
         f"- yfinance events in the price window: {n(len(rows))}",
         f"- same decision session: {n(len(same))}",
         f"- off by one trading day: {n(len(one))}",
         f"- off by more than one trading day: {n(len(far))}",
         f"- no matching `8-K` within three days (vendor time used): {n(len(unm))}",
         f"- `8-K` filings matching no earnings date (excluded): "
         f"{n(len(res['extra_8k']))}", ""]
    for title, rr in (("Off by more than one trading day", far), ("Off by one trading day", one), ("Unmatched", unm)):
        L += [f"## {title}", ""]
        if not rr:
            L += ["None. <!-- text-only -->", ""]
            continue
        L += ["| ticker | yfinance (ET) | 8-K accepted (ET) | D yfinance | D 8-K | gap (sessions) | D used |",
              "|---|---|---|---|---|---|---|"]
        for r in rr:
            L.append(f"| {r['ticker']} | `{r['yfinance_et']}` | {_c(r['edgar_8k_et'])} | {_c(r['D_yfinance'])} | "
                     f"{_c(r['D_8k'])} | {n(r['gap']) if r['gap'] is not None else 'n/a'} | {_c(r['D_used'])} |")
        L.append("")
    L += ["## 8-K filings that are not earnings releases (excluded)", ""]
    if res["extra_8k"]:
        L += ["| ticker | 8-K accepted (ET) | accession |", "|---|---|---|"]
        L += [f"| {r['ticker']} | `{r['edgar_8k_et']}` | {_c(r['accession'])} |" for r in res["extra_8k"]]
    else:
        L.append("None. <!-- text-only -->")
    L += ["", "## Tickers with yfinance-sourced events (no 8-K Item 2.02)", "",
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
