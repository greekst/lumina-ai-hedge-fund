# -*- coding: utf-8 -*-
"""
backtest/snapshot_pit.py — Session 3 frozen snapshot over the point-in-time candidate pool.

Same layout as backtest/snapshot_sp100.py, plus:
  shares/<T>.json       PIT share counts (backtest/pit_universe.shares_series), keyed by acceptanceDateTime
  universe.json         every candidate (not only today's top 100) with CIK(s), sector, sector ETF and seed
  prices/*.csv.gz       gzipped (deterministic, mtime 0) to keep the repository small
  fundamentals/*.json.gz  incl. the prior-year comparative reported in the same filing (review P1-5)

Membership is NOT stored: the harness decides it from these data at each D-1 (rank <= 100), so the
poisoned-future tests cover it.

Events: yfinance earnings dates (limit 60, back to ~2011) matched to SEC EDGAR 8-K Item 2.02 (+-3 days);
timestamp = the earlier of the two, plus the issuer-convention fix from the Session 2 review (P0-1).

  python -m backtest.snapshot_pit --id 2026-11-04-pit
"""

from __future__ import annotations

import argparse
import re
import gzip
import json
import os
import time
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from backtest import pit_universe as PU
from backtest.edgar import EdgarClient, EdgarUnavailable, earnings_8k, fundamentals_from_companyfacts
from backtest.sec_crosscheck import apply_issuer_convention, match_8k, resolve_event_time
from backtest.snapshot import SNAP_ROOT, _safe, _sha256, fetch_prices, fetch_splits
from backtest.universe import SECTOR_ETF

BENCH = ["SPY", "^VIX"] + sorted(set(SECTOR_ETF.values()))
EDGAR_SINCE = "2012-01-01"
CACHE_YF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "yf_pit")

# Successor registrants (same company, new CIK); history lives under the predecessor. Verified by hand
# against EDGAR (company names/filing histories) — see LOG.md Session 3. Merges of two operating companies
# (e.g. Praxair + Linde AG) are NOT treated as the same company.
PREDECESSOR_CIKS: Dict[str, List[int]] = {
    "XOM": [34088],        # Exxon Mobil Corp -> ExxonMobil Holdings Corp (2026-07)
    "BLK": [1364742],      # BlackRock (old) -> new BlackRock, Inc. (2024-10)
    "AVGO": [1441634, 1649338],  # Avago Technologies -> Broadcom Ltd (2016) -> Broadcom Inc (2018)
    "DIS": [1001039],      # TWDC Enterprises 18 (old Walt Disney Co) -> The Walt Disney Company (2019)
    "CI": [701221],        # Cigna Corp (old) -> Cigna Group holding company (2018, Express Scripts deal)
    "MDT": [64670],        # Medtronic, Inc. -> Medtronic plc (2015, Covidien)
    "GOOGL": [1288776],    # Google Inc. -> Alphabet Inc. (2015-10 holding-company reorganisation)
    "MRVL": [1058057],     # Marvell Technology Group Ltd (Bermuda) -> Marvell Technology, Inc. (Delaware, 2021)
}

# GICS sector for candidates not in the current S&P 500 file (which gives GICS directly), by SIC code.
def sic_sector(sic: int) -> str:
    s = int(sic or 0)
    if s in (1311, 1381, 1382, 1389, 2911, 4922, 4923, 5171, 5172) or 2900 <= s <= 2999:
        return "Energy"
    if 1000 <= s < 1500 or 2400 <= s < 2500 or 2600 <= s < 2700 or 2800 <= s < 2830 or 2860 <= s < 2900 \
            or 3000 <= s < 3400:
        return "Materials"
    if 2830 <= s < 2837 or 3841 <= s <= 3851 or 8000 <= s < 8100 or s in (5122, 8731):
        return "Health Care"
    if 2000 <= s < 2200 or 2840 <= s <= 2844 or s in (5141, 5411, 5331, 5912, 5399):
        return "Consumer Staples"
    if 3570 <= s < 3580 or 3660 <= s < 3700 or 3820 <= s < 3830 or s in (3861, 7371, 7372, 7373, 7374, 7379):
        return "Information Technology"
    if 4800 <= s < 4900 or 2700 <= s < 2800 or s in (7370, 7812, 7819, 7822):
        return "Communication Services"
    if 4900 <= s < 5000:
        return "Utilities"
    if s in (6798,) or 6500 <= s < 6600:
        return "Real Estate"
    if 6000 <= s < 6800:
        return "Financials"
    if 2200 <= s < 2400 or 2500 <= s < 2600 or 3630 <= s < 3640 or 3710 <= s <= 3716 or 3900 <= s < 4000 \
            or 5200 <= s < 6000 or 7000 <= s < 7100 or 7900 <= s < 8000 or s in (3011, 3751, 3942, 3944, 7011):
        return "Consumer Discretionary"
    return "Industrials"


# Not common stock of an operating company: never ranked (kept in the snapshot for transparency).
EXCLUDE_SIC = {6221: "commodity/crypto trust (SIC 6221), not common stock"}

# Hand overrides where SIC maps poorly to today's GICS (checked against the company's line of business).
SECTOR_OVERRIDE: Dict[str, str] = {}


def _gz_json(path: str, obj: Any) -> None:
    raw = json.dumps(obj, indent=1, sort_keys=True).encode("utf-8")
    with open(path, "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
            gz.write(raw)


def _gz_csv(df: pd.DataFrame, path: str) -> None:
    raw = df.to_csv(float_format="%.6f", lineterminator="\n").encode("utf-8")
    with open(path, "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
            gz.write(raw)


def _yf_events(sym: str, limit: int = 60) -> List[str]:
    import yfinance as yf
    os.makedirs(CACHE_YF, exist_ok=True)
    p = os.path.join(CACHE_YF, f"events_{sym}.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    out: List[str] = []
    for attempt in range(3):
        try:
            ed = yf.Ticker(sym).get_earnings_dates(limit=limit)
            for ts, _row in (ed if ed is not None else pd.DataFrame()).iterrows():
                ts = pd.Timestamp(ts)
                if ts.tz is not None:
                    ts = ts.tz_convert("America/New_York").tz_localize(None)
                out.append(ts.strftime("%Y-%m-%d %H:%M"))
            break
        except Exception:  # noqa: BLE001
            time.sleep(3 * (attempt + 1))
    out = sorted(set(out))
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    return out


def _cached(name: str, fn):
    os.makedirs(CACHE_YF, exist_ok=True)
    p = os.path.join(CACHE_YF, name)
    if os.path.exists(p):
        return pd.read_pickle(p)
    v = fn()
    pd.to_pickle(v, p)
    return v


def resolve_events(yfe: List[str], k8: List[Dict[str, str]], end: str, events_from: str) -> List[Dict[str, Any]]:
    """Session 2 rule (snapshot_sp100), unchanged: vendor dates identify earnings; earlier of 8-K / vendor."""
    evs, kept_y = [], []
    for y in sorted(yfe):
        if y[:10] >= end:
            continue
        if kept_y and (pd.Timestamp(y) - pd.Timestamp(kept_y[-1])).days < 5:
            continue
        kept_y.append(y)
        m = match_8k(y, [{"accepted_at_et": e["accepted_at_et"], "accession": e["accession"]} for e in k8])
        ts, rule = resolve_event_time(m["accepted_at_et"] if m else None, y)
        ts, rule = apply_issuer_convention(ts, rule, y, kept_y[:-1], m["accepted_at_et"] if m else None)
        if ts[:10] < events_from:
            continue
        evs.append({"announced_at_et": ts[:16], "rule": rule, "vendor_et": y,
                    "edgar_8k_et": m["accepted_at_et"] if m else None, "accession": m["accession"] if m else None,
                    "source": "earlier of SEC EDGAR 8-K Item 2.02 acceptance and yfinance.get_earnings_dates"})
    return sorted(evs, key=lambda e: e["announced_at_et"])


# ---------------------------------------------------------------------------
# Event rules v2 (Session 4; independent review Session 3, P2-1 and P2-2). Rules v1 above stay as pre-registered.
# ---------------------------------------------------------------------------

MISDATED_MAX_DAYS = 45   # a vendor-only date 4..45 days after an Item 2.02 8-K is the 10-Q date, not the release
GAP_DAYS = 45            # an Item 2.02 8-K with no event within +-45 days lies in a vendor-series gap


def periodic_filings(subs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Original 10-Q/10-K filings as {form, end, accepted_at} (naive ET), from EDGAR submissions."""
    from backtest.edgar import to_et
    out = [{"form": s["form"], "end": s.get("reportDate") or "", "accepted_at": to_et(s["acceptanceDateTime"])}
           for s in subs if s.get("form") in ("10-Q", "10-K") and s.get("reportDate")]
    return sorted(out, key=lambda r: (r["accepted_at"], r["end"]))


def earnings_8k_events(k8: List[Dict[str, str]], periodic: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Item 2.02 8-Ks that look like the quarterly earnings release: for each original 10-Q/10-K (period end R,
    accepted A), the LATEST Item 2.02 8-K accepted in (R, A] and within 100 days of R. One per reporting period.
    Removes other Item 2.02 uses (delivery numbers, monthly sales, preliminary results earlier in the window).
    Identification only (which dates are earnings releases); no outcome is used."""
    out: Dict[str, Dict[str, str]] = {}
    for p in periodic:
        if p.get("form") not in ("10-Q", "10-K") or not p.get("end"):
            continue
        R, A = pd.Timestamp(p["end"]), pd.Timestamp(p["accepted_at"])
        c = [e for e in k8 if R < pd.Timestamp(e["accepted_at_et"]) <= A and (pd.Timestamp(e["accepted_at_et"]) - R).days <= 100]
        if c:
            e = max(c, key=lambda e: e["accepted_at_et"])
            out[e["accession"]] = e
    return sorted(out.values(), key=lambda e: e["accepted_at_et"])


def eight_k_only_time(k8_time: str) -> Tuple[str, str]:
    """Timestamp for an event known only from its 8-K: pre-market (07:00) of the acceptance day, whatever the
    acceptance time. An 8-K can be accepted hours after the press release (ADM: 07:00 release, 8-K after 16:00), so
    the acceptance time itself would be one session late in 1.6% of the 22,869 events where vendor and 8-K agree
    (results/pit2_changes_2026-11-04.md); pre-market of the acceptance day cuts that to 0.45%, and the issuer filter
    (`eight_k_lag_ok`) removes the issuers whose 8-Ks trail by days. Only ever moves D earlier (removes information)."""
    return min(k8_time[:16], f"{k8_time[:10]} 07:00"), "8-K only; pre-market of acceptance day"


MAX_8K_LAG_RATE = 0.10   # issuer filter for 8-K-only events


def _d_bus(ts: str) -> "np.datetime64":
    """Decision day for an announcement on the business-day calendar (weekends only; no holiday list — a session
    calendar is not available when events are built): after 16:00 -> that day (rolled back to a business day),
    otherwise the business day strictly before it. Mirrors `pit.decision_session`."""
    d = np.datetime64(ts[:10])
    if ts[11:16] >= "16:00":
        return np.busday_offset(d, 0, roll="backward")
    return np.busday_offset(d, -1, roll="forward")


def eight_k_lag_ok(v1_events: List[Dict[str, Any]]) -> bool:
    """True if the issuer's own 8-Ks are timely: among its events where vendor date and Item 2.02 8-K agree (>= 4),
    timing from the 8-K alone (`eight_k_only_time`) would give a LATER decision day than the event in at most 10%.
    Issuers whose 8-Ks trail by days (BBWI, CCB, URG) get no 8-K-only events. A next-morning 8-K after an after-close
    release (COST) is not late: it gives the same decision day. A data-quality property of the issuer's filing habit,
    not an outcome."""
    m = [e for e in v1_events if e.get("vendor_et") and e.get("edgar_8k_et")]
    if len(m) < 4:
        return False
    late = sum(_d_bus(eight_k_only_time(e["edgar_8k_et"])[0]) > _d_bus(e["announced_at_et"]) for e in m)
    return bool(late / len(m) <= MAX_8K_LAG_RATE)


VENDOR_GAP_DAYS = 60     # ... and no vendor date within +-60 days (a quarter is ~91 days apart)


def release_8k_on(all_8k: List[Dict[str, str]], day: str) -> bool:
    """True if an 8-K that can carry an earnings release (Item 2.02 or 7.01, or exhibits only: 9.01 alone, as GE
    2020-04-29 and Welltower 2019-02-12 furnished theirs) was accepted on `day` or the calendar day before."""
    d = pd.Timestamp(day[:10])
    for e in all_8k:
        a = pd.Timestamp(e["accepted_at_et"][:10])
        if 0 <= (d - a).days <= 1:
            items = {i.strip() for i in str(e.get("items", "")).split(",") if i.strip()}
            if items & {"2.02", "7.01"} or items == {"9.01"}:
                return True
    return False


def resolve_events_v2(yfe: List[str], k8: List[Dict[str, str]], all_8k: List[Dict[str, str]],
                      periodic: List[Dict[str, str]], end: str, events_from: str) -> List[Dict[str, Any]]:
    """Rules v1 (`resolve_events`, with `k8` = the Item 2.02 8-Ks), then:
    P2-2  a vendor-only event (no Item 2.02 8-K within +-3 days) is not an earnings date when (a) an earnings 8-K
          (`earnings_8k_events`) of the issuer was accepted 4..45 days before it and (b) no 8-K that could carry a
          release was accepted on the vendor date or the day before (`release_8k_on`) — i.e. the vendor date is the
          10-Q/10-K date (COST 2023-06-01, INTC 2015-04-27, LIN 2020-03-01, BRK.B 2016-05-06). If that 8-K is already
          an event the vendor date is dropped; otherwise the event is re-timed from the 8-K. Other vendor-only events
          stay (BRK.B Saturday releases, C/MS without Item 2.02; GE 2020-04-29 and WELL 2019-02-12, whose releases were
          furnished as 9.01-only 8-Ks while an earlier Item 2.02 8-K carried something else).
    P2-1  an earnings 8-K with no vendor date within +-60 days and no event within +-45 days lies in a gap of the
          vendor series (BLK 2009-10..2022-07): it becomes an 8-K-only event, timed by `eight_k_only_time`."""
    v1 = resolve_events(yfe, k8, end, "0000-00-00")
    lag_ok = eight_k_lag_ok(v1)
    e8 = [e for e in earnings_8k_events(k8, periodic) if e["accepted_at_et"][:10] < end]
    used = {e["accession"] for e in v1 if e["accession"]}
    vend = sorted(y for y in yfe if y[:10] < end)
    out: List[Dict[str, Any]] = []
    for e in v1:
        if e["accession"]:
            out.append(e)
            continue
        t = pd.Timestamp(e["vendor_et"])
        prev = [k for k in e8 if 4 <= (t - pd.Timestamp(k["accepted_at_et"])).total_seconds() / 86400 <= MISDATED_MAX_DAYS]
        if not prev or release_8k_on(all_8k, e["vendor_et"]):
            out.append(e)
            continue
        k = prev[-1]
        if k["accession"] in used:
            continue                                   # duplicate of an existing event (LIN 2020-03-01)
        used.add(k["accession"])
        if not lag_ok:
            continue                                   # mis-dated vendor date, but the 8-K cannot be trusted for timing
        ts, rule = eight_k_only_time(k["accepted_at_et"])
        out.append({"announced_at_et": ts[:16], "rule": rule + " (vendor date mis-dated: " + e["vendor_et"] + ")",
                    "vendor_et": None, "edgar_8k_et": k["accepted_at_et"], "accession": k["accession"],
                    "source": "SEC EDGAR 8-K Item 2.02 acceptance (vendor date replaced, rules v2 P2-2)"})
    for k in e8:
        if k["accession"] in used:
            continue
        t = pd.Timestamp(k["accepted_at_et"])
        if any(abs((pd.Timestamp(x["announced_at_et"]) - t).days) <= GAP_DAYS for x in out) or \
                any(abs((pd.Timestamp(y) - t).days) <= VENDOR_GAP_DAYS for y in vend):
            continue
        if not lag_ok:
            continue
        ts, rule = eight_k_only_time(k["accepted_at_et"])
        out.append({"announced_at_et": ts[:16], "rule": rule + " (vendor-series gap)", "vendor_et": None,
                    "edgar_8k_et": k["accepted_at_et"], "accession": k["accession"],
                    "source": "SEC EDGAR 8-K Item 2.02 acceptance (no vendor date; rules v2 P2-1)"})
        used.add(k["accession"])
    return sorted((e for e in out if e["announced_at_et"][:10] >= events_from), key=lambda e: e["announced_at_et"])


def build(snapshot_id: str, start: str, end: str, events_from: str, only: List[str] = None) -> str:
    with open(os.path.join(PU.PDIR, "candidates.json"), encoding="utf-8") as fh:
        cand = json.load(fh)
    with open(os.path.join(os.path.dirname(PU.PDIR), "sp500_constituents.csv"), encoding="utf-8") as fh:
        import csv
        gics = {r["Symbol"].strip().replace(".", "-"): r["GICS Sector"] for r in csv.DictReader(fh)}
    root = os.path.join(SNAP_ROOT, snapshot_id)
    for sub in ("prices", "fundamentals", "shares"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    ed = EdgarClient()
    members, problems, events, splits, xcheck = [], {}, {}, {}, {}
    for sym in BENCH:
        p = os.path.join(root, "prices", f"{_safe(sym)}.csv.gz")
        if not os.path.exists(p):
            _gz_csv(_cached(f"px_{sym}.pkl", lambda: fetch_prices(sym, start, end)), p)
    for c in cand["candidates"]:
        ysym = c["ticker"]                       # SEC/yfinance dash form, e.g. BRK-B
        t = ysym.replace("-", ".")               # snapshot form, e.g. BRK.B (as in Session 2)
        if only and t not in only:
            continue
        try:
            px = _cached(f"px_{ysym}.pkl", lambda: fetch_prices(ysym, start, end))
            sp = _cached(f"sp_{ysym}.pkl", lambda: [x for x in fetch_splits(ysym) if x["date"] < end])
        except Exception as e:  # noqa: BLE001
            problems[t] = f"prices: {type(e).__name__}"
            continue
        if px is None or px.empty:
            problems[t] = "prices: empty"
            continue
        ciks = PREDECESSOR_CIKS.get(t, []) + [int(c["cik"])]
        try:
            b = ed.bundle_ciks(ciks, since=EDGAR_SINCE)
        except EdgarUnavailable as e:
            problems[t] = f"edgar: {e}"
            continue
        top = ed.get_json(f"https://data.sec.gov/submissions/CIK{int(c['cik']):010d}.json")
        forms = {s.get("form") for s in b["subs"]}
        if not forms & {"10-K", "10-Q"}:
            problems[t] = f"not a domestic 10-K/10-Q filer (forms: {sorted(f for f in forms if f)[:6]})"
            continue
        shares = PU.shares_series(b["facts"], b["subs"], since=EDGAR_SINCE)
        if not shares:   # e.g. Visa: share counts and EPS only per class
            shares = PU.shares_from_public_float(b["facts"], b["subs"], px, since=EDGAR_SINCE)
        fund = fundamentals_from_companyfacts(b["facts"], b["subs"], since=EDGAR_SINCE, comparatives=True)
        k8 = [e for e in earnings_8k(b["subs"], since=EDGAR_SINCE) if e["accepted_at_et"][:10] < end]
        yfe = _yf_events(ysym)
        evs = resolve_events(yfe, k8, end, events_from)
        xcheck[t] = {"yfinance": [y for y in yfe if y[:10] < end],
                     "edgar_2_02": [{"accepted_at_et": e["accepted_at_et"], "accession": e["accession"]} for e in k8]}
        floats = PU.public_floats(b["facts"], b["subs"], since=EDGAR_SINCE)
        sic = int(top.get("sic") or 0)
        exclude = EXCLUDE_SIC.get(sic, "") or (
            "only listed security is a preferred share / unit / warrant, not common stock"
            if "-" in ysym and ysym not in PU.DASH_OK else "") or (
            "limited partnership units (MLP), not common stock" if re.search(r"(\bL\.?P\.?$|PARTNERS,? L\.?P)", c["name"].upper()) else "")
        sector = SECTOR_OVERRIDE.get(t) or gics.get(ysym) or sic_sector(top.get("sic"))
        members.append({"ticker": t, "cik": int(c["cik"]), "ciks": ciks, "name": c["name"], "seed": c["seed"],
                        "sector": sector, "sector_source": "S&P 500 file (GICS)" if ysym in gics and t not in SECTOR_OVERRIDE
                        else ("hand override" if t in SECTOR_OVERRIDE else f"SIC {top.get('sic')} map"),
                        "sector_etf": SECTOR_ETF[sector], "price_multiplier": PU.PRICE_MULT.get(ysym, 1.0),
                        "sic": sic, "exclude_reason": exclude})
        events[t] = evs
        splits[t] = sp
        _gz_csv(px, os.path.join(root, "prices", f"{_safe(t)}.csv.gz"))
        _gz_json(os.path.join(root, "fundamentals", f"{_safe(t)}.json.gz"),
                 {"ticker": t, "ciks": ciks, "source": "SEC EDGAR companyfacts; PIT key = acceptanceDateTime",
                  "filings": fund})
        with open(os.path.join(root, "shares", f"{_safe(t)}.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"ticker": t, "ciks": ciks, "source": "SEC EDGAR companyfacts dei/us-gaap; PIT key = acceptanceDateTime",
                       "shares": shares, "public_float": floats}, fh, indent=1, sort_keys=True)
        first_px = str(px.index.min().date())
        if not shares:
            problems[t] = "no share counts"
        elif shares[0]["accepted_at"][:10] > max(first_px, EDGAR_SINCE) and \
                (pd.Timestamp(shares[0]["accepted_at"]) - pd.Timestamp(max(first_px, EDGAR_SINCE))).days > 200:
            problems[t] = f"share counts start {shares[0]['accepted_at'][:10]}, prices start {first_px} (possible CIK change)"
    for name, obj in (("events.json", events), ("splits.json", splits), ("event_crosscheck.json", xcheck)):
        with open(os.path.join(root, name), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh, indent=1, sort_keys=True)
    with open(os.path.join(root, "universe.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"label": "POINT-IN-TIME top-100 US-listed domestic filers by market cap at D-1 (decided in the harness)",
                   "rule": cand["rule"], "candidates_inputs": cand["inputs"], "members": sorted(members, key=lambda m: m["ticker"]),
                   "flagged": problems, "top_n": PU.TOP_N}, fh, indent=1, sort_keys=True)
    files = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs if f != "manifest.json")
    manifest = {
        "snapshot_id": snapshot_id, "tickers": sorted(m["ticker"] for m in members), "benchmarks": BENCH,
        "price_start": start, "price_end_exclusive": end, "events_from": events_from, "pit_universe": True,
        "universe": "point-in-time: top 100 by EDGAR shares x split-adjusted close at D-1 among the candidate pool",
        "sources": {
            "prices": "yfinance Ticker.history(auto_adjust=False): OHLC scaled to Adj Close; CloseSplitAdj = split-adjusted only",
            "splits": "yfinance Ticker.splits",
            "events": "yfinance earnings dates matched (+-3d) to SEC EDGAR 8-K Item 2.02 acceptance; timestamp = earlier of the two",
            "fundamentals": "SEC EDGAR companyfacts (XBRL); PIT key = submissions acceptanceDateTime; incl. same-filing prior-year comparatives",
            "shares": "SEC EDGAR dei:EntityCommonStockSharesOutstanding / us-gaap weighted shares; PIT key = acceptanceDateTime",
            "universe": "candidate pool: fja05680/sp500 historical S&P 500 components since 2014 + SEC listed sweep, screened (rank <= 150)",
        },
        "sha256": {f: _sha256(os.path.join(root, f)) for f in files},
    }
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(f"snapshot {root}: {len(members)} tickers; flagged: {len(problems)}; edgar requests {ed.n_requests}")
    return root


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--start", default="2013-01-01")
    ap.add_argument("--end", default="2026-11-04")
    ap.add_argument("--events-from", default="2014-06-01")
    ap.add_argument("--tickers", default="")
    a = ap.parse_args()
    build(a.id, a.start, a.end, a.events_from, [t for t in a.tickers.split(",") if t] or None)


if __name__ == "__main__":
    main()
