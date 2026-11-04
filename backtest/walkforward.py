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
from core.ai_hedge_fund.alpha158_engine import Alpha158Engine  # noqa: E402
from core.ai_hedge_fund.cost_model import CostModel  # noqa: E402
from core.ai_hedge_fund.deterministic_metrics import DeterministicMetrics  # noqa: E402

HORIZONS = (1, 5, 20)
STRATEGIES = ("council", "factors_only", "buy_and_hold")
VIX_TURBULENCE = 30.0
SEED = 20261104
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


# ---------------------------------------------------------------------------
# Point-in-time decision inputs
# ---------------------------------------------------------------------------

def build_inputs(snap: Snapshot, ticker: str, D: pd.Timestamp, announced_at: str) -> Dict[str, Any]:
    """Everything a strategy may see. Uses bars through D-1 and filings accepted < announcement."""
    sessions = snap.sessions(ticker)
    prev = sessions[sessions < D]
    last_bar = prev[-1]
    bars = snap.bars_through(ticker, last_bar)
    px_val = float(bars["CloseSplitAdj"].iloc[-1])
    fund = pit_fundamentals(snap.fundamentals.get(ticker, []), pd.Timestamp(announced_at), px_val,
                            snap.splits.get(ticker, []))
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


def decide_council(inp: Dict[str, Any]) -> Dict[str, Any]:
    from core.ai_hedge_fund.agents import ALL_ANALYST_AGENTS, PortfolioManagerAgent, RiskManagerAgent
    from core.ai_hedge_fund.hedge_fund_council import HedgeFundCouncil
    stock, ctx = dict(inp["stock"]), dict(inp["context"])
    with pit_market_turbulence(inp["vix"]), _quiet():
        analysts = [a.evaluate(stock, ctx) for a in ALL_ANALYST_AGENTS]
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
        out[f"hit_{h}"] = int((und > 0) if decision["long"] else (und <= 0))
        stop = decision.get("stop_loss_price")
        window_low = float(lows.iloc[i0 + 1: i0 + h + 1].min())
        # stop is on the same adjusted-price basis as the snapshot lows (set from close of D-1)
        out[f"stop_breached_{h}"] = int(bool(decision["long"] and stop and window_low <= float(stop)))
    return out


def run(snapshot_root: str, n_events: int = 12, tickers: Optional[List[str]] = None,
        out_dir: str = RESULTS_DIR, write: bool = True) -> Dict[str, Any]:
    random.seed(SEED)
    np.random.seed(SEED)
    snap = Snapshot.load(snapshot_root)
    cost = CostModel()  # fixed defaults, independent of env, for reproducibility
    tickers = tickers or snap.manifest["tickers"]
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
            events.append((ev, D))
        for k, (ev, D) in enumerate(events[-n_events:], 1):
            inp = build_inputs(snap, t, D, ev["announced_at_et"])
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
                    **sc,
                })
            postmortems.setdefault(quarter, []).append(_postmortem_entry(t, D, ev, inp, decisions, rows[-len(STRATEGIES):]))
    df = pd.DataFrame(rows).sort_values(["ticker", "event_no", "strategy"]).reset_index(drop=True)
    summary = summarize(df)
    result = {"rows": df, "summary": summary, "postmortems": postmortems, "snapshot_id": snap.snapshot_id}
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


def summarize(df: pd.DataFrame) -> Dict[str, Any]:
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
    return out


def _fmt(x: Any, pct: bool = True) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x * 100:+.2f}%" if pct else f"{x:.2f}"


def summary_markdown(summary: Dict[str, Any], snap_id: str, manifest: Dict[str, Any]) -> str:
    L = [f"# Walk-forward earnings backtest — snapshot {snap_id}", "",
         "All figures: SOURCED FACT inputs from the snapshot (prices: yfinance adjusted; fundamentals: Finnhub "
         "as-reported, PIT by acceptedDate; events: yfinance earnings dates) — "
         f"source: `backtest/snapshots/{snap_id}`, as_of: {snap_id}. Strategy outputs are MODEL ASSUMPTION / backtest results.",
         "", "Costs: 5 bps commission + 5 bps slippage per side (long-only). Council runs with LUMINA_LLM_MODE=mock "
         "(deterministic persona rules; no LLM calls).", "",
         "| strategy | h | events | longs | hit rate | long hit | avg net | avg excess vs SPY | Sharpe (q, ann.) | max DD (q) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for key, m in summary["overall"].items():
        strat, h = key.split("|")
        L.append(f"| {strat} | T+{h} | {m['n_events']} | {m['n_long']} | {_fmt(m['hit_rate'])[1:]} | "
                 f"{_fmt(m['long_hit_rate'])[1:] if m['long_hit_rate'] is not None else 'n/a'} | {_fmt(m['avg_net_ret'])} | "
                 f"{_fmt(m['avg_excess_ret'])} | {_fmt(m['sharpe_quarterly_ann'], pct=False)} | {_fmt(m['max_drawdown_quarterly'])} |")
    L += ["", "## Council marginal contribution vs factors-only (paired by event)", "",
          "| h | mean(council − factors) | 95% bootstrap CI | decisions differ |", "|---|---|---|---|"]
    for h, m in summary["council_minus_factors"].items():
        L.append(f"| T+{h} | {_fmt(m['mean_diff'])} | [{_fmt(m['ci95_bootstrap'][0])}, {_fmt(m['ci95_bootstrap'][1])}] | "
                 f"{m['share_events_decisions_differ'] * 100:.0f}% |")
    L += ["", "## By quarter (T+5 avg net return / hit rate)", "",
          "| quarter | " + " | ".join(STRATEGIES) + " |", "|---|" + "---|" * len(STRATEGIES)]
    for qtr in sorted(summary["by_quarter"]):
        cells = []
        for s in STRATEGIES:
            m = summary["by_quarter"][qtr].get(f"{s}|5")
            cells.append(f"{_fmt(m['avg_net_ret'])} / {m['hit_rate'] * 100:.0f}% (n={m['n']}, long={m['n_long']})" if m else "")
        L.append(f"| {qtr} | " + " | ".join(cells) + " |")
    L += ["", "TradingAgents baseline: **skipped** — no offline/mock mode (LLM-only); see `backtest/tradingagents_adapter.py`.", ""]
    return "\n".join(L)


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
    a = ap.parse_args()
    if os.getenv("LUMINA_LLM_MODE", "mock") != "mock":
        raise SystemExit("walkforward runs with LUMINA_LLM_MODE=mock only (no live LLM spend; LLM look-ahead risk)")
    from backtest.snapshot import verify
    bad = verify(a.snapshot)
    if bad:
        raise SystemExit(f"snapshot hash mismatch: {bad}")
    res = run(a.snapshot, a.events, [t for t in a.tickers.split(",") if t] or None, a.out)
    print(json.dumps(res["paths"], indent=1))
    print("output sha256:", digest(res["paths"]))


if __name__ == "__main__":
    main()
