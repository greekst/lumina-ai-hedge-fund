# -*- coding: utf-8 -*-
"""
backtest/edgar.py — SEC EDGAR as the primary point-in-time source.

  * fundamentals: XBRL `companyfacts` (data.sec.gov/api/xbrl/companyfacts/CIK##########.json)
  * availability timestamp: the filing's `acceptanceDateTime` from the submissions index
    (data.sec.gov/submissions/CIK##########.json). companyfacts only carries the `filed` *date*;
    we join on the accession number to get the exact acceptance time.
  * earnings timestamp: acceptance time of 8-K filings whose `items` include 2.02
    ("Results of Operations and Financial Condition").

Fair access (https://www.sec.gov/os/accessing-edgar-data): every request declares the
User-Agent from the `SEC_USER_AGENT` environment variable (never written anywhere) and the
client is throttled to <= 5 requests/second (SEC limit: 10). Every response is cached on
disk (git-ignored) so reruns never refetch.

Timestamps: EDGAR `acceptanceDateTime` is UTC ("...Z"); verified against AAPL 8-Ks
(21:30Z in January = 20:30Z in July = 16:30 America/New_York). We store naive
America/New_York strings, the convention used by the rest of the snapshot.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

import pandas as pd

CACHE_DIR = os.getenv("LUMINA_SEC_CACHE",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "edgar"))
MIN_INTERVAL_S = 0.2  # 5 requests/second
SOURCE = "SEC EDGAR companyfacts (XBRL) + submissions acceptanceDateTime"

# Same concept priority as the Finnhub snapshot (backtest/snapshot.py) so values are comparable.
CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet", "RevenuesNetOfInterestExpense"],
    "net_income": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding",
                       "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
                       "WeightedAverageNumberOfSharesOutstandingBasic"],
}
INSTANT = {"equity"}
PERIODIC_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A", "10-KT", "10-QT"}


# Successor registrants: the SEC ticker map points at the *current* CIK; history lives under the
# predecessor. Facts and filings of all listed CIKs are merged (oldest first). Verified by hand.
PREDECESSOR_CIKS: Dict[str, List[int]] = {
    "XOM": [34088],     # Exxon Mobil Corp -> ExxonMobil Holdings Corp (holding-company reorganisation, 2026-07)
    "BLK": [1364742],   # BlackRock, Inc. (old; now "BlackRock Finance, Inc.") -> new BlackRock, Inc. (2024-10, GIP deal)
}
# Upper bound on the YTD length (days) for each fiscal period, so trailing-twelve-month columns
# that some filers (e.g. AMZN cash-flow/NI) add to 10-Qs are not mistaken for year-to-date values.
FP_MAX_DAYS = {"Q1": 105, "Q2": 196, "Q3": 287, "Q4": 380, "FY": 380}


class EdgarUnavailable(RuntimeError):
    pass


class EdgarClient:
    _lock = threading.Lock()
    _last = 0.0

    def __init__(self, user_agent: Optional[str] = None, cache_dir: str = CACHE_DIR, offline: bool = False):
        self.user_agent = user_agent if user_agent is not None else os.getenv("SEC_USER_AGENT", "")
        self.cache_dir = cache_dir
        self.offline = offline
        self.n_requests = 0
        self.n_cache_hits = 0
        os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------------ http + cache
    def _cache_path(self, url: str) -> str:
        return os.path.join(self.cache_dir, hashlib.sha256(url.encode()).hexdigest()[:32] + ".json.gz")

    def get_json(self, url: str) -> Any:
        path = self._cache_path(url)
        if os.path.exists(path):
            self.n_cache_hits += 1
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        if self.offline:
            raise EdgarUnavailable(f"offline and not cached: {url}")
        if not self.user_agent:
            raise EdgarUnavailable("SEC_USER_AGENT not set — SEC requires a declared contact User-Agent")
        import requests
        for attempt in range(5):
            with EdgarClient._lock:
                wait = MIN_INTERVAL_S - (time.monotonic() - EdgarClient._last)
                if wait > 0:
                    time.sleep(wait)
                EdgarClient._last = time.monotonic()
            r = requests.get(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
                             timeout=60)
            self.n_requests += 1
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 404:
                raise EdgarUnavailable(f"404 {url}")
            if r.status_code != 200:
                raise EdgarUnavailable(f"HTTP {r.status_code} {url}")
            data = r.json()
            tmp = path + ".tmp"
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
            return data
        raise EdgarUnavailable(f"rate-limited: {url}")

    # ------------------------------------------------------------------ endpoints
    def ticker_map(self) -> Dict[str, int]:
        d = self.get_json("https://www.sec.gov/files/company_tickers.json")
        return {v["ticker"].upper(): int(v["cik_str"]) for v in d.values()}

    def cik(self, ticker: str) -> int:
        m = self.ticker_map()
        t = ticker.upper()
        for cand in (t, t.replace(".", "-"), t.replace("-", ".")):
            if cand in m:
                return m[cand]
        raise EdgarUnavailable(f"no CIK for {ticker}")

    def ciks(self, ticker: str) -> List[int]:
        return PREDECESSOR_CIKS.get(ticker.upper(), []) + [self.cik(ticker)]

    def bundle(self, ticker: str) -> Dict[str, Any]:
        """Merged companyfacts (us-gaap) + submissions across predecessor/successor CIKs."""
        gaap: Dict[str, Any] = {}
        subs: List[Dict[str, Any]] = []
        for c in self.ciks(ticker):
            try:
                f = self.companyfacts(c)
            except EdgarUnavailable:
                f = {}
            for concept, node in ((f.get("facts") or {}).get("us-gaap", {}) or {}).items():
                dst = gaap.setdefault(concept, {"units": {}})
                for unit, rows in (node.get("units") or {}).items():
                    dst["units"].setdefault(unit, []).extend(rows)
            subs += self.submissions(c)
        return {"facts": {"facts": {"us-gaap": gaap}}, "subs": subs, "ciks": self.ciks(ticker)}

    def bundle_ciks(self, ciks: List[int], since: str = "2019-01-01") -> Dict[str, Any]:
        """Like `bundle`, for explicit CIKs (oldest predecessor first). Keeps the dei taxonomy too."""
        tax: Dict[str, Dict[str, Any]] = {"us-gaap": {}, "dei": {}}
        subs: List[Dict[str, Any]] = []
        for c in ciks:
            try:
                f = self.companyfacts(c)
            except EdgarUnavailable:
                f = {}
            for t in ("us-gaap", "dei"):
                for concept, node in ((f.get("facts") or {}).get(t, {}) or {}).items():
                    dst = tax[t].setdefault(concept, {"units": {}})
                    for unit, rows in (node.get("units") or {}).items():
                        dst["units"].setdefault(unit, []).extend(rows)
            subs += self.submissions(c, since=since)
        return {"facts": {"facts": tax}, "subs": subs, "ciks": list(ciks)}

    def companyfacts(self, cik: int) -> Dict[str, Any]:
        return self.get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")

    def submissions(self, cik: int, since: str = "2019-01-01") -> List[Dict[str, Any]]:
        """All filings (recent + paged history back to `since`) as a list of dicts."""
        d = self.get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        blocks = [d["filings"]["recent"]]
        for f in d["filings"].get("files", []) or []:
            if f.get("filingTo", "") >= since:
                blocks.append(self.get_json(f"https://data.sec.gov/submissions/{f['name']}"))
        out = []
        for b in blocks:
            keys = list(b.keys())
            for i in range(len(b["accessionNumber"])):
                out.append({k: b[k][i] for k in keys})
        return out


def to_et(acceptance_utc: str) -> str:
    """'2025-01-30T21:30:23.000Z' -> '2025-01-30 16:30:23' (naive America/New_York)."""
    ts = pd.Timestamp(acceptance_utc)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("America/New_York").tz_localize(None).strftime("%Y-%m-%d %H:%M:%S")


def acceptance_index(subs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {s["accessionNumber"]: s for s in subs}


def earnings_8k(subs: List[Dict[str, Any]], since: str = "2019-01-01") -> List[Dict[str, str]]:
    """8-K (and 8-K/A excluded) filings with Item 2.02, sorted by acceptance."""
    out = []
    for s in subs:
        if s.get("form") != "8-K" or "2.02" not in str(s.get("items", "")).split(","):
            continue
        if s["filingDate"] < since:
            continue
        out.append({"accepted_at_et": to_et(s["acceptanceDateTime"]), "accession": s["accessionNumber"],
                    "items": s["items"], "filing_date": s["filingDate"], "source": "SEC EDGAR 8-K Item 2.02 acceptanceDateTime"})
    return sorted(out, key=lambda e: e["accepted_at_et"])


PRIOR_KEYS = ("revenue", "net_income")   # flow items for which the filing's own prior-year comparative is kept


def fundamentals_from_companyfacts(facts: Dict[str, Any], subs: List[Dict[str, Any]],
                                   since: str = "2019-01-01", comparatives: bool = False) -> List[Dict[str, Any]]:
    """One record per periodic filing (10-Q/10-K, incl. amendments) in the same shape as the
    Finnhub snapshot: the filing's *current* period, YTD for flow items (longest duration ending
    at the period end), instant at the period end for equity. PIT key = acceptance time (ET)."""
    acc = acceptance_index(subs)
    gaap = (facts.get("facts") or {}).get("us-gaap", {}) or {}
    # accn -> concept -> list of facts
    by_accn: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for name, cands in CONCEPTS.items():
        for c in cands:
            node = gaap.get(c)
            if not node:
                continue
            for unit, rows in (node.get("units") or {}).items():
                for r in rows:
                    if r.get("form") not in PERIODIC_FORMS or r.get("filed", "") < since:
                        continue
                    by_accn.setdefault(r["accn"], {}).setdefault(c, []).append(dict(r, unit=unit))
    records = []
    for accn, cmap in by_accn.items():
        sub = acc.get(accn)
        if not sub:
            continue  # cannot timestamp precisely -> not usable point-in-time
        durs = [r for name in ("revenue", "net_income") for c in CONCEPTS[name] for r in cmap.get(c, []) if r.get("start")]
        if not durs:
            continue
        period_end = max(r["end"] for r in durs)
        fp = next((r.get("fp") for r in durs if r["end"] == period_end and r.get("fp")), "FY")
        cap = FP_MAX_DAYS.get(fp, 380)
        ok = [r for r in durs if r["end"] == period_end
              and (pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days <= cap]
        if not ok:
            continue
        ytd_start = min(r["start"] for r in ok)
        rec: Dict[str, Any] = {
            "form": sub.get("form"), "start": ytd_start, "end": period_end,
            "accepted_at": to_et(sub["acceptanceDateTime"]), "filed": sub.get("filingDate"),
            "access_number": accn, "fp": fp, "source": SOURCE,
        }
        for name, cands in CONCEPTS.items():
            for c in cands:
                rows = cmap.get(c, [])
                if name in INSTANT:
                    hit = [r for r in rows if r["end"] == period_end and not r.get("start")]
                else:
                    hit = [r for r in rows if r["end"] == period_end and r.get("start") == ytd_start]
                if hit:
                    rec[name] = float(hit[-1]["val"])
                    rec[name + "_concept"] = "us-gaap_" + c
                    if comparatives and name in PRIOR_KEYS:
                        # Review P1-5: the prior-year comparative of the SAME length reported inside THIS filing
                        # (restated for spin-offs/discontinued ops/accounting changes; same acceptance time).
                        cur_len = (pd.Timestamp(period_end) - pd.Timestamp(ytd_start)).days
                        tgt = pd.Timestamp(period_end) - pd.DateOffset(years=1)
                        pri = [r for r in rows if r.get("start") and r["end"] < period_end
                               and abs((pd.Timestamp(r["end"]) - tgt).days) <= 10
                               and abs((pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days - cur_len) <= 20]
                        if pri:
                            rec[name + "_prior"] = float(pri[-1]["val"])
                    break
        records.append(rec)
    records.sort(key=lambda x: (x["accepted_at"], x["end"], x["form"] or ""))
    return records
