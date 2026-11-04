# -*- coding: utf-8 -*-
"""
backtest/universe.py — Session 2 universe: an S&P 100 *proxy*.

Why a proxy: the official S&P 100 constituent list could not be retrieved from this sandbox on
2026-11-04 (en.wikipedia.org, spglobal.com, ssga.com and ishares.com refused by the network policy;
Finnhub /index/constituents and /etf/holdings return 403 on this plan; Yahoo index components 401;
Bright Data inactive). See LOG.md.

Rule (deterministic, documented):
  1. S&P 500 constituents with GICS sector and CIK from the `datasets/s-and-p-500-companies`
     GitHub dataset (data/constituents.csv, itself derived from Wikipedia's S&P 500 table),
     fetched 2026-11-04; the raw file and its sha256 are frozen in backtest/universe/.
  2. Market capitalisation from Finnhub /stock/profile2 (`marketCapitalization`, USD millions)
     on 2026-11-04.
  3. One share class per CIK (keep the larger listing, e.g. GOOGL over GOOG).
  4. The 100 largest by market cap.

Known bias: this is today's list applied to 2023-2026 events, i.e. survivorship-biased in the same
way a current-constituents S&P 100 would be. Reported as such.

  python -m backtest.universe --fetch     # network: Finnhub (cached), writes backtest/universe/
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from typing import Dict, List

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
UDIR = os.path.join(HERE, "universe")
CACHE = os.path.join(HERE, "cache", "finnhub_profile")
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
AS_OF = "2026-11-04"

SECTOR_ETF = {
    "Information Technology": "XLK", "Financials": "XLF", "Health Care": "XLV", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Energy": "XLE", "Industrials": "XLI", "Materials": "XLB", "Utilities": "XLU",
    "Real Estate": "XLRE", "Communication Services": "XLC",
}


def _profile(sym: str) -> Dict:
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, sym.replace(".", "_") + ".json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    key = os.getenv("FINNHUB_API_KEY", "")
    for attempt in range(5):
        r = requests.get("https://finnhub.io/api/v1/stock/profile2", params={"symbol": sym, "token": key}, timeout=30)
        time.sleep(1.1)  # free tier: 60/min
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        d = r.json()
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        return d
    raise RuntimeError(f"finnhub profile2 rate-limited: {sym}")


def fetch() -> List[Dict]:
    os.makedirs(UDIR, exist_ok=True)
    raw = requests.get(SP500_URL, timeout=60).content
    with open(os.path.join(UDIR, "sp500_constituents.csv"), "wb") as fh:
        fh.write(raw)
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    out = []
    for r in rows:
        sym = r["Symbol"].strip()
        prof = _profile(sym)  # Finnhub uses the dotted class form (BRK.B)
        out.append({"ticker": sym, "name": r["Security"], "sector": r["GICS Sector"], "cik": int(r["CIK"]),
                    "market_cap_musd": prof.get("marketCapitalization")})
    best: Dict[int, Dict] = {}
    for r in out:
        if r["market_cap_musd"] is None:
            continue
        if r["cik"] not in best or r["market_cap_musd"] > best[r["cik"]]["market_cap_musd"]:
            best[r["cik"]] = r
    top = sorted(best.values(), key=lambda r: (-r["market_cap_musd"], r["ticker"]))[:100]
    no_cap = sorted(r["ticker"] for r in out if r["market_cap_musd"] is None)
    meta = {
        "as_of": AS_OF, "rule": "100 largest S&P 500 members by Finnhub marketCapitalization, one share class per CIK",
        "label": "S&P 100 PROXY (official list unreachable from sandbox)",
        "sp500_source": SP500_URL, "sp500_sha256": hashlib.sha256(raw).hexdigest(), "sp500_rows": len(rows),
        "market_cap_source": f"Finnhub /stock/profile2 marketCapitalization, fetched {AS_OF}",
        "no_market_cap": no_cap, "sector_etf": SECTOR_ETF,
        "members": [dict(r, sector_etf=SECTOR_ETF[r["sector"]]) for r in sorted(top, key=lambda r: r["ticker"])],
    }
    with open(os.path.join(UDIR, f"sp100_proxy_{AS_OF}.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=1, sort_keys=True)
    return meta["members"]


def load(as_of: str = AS_OF) -> Dict:
    with open(os.path.join(UDIR, f"sp100_proxy_{as_of}.json"), encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        m = fetch()
        print(len(m), "members")
