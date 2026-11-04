# -*- coding: utf-8 -*-
"""
backtest/delisted_gap.py — Session 4 Phase A: quantify the delisted-company gap from data.

No delisted-price provider is reachable from this sandbox (allowed hosts: Yahoo, SEC, FRED, Hugging Face, Finnhub,
Gemini; Yahoo keeps no history for delisted tickers; Finnhub candles are 403 on this plan). Without prices these
companies cannot be ranked by market cap or given returns, so they stay out of the snapshot. This module measures
how many top-100 earnings events the gap costs, per earnings season, using EDGAR only:

  * gap companies: every company in the public-float top 150 in any year 2014-2025 (dei:EntityPublicFloat frames)
    with no current listing and a plausible float (<= 15x its largest total assets) — the completeness check of
    results/pit_universe_2026-11-04.md (`pit_universe.gaps`).
  * their earnings events: SEC 8-K Item 2.02 acceptance times, reduced to one per reporting period with the same
    rule the new base snapshot uses for 8-K-only events (`snapshot_pit.earnings_8k_events`).
  * "would have been top 100" (an ESTIMATE): the latest public float accepted before D (<= 460 days old) is at
    least the 100th-largest PIT market cap of the candidate pool on the float's own date (ranking rules v2).
    Public float excludes affiliate holdings, so it understates market cap (a lower bound on membership); an upper
    bound uses 150th-largest instead. Neither is used in any test; they size the gap only.

  python -m backtest.delisted_gap --snapshot backtest/snapshots/2026-11-04-pit-r1
Writes results/delisted_gap_2026-11-04.md / .json (every number tagged).
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from typing import Any, Dict, List

import pandas as pd

from backtest import pit_universe as PU
from backtest.edgar import EdgarClient, EdgarUnavailable, earnings_8k
from backtest.pit import Snapshot, decision_session
from backtest.snapshot_pit import PREDECESSOR_CIKS, earnings_8k_events, periodic_filings
from core.reporting.tagged import assumption, fact

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
AS_OF = "2026-11-04"
FLOAT_MAX_AGE_DAYS = 460


def _season(d: pd.Timestamp) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def run(snapshot_root: str, h1_csv: str, ed: EdgarClient) -> Dict[str, Any]:
    snap = Snapshot.load(snapshot_root)
    with open(os.path.join(PU.PDIR, "candidates.json"), encoding="utf-8") as fh:
        cand = json.load(fh)
    exch = json.loads(PU._read_gz(os.path.join(PU.PDIR, "sec_company_tickers_exchange.json.gz")))
    live = {int(r[0]) for r in exch["data"]}
    pred = {c for v in PREDECESSOR_CIKS.values() for c in v}
    gaps = [g for g in PU.gaps(cand, ed) if g["cik"] not in live and g["cik"] not in pred and g["plausible"]]
    sessions = snap.sessions("SPY")
    cap_rank: Dict[str, List[float]] = {}

    def nth_cap(day: pd.Timestamp, n: int) -> float:
        k = str(day.date())
        if k not in cap_rank:
            cap_rank[k] = sorted(PU.market_caps_on(snap, day).values(), reverse=True)
        caps = cap_rank[k]
        return caps[n - 1] if len(caps) >= n else 0.0

    rows: List[Dict[str, Any]] = []
    per_co: List[Dict[str, Any]] = []
    for g in gaps:
        try:
            b = ed.bundle_ciks([g["cik"]], since="2012-01-01")
        except EdgarUnavailable as e:
            per_co.append({"cik": g["cik"], "name": g["name"], "error": str(e)})
            continue
        floats = PU.public_floats(b["facts"], b["subs"], since="2012-01-01")
        k8 = earnings_8k(b["subs"], since="2014-01-01")
        evs = earnings_8k_events(k8, periodic_filings(b["subs"]))
        n_lo = n_hi = 0
        for e in evs:
            D = decision_session(sessions, e["accepted_at_et"])
            if D is None or D < pd.Timestamp("2015-01-01") or D > pd.Timestamp("2026-09-24"):
                continue
            cutoff = pd.Timestamp(f"{D.date()} 16:00:00")
            fr = [f for f in floats if pd.Timestamp(f["accepted_at"]) < cutoff
                  and (D - pd.Timestamp(f["as_of"])).days <= FLOAT_MAX_AGE_DAYS]
            if not fr:
                continue
            f = fr[-1]
            fd = sessions[sessions <= pd.Timestamp(f["as_of"])]
            if not len(fd):
                continue
            lo = f["value"] >= nth_cap(fd[-1], 100)
            hi = f["value"] >= nth_cap(fd[-1], 150)
            n_lo += int(lo)
            n_hi += int(hi)
            if hi:
                rows.append({"cik": g["cik"], "name": g["name"], "decision_date": str(D.date()), "season": _season(D),
                             "accepted_at_et": e["accepted_at_et"], "float_usd": f["value"], "float_as_of": f["as_of"],
                             "top100_est": bool(lo)})
        per_co.append({"cik": g["cik"], "name": g["name"], "best_float_rank": g["best_float_rank"],
                       "events_8k_since_2015": len([e for e in evs if e["accepted_at_et"] >= "2015-01-01"]),
                       "events_top100_est": n_lo, "events_top150_float_bound": n_hi})
    h1 = pd.read_csv(h1_csv, usecols=["ticker", "strategy", "decision_date"])
    h1 = h1[h1.strategy == "council"]
    h1_season = Counter(_season(pd.Timestamp(d)) for d in h1.decision_date)
    lo_s = Counter(r["season"] for r in rows if r["top100_est"])
    hi_s = Counter(r["season"] for r in rows)
    seasons = sorted(set(h1_season) | set(hi_s))
    by_season = [{"season": s, "h1_events": h1_season.get(s, 0), "lost_est": lo_s.get(s, 0), "lost_upper": hi_s.get(s, 0)}
                 for s in seasons]
    return {"snapshot": os.path.basename(snapshot_root.rstrip("/")), "gap_companies": len(gaps), "per_company": per_co,
            "events": rows, "by_season": by_season, "h1_events": int(len(h1)),
            "lost_est": sum(lo_s.values()), "lost_upper": sum(hi_s.values())}


def write(res: Dict[str, Any]) -> None:
    src = "SEC EDGAR 8-K Item 2.02 + dei:EntityPublicFloat; PIT caps " + res["snapshot"]
    def T(v: float, s: str = src) -> str:
        return fact(v, s, AS_OF, decimals=0).render(with_label=False)

    def M(v: float, pct: bool = False) -> str:
        return (assumption(v * 100.0, "estimate: " + src, AS_OF, unit="%", decimals=1) if pct
                else assumption(v, "estimate: " + src, AS_OF, decimals=0)).render(with_label=False)
    n, lo, hi = res["h1_events"], res["lost_est"], res["lost_upper"]
    L = ["# Delisted-company gap — Session 4 Phase A", "",
         "No delisted-price provider is configured for this environment (no API key or network secret; allowed hosts: Yahoo, SEC, FRED, "
         "Hugging Face, Finnhub, Gemini). Yahoo keeps no history for delisted tickers and Finnhub candles return 403 on this plan. "
         "The gap therefore stays as documented, and is sized here from EDGAR only. <!-- text-only -->", "",
         "Method (backtest/delisted_gap.py): gap companies are the public-float top 150 of any year with no current listing and a plausible float; "
         "their earnings events are 8-K Item 2.02 filings reduced to one per reporting period; an event counts as lost if the latest public float "
         "known before D (at most 460 days old) is at least the 100th-largest point-in-time market cap of the candidate pool on the float's date. "
         "The float understates market cap, so this is a lower bound; using the 150th-largest gives an upper bound. Window: D in 2015-01-01..2026-09-24 "
         "(the H1 sample window). <!-- text-only -->", "",
         f"- Gap companies examined: {T(res['gap_companies'])}.",
         f"- H1 sample (pre-registered run, base snapshot): {T(n, s='wf-backtest 2026-11-04-pit_phaseD')} events.",
         f"- Estimated lost top-100 events: {M(lo)} ({M(lo / (n + lo) if n else 0, True)} of the sample incl. them); "
         f"upper bound {M(hi)} ({M(hi / (n + hi) if n else 0, True)}).", "",
         "## Per company (events since 2015 with an estimated top-100 / top-150-bound float)", "",
         "| company (EDGAR name) | best float rank | 8-K earnings events since 2015 | lost, estimate | lost, upper bound |", "|---|---|---|---|---|"]
    for c in sorted(res["per_company"], key=lambda c: (-c.get("events_top150_float_bound", 0), c["cik"])):
        if c.get("error") or not c.get("events_top150_float_bound"):
            continue
        L.append(f"| {c['name']} | {T(c['best_float_rank'])} | {T(c['events_8k_since_2015'])} | {M(c['events_top100_est'])} | "
                 f"{M(c['events_top150_float_bound'])} |")
    errs = [c for c in res["per_company"] if c.get("error")]
    if errs:
        L += ["", "EDGAR unavailable for: " + ", ".join(f"{c['name']} ({c['error'][:40]})" for c in errs) + " <!-- text-only -->"]
    L += ["", "## Per earnings season", "", "| season | H1 events | lost, estimate | lost, upper bound |", "|---|---|---|---|"]
    for r in res["by_season"]:
        L.append(f"| `{r['season']}` | {T(r['h1_events'], s='wf-backtest 2026-11-04-pit_phaseD')} | {M(r['lost_est'])} | "
                 f"{M(r['lost_upper'])} |")
    L += ["", "**Reading.** The lost events cluster in the early seasons (most gap companies were acquired by 2019). H1 demeans within ticker, so a "
          "missing company removes its own events but does not shift the other tickers' statistic; it can still matter through the pooled "
          "long-minus-flat comparison. The direction of any bias is unknown (independent review Session 3, P1-5). Closing the gap needs a "
          "delisted-price source (CRSP, Norgate, EODHD or similar) added to the environment. <!-- text-only -->", ""]
    with open(os.path.join(RESULTS, "delisted_gap_2026-11-04.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    with open(os.path.join(RESULTS, "delisted_gap_2026-11-04.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=os.path.join(ROOT, "backtest", "snapshots", "2026-11-04-pit-r1"))
    ap.add_argument("--h1-csv", default=os.path.join(RESULTS, "walkforward_2026-11-04-pit_phaseD.csv"))
    a = ap.parse_args()
    r = run(a.snapshot, a.h1_csv, EdgarClient())
    write(r)
    print(f"gap companies {r['gap_companies']}; lost est {r['lost_est']} / upper {r['lost_upper']} vs H1 {r['h1_events']}")
