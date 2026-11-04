# -*- coding: utf-8 -*-
"""
backtest/pit.py — point-in-time (PIT) data access over a frozen snapshot.

Hard rule 4: anything returned for a cutoff `asof` uses only information whose
availability timestamp is strictly before `asof`:
  * prices: bars with date <= `last_bar` (caller passes the last *completed* session)
  * fundamentals: filings with `accepted_at` < cutoff timestamp
  * events: only used to schedule decisions; their outcome is never an input.

Every value carries `source` and `as_of` so reports can tag it (hard rule 5).
"""

from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.snapshot import _safe

MARKET_CLOSE = "16:00"


@dataclass
class Snapshot:
    root: str
    prices: Dict[str, pd.DataFrame] = field(default_factory=dict)
    fundamentals: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    events: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)
    splits: Dict[str, List[Dict[str, float]]] = field(default_factory=dict)
    manifest: Dict[str, Any] = field(default_factory=dict)
    universe: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # ticker -> {sector, sector_etf, ...}
    shares: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # ticker -> PIT share counts (Session 3)
    floats: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # ticker -> PIT public float (Session 3)

    @classmethod
    def load(cls, root: str) -> "Snapshot":
        with open(os.path.join(root, "manifest.json"), encoding="utf-8") as fh:
            man = json.load(fh)
        if man.get("base"):
            # Session 3 review overlay: everything from the frozen base snapshot, share counts/floats from the overlay.
            snap = cls.load(os.path.join(os.path.dirname(root), man["base"]))
            snap.root, snap.manifest = root, dict(snap.manifest, **{k: v for k, v in man.items() if k != "sha256"})
            snap.shares, snap.floats = {}, {}
            for t in snap.manifest["tickers"]:
                with open(os.path.join(root, "shares", f"{_safe(t)}.json"), encoding="utf-8") as fh:
                    d_ = json.load(fh)
                snap.shares[t], snap.floats[t] = d_["shares"], d_.get("public_float", [])
            return snap
        snap = cls(root=root)
        with open(os.path.join(root, "manifest.json"), encoding="utf-8") as fh:
            snap.manifest = json.load(fh)
        with open(os.path.join(root, "events.json"), encoding="utf-8") as fh:
            snap.events = json.load(fh)
        sp = os.path.join(root, "splits.json")
        if os.path.exists(sp):
            with open(sp, encoding="utf-8") as fh:
                snap.splits = json.load(fh)
        up = os.path.join(root, "universe.json")
        if os.path.exists(up):
            with open(up, encoding="utf-8") as fh:
                snap.universe = {m["ticker"]: m for m in json.load(fh)["members"]}
        for t in snap.manifest["tickers"] + snap.manifest["benchmarks"]:
            p = os.path.join(root, "prices", f"{_safe(t)}.csv")
            p = p if os.path.exists(p) else p + ".gz"   # Session 3 snapshots store gzipped CSV
            df = pd.read_csv(p, index_col="date", parse_dates=True)
            snap.prices[t] = df.sort_index()
        for t in snap.manifest["tickers"]:
            p = os.path.join(root, "fundamentals", f"{_safe(t)}.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    snap.fundamentals[t] = json.load(fh)["filings"]
            elif os.path.exists(p + ".gz"):
                with gzip.open(p + ".gz", "rt", encoding="utf-8") as fh:
                    snap.fundamentals[t] = json.load(fh)["filings"]
            sp_ = os.path.join(root, "shares", f"{_safe(t)}.json")
            if os.path.exists(sp_):   # Session 3 PIT-universe snapshots: share counts keyed by acceptance
                with open(sp_, encoding="utf-8") as fh:
                    d_ = json.load(fh)
                snap.shares[t] = d_["shares"]
                snap.floats[t] = d_.get("public_float", [])
        return snap

    @property
    def snapshot_id(self) -> str:
        return self.manifest["snapshot_id"]

    # ------------------------------------------------------------------ prices
    def sessions(self, ticker: str = "SPY") -> pd.DatetimeIndex:
        return self.prices[ticker].index

    def bars_through(self, ticker: str, last_bar: pd.Timestamp) -> pd.DataFrame:
        df = self.prices[ticker]
        return df.loc[df.index <= last_bar]

    def close_on(self, ticker: str, day: pd.Timestamp) -> float:
        return float(self.prices[ticker].loc[day, "Close"])


# ---------------------------------------------------------------------------
# Event alignment
# ---------------------------------------------------------------------------

def decision_session(sessions: pd.DatetimeIndex, announced_at_et: str) -> Optional[pd.Timestamp]:
    """D = last session whose 16:00 ET close is strictly before the announcement.
    After-close (>= 16:00) on day X -> D = X. Pre-open or intraday -> D = previous session."""
    ts = pd.Timestamp(announced_at_et)
    day = ts.normalize()
    after_close = ts.strftime("%H:%M") >= MARKET_CLOSE
    cands = sessions[sessions <= day] if after_close else sessions[sessions < day]
    return cands[-1] if len(cands) else None


# ---------------------------------------------------------------------------
# Fundamentals (as-reported YTD filings -> TTM)
# ---------------------------------------------------------------------------

def _days(f: Dict[str, Any]) -> int:
    return (pd.Timestamp(f["end"]) - pd.Timestamp(f["start"])).days


def _same_len(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Same reporting length within 20 days (handles 52/53-week fiscal calendars)."""
    return abs(_days(a) - _days(b)) <= 20


def _is_fy(f: Dict[str, Any]) -> bool:
    return _days(f) >= 340


def _available(filings: List[Dict[str, Any]], cutoff: pd.Timestamp) -> List[Dict[str, Any]]:
    """Filings accepted strictly before cutoff; latest acceptance wins for a given (start, end)."""
    best: Dict[tuple, Dict[str, Any]] = {}
    for f in filings:
        if not f.get("accepted_at") or not f.get("start") or not f.get("end"):
            continue
        if pd.Timestamp(f["accepted_at"]) >= cutoff:
            continue
        key = (f["start"], f["end"])
        if key not in best or f["accepted_at"] > best[key]["accepted_at"]:
            best[key] = f
    return sorted(best.values(), key=lambda f: (f["end"], f["accepted_at"]))


def _ttm(avail: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    """TTM = latest FY + (current YTD - prior-year YTD of same length)."""
    have = [f for f in avail if key in f]
    if not have:
        return None
    cur = have[-1]
    if _is_fy(cur):
        return {"value": cur[key], "end": cur["end"], "accepted_at": cur["accepted_at"], "method": "FY",
                "source": cur.get("source")}
    prior_end = pd.Timestamp(cur["end"]) - pd.DateOffset(years=1)
    prior = [f for f in have if _same_len(f, cur) and abs((pd.Timestamp(f["end"]) - prior_end).days) <= 10]
    fy = [f for f in have if _is_fy(f) and prior_end < pd.Timestamp(f["end"]) < pd.Timestamp(cur["end"])]
    if not prior or not fy:
        return None
    val = fy[-1][key] + cur[key] - prior[-1][key]
    return {"value": val, "end": cur["end"], "accepted_at": cur["accepted_at"], "method": "FY+YTD-YTDprior",
            "source": cur.get("source")}


def _yoy_growth(avail: List[Dict[str, Any]], key: str, mode: str = "legacy") -> Optional[Dict[str, Any]]:
    """mode="legacy" (Sessions 1-2): current YTD vs the prior year's YTD *as originally reported* in an older
    filing. mode="comparative" (Session 3, review P1-5): current YTD vs the prior-year comparative reported in
    the SAME filing (restated for spin-offs / discontinued operations; same acceptance time, so PIT-safe).
    If the filing carries no comparative, falls back to legacy and says so in `method`."""
    have = [f for f in avail if key in f]
    if not have:
        return None
    cur = have[-1]
    if mode == "comparative" and cur.get(key + "_prior"):
        g = (cur[key] / cur[key + "_prior"] - 1.0) * 100.0
        return {"value": g, "end": cur["end"], "accepted_at": cur["accepted_at"],
                "method": f"YoY {_days(cur)}d YTD vs same-filing comparative", "source": cur.get("source")}
    prior_end = pd.Timestamp(cur["end"]) - pd.DateOffset(years=1)
    prior = [f for f in have if _same_len(f, cur) and abs((pd.Timestamp(f["end"]) - prior_end).days) <= 10]
    if not prior or not prior[-1][key]:
        return None
    g = (cur[key] / prior[-1][key] - 1.0) * 100.0
    return {"value": g, "end": cur["end"], "accepted_at": cur["accepted_at"], "method": f"YoY {_days(cur)}d YTD",
            "source": cur.get("source")}


def _split_factor_after(splits: List[Dict[str, float]], when: str) -> float:
    f = 1.0
    for sp in splits or []:
        if sp["date"] > when[:10]:
            f *= float(sp["ratio"])
    return f


def pit_fundamentals(filings: List[Dict[str, Any]], cutoff: pd.Timestamp, price: float,
                     splits: Optional[List[Dict[str, float]]] = None, yoy: str = "legacy") -> Dict[str, Any]:
    """Valuation inputs as known strictly before `cutoff`. Returns tagged values (None if unavailable).

    `price` must be on the *current* share basis (snapshot `CloseSplitAdj`). As-reported EPS is
    divided by the product of splits after each filing's acceptance — a unit conversion only;
    ratios (P/E, P/B) are invariant to it, so this introduces no look-ahead."""
    avail = []
    for f in _available(filings, cutoff):
        k = _split_factor_after(splits or [], f["accepted_at"])
        f = dict(f)
        if "eps_diluted" in f:
            f["eps_diluted"] = f["eps_diluted"] / k
        if "diluted_shares" in f:
            f["diluted_shares"] = f["diluted_shares"] * k
        avail.append(f)
    out: Dict[str, Any] = {"_tags": {}}

    def put(name: str, value: Optional[float], meta: Optional[Dict[str, Any]], note: str) -> None:
        out[name] = None if value is None or not np.isfinite(value) else round(float(value), 4)
        if meta:
            src = meta.get("source") or "finnhub financials-reported (SEC XBRL)"
            out["_tags"][name] = {"source": f"{src}; {note}", "as_of": meta["accepted_at"][:10],
                                  "period_end": meta["end"], "method": meta.get("method", "")}

    ni = _ttm(avail, "net_income")
    eq_f = [f for f in avail if "equity" in f]
    eq = eq_f[-1] if eq_f else None
    rev_g = _yoy_growth(avail, "revenue", yoy)

    # Shares (current basis): latest weighted diluted shares. Fallback: NI / EPS from the latest
    # filing, only if its EPS is not a whole number (some as-reported EPS values are truncated).
    sh_f = [f for f in avail if f.get("diluted_shares")]
    shares, sh_note = (sh_f[-1]["diluted_shares"], "weighted diluted shares") if sh_f else (None, "")
    # Independent review P1-4: some filers tag share counts in millions (MCD: 718.2). If the same filing's
    # NI / shares disagrees with its own diluted EPS by >25% and the EPS is not an integer-truncated value,
    # use NI / EPS from that filing instead (both numbers are from the same accepted filing: no look-ahead).
    if sh_f:
        lf = sh_f[-1]
        e_, n_ = lf.get("eps_diluted"), lf.get("net_income")
        if e_ and n_ and abs(e_ - round(e_)) > 1e-9 and shares and abs((n_ / shares) / e_ - 1.0) > 0.25:
            shares, sh_note = n_ / e_, "NI / reported EPS (share count failed sanity check)"
    if shares is None:
        e_f = [f for f in avail if f.get("eps_diluted") and f.get("net_income")
               and abs(f["eps_diluted"] - round(f["eps_diluted"])) > 1e-9]
        if e_f:
            shares, sh_note = e_f[-1]["net_income"] / e_f[-1]["eps_diluted"], "NI / reported EPS"
    eps = (ni["value"] / shares) if (ni and shares and shares > 0) else None

    roe = (ni["value"] / eq["equity"] * 100.0) if (ni and eq and eq["equity"] > 0) else None
    put("roe", roe, ni, "TTM net income / latest equity")
    pe = (price / eps) if (eps and eps > 0) else None
    put("pe_trailing", pe, ni, f"split-adj close(D-1) / (TTM net income / {sh_note})")
    pb = (price / (eq["equity"] / shares)) if (eq and shares and shares > 0 and eq["equity"] > 0) else None
    put("pb_ratio", pb, eq, f"split-adj close(D-1) / (equity / {sh_note})")
    put("revenue_growth", rev_g["value"] if rev_g else None, rev_g, "YoY revenue growth, same-length YTD")
    return out


# ---------------------------------------------------------------------------
# Technicals (mirrors MarketDataFeed.get_stock_data, computed on truncated bars)
# ---------------------------------------------------------------------------

def pit_history_metrics(bars: pd.DataFrame) -> Dict[str, Any]:
    closes = bars["Close"].tail(252)
    hm: Dict[str, Any] = {}
    if len(closes) > 20:
        hm["return_20d_pct"] = round((closes.iloc[-1] / closes.iloc[-20] - 1) * 100, 2)
        hm["sma_20"] = round(float(closes.tail(20).mean()), 4)
        if len(closes) >= 50:
            hm["sma_50"] = round(float(closes.tail(50).mean()), 4)
        if len(closes) >= 200:
            hm["sma_200"] = round(float(closes.tail(200).mean()), 4)
        hm["volatility_annualized_pct"] = round(float(closes.pct_change().dropna().std() * (252 ** 0.5) * 100), 2)
    tail = bars.tail(253)
    prev = tail["Close"].shift(1)
    tr = pd.concat([tail["High"] - tail["Low"], (tail["High"] - prev).abs(), (tail["Low"] - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1]) if len(tail) >= 15 else None
    price = float(bars["Close"].iloc[-1])
    if atr and price > 0:
        hm["atr_14"] = round(atr, 4)
        hm["atr_pct"] = round(atr / price * 100.0, 2)
        stop_pct = round(max(4.0, min(15.0, hm["atr_pct"] * 2.5)), 1)
        hm["dynamic_stop_pct"] = stop_pct
        hm["dynamic_stop_loss_price"] = round(price * (1 - stop_pct / 100.0), 2)
    return hm
