# -*- coding: utf-8 -*-
"""
backtest/snapshot_sp100.py — Session 2 frozen snapshot over the S&P 100 proxy universe.

Network happens only here (cached). The snapshot has the same layout as backtest/snapshot.py
plus `universe.json` (sector + SPDR sector ETF per ticker) and `event_crosscheck.json`.

  events        SEC EDGAR 8-K Item 2.02 acceptanceDateTime (ET) — PRIMARY earnings timestamp.
                8-Ks within 45 days of the previous kept one are treated as the same event
                (pre-announcements, re-filings) and only the first is kept.
  fundamentals  SEC EDGAR companyfacts, PIT key = acceptanceDateTime (backtest/edgar.py)
  prices        yfinance daily OHLCV (split+dividend adjusted) + CloseSplitAdj; stocks, SPY, ^VIX
                and the 11 SPDR sector ETFs
  splits        yfinance (unit conversion of as-reported per-share values only)
  crosscheck    yfinance get_earnings_dates vs the 8-K time, per event (not used by the harness)

  python -m backtest.snapshot_sp100 --id 2026-11-04-sp100
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Dict, List

import pandas as pd

from backtest.edgar import EdgarClient, EdgarUnavailable, earnings_8k, fundamentals_from_companyfacts
from backtest.snapshot import SNAP_ROOT, _safe, _sha256, fetch_prices, fetch_splits
from backtest import universe as U

BENCH = ["SPY", "^VIX"] + sorted(set(U.SECTOR_ETF.values()))
CLUSTER_DAYS = 45


def yf_symbol(t: str) -> str:
    return t.replace(".", "-")


def cluster_events(k8: List[Dict[str, str]]) -> List[Dict[str, str]]:
    kept: List[Dict[str, str]] = []
    for e in k8:
        if kept and (pd.Timestamp(e["accepted_at_et"]) - pd.Timestamp(kept[-1]["accepted_at_et"])).days < CLUSTER_DAYS:
            kept[-1].setdefault("merged_accessions", []).append(e["accession"])
            continue
        kept.append(dict(e))
    return kept


def _yf_events(t: str) -> List[str]:
    import yfinance as yf
    for attempt in range(3):
        try:
            ed = yf.Ticker(yf_symbol(t)).get_earnings_dates(limit=24)
            out = []
            for ts, _row in ed.iterrows():
                ts = pd.Timestamp(ts)
                if ts.tz is not None:
                    ts = ts.tz_convert("America/New_York").tz_localize(None)
                out.append(ts.strftime("%Y-%m-%d %H:%M"))
            return sorted(out)
        except Exception:
            time.sleep(3 * (attempt + 1))
    return []


def build(snapshot_id: str, start: str, end: str, tickers: List[str] = None) -> str:
    uni = U.load()
    members = [m for m in uni["members"] if not tickers or m["ticker"] in tickers]
    root = os.path.join(SNAP_ROOT, snapshot_id)
    for sub in ("prices", "fundamentals"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    ed = EdgarClient()
    events: Dict[str, List[Dict[str, Any]]] = {}
    splits: Dict[str, List[Dict[str, float]]] = {}
    xcheck: Dict[str, Any] = {}
    problems: Dict[str, str] = {}
    for sym in BENCH:
        p = os.path.join(root, "prices", f"{_safe(sym)}.csv")
        if not os.path.exists(p):
            fetch_prices(sym, start, end).to_csv(p, float_format="%.6f")
    for m in members:
        t = m["ticker"]
        p = os.path.join(root, "prices", f"{_safe(t)}.csv")
        try:
            if not os.path.exists(p):
                fetch_prices(yf_symbol(t), start, end).to_csv(p, float_format="%.6f")
            splits[t] = [x for x in fetch_splits(yf_symbol(t)) if x["date"] < end]
        except Exception as e:  # noqa: BLE001
            problems[t] = f"prices: {type(e).__name__}"
            continue
        try:
            b = ed.bundle(t)
        except EdgarUnavailable as e:
            problems[t] = f"edgar: {e}"
            continue
        fund = fundamentals_from_companyfacts(b["facts"], b["subs"])
        k8 = [e for e in cluster_events(earnings_8k(b["subs"])) if e["accepted_at_et"][:10] < end]
        yfe = _yf_events(t)
        xcheck[t] = {"yfinance": yfe}
        if len([e for e in k8 if e["accepted_at_et"] >= "2022-01-01"]) >= 4:
            events[t] = [{"announced_at_et": e["accepted_at_et"][:16], "source": e["source"], "accession": e["accession"],
                          "merged_accessions": e.get("merged_accessions", [])} for e in k8]
        else:
            # issuer does not furnish earnings under 8-K Item 2.02 (e.g. results released with the 10-Q)
            events[t] = [{"announced_at_et": x, "source": "yfinance.get_earnings_dates (no 8-K 2.02 filed)",
                          "accession": None, "merged_accessions": []} for x in yfe if x[:10] < end]
            problems[t] = f"events from yfinance: only {len(k8)} 8-K 2.02 filings"
        with open(os.path.join(root, "fundamentals", f"{_safe(t)}.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"ticker": t, "ciks": b["ciks"], "source": "SEC EDGAR companyfacts; PIT key = acceptanceDateTime",
                       "filings": fund}, fh, indent=1, sort_keys=True)
        if not fund or min(f["accepted_at"] for f in fund) > "2022-01-01":
            problems[t] = "edgar: no periodic filing before 2022 (possible CIK change)"
        time.sleep(0.5)
    with open(os.path.join(root, "events.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(events, fh, indent=1, sort_keys=True)
    with open(os.path.join(root, "splits.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(splits, fh, indent=1, sort_keys=True)
    with open(os.path.join(root, "event_crosscheck.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(xcheck, fh, indent=1, sort_keys=True)
    ok = [m for m in members if m["ticker"] in events]
    with open(os.path.join(root, "universe.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({k: v for k, v in uni.items() if k != "members"} | {"members": ok, "excluded": problems},
                  fh, indent=1, sort_keys=True)
    files = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root)
                   for f in fs if f != "manifest.json")
    manifest = {
        "snapshot_id": snapshot_id, "tickers": [m["ticker"] for m in ok], "benchmarks": BENCH,
        "price_start": start, "price_end_exclusive": end,
        "universe": uni["label"] + "; " + uni["rule"],
        "sources": {
            "prices": "yfinance Ticker.history(auto_adjust=False): OHLC scaled to Adj Close; CloseSplitAdj = split-adjusted only",
            "splits": "yfinance Ticker.splits",
            "events": "SEC EDGAR 8-K Item 2.02 acceptanceDateTime (UTC -> America/New_York); 45-day clusters keep the first",
            "fundamentals": "SEC EDGAR companyfacts (XBRL); PIT key = submissions acceptanceDateTime",
            "universe": uni["sp500_source"] + " + " + uni["market_cap_source"],
        },
        "sha256": {f: _sha256(os.path.join(root, f)) for f in files},
    }
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(f"snapshot {root}: {len(ok)} tickers; excluded/flagged: {problems}; edgar requests {ed.n_requests}")
    return root


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2026-11-04")
    ap.add_argument("--tickers", default="")
    a = ap.parse_args()
    build(a.id, a.start, a.end, [t for t in a.tickers.split(",") if t] or None)


if __name__ == "__main__":
    main()
