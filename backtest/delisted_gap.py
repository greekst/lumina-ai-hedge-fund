# -*- coding: utf-8 -*-
"""
backtest/delisted_gap.py — Session 4 Phase A: quantify the delisted-company gap from data.

No delisted-price provider is reachable from this sandbox (allowed hosts: Yahoo, SEC, FRED, Hugging Face, Finnhub,
Gemini; Yahoo keeps no history for delisted tickers; Finnhub candles are 403 on this plan). Without prices these
companies cannot be ranked by market cap or given returns, so they stay out of the snapshot. This module measures
how many top-100 earnings events the gap costs, per earnings season, using EDGAR only:

  * gap companies: `find_gaps` — top 150 by dei:EntityPublicFloat among plausible filers (float <= 15x largest total
    assets, applied before ranking) in any year 2014-2025, with no current common-stock listing (revised after the
    Session 4 independent review, P1-1; Session 3's `pit_universe.gaps` is left as it was).
  * their earnings events: SEC 8-K Item 2.02 acceptance times, reduced to one per reporting period with the same
    rule the new base snapshot uses for 8-K-only events (`snapshot_pit.earnings_8k_events`).
  * "would have been top 100" (an ESTIMATE): the latest public float accepted before D (<= 460 days old) is at
    least the 100th-largest PIT market cap of the candidate pool on the float's own date (ranking rules v2).
    Public float excludes affiliate holdings, so it understates market cap (a lower bound on membership); an upper
    bound (PARTIAL: only companies a float screen can find) uses 150th-largest instead. Neither is used in any test; they size the gap only.

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


SPIKE = 2.0   # a float more than 2x BOTH neighbouring years' values is a tagging error (Discover 2022: 82.5bn between 35.5 and 29.1)


def _clean_floats(vals: List[float]) -> List[bool]:
    """Keep-mask over a company's float values in time order: drop isolated upward spikes (> 2x the previous AND the next
    distinct value). Growth (Aetna 28 -> 43 -> 42 -> 49bn) is kept; a global median would wrongly cut it."""
    keep = [True] * len(vals)
    for i, v in enumerate(vals):
        prev = next((vals[j] for j in range(i - 1, -1, -1) if vals[j] != v), None)
        nxt = next((vals[j] for j in range(i + 1, len(vals)) if vals[j] != v), None)
        if prev and nxt and v > SPIKE * prev and v > SPIKE * nxt:
            keep[i] = False
    return keep


def find_gaps(cands: Dict[str, Any], ed: EdgarClient, unranked: set, rank_n: int = 150) -> List[Dict[str, Any]]:
    """Independent review Session 4, P1-1 (replaces `pit_universe.gaps` here; that function stays as Session 3 used it):
    (c) plausibility (float <= 15x the company's largest total assets) is applied BEFORE ranking, so x1000-tagged floats
    no longer fill top-150 slots; (a) a candidate that is never ranked (`unranked`: only a preferred share listed, e.g.
    E. I. du Pont CIK 30554 via CTA-PA) counts as a gap; (d) a float that is an isolated spike, more than twice both
    neighbouring years' values, is dropped (Discover 2022). Still blind to filers without float frames (21st Century Fox) and to controlled companies
    (VMware): listed in the report, not estimated."""
    have = {c["cik"] for c in cands["candidates"]} - unranked
    assets: Dict[int, float] = {}
    for y in range(2013, 2026):
        try:
            for r in ed.get_json(f"https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/CY{y}Q4I.json")["data"]:
                assets[r["cik"]] = max(assets.get(r["cik"], 0.0), float(r["val"]))
        except Exception:  # noqa: BLE001
            pass
    per_year: Dict[int, Dict[int, Dict[str, Any]]] = {}
    for y in range(2014, 2026):
        best: Dict[int, Dict[str, Any]] = {}
        for q in (1, 2, 3, 4):
            try:
                rows = ed.get_json(f"https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/CY{y}Q{q}I.json")["data"]
            except Exception:  # noqa: BLE001
                rows = []
            for r in rows:
                a = assets.get(r["cik"])
                if not a or float(r["val"]) > 15.0 * a:
                    continue
                if r["cik"] not in best or r["val"] > best[r["cik"]]["val"]:
                    best[r["cik"]] = r
        per_year[y] = best
    years = sorted(per_year)
    spike: set = set()
    for c in {c for best in per_year.values() for c in best}:
        ys = [y for y in years if c in per_year[y]]
        for y, k_ in zip(ys, _clean_floats([float(per_year[y][c]["val"]) for y in ys])):
            if not k_:
                spike.add((c, y))
    found: Dict[int, Dict[str, Any]] = {}
    for y, best in sorted(per_year.items()):
        ok = {c: r for c, r in best.items() if (c, y) not in spike}
        for i, r in enumerate(sorted(ok.values(), key=lambda r: (-r["val"], r["cik"]))[:rank_n]):
            if r["cik"] in have:
                continue
            g = found.setdefault(r["cik"], {"cik": r["cik"], "name": r["entityName"], "years": [], "best_float_rank": i + 1,
                                            "max_public_float_usd": r["val"], "plausible": True})
            g["years"].append(y)
            g["best_float_rank"] = min(g["best_float_rank"], i + 1)
            g["max_public_float_usd"] = max(g["max_public_float_usd"], r["val"])
    return sorted(found.values(), key=lambda g: (g["best_float_rank"], g["cik"]))


def run(snapshot_root: str, h1_csv: str, ed: EdgarClient) -> Dict[str, Any]:
    snap = Snapshot.load(snapshot_root)
    with open(os.path.join(PU.PDIR, "candidates.json"), encoding="utf-8") as fh:
        cand = json.load(fh)
    exch = json.loads(PU._read_gz(os.path.join(PU.PDIR, "sec_company_tickers_exchange.json.gz")))
    unranked = {int(m["cik"]) for m in snap.universe.values() if m.get("exclude_reason", "").startswith("only listed security")}
    live = {int(r[0]) for r in exch["data"]} - unranked
    pred = {c for v in PREDECESSOR_CIKS.values() for c in v}
    gaps = [g for g in find_gaps(cand, ed, unranked) if g["cik"] not in live and g["cik"] not in pred]
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
        keep = _clean_floats([f["value"] for f in floats])
        floats = [f for f, k_ in zip(floats, keep) if k_]
        k8 = earnings_8k(b["subs"], since="2014-01-01")
        evs = earnings_8k_events(k8, periodic_filings(b["subs"]))
        n_lo = n_hi = 0
        for e in evs:
            D = decision_session(sessions, e["accepted_at_et"])
            if D is None or D < pd.Timestamp("2015-01-01") or D > pd.Timestamp("2026-09-30"):
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
         "Method (backtest/delisted_gap.py, revised after the Session 4 independent review, P1-1): gap companies are the top one hundred fifty by "
         "public float among plausible filers (float at most fifteen times the company's largest total assets; ranked after that filter) in any "
         "year, with no current common-stock listing (a company whose only listing is a preferred share, such as E. I. du Pont, counts), "
         "dropping a float value that is more than twice both neighbouring years' values (Discover's mis-tagged 2022 float); "
         "their earnings events are 8-K Item 2.02 filings reduced to one per reporting period; an event counts as lost if the latest public float "
         "known before D (at most 460 days old) is at least the 100th-largest point-in-time market cap of the candidate pool on the float's date. "
         "The float understates market cap, so this is a lower bound; using the 150th-largest gives a PARTIAL upper bound: it covers only the companies "
         "this float screen can find. Window: D in 2015-01-01..2026-09-30 "
         "(the H1 sample window). <!-- text-only -->", "",
         f"- Gap companies examined: {T(res['gap_companies'])}.",
         f"- H1 sample (Session 4 rerun, snapshot pit2): {T(n, s='wf-backtest 2026-11-04-pit2_phaseD')} events.",
         f"- Estimated lost top-100 events: {M(lo)} ({M(lo / (n + lo) if n else 0, True)} of the sample incl. them); "
         f"partial upper bound {M(hi)} ({M(hi / (n + hi) if n else 0, True)}).",
         "- Not found by a float screen, so not counted: filers without public-float frames (21st Century Fox, roughly top-hundred size "
         "2015-2019; the reviewer estimates about sixteen events) and controlled companies whose float is far below their market cap "
         "(VMware). Each lost event is also replaced in the sample by the event of a company ranked just outside the top hundred. <!-- text-only -->", "",
         "## Per company (events since 2015 with an estimated top-100 / top-150-bound float)", "",
         "| company (EDGAR name) | best float rank | 8-K earnings events since 2015 | lost, estimate | lost, partial upper bound |", "|---|---|---|---|---|"]
    for c in sorted(res["per_company"], key=lambda c: (-c.get("events_top150_float_bound", 0), c["cik"])):
        if c.get("error") or not c.get("events_top150_float_bound"):
            continue
        L.append(f"| {c['name']} | {T(c['best_float_rank'])} | {T(c['events_8k_since_2015'])} | {M(c['events_top100_est'])} | "
                 f"{M(c['events_top150_float_bound'])} |")
    errs = [c for c in res["per_company"] if c.get("error")]
    if errs:
        L += ["", "EDGAR unavailable for: " + ", ".join(f"{c['name']} ({c['error'][:40]})" for c in errs) + " <!-- text-only -->"]
    L += ["", "## Per earnings season", "", "| season | H1 events | lost, estimate | lost, partial upper bound |", "|---|---|---|---|"]
    for r in res["by_season"]:
        L.append(f"| `{r['season']}` | {T(r['h1_events'], s='wf-backtest 2026-11-04-pit2_phaseD')} | {M(r['lost_est'])} | "
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
    ap.add_argument("--snapshot", default=os.path.join(ROOT, "backtest", "snapshots", "2026-11-04-pit2"))
    ap.add_argument("--h1-csv", default=os.path.join(RESULTS, "walkforward_2026-11-04-pit2_phaseD.csv"))
    a = ap.parse_args()
    r = run(a.snapshot, a.h1_csv, EdgarClient())
    write(r)
    print(f"gap companies {r['gap_companies']}; lost est {r['lost_est']} / upper {r['lost_upper']} vs H1 {r['h1_events']}")
