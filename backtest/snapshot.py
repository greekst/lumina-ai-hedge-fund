# -*- coding: utf-8 -*-
"""
backtest/snapshot.py — build a frozen, hashed data snapshot for walk-forward backtests.

Network happens ONLY here. The backtest itself reads the snapshot and never touches
the network, so reruns are byte-identical.

Sources (each file records its source):
  prices        yfinance daily OHLCV, split/dividend adjusted (auto_adjust=True)
  events        yfinance `get_earnings_dates` announcement timestamps (exchange tz)
  fundamentals  Finnhub `/stock/financials-reported` (SEC XBRL as reported) with
                `acceptedDate` — the point-in-time availability timestamp

Usage:
  python -m backtest.snapshot --id 2026-11-04 --tickers AAPL,MSFT,... --start 2021-01-01
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from typing import Dict, List

import pandas as pd

DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "JNJ", "XOM", "PG"]
BENCHMARKS = ["SPY", "^VIX"]
SNAP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")

# Concepts kept from as-reported financials (first match wins per group).
CONCEPTS = {
    "revenue": ["us-gaap_Revenues", "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap_SalesRevenueNet", "us-gaap_RevenuesNetOfInterestExpense"],
    "net_income": ["us-gaap_NetIncomeLoss", "us-gaap_NetIncomeLossAvailableToCommonStockholdersBasic",
                   "us-gaap_ProfitLoss"],
    "eps_diluted": ["us-gaap_EarningsPerShareDiluted", "us-gaap_EarningsPerShareBasicAndDiluted"],
    "equity": ["us-gaap_StockholdersEquity",
               "us-gaap_StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "diluted_shares": ["us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding",
                       "us-gaap_WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
                       "us-gaap_WeightedAverageNumberOfSharesOutstandingBasic",
                       "dei_EntityCommonStockSharesOutstanding"],
}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe(t: str) -> str:
    return t.replace("^", "_").replace(".", "_")


def fetch_prices(ticker: str, start: str, end: str) -> pd.DataFrame:
    """OHLCV split+dividend adjusted (for returns/technicals) plus `CloseSplitAdj`
    (split-adjusted only, no dividend adjustment) for valuation ratios."""
    import yfinance as yf
    for attempt in range(4):
        raw = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
        if raw is not None and not raw.empty:
            break
        time.sleep(2 ** attempt)
    factor = raw["Adj Close"] / raw["Close"]
    df = pd.DataFrame({
        "Open": raw["Open"] * factor, "High": raw["High"] * factor, "Low": raw["Low"] * factor,
        "Close": raw["Adj Close"], "Volume": raw["Volume"], "CloseSplitAdj": raw["Close"],
    })
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df.round(6)


def fetch_splits(ticker: str) -> List[Dict[str, float]]:
    import yfinance as yf
    sp = yf.Ticker(ticker).splits
    return [{"date": str(pd.Timestamp(d).date()), "ratio": float(r)} for d, r in sp.items() if float(r) > 0]


def fetch_events(ticker: str, end: str) -> List[Dict[str, str]]:
    import yfinance as yf
    ed = yf.Ticker(ticker).get_earnings_dates(limit=24)
    out = []
    for ts, row in ed.iterrows():
        ts = pd.Timestamp(ts)
        if ts.tz is not None:
            ts = ts.tz_convert("America/New_York").tz_localize(None)
        if str(ts.date()) > end or pd.isna(row.get("Reported EPS")):
            continue  # only events that had happened by the snapshot date
        out.append({"announced_at_et": ts.strftime("%Y-%m-%d %H:%M"),
                    "source": "yfinance.get_earnings_dates"})
    return sorted(out, key=lambda e: e["announced_at_et"])


def _finnhub(path: str, params: Dict[str, str]) -> Dict:
    import requests
    key = os.getenv("FINNHUB_API_KEY", "")
    if not key:
        raise RuntimeError("FINNHUB_API_KEY not set")
    for attempt in range(4):
        r = requests.get(f"https://finnhub.io/api/v1/{path}", params=dict(params, token=key), timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"finnhub {path} rate-limited")


def fetch_fundamentals(ticker: str) -> List[Dict]:
    filings = []
    for freq in ("quarterly", "annual"):
        data = _finnhub("stock/financials-reported", {"symbol": ticker, "freq": freq}).get("data", [])
        for f in data:
            rep = f.get("report", {}) or {}
            items = {}
            for section in ("ic", "bs", "cf"):
                for it in rep.get(section, []) or []:
                    items.setdefault(it.get("concept"), it.get("value"))
            vals = {}
            for name, cands in CONCEPTS.items():
                for c in cands:
                    v = items.get(c)
                    if isinstance(v, (int, float)):
                        vals[name] = float(v)
                        vals[name + "_concept"] = c
                        break
            filings.append({
                "form": f.get("form"), "start": str(f.get("startDate", ""))[:10], "end": str(f.get("endDate", ""))[:10],
                "accepted_at": str(f.get("acceptedDate", "")), "filed": str(f.get("filedDate", ""))[:10],
                "access_number": f.get("accessNumber"), **vals,
            })
    filings.sort(key=lambda x: (x["accepted_at"], x["end"], x["form"] or ""))
    return filings


def build(snapshot_id: str, tickers: List[str], start: str, end: str) -> str:
    root = os.path.join(SNAP_ROOT, snapshot_id)
    os.makedirs(os.path.join(root, "prices"), exist_ok=True)
    os.makedirs(os.path.join(root, "fundamentals"), exist_ok=True)
    events: Dict[str, List[Dict[str, str]]] = {}
    for t in tickers + BENCHMARKS:
        fetch_prices(t, start, end).to_csv(os.path.join(root, "prices", f"{_safe(t)}.csv"), float_format="%.6f")
    splits: Dict[str, List[Dict[str, float]]] = {}
    for t in tickers:
        events[t] = fetch_events(t, end)
        splits[t] = [x for x in fetch_splits(t) if x["date"] < end]
        with open(os.path.join(root, "fundamentals", f"{_safe(t)}.json"), "w", encoding="utf-8") as fh:
            json.dump({"ticker": t, "source": "finnhub /stock/financials-reported (SEC XBRL as reported)",
                       "filings": fetch_fundamentals(t)}, fh, indent=1, sort_keys=True)
        time.sleep(1.0)
    with open(os.path.join(root, "events.json"), "w", encoding="utf-8") as fh:
        json.dump(events, fh, indent=1, sort_keys=True)
    with open(os.path.join(root, "splits.json"), "w", encoding="utf-8") as fh:
        json.dump(splits, fh, indent=1, sort_keys=True)
    files = sorted(
        os.path.relpath(os.path.join(d, f), root)
        for d, _, fs in os.walk(root) for f in fs if f != "manifest.json"
    )
    manifest = {
        "snapshot_id": snapshot_id, "tickers": tickers, "benchmarks": BENCHMARKS,
        "price_start": start, "price_end_exclusive": end,
        "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": {
            "prices": "yfinance Ticker.history(auto_adjust=False): OHLC scaled to Adj Close (split+dividend adjusted); CloseSplitAdj = split-adjusted only",
            "splits": "yfinance Ticker.splits (used only to put as-reported EPS on the current share basis)",
            "events": "yfinance get_earnings_dates (announcement timestamp, America/New_York)",
            "fundamentals": "Finnhub /stock/financials-reported; PIT key = acceptedDate",
        },
        "sha256": {f: _sha256(os.path.join(root, f)) for f in files},
    }
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    return root


def verify(root: str) -> List[str]:
    """Return list of files whose hash no longer matches the manifest."""
    with open(os.path.join(root, "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    return [f for f, h in man["sha256"].items() if _sha256(os.path.join(root, f)) != h]


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a frozen walk-forward data snapshot.")
    ap.add_argument("--id", required=True, help="snapshot id, e.g. 2026-11-04")
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default=None, help="exclusive end date (default: snapshot id)")
    a = ap.parse_args()
    root = build(a.id, [t.strip().upper() for t in a.tickers.split(",") if t.strip()], a.start, a.end or a.id)
    print(f"snapshot written: {root}")


if __name__ == "__main__":
    main()
