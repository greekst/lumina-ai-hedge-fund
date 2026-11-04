# -*- coding: utf-8 -*-
"""
backtest/walkforward.py — walk-forward earnings-event backtest.

For each ticker and each of its last N earnings announcements (default 12):
  * D  = last session whose close (16:00 ET) precedes the announcement
  * features frozen at the close of D-1 (prices, Alpha158, metrics, filings accepted < announcement)
  * entry at the close of D (before the news), exits at the close of D+h for h in {1, 5, 20}
  * round-trip fees + slippage from core.ai_hedge_fund.cost_model (long-only, no shorting)

Strategies scored on identical events:
  council       7 persona agents (LUMINA_LLM_MODE=mock -> deterministic persona rules)
                + cross-debate + CRO risk/veto + PM verdict; long iff BUY/ACCUMULATE
  factors_only  no agents/LLM: Alpha158 trend rule (ROC60 > 0 and close above 20d mean)
                + the same CRO veto; isolates the council's marginal contribution
  buy_and_hold  always long through the window, no trading costs (benchmark)
  tradingagents external TauricResearch/TradingAgents — skipped: no offline/mock mode
                (see backtest/tradingagents_adapter.py)

Reads only a frozen snapshot (backtest/snapshot.py). Output is byte-identical across reruns.

  python -m backtest.walkforward --snapshot backtest/snapshots/2026-11-04
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import random
from typing import Any, Dict, Iterator, List, Optional

import numpy as np
import pandas as pd

os.environ.setdefault("LUMINA_LLM_MODE", "mock")

from backtest.pit import Snapshot, decision_session, pit_fundamentals, pit_history_metrics  # noqa: E402
from backtest.stats import cluster_diff, cluster_diff_2way, describe  # noqa: E402
from core.ai_hedge_fund.alpha158_engine import Alpha158Engine  # noqa: E402
from core.ai_hedge_fund.cost_model import CostModel  # noqa: E402
from core.ai_hedge_fund.deterministic_metrics import DeterministicMetrics  # noqa: E402

HORIZONS = (1, 5, 20)
STRATEGIES = ("council", "factors_only", "buy_and_hold")
VIX_TURBULENCE = 30.0
VIX_BUCKETS = ((0.0, 15.0, "VIX<15"), (15.0, 25.0, "VIX15-25"), (25.0, float("inf"), "VIX>25"))


def vix_bucket(v: Optional[float]) -> str:
    if v is None or not np.isfinite(v):
        return "n/a"
    for lo, hi, name in VIX_BUCKETS:
        if lo <= v < hi:
            return name
    return "n/a"
SEED = 20261104
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


# ---------------------------------------------------------------------------
# Point-in-time decision inputs
# ---------------------------------------------------------------------------

def build_inputs(snap: Snapshot, ticker: str, D: pd.Timestamp, announced_at: str, yoy: str = "legacy") -> Dict[str, Any]:
    """Everything a strategy may see. Uses bars through D-1 and filings accepted < announcement."""
    sessions = snap.sessions(ticker)
    prev = sessions[sessions < D]
    last_bar = prev[-1]
    bars = snap.bars_through(ticker, last_bar)
    px_val = float(bars["CloseSplitAdj"].iloc[-1])
    # Filings must be public before the decision (close of D) AND before the announcement. For a
    # pre-market release D is the previous session, so a filing accepted overnight is excluded.
    cutoff = min(pd.Timestamp(announced_at), pd.Timestamp(f"{D.date()} 16:00:00"))
    fund = pit_fundamentals(snap.fundamentals.get(ticker, []), cutoff, px_val, snap.splits.get(ticker, []), yoy=yoy)
    hm = pit_history_metrics(bars)
    det = DeterministicMetrics.compute_price_metrics(bars.tail(252))
    a158 = Alpha158Engine.get_latest_factors(bars.tail(300)[["Open", "High", "Low", "Close", "Volume"]])
    vix_bars = snap.bars_through("^VIX", last_bar)
    vix = float(vix_bars["Close"].iloc[-1]) if len(vix_bars) else None
    stock = {
        "symbol": ticker, "name": ticker, "company_name": ticker, "currency": "USD",
        "current_price": round(float(bars["Close"].iloc[-1]), 4),
        "pe_trailing": fund["pe_trailing"], "pb_ratio": fund["pb_ratio"], "roe": fund["roe"],
        "revenue_growth": fund["revenue_growth"], "history_metrics": hm,
        "atr_pct": hm.get("atr_pct"), "dynamic_stop_pct": hm.get("dynamic_stop_pct"),
        "dynamic_stop_loss_price": hm.get("dynamic_stop_loss_price"),
        "news_sentiment_summary": "N/A (no point-in-time news archive in snapshot)",
    }
    return {
        "stock": stock, "fund_tags": fund["_tags"], "det": det, "alpha158": a158, "vix": vix,
        "features_through": str(last_bar.date()),
        "context": {"lang": "en", "deterministic_metrics": det,
                    "qlib_alpha158": {k: round(a158[k], 6) for k in ("ROC20", "ROC60", "MA20", "STD20") if k in a158}},
    }


@contextlib.contextmanager
def pit_market_turbulence(vix: Optional[float]) -> Iterator[None]:
    """Replace the live options-GEX turbulence feed with a PIT proxy: VIX(D-1) >= 30."""
    from core.ai_hedge_fund.options_gex_feed import OptionsGexFeed
    orig = OptionsGexFeed.__dict__["get_market_turbulence_warning"]
    turb = bool(vix is not None and vix >= VIX_TURBULENCE)
    OptionsGexFeed.get_market_turbulence_warning = classmethod(
        lambda cls: {"is_turbulence": turb, "summary_text": f"PIT proxy: VIX={vix}", "source": "VIX close D-1"})
    try:
        yield
    finally:
        OptionsGexFeed.get_market_turbulence_warning = orig


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


def decide_council(inp: Dict[str, Any], analyst_override: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Mock council. `analyst_override` (agent_id -> sanitized analyst result) replaces individual
    persona outputs, e.g. with live-LLM stances; every other step is identical and deterministic."""
    from core.ai_hedge_fund.agents import ALL_ANALYST_AGENTS, PortfolioManagerAgent, RiskManagerAgent
    from core.ai_hedge_fund.hedge_fund_council import HedgeFundCouncil
    stock, ctx = dict(inp["stock"]), dict(inp["context"])
    over = analyst_override or {}
    with pit_market_turbulence(inp["vix"]), _quiet():
        analysts = [dict(over[a.agent_id]) if a.agent_id in over else a.evaluate(stock, ctx) for a in ALL_ANALYST_AGENTS]
        debate = HedgeFundCouncil._run_cross_debate(stock, analysts, ctx)
        risk = RiskManagerAgent.evaluate_risk(stock, analysts, ctx)
        syn = PortfolioManagerAgent.synthesize_verdict(stock, analysts, risk, ctx, cross_debate=debate)
    v = syn["verdict"]
    return {
        "action": v["action"], "allocation_pct": float(v["allocation_pct"]), "confidence": int(v["confidence_score"]),
        "long": int(v["action"] in ("BUY", "ACCUMULATE")), "veto": int(bool(risk.get("veto_triggered"))),
        "stop_loss_price": risk.get("stop_loss_price"), "degraded": int(bool(v.get("degraded_mode"))),
        "agent_scores": {a["agent_id"]: int(a["score"]) for a in analysts},
        "agent_stances": {a["agent_id"]: a["stance"] for a in analysts},
        "debate_occurred": int(bool(debate.get("occurred"))), "veto_reason": risk.get("veto_reason", ""),
    }


def decide_factors_only(inp: Dict[str, Any]) -> Dict[str, Any]:
    from core.ai_hedge_fund.agents import RiskManagerAgent
    a = inp["alpha158"]
    trend = (a.get("ROC60", 0.0) > 0.0) and (a.get("MA20", 0.0) < 0.0)  # MA20 = mean20/close - 1 < 0 -> close above mean
    with pit_market_turbulence(inp["vix"]), _quiet():
        risk = RiskManagerAgent.evaluate_risk(dict(inp["stock"]), [], dict(inp["context"]))
    veto = bool(risk.get("veto_triggered"))
    long_ = int(trend and not veto)
    return {"action": "BUY" if long_ else "HOLD", "allocation_pct": 5.0 if long_ else 0.0,
            "confidence": int(round(50 + 50 * np.tanh(10 * a.get("ROC60", 0.0)))), "long": long_, "veto": int(veto),
            "stop_loss_price": risk.get("stop_loss_price"), "degraded": 0}


def decide_buy_and_hold(inp: Dict[str, Any]) -> Dict[str, Any]:
    return {"action": "HOLD_LONG", "allocation_pct": 100.0, "confidence": 50, "long": 1, "veto": 0,
            "stop_loss_price": None, "degraded": 0}


DECIDERS = {"council": decide_council, "factors_only": decide_factors_only, "buy_and_hold": decide_buy_and_hold}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score(snap: Snapshot, ticker: str, D: pd.Timestamp, strategy: str, decision: Dict[str, Any],
          cost: CostModel) -> Dict[str, Any]:
    sessions = snap.sessions(ticker)
    i0 = sessions.get_loc(D)
    entry = snap.close_on(ticker, D)
    spy_entry = snap.close_on("SPY", D)
    etf = (snap.universe.get(ticker) or {}).get("sector_etf")
    if etf and (D not in snap.prices[etf].index or sessions[i0 + max(HORIZONS)] not in snap.prices[etf].index):
        # Session 3: the ETF did not trade yet (XLC from 2018-06, XLRE from 2015-10) -> SPY as the benchmark
        etf = "SPY"
    etf_entry = snap.close_on(etf, D) if etf else None
    out: Dict[str, Any] = {"entry_close": entry}
    lows = snap.prices[ticker]["Low"]
    for h in HORIZONS:
        exit_day = sessions[i0 + h]
        px = snap.close_on(ticker, exit_day)
        und = px / entry - 1.0
        spy = snap.close_on("SPY", exit_day) / spy_entry - 1.0
        if not decision["long"]:
            net = 0.0
        elif strategy == "buy_and_hold":
            net = und
        else:
            net = cost.round_trip_return(entry, px)
        out[f"exit_date_{h}"] = str(exit_day.date())
        out[f"underlying_ret_{h}"] = und
        out[f"spy_ret_{h}"] = spy
        out[f"net_ret_{h}"] = net
        out[f"excess_ret_{h}"] = (net - spy) if decision["long"] else 0.0
        sec = (snap.close_on(etf, exit_day) / etf_entry - 1.0) if etf else float("nan")
        out[f"sector_ret_{h}"] = sec
        out[f"excess_sector_{h}"] = (net - sec) if decision["long"] else 0.0
        out[f"hit_{h}"] = int((und > 0) if decision["long"] else (und <= 0))
        stop = decision.get("stop_loss_price")
        window_low = float(lows.iloc[i0 + 1: i0 + h + 1].min())
        # stop is on the same adjusted-price basis as the snapshot lows (set from close of D-1)
        out[f"stop_breached_{h}"] = int(bool(decision["long"] and stop and window_low <= float(stop)))
    return out


def run(snapshot_root: str, n_events: Optional[int] = 12, tickers: Optional[List[str]] = None,
        out_dir: str = RESULTS_DIR, write: bool = True, universe: str = "static", d_from: Optional[str] = None,
        d_to: Optional[str] = None, yoy: str = "legacy", tag: str = "", two_way: bool = False,
        snap: Optional[Snapshot] = None) -> Dict[str, Any]:
    """universe="static": every snapshot ticker (Sessions 1-2). universe="pit" (Session 3): an event counts only
    if its company ranks <= TOP_N by point-in-time market cap at the close of D-1 (backtest/pit_universe.py).
    universe="static_top:YYYY-MM-DD": the TOP_N companies by market cap at that session, applied to every
    event (the survivorship-biased comparison on the same data). d_from/d_to bound the decision date D."""
    from backtest import pit_universe as PU
    random.seed(SEED)
    np.random.seed(SEED)
    snap = snap or Snapshot.load(snapshot_root)
    cost = CostModel()  # fixed defaults, independent of env, for reproducibility
    tickers = tickers or snap.manifest["tickers"]
    spy = snap.sessions("SPY")
    rank_cache: Dict[pd.Timestamp, Dict[str, int]] = {}

    def rank(day: pd.Timestamp) -> Dict[str, int]:
        if day not in rank_cache:
            rank_cache[day] = PU.rank_on(snap, day)
        return rank_cache[day]
    static_set = None
    if universe.startswith("static_top:"):
        r = rank(pd.Timestamp(universe.split(":", 1)[1]))
        static_set = {t for t, v in r.items() if v <= PU.TOP_N}
        tickers = [t for t in tickers if t in static_set]
    rows: List[Dict[str, Any]] = []
    postmortems: Dict[str, List[Dict[str, Any]]] = {}
    for t in tickers:
        sessions = snap.sessions(t)
        events = []
        for ev in snap.events.get(t, []):
            D = decision_session(sessions, ev["announced_at_et"])
            if D is None:
                continue
            i0 = sessions.get_loc(D)
            if i0 < 300 or i0 + max(HORIZONS) >= len(sessions):
                continue
            if (d_from and D < pd.Timestamp(d_from)) or (d_to and D > pd.Timestamp(d_to)):
                continue
            rk = None
            if universe == "pit":
                prev = spy[spy < D]
                rk = rank(prev[-1]).get(t) if len(prev) else None
                if rk is None or rk > PU.TOP_N:
                    continue
            events.append((ev, D, rk))
        for k, (ev, D, rk) in enumerate(events[-n_events:] if n_events else events, 1):
            inp = build_inputs(snap, t, D, ev["announced_at_et"], yoy=yoy)
            ann = pd.Timestamp(ev["announced_at_et"])
            quarter = f"{ann.year}Q{(ann.month - 1) // 3 + 1}"
            decisions = {}
            for strat in STRATEGIES:
                dec = DECIDERS[strat](inp)
                decisions[strat] = dec
                sc = score(snap, t, D, strat, dec, cost)
                rows.append({
                    "snapshot_id": snap.snapshot_id, "ticker": t, "event_no": k, "quarter": quarter,
                    "announced_at_et": ev["announced_at_et"], "event_source": ev["source"],
                    "decision_date": str(D.date()), "features_through": inp["features_through"],
                    "strategy": strat, "action": dec["action"], "long": dec["long"],
                    "allocation_pct": dec["allocation_pct"], "confidence": dec["confidence"],
                    "cro_veto": dec["veto"], "degraded": dec["degraded"],
                    "pe_trailing": inp["stock"]["pe_trailing"], "roe": inp["stock"]["roe"],
                    "revenue_growth": inp["stock"]["revenue_growth"], "vix_d1": inp["vix"],
                    "vix_bucket": vix_bucket(inp["vix"]),
                    "sector": (snap.universe.get(t) or {}).get("sector", "n/a"),
                    "sector_etf": (snap.universe.get(t) or {}).get("sector_etf", ""),
                    **sc,
                    **({"pit_rank_d1": rk} if universe == "pit" else {}),
                })
            postmortems.setdefault(quarter, []).append(_postmortem_entry(t, D, ev, inp, decisions, rows[-len(STRATEGIES):]))
    df = pd.DataFrame(rows).sort_values(["ticker", "event_no", "strategy"]).reset_index(drop=True)
    summary = summarize(df, two_way=two_way)
    out_id = snap.snapshot_id + (f"_{tag}" if tag else "")
    result = {"rows": df, "summary": summary, "postmortems": postmortems, "snapshot_id": out_id}
    if universe != "static" or d_from or d_to or yoy != "legacy":
        summary["run"] = {"universe": universe, "decision_date_from": d_from, "decision_date_to": d_to,
                          "yoy": yoy, "n_events_per_ticker": n_events, "top_n": PU.TOP_N,
                          "n_tickers_with_events": int(df.ticker.nunique()) if len(df) else 0}
    if write:
        result["paths"] = write_outputs(result, out_dir, snap)
    return result


def _postmortem_entry(t, D, ev, inp, decisions, scored_rows) -> Dict[str, Any]:
    """Deterministic expected-vs-actual record (stored for later learning; nothing is fit)."""
    by = {r["strategy"]: r for r in scored_rows}
    c = decisions["council"]
    atr = inp["stock"]["history_metrics"].get("atr_pct") or 0.0
    act1 = by["council"]["underlying_ret_1"] * 100.0
    return {
        "ticker": t, "announced_at_et": ev["announced_at_et"], "decision_date": str(D.date()),
        "expected": {
            "council_action": c["action"], "council_confidence": c["confidence"], "council_long": c["long"],
            "agent_stances": c.get("agent_stances"), "agent_scores": c.get("agent_scores"),
            "cro_veto": c["veto"], "veto_reason": c.get("veto_reason", ""),
            "factors_only_long": decisions["factors_only"]["long"],
            "implied_1d_move_pct_from_atr": round(atr, 4),
            "label": "MODEL ASSUMPTION",
        },
        "actual": {f"ret_{h}d_pct": round(by["council"][f"underlying_ret_{h}"] * 100.0, 4) for h in HORIZONS}
        | {f"spy_{h}d_pct": round(by["council"][f"spy_ret_{h}"] * 100.0, 4) for h in HORIZONS}
        | {"label": "SOURCED FACT", "source": "snapshot prices (yfinance adjusted close)"},
        "diff": {
            **{f"council_correct_{h}d": by["council"][f"hit_{h}"] for h in HORIZONS},
            **{f"factors_correct_{h}d": by["factors_only"][f"hit_{h}"] for h in HORIZONS},
            "abs_move_vs_atr_ratio": round(abs(act1) / atr, 4) if atr else None,
            "stop_breached_20d": by["council"]["stop_breached_20"],
            "missed_upside": int(not c["long"] and by["council"]["underlying_ret_20"] > 0.05),
            "avoided_drawdown": int(not c["long"] and by["council"]["underlying_ret_20"] < -0.05),
        },
    }


# ---------------------------------------------------------------------------
# Summary statistics (deterministic)
# ---------------------------------------------------------------------------

def _bootstrap_ci(x: np.ndarray, n: int = 2000, seed: int = SEED) -> List[float]:
    if len(x) < 2:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def summarize(df: pd.DataFrame, two_way: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {"overall": {}, "by_quarter": {}, "council_minus_factors": {}}
    for strat in STRATEGIES:
        s = df[df.strategy == strat]
        for h in HORIZONS:
            q = s.groupby("quarter")[f"net_ret_{h}"].mean().sort_index()
            sd = q.std(ddof=1)
            equity = (1.0 + q).cumprod()
            mdd = float((equity / equity.cummax() - 1.0).min()) if len(q) else 0.0
            longs = s[s.long == 1]
            out["overall"][f"{strat}|{h}"] = {
                "n_events": int(len(s)), "n_long": int(len(longs)),
                "hit_rate": float(s[f"hit_{h}"].mean()),
                "long_hit_rate": float(longs[f"hit_{h}"].mean()) if len(longs) else None,
                "avg_net_ret": float(s[f"net_ret_{h}"].mean()),
                "avg_excess_ret": float(s[f"excess_ret_{h}"].mean()),
                "avg_net_ret_when_long": float(longs[f"net_ret_{h}"].mean()) if len(longs) else None,
                "sharpe_quarterly_ann": float(q.mean() / sd * np.sqrt(4)) if sd and sd > 0 else None,
                "max_drawdown_quarterly": mdd,
            }
            for qtr, g in s.groupby("quarter"):
                out["by_quarter"].setdefault(qtr, {})[f"{strat}|{h}"] = {
                    "n": int(len(g)), "n_long": int(g.long.sum()),
                    "avg_net_ret": float(g[f"net_ret_{h}"].mean()), "hit_rate": float(g[f"hit_{h}"].mean()),
                }
    for h in HORIZONS:
        a = df[df.strategy == "council"].set_index(["ticker", "event_no"])[f"net_ret_{h}"]
        b = df[df.strategy == "factors_only"].set_index(["ticker", "event_no"])[f"net_ret_{h}"]
        d = (a - b).dropna().to_numpy()
        out["council_minus_factors"][str(h)] = {
            "mean_diff": float(d.mean()), "ci95_bootstrap": _bootstrap_ci(d), "n": int(len(d)),
            "share_events_decisions_differ": float((df[df.strategy == "council"].long.to_numpy()
                                                    != df[df.strategy == "factors_only"].long.to_numpy()).mean()),
        }
    if "sector" in df.columns and (df["sector"] != "n/a").any():
        out["cells"] = summarize_cells(df, two_way=two_way)
    return out


CELL_METRICS = ("net_ret", "excess_ret", "excess_sector")


def _cell(sub: pd.DataFrame, two_way: bool = False) -> Dict[str, Any]:
    d: Dict[str, Any] = {"n_events": int((sub.strategy == "council").sum())}
    for strat in STRATEGIES:
        s = sub[sub.strategy == strat]
        for h in HORIZONS:
            for m in CELL_METRICS:
                d[f"{strat}|{h}|{m}"] = describe(s[f"{m}_{h}"].to_numpy(), s["month"].to_numpy())
    for strat in ("council", "factors_only"):
        s = sub[sub.strategy == strat]
        d[f"{strat}|long_rate"] = float(s["long"].mean()) if len(s) else None
        for h in HORIZONS:
            # selection skill on the sector-relative underlying return (decision-independent outcome)
            y = (s[f"underlying_ret_{h}"] - s[f"sector_ret_{h}"])
            d[f"{strat}|{h}|selection_skill"] = cluster_diff(y.to_numpy(), s["long"].to_numpy() == 1, s["month"].to_numpy())
            # Independent review P1-1: in a universe picked by today's size, tickers carry persistent drift, so
            # long-minus-flat also measures WHICH tickers a strategy likes. Demeaning within ticker (fixed effects)
            # leaves only the timing of the decision across that ticker's own events.
            yd = y - y.groupby(s["ticker"]).transform("mean")
            d[f"{strat}|{h}|selection_skill_fe"] = cluster_diff(yd.to_numpy(), s["long"].to_numpy() == 1, s["month"].to_numpy())
            if two_way:   # Session 3: two-way (season x ticker) pigeonhole bootstrap
                d[f"{strat}|{h}|selection_skill_fe_2way"] = cluster_diff_2way(
                    yd.to_numpy(), s["long"].to_numpy() == 1, s["month"].to_numpy(), s["ticker"].to_numpy())
    a = sub[sub.strategy == "council"].set_index(["ticker", "event_no"])
    b = sub[sub.strategy == "factors_only"].set_index(["ticker", "event_no"])
    for h in HORIZONS:
        diff = (a[f"net_ret_{h}"] - b[f"net_ret_{h}"]).dropna()
        d[f"council_minus_factors|{h}"] = describe(diff.to_numpy(), a.loc[diff.index, "month"].to_numpy())
    return d


def summarize_cells(df: pd.DataFrame, two_way: bool = False) -> Dict[str, Any]:
    """Session 2: overall / VIX(D-1) regime / GICS sector cells with iid and season-clustered
    bootstrap CIs and minimum detectable effects. Clusters = calendar quarter of the decision date."""
    # Clusters = earnings season (calendar quarter of D). Independent review P1-2: calendar months understate
    # uncertainty (T+20 windows cross month ends; events bunch in Jan/Apr/Jul/Oct, so ~13 seasons, not 36 months).
    d = pd.to_datetime(df["decision_date"])
    df = df.assign(month=d.dt.year.astype(str) + "Q" + d.dt.quarter.astype(str))
    res: Dict[str, Any] = {"overall": _cell(df, two_way), "by_regime": {}, "by_sector": {}}
    for name, g in sorted(df.groupby("vix_bucket"), key=lambda kv: kv[0]):
        res["by_regime"][name] = _cell(g, two_way)
    for name, g in sorted(df.groupby("sector"), key=lambda kv: kv[0]):
        res["by_sector"][name] = _cell(g, two_way)
    return res


def _fmt(x: Any, pct: bool = True, src: str = "", as_of: str = "", decimals: int = 2) -> str:
    """Tagged cell: `value [SOURCED FACT · src, as_of]` (hard rule 5)."""
    from core.reporting.tagged import fact
    v = None if x is None or (isinstance(x, float) and not np.isfinite(x)) else (x * 100 if pct else x)
    t = fact(v, src, as_of, unit="%" if pct else "", decimals=decimals)
    return t.render(with_label=False)


def summary_markdown(summary: Dict[str, Any], snap_id: str, manifest: Dict[str, Any]) -> str:
    src = f"wf-backtest {snap_id}"
    F = lambda x, pct=True: _fmt(x, pct, src, snap_id)  # noqa: E731
    N = lambda x: _fmt(x, False, src, snap_id, decimals=0)  # noqa: E731  (counts)
    L = [f"# Walk-forward earnings backtest — snapshot {snap_id}", "",
         f"Source alias `{src}` = simulated strategy results computed by backtest/walkforward.py from the frozen snapshot "
         f"`backtest/snapshots/{snap_id}` (prices: {manifest['sources'].get('prices', 'n/a')}; fundamentals: "
         f"{manifest['sources'].get('fundamentals', 'n/a')}; events: {manifest['sources'].get('events', 'n/a')}). <!-- text-only -->", "",
         "Costs: commission and slippage of five bps each per side (long-only). Council runs with LUMINA_LLM_MODE=mock "
         "(deterministic persona rules; no LLM calls). Sharpe: quarterly equal-weight portfolio of event returns, "
         "annualised by sqrt(four). <!-- text-only -->", ""]
    run = summary.get("run")
    if run:
        L += [f"Run (Session 3): universe `{run['universe']}`, decision dates `{run['decision_date_from']}` to "
              f"`{run['decision_date_to']}`, YoY growth method `{run['yoy']}`, events per ticker "
              f"{'all in window' if not run['n_events_per_ticker'] else 'last N'}; tickers with events: "
              f"{N(run['n_tickers_with_events'])}. In the pit universe an event counts only if its company ranks in the top "
              f"hundred by point-in-time market cap at the close of D-1 (backtest/pit_universe.py). <!-- text-only -->", ""]
    L += ["| strategy / horizon | events | longs | hit rate | long hit | avg net | avg excess vs SPY | Sharpe (q, ann.) | max DD (q) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for key, m in summary["overall"].items():
        strat, h = key.split("|")
        L.append(f"| {strat} T+{h} | {N(m['n_events'])} | {N(m['n_long'])} | {F(m['hit_rate'])} | "
                 f"{F(m['long_hit_rate'])} | {F(m['avg_net_ret'])} | {F(m['avg_excess_ret'])} | "
                 f"{F(m['sharpe_quarterly_ann'], False)} | {F(m['max_drawdown_quarterly'])} |")
    L += ["", "## Council marginal contribution vs factors-only (paired by event)", "",
          "| horizon | mean(council − factors) | 95% i.i.d. bootstrap CI low (too narrow, see clustered CIs) | i.i.d. CI high | share of events where decisions differ |",
          "|---|---|---|---|---|"]
    for h, m in summary["council_minus_factors"].items():
        L.append(f"| T+{h} | {F(m['mean_diff'])} | {F(m['ci95_bootstrap'][0])} | {F(m['ci95_bootstrap'][1])} | "
                 f"{F(m['share_events_decisions_differ'])} |")
    L += ["", "## By quarter — T+5 average net return (hit rate)", "",
          "| quarter | " + " | ".join(STRATEGIES) + " |", "|---|" + "---|" * len(STRATEGIES)]
    for qtr in sorted(summary["by_quarter"]):
        cells = []
        for s_ in STRATEGIES:
            m = summary["by_quarter"][qtr].get(f"{s_}|5")
            cells.append(f"{F(m['avg_net_ret'])} ({F(m['hit_rate'])})" if m else "")
        L.append(f"| {qtr} | " + " | ".join(cells) + " |")
    if "cells" in summary:
        L += cells_markdown(summary["cells"], F, N)
    L += ["", "TradingAgents baseline: skipped — no offline/mock mode (LLM-only); see backtest/tradingagents_adapter.py. <!-- text-only -->", ""]
    md = "\n".join(L)
    from core.reporting.tagged import untagged_numbers
    bad = untagged_numbers(md)
    if bad:
        raise ValueError(f"untagged numbers in summary: {bad[:5]}")
    return md


MIN_CLUSTERS = 8  # below this many seasons a cluster bootstrap CI is not reported (unreliable)


def _ci(F, m: Dict[str, Any], kind: str = "cluster") -> str:
    c = m.get(kind) or {}
    if m.get("mean") is None:
        return "n/a"
    lo, hi = c.get("lo"), c.get("hi")
    if kind == "cluster" and (c.get("n_clusters") or 0) < MIN_CLUSTERS:
        return f"{F(m['mean'])} [too few seasons for a CI]"
    return f"{F(m['mean'])} [{F(lo)} … {F(hi)}]" if lo is not None else F(m["mean"])


def cells_markdown(cells: Dict[str, Any], F, N) -> List[str]:
    L = ["", "## Session 2 — inference with uncertainty", "",
         "Each cell: mean, then the 95% season-clustered bootstrap CI in brackets (clusters = calendar quarter of D; "
         "events in one earnings season share market moves and overlapping windows, so i.i.d. CIs would be too narrow; "
         "correlation within a ticker across seasons is not modelled). Excess vs sector = net return "
         "minus the matching SPDR sector ETF over the same window; a flat (not long) decision has zero excess. "
         "MDE = minimum detectable effect at five percent two-sided and eighty percent power, from the clustered SE. "
         "<!-- text-only -->", "",
         "### Overall, all horizons", "",
         "| strategy / horizon | events | avg net | excess vs SPY | excess vs sector ETF | MDE (excess vs sector) |",
         "|---|---|---|---|---|---|"]
    o = cells["overall"]
    for strat in STRATEGIES:
        for h in HORIZONS:
            ms = o[f"{strat}|{h}|excess_sector"]
            L.append(f"| {strat} T+{h} | {N(ms['n'])} | {_ci(F, o[f'{strat}|{h}|net_ret'])} | "
                     f"{_ci(F, o[f'{strat}|{h}|excess_ret'])} | {_ci(F, ms)} | {F(ms['mde80'])} |")
    L += ["", "### Council minus factors-only (paired by event)", "",
          "| horizon | events | mean diff [clustered CI] | i.i.d. CI low | i.i.d. CI high | MDE |", "|---|---|---|---|---|---|"]
    for h in HORIZONS:
        m = o[f"council_minus_factors|{h}"]
        L.append(f"| T+{h} | {N(m['n'])} | {_ci(F, m)} | {F(m['iid']['lo'])} | {F(m['iid']['hi'])} | {F(m['mde80'])} |")
    L += ["", "### Selection skill: do the events a strategy goes long on beat the ones it skips?", "",
          "Mean sector-relative underlying return (stock minus its sector ETF, before costs) of long events minus that "
          "of flat events. It does not reward being long more often. The pooled version still mixes in WHICH tickers a "
          "strategy favours (tickers in a universe chosen by today's size carry persistent drift), so the headline is "
          "the within-ticker version: returns demeaned by ticker, i.e. does the decision time a ticker's own events? "
          "<!-- text-only -->", "",
          "| strategy / horizon | long rate | longs | flats | long − flat, within ticker (fixed effects) [clustered CI] | MDE | long − flat, pooled [clustered CI] |",
          "|---|---|---|---|---|---|---|"]
    for strat in ("council", "factors_only"):
        for h in HORIZONS:
            m, fe = o[f"{strat}|{h}|selection_skill"], o[f"{strat}|{h}|selection_skill_fe"]
            L.append(f"| {strat} T+{h} | {F(o[f'{strat}|long_rate'])} | {N(m['n_in'])} | {N(m['n_out'])} | {_sk(F, fe)} | "
                     f"{F(fe['mde80'])} | {_sk(F, m)} |")
    if f"council|{HORIZONS[0]}|selection_skill_fe_2way" in o:
        L += ["", "Two-way clustered (earnings season x ticker, pigeonhole bootstrap; conservative) version of the "
              "within-ticker selection skill: <!-- text-only -->", "",
              "| strategy / horizon | long − flat, within ticker | 95% CI low | 95% CI high | one-sided 95% lower bound | "
              "one-sided p | seasons | tickers | MDE (one-sided, 80% power) |", "|---|---|---|---|---|---|---|---|---|"]
        for strat in ("council", "factors_only"):
            for h in HORIZONS:
                w = o[f"{strat}|{h}|selection_skill_fe_2way"]
                L.append(f"| {strat} T+{h} | {F(w['mean'])} | {F(w['lo'])} | {F(w['hi'])} | {F(w['p05'])} | "
                         f"{F(w['p_one_sided'], False)} | {N(w['n_c1'])} | {N(w['n_c2'])} | {F(w['mde80_one_sided'])} |")
    for title, key in (("By regime: VIX close on D-1", "by_regime"), ("By GICS sector", "by_sector")):
        L += ["", f"### {title} — T+20", "",
              "| cell | events | seasons | buy-and-hold excess vs sector | council excess vs sector | factors-only excess vs sector | council − factors | MDE (council − factors) | council selection skill (within ticker) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for name, c in cells[key].items():
            d = c["council_minus_factors|20"]
            nc = (d.get("cluster") or {}).get("n_clusters") or 0
            L.append(f"| {name} | {N(c['n_events'])} | {N(nc)} | {_ci(F, c['buy_and_hold|20|excess_sector'])} | "
                     f"{_ci(F, c['council|20|excess_sector'])} | {_ci(F, c['factors_only|20|excess_sector'])} | "
                     f"{_ci(F, d)} | {F(d['mde80']) if nc >= MIN_CLUSTERS else 'n/a'} | "
                     f"{_sk(F, c['council|20|selection_skill_fe']) if nc >= MIN_CLUSTERS else 'n/a'} |")
    return L


def _sk(F, m: Dict[str, Any]) -> str:
    return f"{F(m['mean'])} [{F(m['lo'])} … {F(m['hi'])}]" if m.get("mean") is not None else "n/a"


def write_outputs(result: Dict[str, Any], out_dir: str, snap: Snapshot) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    sid = result["snapshot_id"]
    csv_path = os.path.join(out_dir, f"walkforward_{sid}.csv")
    result["rows"].to_csv(csv_path, index=False, float_format="%.8f", lineterminator="\n")
    js_path = os.path.join(out_dir, f"walkforward_{sid}_summary.json")
    with open(js_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result["summary"], fh, indent=1, sort_keys=True, default=lambda x: None)
    md_path = os.path.join(out_dir, f"walkforward_{sid}_summary.md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(summary_markdown(result["summary"], sid, snap.manifest))
    pm_dir = os.path.join(out_dir, f"postmortem_{sid}")
    os.makedirs(pm_dir, exist_ok=True)
    for qtr, entries in sorted(result["postmortems"].items()):
        with open(os.path.join(pm_dir, f"{qtr}.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(sorted(entries, key=lambda e: e["ticker"]), fh, indent=1, sort_keys=True, ensure_ascii=False)
    return {"csv": csv_path, "summary_json": js_path, "summary_md": md_path, "postmortem_dir": pm_dir}


def digest(paths: Dict[str, str]) -> str:
    h = hashlib.sha256()
    files = [paths["csv"], paths["summary_json"], paths["summary_md"]]
    files += sorted(os.path.join(paths["postmortem_dir"], f) for f in os.listdir(paths["postmortem_dir"]))
    for p in files:
        with open(p, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--snapshot", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots", "2026-11-04"))
    ap.add_argument("--events", type=int, default=12)
    ap.add_argument("--tickers", default="")
    ap.add_argument("--out", default=RESULTS_DIR)
    ap.add_argument("--universe", default="static", help="static | pit | static_top:YYYY-MM-DD (Session 3)")
    ap.add_argument("--from", dest="d_from", default=None, help="first decision date (inclusive)")
    ap.add_argument("--to", dest="d_to", default=None, help="last decision date (inclusive)")
    ap.add_argument("--yoy", default="legacy", choices=("legacy", "comparative"))
    ap.add_argument("--tag", default="", help="suffix for output file names")
    ap.add_argument("--two-way", action="store_true", help="add season x ticker clustered selection skill")
    a = ap.parse_args()
    if os.getenv("LUMINA_LLM_MODE", "mock") != "mock":
        raise SystemExit("walkforward runs with LUMINA_LLM_MODE=mock only (no live LLM spend; LLM look-ahead risk)")
    from backtest.snapshot import verify
    bad = verify(a.snapshot)
    if bad:
        raise SystemExit(f"snapshot hash mismatch: {bad}")
    res = run(a.snapshot, a.events or None, [t for t in a.tickers.split(",") if t] or None, a.out, universe=a.universe,
              d_from=a.d_from, d_to=a.d_to, yoy=a.yoy, tag=a.tag, two_way=a.two_way)
    print(json.dumps(res["paths"], indent=1))
    print("output sha256:", digest(res["paths"]))


if __name__ == "__main__":
    main()
