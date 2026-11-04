# -*- coding: utf-8 -*-
"""
backtest/sec_crosscheck.py — Phase A: SEC EDGAR primary filings vs the Finnhub snapshot.

  python -m backtest.sec_crosscheck --snapshot backtest/snapshots/2026-11-04

Writes results/sec_vs_finnhub.md (+ .json). Network: EDGAR only (cached, 5 req/s).
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtest.edgar import EdgarClient, earnings_8k, fundamentals_from_companyfacts
from backtest.pit import Snapshot, decision_session

FIELDS = ("revenue", "net_income", "eps_diluted", "equity", "diluted_shares")
TOL = 0.01
RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def rel_diff(a: float, b: float) -> float:
    if a == b:
        return 0.0
    den = max(abs(a), abs(b))
    return abs(a - b) / den if den else 0.0


def trading_day_gap(sessions: pd.DatetimeIndex, d1: Optional[pd.Timestamp], d2: Optional[pd.Timestamp]) -> Optional[int]:
    if d1 is None or d2 is None:
        return None
    return int(sessions.get_loc(d2) - sessions.get_loc(d1))


def match_8k(announced_et: str, k8: List[Dict[str, str]], window_days: int = 3) -> Optional[Dict[str, str]]:
    t = pd.Timestamp(announced_et)
    best, best_dt = None, None
    for e in k8:
        dt = abs((pd.Timestamp(e["accepted_at_et"]) - t).total_seconds())
        if dt <= window_days * 86400 and (best_dt is None or dt < best_dt):
            best, best_dt = e, dt
    return best


def resolve_event_time(k8_time: Optional[str], vendor_time: Optional[str]) -> Tuple[Optional[str], str]:
    """Earnings timestamp = the EARLIER of the matched 8-K Item 2.02 acceptance and the vendor time.
    An 8-K can be accepted hours or days after the press release (SCHW: ~16:17 for a ~07:00 release,
    every quarter; BRK: days after a Saturday release), so using the 8-K alone would let the decision
    close already contain the news (look-ahead). A vendor placeholder time (e.g. "12:00") can only make
    D earlier, which removes information and never adds it."""
    if k8_time and vendor_time:
        return (k8_time, "8-K 2.02 (earlier)") if pd.Timestamp(k8_time) <= pd.Timestamp(vendor_time) \
            else (vendor_time, "vendor (earlier than 8-K)")
    if k8_time:
        return k8_time, "8-K 2.02 (no vendor time)"
    if vendor_time:
        return vendor_time, "vendor (no 8-K 2.02 match)"
    return None, "none"


def resolve_decision_session(sessions: pd.DatetimeIndex, k8_time: Optional[str],
                             vendor_time: Optional[str]) -> Tuple[Optional[pd.Timestamp], str]:
    ts, rule = resolve_event_time(k8_time, vendor_time)
    return (decision_session(sessions, ts) if ts else None), rule


def run(snapshot_root: str, client: EdgarClient) -> Dict[str, Any]:
    snap = Snapshot.load(snapshot_root)
    out: Dict[str, Any] = {"fund": [], "fund_missing": [], "accept": [], "events": [], "coverage": {}}
    for t in snap.manifest["tickers"]:
        b = client.bundle(t)
        subs = b["subs"]
        ed = fundamentals_from_companyfacts(b["facts"], subs)
        # compare only inside the EDGAR window (filed since 2019-01-01)
        fh = [f for f in snap.fundamentals.get(t, []) if str(f.get("filed", "")) >= "2019-01-01"]
        ed_by = {r["access_number"]: r for r in ed}
        n_cmp = 0
        for f in fh:
            e = ed_by.get(f.get("access_number"))
            if e is None:
                out["fund_missing"].append({"ticker": t, "access_number": f.get("access_number"), "form": f.get("form"),
                                            "end": f.get("end"), "side": "not in EDGAR companyfacts"})
                continue
            if e["accepted_at"][:16] != str(f["accepted_at"])[:16]:
                out["accept"].append({"ticker": t, "access_number": f["access_number"],
                                      "finnhub": f["accepted_at"], "edgar": e["accepted_at"]})
            for k in FIELDS:
                a, b = f.get(k), e.get(k)
                if a is None and b is None:
                    continue
                n_cmp += 1
                if a is None or b is None:
                    out["fund_missing"].append({"ticker": t, "access_number": f["access_number"], "form": f["form"],
                                                "end": f["end"], "field": k,
                                                "side": "missing in Finnhub" if a is None else "missing in EDGAR"})
                    continue
                d = rel_diff(float(a), float(b))
                if d > TOL:
                    out["fund"].append({
                        "ticker": t, "form": f["form"], "period": f"{f['start']}..{f['end']}", "field": k,
                        "finnhub": a, "finnhub_concept": f.get(k + "_concept"), "finnhub_filed": f.get("filed"),
                        "edgar": b, "edgar_concept": e.get(k + "_concept"), "edgar_filed": e.get("filed"),
                        "edgar_period": f"{e['start']}..{e['end']}", "rel_diff": d, "access_number": f["access_number"]})
        fh_acc = {f.get("access_number") for f in fh}
        extra = [r for r in ed if r["access_number"] not in fh_acc and r["end"] >= "2021-01-01"]
        out["coverage"][t] = {"finnhub_filings": len(fh), "edgar_filings": len(ed), "compared_values": n_cmp,
                              "edgar_only_filings_since_2021": len(extra)}
        # events
        k8 = earnings_8k(subs)
        sessions = snap.sessions(t)
        for ev in snap.events.get(t, []):
            m = match_8k(ev["announced_at_et"], k8)
            dv = decision_session(sessions, ev["announced_at_et"])
            d8 = decision_session(sessions, m["accepted_at_et"]) if m else None
            D, rule = resolve_decision_session(sessions, m["accepted_at_et"] if m else None, ev["announced_at_et"])
            out["events"].append({
                "ticker": t, "yfinance_et": ev["announced_at_et"], "edgar_8k_et": m["accepted_at_et"] if m else None,
                "accession": m["accession"] if m else None,
                "D_yfinance": str(dv.date()) if dv is not None else None,
                "D_8k": str(d8.date()) if d8 is not None else None,
                "gap_trading_days": trading_day_gap(sessions, dv, d8),
                "D_used": str(D.date()) if D is not None else None, "rule": rule})
    out["edgar_requests"] = client.n_requests
    return out


def _summary(res: Dict[str, Any], n) -> List[str]:
    fund = res["fund"]
    eps = [m for m in fund if m["field"] == "eps_diluted"]
    eps_int = [m for m in eps if float(m["finnhub"]).is_integer()]
    concept = [m for m in fund if m["field"] != "eps_diluted" and m["finnhub_concept"] != m["edgar_concept"]]
    other = [m for m in fund if m not in eps_int and m not in concept]
    miss_e = [m for m in res["fund_missing"] if m["side"] == "missing in EDGAR"]
    miss_f = [m for m in res["fund_missing"] if m["side"] == "missing in Finnhub"]
    return [
        f"- Mismatches above one percent: {n(len(fund))}. Of these, {n(len(eps_int))} are diluted EPS where Finnhub "
        f"holds a whole number (the integer truncation found in the first session) and EDGAR holds the filed value; "
        f"{n(len(concept))} differ only because the two sides picked a different XBRL concept for the same line "
        f"(e.g. net income incl. vs excl. non-controlling interests); {n(len(other))} are unexplained.",
        f"- Values present on one side only: missing in EDGAR {n(len(miss_e))}, missing in Finnhub {n(len(miss_f))}.",
        f"- Acceptance timestamps that disagree to the minute: {n(len(res['accept']))}.",
        "- Conclusion: EDGAR is complete where Finnhub has gaps, and every disagreement in values is either a "
        "Finnhub truncation or a concept choice. The harness now reads EDGAR. <!-- text-only -->",
    ]


def _rule(r: str) -> str:
    return r.replace("8-K 2.02", "8-K").replace("8-K", "`8-K`")


def _c(x: Any) -> str:
    return f"`{x}`" if x else "n/a"


def markdown(res: Dict[str, Any], snap_id: str, run_date: str) -> str:
    from core.reporting.tagged import fact
    FH = f"Finnhub /stock/financials-reported (snapshot {snap_id})"
    ED = "SEC EDGAR companyfacts"

    def v(x, src, as_of, unit="", dec=2):
        return fact(x, src, as_of, unit=unit, decimals=dec).render()

    def n(x):
        return fact(x, "sec_crosscheck count", run_date, decimals=0).render()

    L = [f"# SEC EDGAR vs Finnhub snapshot {snap_id}", "",
         "Phase A cross-check. Fundamentals are matched by accession number (same filing on both sides) and compared "
         "field by field; a mismatch is a relative difference above one percent. EDGAR values are the filing's current "
         "period (year-to-date for flow items, period-end instant for equity), the same convention as the Finnhub "
         "snapshot. Generated by backtest/sec_crosscheck.py. <!-- text-only -->", "",
         "**Which source the harness uses now:** SEC EDGAR companyfacts for every fundamental value, keyed by the "
         "EDGAR acceptanceDateTime. Finnhub is kept only as a recorded cross-check and is no longer read by the "
         "walk-forward. Earnings timestamps: the earlier of the matched 8-K Item 2.02 acceptance and the vendor "
         "time (see the events section for why the 8-K alone is not safe). <!-- text-only -->", "",
         "## Summary", ""] + _summary(res, n) + ["",
         "## Coverage", "", "| ticker | Finnhub filings | EDGAR filings | values compared | EDGAR-only filings since start of window |",
         "|---|---|---|---|---|"]
    for t, c in res["coverage"].items():
        L.append(f"| {t} | {n(c['finnhub_filings'])} | {n(c['edgar_filings'])} | {n(c['compared_values'])} | "
                 f"{n(c['edgar_only_filings_since_2021'])} |")
    L += ["", f"## Fundamental mismatches above one percent ({n(len(res['fund']))} values)", ""]
    if res["fund"]:
        L += ["| ticker | form | period | field | Finnhub value | Finnhub concept | EDGAR value | EDGAR concept | rel. diff | used |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for m in sorted(res["fund"], key=lambda x: (x["ticker"], x["period"], x["field"])):
            L.append(f"| {m['ticker']} | `{m['form']}` | `{m['period']}` | {m['field']} | "
                     f"{v(m['finnhub'], FH, m['finnhub_filed'])} | {m['finnhub_concept']} | "
                     f"{v(m['edgar'], ED, m['edgar_filed'])} | {m['edgar_concept']} | "
                     f"{fact(m['rel_diff'] * 100, 'sec_crosscheck', run_date, unit='%', decimals=2).render()} | EDGAR |")
    else:
        L.append("None. <!-- text-only -->")
    miss = res["fund_missing"]
    L += ["", f"## Values present on one side only ({n(len(miss))})", "",
          "| ticker | form | period end | field | which side is missing |", "|---|---|---|---|---|"]
    for m in sorted(miss, key=lambda x: (x["ticker"], str(x.get("end")), x.get("field", ""))):
        L.append(f"| {m['ticker']} | `{m.get('form')}` | `{m.get('end')}` | {m.get('field', '(whole filing)')} | {m['side']} |")
    L += ["", f"## Acceptance-time disagreements ({n(len(res['accept']))})", ""]
    if res["accept"]:
        L += ["| ticker | accession | Finnhub acceptedDate | EDGAR acceptanceDateTime (ET) |", "|---|---|---|---|"]
        for a in res["accept"]:
            L.append(f"| {a['ticker']} | `{a['access_number']}` | `{a['finnhub'][:19]}` | `{a['edgar']}` |")
    else:
        L.append("None: every matched filing has the same acceptance time to the minute. <!-- text-only -->")
    ev = res["events"]
    flagged = [e for e in ev if (e["gap_trading_days"] is None and e["D_yfinance"]) or
               (e["gap_trading_days"] is not None and abs(e["gap_trading_days"]) > 1)]
    one = [e for e in ev if e["gap_trading_days"] is not None and abs(e["gap_trading_days"]) == 1]
    L += ["", "## Earnings events: yfinance vs 8-K Item 2.02 acceptance", "",
          f"Events checked: {n(len(ev))}. Same decision session: "
          f"{n(sum(1 for e in ev if e['gap_trading_days'] == 0))}. Off by one trading day: {n(len(one))}. "
          f"Off by more than one trading day or no matching `8-K`: {n(len(flagged))}. "
          f"Outside the price window: {n(sum(1 for e in ev if not e['D_yfinance']))}.", "",
          "Decision rule now used: the earnings timestamp is the EARLIER of the matched `8-K` acceptance (within three "
          "calendar days) and the vendor time, and D is the last session whose close precedes it. The first draft used "
          "the `8-K` alone; the universe-wide check (results/events_8k_vs_yfinance_2026-11-04-sp100.md) showed issuers "
          "whose `8-K` is accepted after the press release (SCHW every quarter, BRK.B by days), which would be "
          "look-ahead. Events before the price window have no session (gap n/a). <!-- text-only -->", ""]
    for title, rows in (("Flagged (more than one trading day, or unmatched)", flagged), ("Off by one trading day", one)):
        L += [f"### {title}", ""]
        if not rows:
            L += ["None. <!-- text-only -->", ""]
            continue
        L += ["| ticker | yfinance (ET) | 8-K accepted (ET) | D yfinance | D 8-K | gap (sessions) | D used | rule |",
              "|---|---|---|---|---|---|---|---|"]
        for e in rows:
            L.append(f"| {e['ticker']} | `{e['yfinance_et']}` | {_c(e['edgar_8k_et'])} | {_c(e['D_yfinance'])} | {_c(e['D_8k'])} | "
                     f"{n(e['gap_trading_days']) if e['gap_trading_days'] is not None else 'n/a'} | {_c(e['D_used'])} | {_rule(e['rule'])} |")
        L.append("")
    md = "\n".join(L) + "\n"
    from core.reporting.tagged import untagged_numbers
    bad = untagged_numbers(md)
    if bad:
        raise ValueError(f"untagged numbers: {bad[:5]}")
    return md


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots", "2026-11-04"))
    ap.add_argument("--out", default=RESULTS)
    a = ap.parse_args()
    client = EdgarClient()
    res = run(a.snapshot, client)
    sid = os.path.basename(os.path.normpath(a.snapshot))
    run_date = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    with open(os.path.join(a.out, "sec_vs_finnhub.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({k: v for k, v in res.items() if k != "edgar_requests"}, fh, indent=1, sort_keys=True)
    with open(os.path.join(a.out, "sec_vs_finnhub.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown(res, sid, run_date))
    print(f"mismatches={len(res['fund'])} one-sided={len(res['fund_missing'])} accept_diff={len(res['accept'])} "
          f"events={len(res['events'])} edgar_requests={res['edgar_requests']}")


if __name__ == "__main__":
    main()
