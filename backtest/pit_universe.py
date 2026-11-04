# -*- coding: utf-8 -*-
"""
backtest/pit_universe.py — Session 3: point-in-time (PIT) universe, removing survivorship bias.

Universe on decision session D = the 100 largest US-listed domestic filers (10-K/10-Q filers; ADRs and
20-F/40-F filers excluded) by market capitalisation at the close of D-1, where

    market cap(D-1) = shares(PIT) x split factor(after the shares' date) x CloseSplitAdj(D-1) x class multiplier

  shares(PIT)   from the latest periodic filing (10-K/10-Q and amendments) ACCEPTED BEFORE 16:00 ET on D-1
                (SEC submissions acceptanceDateTime), chosen per filing by `shares_from_filing`:
                  1. dei:EntityCommonStockSharesOutstanding (cover page), if within [0.8, 1.25]x of the same
                     filing's weighted share count (multi-class filers report the cover value per class, which
                     is absent or partial in companyfacts);
                  2. else us-gaap weighted average diluted shares (basic if diluted is absent);
                  3. else net income / diluted EPS of the same filing.
                  A weighted count that disagrees with NI / EPS by > 25% (unit errors, e.g. MCD in millions)
                  is replaced by NI / EPS.
  price         split-adjusted close (today's share basis), so shares are put on today's basis by the product
                of splits after the shares' date (unit conversion only; a ratio, no look-ahead in the rank).
  multiplier    BRK-B x 1500 (Berkshire reports Class A-equivalent shares). Other multi-class companies use
                total economic shares x the price of one listed class (classes trade at ~equal prices).

Candidate pool (a superset; membership itself is decided PIT by rank):
  * every S&P 500 member on any date since 2014-01-01 (fja05680/sp500 historical components, frozen), plus
  * a sweep of every company listed today on NYSE/Nasdaq/CBOE (SEC company_tickers_exchange.json) whose
    EDGAR frames show >= 100M shares at any quarter 2013-2026 (catches large non-index names, e.g. pre-
    inclusion IPOs),
  * screened with EDGAR frames x monthly yfinance closes at each quarter end 2014Q1-2026Q3: a company is a
    candidate if it ranks <= 200 at any quarter end (margin of 100 over the target 100). The screen needs a
    quarterly us-gaap share count (drops 20-F/40-F filers, which report annually) and carries the last
    value forward up to two quarters (10-Ks rarely tag a separate Q4). Frames hold the LATEST filed value for
    a period (possibly restated for a later split), so screen caps can be overstated; that only enlarges the
    superset. Completeness is checked separately against dei:EntityPublicFloat (`gaps`).
  Companies with no price history (delisted/acquired; Yahoo keeps no history for them) cannot be ranked.
  They are found and listed by `gaps()` from dei:EntityPublicFloat (a USD market value on every 10-K cover,
  needs no prices), and their effect is documented (LOG.md, results/pit_universe_*.md).

  python -m backtest.pit_universe --screen        # network (cached): EDGAR frames, yfinance monthly
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
import os
import time
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.edgar import PERIODIC_FORMS, EdgarClient, to_et

HERE = os.path.dirname(os.path.abspath(__file__))
PDIR = os.path.join(HERE, "universe", "pit")
CACHE = os.path.join(HERE, "cache", "yf_screen")
HIST_URL = ("https://raw.githubusercontent.com/fja05680/sp500/master/"
            "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv")
EXCH_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
LISTED = {"NYSE", "Nasdaq", "CBOE", "TXSE"}
TOP_N = 100
SCREEN_RANK = 200
SWEEP_MIN_SHARES = 1e8
HIST_SINCE = "2014-01-01"
SCREEN_QUARTERS = [(y, q) for y in range(2014, 2027) for q in (1, 2, 3, 4) if (y, q) <= (2026, 3)]
PRICE_MULT = {"BRK-B": 1500.0}
# Dual listings of one company: the listing used for prices/returns (the other is the same company).
PREFERRED = {"GOOG": "GOOGL", "FOX": "FOXA", "NWS": "NWSA", "BRK-A": "BRK-B", "UA": "UAA", "LEN-B": "LEN",
             "BF-A": "BF-B", "HEI-A": "HEI", "LBRDA": "LBRDK", "Z": "Z", "ZG": "Z", "DISCB": "DISCA", "DISCK": "DISCA"}
DASH_OK = {"BRK-B", "BF-B"}
DEI = "EntityCommonStockSharesOutstanding"
W_DIL = "WeightedAverageNumberOfDilutedSharesOutstanding"
W_BAS = "WeightedAverageNumberOfSharesOutstandingBasic"
W_BAD = "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"   # loss-makers often tag basic = diluted


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_gz(path: str, raw: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
            gz.write(raw)


def _read_gz(path: str) -> bytes:
    with gzip.open(path, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Shares outstanding, point in time (one value per accepted periodic filing)
# ---------------------------------------------------------------------------

def shares_from_filing(dei: Optional[float], w_dil: Optional[float], w_bas: Optional[float],
                       ni: Optional[float], eps: Optional[float], require_check: bool = False) -> Tuple[Optional[float], str]:
    """Pick the share count for market cap from values reported in ONE filing (see module doc)."""
    w, wname = (w_dil, "weighted diluted") if w_dil else ((w_bas, "weighted basic") if w_bas else (None, ""))
    # NI / EPS is noisy when EPS is small or rounded (WFC 2020Q1: EPS 0.01; preferred dividends), so it only
    # (a) replaces a weighted count that is off by orders of magnitude (unit error, e.g. MCD tagged in millions)
    # and (b) stands in when no weighted count exists.
    implied = (ni / eps) if (ni and eps and abs(eps) >= 0.05 and ni / eps > 0) else None
    if w and implied and not (1e-3 <= w / implied <= 1e3):
        w, wname = implied, "net income / diluted EPS (weighted count failed unit sanity check)"
    if w is None and implied:
        w, wname = implied, "net income / diluted EPS"
    if dei and dei > 1:
        if w is None:
            if require_check:
                return None, ""
            return dei, "dei cover shares (unchecked: no weighted count in filing)"
        if 0.8 <= dei / w <= 1.25:
            return dei, "dei cover shares"
    return (w, wname) if w else (None, "")


def shares_series(facts: Dict[str, Any], subs: List[Dict[str, Any]], since: str = "2012-01-01") -> List[Dict[str, Any]]:
    """[{accepted_at, as_of, shares, method, form, accn}] from companyfacts, PIT key = acceptanceDateTime."""
    acc = {s["accessionNumber"]: s for s in subs}
    gaap = (facts.get("facts") or {}).get("us-gaap", {}) or {}
    dei = (facts.get("facts") or {}).get("dei", {}) or {}
    by: Dict[str, Dict[str, Any]] = defaultdict(dict)

    def rows(node: Dict[str, Any], unit: str) -> Iterable[Dict[str, Any]]:
        for r in ((node or {}).get("units") or {}).get(unit, []):
            if r.get("form") in PERIODIC_FORMS and r.get("filed", "") >= since:
                yield r

    for r in rows(gaap.get("Assets"), "USD"):
        if not r.get("start"):
            cur = by[r["accn"]].get("assets")
            if cur is None or r["end"] > cur["end"]:
                by[r["accn"]]["assets"] = r
    for r in rows(dei.get(DEI), "shares"):
        cur = by[r["accn"]].get("dei")
        if cur is None or r["end"] > cur["end"]:
            by[r["accn"]]["dei"] = r
    for key, concept, unit in (("w_dil", W_DIL, "shares"), ("w_dil", W_BAD, "shares"), ("w_bas", W_BAS, "shares"),
                               ("ni", "NetIncomeLoss", "USD"), ("eps", "EarningsPerShareDiluted", "USD/shares"),
                               ("eps", "EarningsPerShareBasicAndDiluted", "USD/shares")):
        for r in rows(gaap.get(concept), unit):
            if not r.get("start"):
                continue
            dur = (pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days
            cur = by[r["accn"]].get(key)
            # latest period end, then the shortest duration (the quarter rather than YTD)
            if cur is None or (r["end"], -dur) > (cur["end"], -cur["_dur"]):
                by[r["accn"]][key] = dict(r, _dur=dur)
    # NI and EPS must describe the same period to imply a share count
    out = []
    for accn, d in by.items():
        sub = acc.get(accn)
        if not sub:
            continue
        ni, eps = d.get("ni"), d.get("eps")
        same = ni and eps and ni["end"] == eps["end"] and ni["start"] == eps["start"]
        val, method = shares_from_filing(
            (d.get("dei") or {}).get("val"), (d.get("w_dil") or {}).get("val"), (d.get("w_bas") or {}).get("val"),
            ni["val"] if same else None, eps["val"] if same else None)
        if not val:
            continue
        as_of = d["dei"]["end"] if method.startswith("dei") else to_et(sub["acceptanceDateTime"])[:10]
        out.append({"accepted_at": to_et(sub["acceptanceDateTime"]), "as_of": as_of, "shares": float(val),
                    "method": method, "form": sub.get("form"), "accn": accn,
                    "assets": float(d["assets"]["val"]) if d.get("assets") else None})
    out.sort(key=lambda x: (x["accepted_at"], x["accn"]))
    return out


def public_floats(facts: Dict[str, Any], subs: List[Dict[str, Any]], since: str = "2012-01-01") -> List[Dict[str, Any]]:
    """[{accepted_at, as_of, value}] dei:EntityPublicFloat (USD) from periodic filings, PIT key = acceptance."""
    acc = {s["accessionNumber"]: s for s in subs}
    out = []
    for r in (((facts.get("facts") or {}).get("dei", {}) or {}).get("EntityPublicFloat") or {}).get("units", {}).get("USD", []):
        sub = acc.get(r["accn"])
        if sub and r.get("form") in PERIODIC_FORMS and r.get("filed", "") >= since and r.get("val"):
            out.append({"accepted_at": to_et(sub["acceptanceDateTime"]), "as_of": r["end"], "value": float(r["val"])})
    out.sort(key=lambda x: (x["accepted_at"], x["as_of"]))
    return out


def shares_from_public_float(facts: Dict[str, Any], subs: List[Dict[str, Any]], prices: pd.DataFrame,
                             since: str = "2012-01-01") -> List[Dict[str, Any]]:
    """Last-resort share count for filers that report neither a non-class cover count nor a weighted count nor EPS
    (Visa reports all of them per class only): dei:EntityPublicFloat (USD, 10-K cover, as of the last business day
    of the second fiscal quarter) / split-adjusted close on that date. The result is already on today's share
    basis, so `as_of` is set past every split. PIT key = the 10-K's acceptanceDateTime. Public float excludes
    affiliate holdings, so this understates shares for controlled companies (not the case for Visa)."""
    acc = {s["accessionNumber"]: s for s in subs}
    dei = (facts.get("facts") or {}).get("dei", {}) or {}
    out = []
    for r in ((dei.get("EntityPublicFloat") or {}).get("units") or {}).get("USD", []):
        sub = acc.get(r["accn"])
        if not sub or r.get("form") not in PERIODIC_FORMS or r.get("filed", "") < since:
            continue
        px = prices.loc[prices.index <= pd.Timestamp(r["end"]), "CloseSplitAdj"]
        if px.empty or not r.get("val"):
            continue
        out.append({"accepted_at": to_et(sub["acceptanceDateTime"]), "as_of": "9999-12-31",
                    "shares": float(r["val"]) / float(px.iloc[-1]),
                    "method": f"public float / split-adjusted close on {r['end']} (no share count reported)",
                    "form": sub.get("form"), "accn": r["accn"]})
    out.sort(key=lambda x: (x["accepted_at"], x["accn"]))
    return out


def split_factor_after(splits: List[Dict[str, float]], when: str) -> float:
    f = 1.0
    for sp in splits or []:
        if sp["date"] > when[:10]:
            f *= float(sp["ratio"])
    return f


JUMP = 3.0          # a share count > 3x away from the last accepted one needs confirmation by the next filing
FLOAT_MAX_RATIO = 10.0
MAX_CAP_TO_ASSETS = 100.0   # unchecked share count (no float, single tag): cap > 100x total assets -> not rankable   # market cap > 10x the latest public float (10-K cover) -> not rankable that day


def accepted_series(series: List[Dict[str, Any]], splits: List[Dict[str, float]]) -> List[Dict[str, Any]]:
    """Drop unconfirmed jumps. Each record's verdict uses only EARLIER records (PIT-safe): a record whose share
    count (on today's split basis) differs from the last accepted one by more than JUMP x is held back; it is
    accepted when the next record confirms its level (then both levels agree), e.g. a large stock merger is
    recognised one filing late, while a one-off tagging error (WTTR, WFC 2020Q1) never enters."""
    out: List[Dict[str, Any]] = []
    last = pending = None
    for r in series:
        v = r["shares"] * split_factor_after(splits, r["as_of"])
        if last is None or 1 / JUMP <= v / last <= JUMP:
            out.append(r)
            last, pending = v, None
        elif pending is not None and 1 / JUMP <= v / pending <= JUMP:
            out.append(r)
            last, pending = v, None
        else:
            pending = v
    return out


def shares_at(series: List[Dict[str, Any]], cutoff: pd.Timestamp) -> Optional[Dict[str, Any]]:
    """Latest share record accepted strictly before `cutoff` (`series` sorted by acceptance)."""
    keys = [r["accepted_at"] for r in series]   # 'YYYY-MM-DD HH:MM:SS' sorts chronologically
    i = bisect.bisect_left(keys, cutoff.strftime("%Y-%m-%d %H:%M:%S"))
    return series[i - 1] if i > 0 else None


def float_at(floats: List[Dict[str, Any]], cutoff: pd.Timestamp) -> Optional[float]:
    """Latest public float (USD) from a 10-K accepted before `cutoff` and at most 15 months old."""
    rec = shares_at(floats, cutoff)
    if rec is None or (cutoff - pd.Timestamp(rec["accepted_at"])).days > 460:
        return None
    return float(rec["value"])


def float_check_ok(cap: float, flt: Optional[float], shares_confirmed: bool = False) -> bool:
    """False if cap > FLOAT_MAX_RATIO x public float. Exception: the float looks tagged in thousands (float x 1000
    within a factor of three of the cap) AND the share count is confirmed by two tags of the same filing (cover
    count agrees with the weighted count; e.g. Duke Energy 2023). A share count tagged x1000 (small banks such as
    NKSH, RRBI) has the same cap/float signature but rests on a single tag, so it stays excluded."""
    if not flt or flt <= 0 or cap <= FLOAT_MAX_RATIO * flt:
        return True
    return shares_confirmed and 1 / 3 <= (flt * 1000.0) / cap <= 3


def market_caps_on(snap, day: pd.Timestamp, tickers: Optional[List[str]] = None) -> Dict[str, float]:
    """PIT market caps at the close of `day` (a session): shares from filings accepted before 16:00 ET on
    `day`, prices up to and including `day` only."""
    cutoff = pd.Timestamp(f"{day.date()} 16:00:00")
    out: Dict[str, float] = {}
    acc = getattr(snap, "_accepted_shares", None)
    if acc is None or acc[0] is not snap.shares:
        acc = (snap.shares, {t: accepted_series(v, snap.splits.get(t, [])) for t, v in snap.shares.items()})
        try:
            snap._accepted_shares = acc
        except AttributeError:
            pass
    floats = getattr(snap, "floats", {}) or {}
    for t in sorted(tickers or snap.manifest["tickers"]):
        df = snap.prices.get(t)
        ser = acc[1].get(t)
        if df is None or not ser or day not in df.index:
            continue
        if (snap.universe.get(t) or {}).get("exclude_reason"):
            continue
        rec = shares_at(ser, cutoff)
        if rec is None:
            continue
        px = float(df.at[day, "CloseSplitAdj"])
        k = split_factor_after(snap.splits.get(t, []), rec["as_of"])
        cap = rec["shares"] * k * px * PRICE_MULT.get(t.replace(".", "-"), 1.0)
        flt = float_at(floats.get(t, []), cutoff)
        confirmed = rec.get("method") == "dei cover shares"
        if not float_check_ok(cap, flt, confirmed):
            continue
        if flt is None and not confirmed and rec.get("assets") and cap > MAX_CAP_TO_ASSETS * rec["assets"]:
            continue   # single-tag share count, no float to check it against, implausible vs assets (RRBI 2019: x1000 tag)
        out[t] = cap
    return out


def rank_on(snap, day: pd.Timestamp) -> Dict[str, int]:
    """Rank (1 = largest) of every candidate with a PIT market cap at the close of `day`. Ties by ticker."""
    caps = market_caps_on(snap, day)
    order = sorted(caps.items(), key=lambda kv: (-kv[1], kv[0]))
    return {t: i + 1 for i, (t, _) in enumerate(order)}


# ---------------------------------------------------------------------------
# Candidate screen (network, cached)
# ---------------------------------------------------------------------------

def _frames(ed: EdgarClient, y: int, q: int) -> Dict[str, Dict[int, float]]:
    base = "https://data.sec.gov/api/xbrl/frames/"
    spec = {"dei": f"dei/{DEI}/shares/CY{y}Q{q}I", "w_dil": f"us-gaap/{W_DIL}/shares/CY{y}Q{q}",
            "w_bas": f"us-gaap/{W_BAS}/shares/CY{y}Q{q}", "ni": f"us-gaap/NetIncomeLoss/USD/CY{y}Q{q}",
            "eps": f"us-gaap/EarningsPerShareDiluted/USD-per-shares/CY{y}Q{q}"}
    out = {}
    for k, path in spec.items():
        try:
            out[k] = {r["cik"]: float(r["val"]) for r in ed.get_json(base + path + ".json")["data"]}
        except Exception:  # noqa: BLE001  (a frame may not exist yet)
            out[k] = {}
    return out


def fetch_inputs(ed: EdgarClient) -> Dict[str, Any]:
    """Freeze the two list inputs (raw bytes, gzipped deterministically) with their sha256."""
    import requests
    os.makedirs(PDIR, exist_ok=True)
    hp = os.path.join(PDIR, "sp500_history.csv.gz")
    if not os.path.exists(hp):
        _write_gz(hp, requests.get(HIST_URL, timeout=120).content)
    xp = os.path.join(PDIR, "sec_company_tickers_exchange.json.gz")
    if not os.path.exists(xp):
        _write_gz(xp, json.dumps(ed.get_json(EXCH_URL), sort_keys=True).encode())
    return {"hist": _read_gz(hp), "exch": _read_gz(xp)}


def _choose_ticker(tks: List[str], prefer: set) -> str:
    tks = sorted(set(PREFERRED.get(t, t) for t in tks))
    plain = [t for t in tks if "-" not in t or t in DASH_OK] or tks
    for t in plain:
        if t in prefer:
            return t
    return sorted(plain, key=lambda t: (len(t), t))[0]


def _monthly(tickers: List[str]) -> Dict[str, pd.DataFrame]:
    """Monthly split-adjusted close + split ratio per ticker (yfinance, cached per ticker)."""
    import yfinance as yf
    os.makedirs(CACHE, exist_ok=True)
    out, todo = {}, []
    for t in tickers:
        p = os.path.join(CACHE, t + ".csv")
        if os.path.exists(p):
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            out[t] = df
        else:
            todo.append(t)
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        for attempt in range(3):
            try:
                raw = yf.download(batch, start="2013-12-01", end="2026-11-01", interval="1mo", auto_adjust=False,
                                  actions=True, group_by="ticker", threads=True, progress=False)
                break
            except Exception:  # noqa: BLE001
                time.sleep(10 * (attempt + 1))
        else:
            continue
        for t in batch:
            try:
                sub = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = pd.DataFrame({"close": sub["Close"], "split": sub.get("Stock Splits", 0.0)}).dropna(subset=["close"])
            except KeyError:
                df = pd.DataFrame(columns=["close", "split"])
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df.to_csv(os.path.join(CACHE, t + ".csv"))
            out[t] = df
        time.sleep(2)
    return out


def screen(write: bool = True) -> Dict[str, Any]:
    ed = EdgarClient()
    inp = fetch_inputs(ed)
    hist_rows = list(csv.reader(io.StringIO(inp["hist"].decode("utf-8"))))[1:]
    hist_since = sorted({t for d, ts in hist_rows if d >= HIST_SINCE for t in ts.split(",")})
    exch = json.loads(inp["exch"])
    by_cik: Dict[int, List[Tuple[str, str, str]]] = defaultdict(list)
    for cik, name, tk, ex in exch["data"]:
        if ex in LISTED:
            by_cik[int(cik)].append((tk.upper(), name, ex))
    tk2cik = {tk: c for c, lst in by_cik.items() for tk, _, _ in lst}
    hist_cik = {}
    for t in hist_since:
        c = tk2cik.get(t.replace(".", "-"))
        if c:
            hist_cik.setdefault(c, []).append(t.replace(".", "-"))
    frames = {yq: _frames(ed, *yq) for yq in [(2013, 4)] + SCREEN_QUARTERS}
    mx: Dict[int, float] = defaultdict(float)
    for fr in frames.values():
        for k in ("dei", "w_dil", "w_bas"):
            for c, v in fr[k].items():
                mx[c] = max(mx[c], v)
    sweep = {c for c in by_cik if mx.get(c, 0) >= SWEEP_MIN_SHARES} - set(hist_cik)
    pool = sorted(set(hist_cik) | sweep)
    latest = set(t.replace(".", "-") for t in hist_rows[-1][1].split(","))
    ticker_of = {c: _choose_ticker([tk for tk, _, _ in by_cik[c]], latest | set(hist_cik.get(c, []))) for c in pool}
    prices = _monthly(sorted(set(ticker_of.values())))
    # rank at each quarter end
    ranks: Dict[int, Dict[str, int]] = defaultdict(dict)
    last: Dict[int, Tuple[int, float]] = {}   # cik -> (quarter index, shares)
    for qi, (y, q) in enumerate(SCREEN_QUARTERS):
        qe = pd.Timestamp(year=y, month=3 * q, day=1)
        fr = frames[(y, q)]
        caps = {}
        for c in pool:
            sh, _ = shares_from_filing(fr["dei"].get(c), fr["w_dil"].get(c), fr["w_bas"].get(c),
                                       fr["ni"].get(c), fr["eps"].get(c), require_check=True)
            if sh:
                last[c] = (qi, sh)
            elif c in last and qi - last[c][0] <= 2:
                sh = last[c][1]
            t = ticker_of[c]
            df = prices.get(t)
            if not sh or df is None or df.empty or qe not in df.index:
                continue
            k = float(np.prod([r for d, r in df["split"].items() if d > qe and r and r > 0])) if "split" in df else 1.0
            caps[c] = sh * k * float(df.at[qe, "close"]) * PRICE_MULT.get(t, 1.0)
        for i, (c, _) in enumerate(sorted(caps.items(), key=lambda kv: (-kv[1], kv[0]))):
            ranks[c][f"{y}Q{q}"] = i + 1
    # Second seed, independent of share counts and of the 100M-share threshold (catches e.g. Visa, whose share
    # counts are reported per class only, and high-priced names like MercadoLibre): listed companies ranked
    # <= FLOAT_RANK by dei:EntityPublicFloat in any calendar year.
    fr_rank = float_ranks(ed)
    float_seed = {c for c, r in fr_rank.items() if c in by_cik and min(r.values()) <= FLOAT_RANK}
    for c in sorted(float_seed - set(pool)):
        ticker_of[c] = _choose_ticker([tk for tk, _, _ in by_cik[c]], latest)
    cands = []
    for c in sorted(set(pool) | float_seed):
        r = ranks.get(c, {})
        best = min(r.values()) if r else None
        fbest = min(fr_rank[c].values()) if c in fr_rank else None
        if (best is not None and best <= SCREEN_RANK) or c in float_seed:
            cands.append({"cik": c, "ticker": ticker_of[c], "name": by_cik[c][0][1], "exchange": by_cik[c][0][2],
                          "listings": sorted(tk for tk, _, _ in by_cik[c]),
                          "seed": "sp500_history" if c in hist_cik else ("listed_sweep" if c in sweep else "public_float"),
                          "best_screen_rank": best, "best_public_float_rank": fbest,
                          "quarters_top100": sum(1 for v in r.values() if v <= TOP_N),
                          "quarters_top150": sum(1 for v in r.values() if v <= SCREEN_RANK)})
    cands.sort(key=lambda d: d["ticker"])
    no_price = sorted(ticker_of[c] for c in pool if prices.get(ticker_of[c]) is None or prices[ticker_of[c]].empty)
    unmapped = sorted(t for t in hist_since if not tk2cik.get(t.replace(".", "-")))
    meta = {
        "rule": f"rank <= {SCREEN_RANK} at any quarter end {SCREEN_QUARTERS[0]}..{SCREEN_QUARTERS[-1]} by EDGAR frames "
                "shares x yfinance month-end split-adjusted close (screen only; membership is decided PIT by rank <= 100)",
        "inputs": {"sp500_history": {"url": HIST_URL, "sha256_raw": _sha(inp["hist"]), "rows": len(hist_rows),
                                     "last_date": hist_rows[-1][0], "tickers_since_2014": len(hist_since)},
                   "sec_company_tickers_exchange": {"url": EXCH_URL, "sha256_raw": _sha(inp["exch"])}},
        "pool": {"sp500_history_live": len(hist_cik), "listed_sweep": len(sweep), "total": len(pool),
                 "no_price_history": no_price},
        "sp500_history_tickers_without_live_listing": unmapped,
        "candidates": cands,
    }
    if write:
        with open(os.path.join(PDIR, "candidates.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(meta, fh, indent=1, sort_keys=True)
    return meta


FLOAT_RANK = 150


def float_ranks(ed: EdgarClient) -> Dict[int, Dict[int, int]]:
    """cik -> {year: rank by dei:EntityPublicFloat (max over the year's cover values)}. Some filers tag the float
    in the wrong unit (e.g. thousands), which only adds harmless candidates."""
    out: Dict[int, Dict[int, int]] = defaultdict(dict)
    for y in range(2014, 2026):
        best: Dict[int, float] = {}
        for q in (1, 2, 3, 4):
            try:
                rows = ed.get_json(f"https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/CY{y}Q{q}I.json")["data"]
            except Exception:  # noqa: BLE001
                rows = []
            for r in rows:
                best[r["cik"]] = max(best.get(r["cik"], 0.0), float(r["val"]))
        for i, (c, _) in enumerate(sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))):
            if i < 400:
                out[c][y] = i + 1
    return out


def gaps(cands: Dict[str, Any], ed: Optional[EdgarClient] = None) -> List[Dict[str, Any]]:
    """Companies in the top 100 by dei:EntityPublicFloat (10-K cover, USD, as of the last business day of the
    second fiscal quarter) in any calendar year 2014-2025 that are not candidates. Public float excludes
    affiliate holdings, so it understates market cap for controlled companies; it is used only to FIND gaps."""
    ed = ed or EdgarClient()
    have = {c["cik"] for c in cands["candidates"]}
    found: Dict[int, Dict[str, Any]] = {}
    for y in range(2014, 2026):
        rows = []
        for q in (1, 2, 3, 4):
            try:
                rows += ed.get_json(f"https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/CY{y}Q{q}I.json")["data"]
            except Exception:  # noqa: BLE001
                pass
        best: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            if r["cik"] not in best or r["val"] > best[r["cik"]]["val"]:
                best[r["cik"]] = r
        top = sorted(best.values(), key=lambda r: (-r["val"], r["cik"]))[:FLOAT_RANK]
        for i, r in enumerate(top):
            if r["cik"] in have:
                continue
            g = found.setdefault(r["cik"], {"cik": r["cik"], "name": r["entityName"], "years": [], "best_float_rank": i + 1,
                                            "max_public_float_usd": r["val"]})
            g["years"].append(y)
            g["best_float_rank"] = min(g["best_float_rank"], i + 1)
            g["max_public_float_usd"] = max(g["max_public_float_usd"], r["val"])
    # Plausibility: public float <= 15x total assets (us-gaap Assets, any year-end frame). Many small filers tag the
    # float in thousands (x1000 too large); their float is then hundreds of times their assets.
    assets: Dict[int, float] = {}
    for y in range(2013, 2026):
        try:
            for r in ed.get_json(f"https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/CY{y}Q4I.json")["data"]:
                assets[r["cik"]] = max(assets.get(r["cik"], 0.0), float(r["val"]))
        except Exception:  # noqa: BLE001
            pass
    for g in found.values():
        a = assets.get(g["cik"])
        g["max_total_assets_usd"] = a
        g["plausible"] = bool(a and g["max_public_float_usd"] <= 15.0 * a)
    return sorted(found.values(), key=lambda g: (g["best_float_rank"], g["cik"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", action="store_true")
    a = ap.parse_args()
    if a.screen:
        m = screen()
        print("pool", m["pool"]["total"], "candidates", len(m["candidates"]), "no price", len(m["pool"]["no_price_history"]))
