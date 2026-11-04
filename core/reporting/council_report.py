# -*- coding: utf-8 -*-
"""
council_report.py — source-tagged council report (Hard rules 3 & 5).

Every number is a `Tagged` value: `value [SOURCED FACT|MODEL ASSUMPTION · source, as_of]`.
Free text written by a model (LLM or persona rules) is shown with its digits redacted,
because a number in prose has no verifiable source; the tagged tables carry the figures.

Two builders share one renderer:
  * build_from_council(ai_res)          live result of HedgeFundCouncil.run_council
  * build_from_pit(snapshot, ticker, i) offline, point-in-time, deterministic (walk-forward event)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from core.reporting.tagged import Tagged, assumption, fact, untagged_numbers

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports")
_DIGITS = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def redact_numbers(text: str) -> str:
    """Replace numeric tokens in model prose with '‹n›' (no unsourced numbers in reports)."""
    return _DIGITS.sub("‹n›", str(text or "")).replace("\n", " ")


@dataclass
class Row:
    label: str
    value: Union[Tagged, str]


@dataclass
class Section:
    heading: str
    rows: List[Row] = field(default_factory=list)
    note: str = ""

    def add(self, label: str, value: Union[Tagged, str]) -> "Section":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            raise TypeError(f"{label}: raw number — wrap it in fact()/assumption()")
        if isinstance(value, str):
            value = redact_numbers(value)
        self.rows.append(Row(label, value))
        return self

    def text(self, label: str, value: str) -> "Section":
        """Categorical / prose cell (digits are redacted)."""
        return self.add(label, str(value))


@dataclass
class Report:
    title: str
    as_of: str
    sections: List[Section] = field(default_factory=list)
    header_notes: List[str] = field(default_factory=list)

    def section(self, heading: str, note: str = "") -> Section:
        s = Section(heading, note=note)
        self.sections.append(s)
        return s

    def tagged_values(self) -> List[Tagged]:
        return [r.value for s in self.sections for r in s.rows if isinstance(r.value, Tagged)]

    def to_markdown(self) -> str:
        L = [f"# {self.title}", "", f"Report as of: {self.as_of} <!-- text-only -->", ""]
        # header notes are code-generated provenance (snapshot ids, dates), never model text
        L += [f"> {n} <!-- text-only -->" for n in self.header_notes]
        L += ["", "Legend: `value [SOURCED FACT · source, as_of]` = observed or deterministically computed from sourced data; "
              "`[MODEL ASSUMPTION · …]` = forecast, score or rule output. Numbers in model prose are redacted as ‹n›.", ""]
        for s in self.sections:
            L += [f"## {s.heading}", ""]
            if s.note:
                L += [f"_{redact_numbers(s.note)}_", ""]
            L += ["| item | value |", "|---|---|"]
            for r in s.rows:
                cell = r.value.render(with_label=False) if isinstance(r.value, Tagged) else r.value
                L.append(f"| {r.label} | {cell.replace('|', '/')} |")
            L.append("")
        md = "\n".join(L)
        bad = untagged_numbers(md)
        if bad:
            raise ValueError(f"untagged numbers in report: {bad[:5]}")
        return md

    def save(self, filename: str, out_dir: str = REPORTS_DIR) -> str:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, filename)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(self.to_markdown())
        return path


# ---------------------------------------------------------------------------
# Shared section builders
# ---------------------------------------------------------------------------

def _council_sections(rep: Report, analysts: List[Dict[str, Any]], risk: Dict[str, Any], verdict: Dict[str, Any],
                      as_of: str, llm_mode: str) -> None:
    src_agents = f"Lumina agents (LUMINA_LLM_MODE={llm_mode}); score = llm_guard stance map or persona rule"
    sec = rep.section("Council views — MODEL ASSUMPTION",
                      note="Stances are categorical model judgements; scores are deterministic (stance map / persona rules), never LLM numbers.")
    for a in analysts:
        sec.text(f"{a.get('name', a.get('agent_id'))} stance", str(a.get("stance", "")))
        sec.add(f"{a.get('name', a.get('agent_id'))} score", assumption(a.get("score"), src_agents, as_of, decimals=0))
    r = rep.section("Risk (CRO) — MODEL ASSUMPTION", note="Rule outputs of RiskManagerAgent (ATR floor, veto rules).")
    r.text("veto", "YES — " + str(risk.get("veto_reason", "")) if risk.get("veto_triggered") else "no")
    r.add("stop-loss price", assumption(risk.get("stop_loss_price"), "RiskManagerAgent ATR/dynamic stop rule", as_of))
    r.add("max allocation", assumption(risk.get("max_allocation_pct"), "RiskManagerAgent allocation rule", as_of, unit="%", decimals=1))
    r.add("safety score", assumption(risk.get("score"), "RiskManagerAgent volatility rule", as_of, decimals=0))
    v = rep.section("Verdict — MODEL ASSUMPTION", note="PortfolioManagerAgent weighted scores → action thresholds.")
    v.text("action", str(verdict.get("action", "")))
    v.add("confidence score", assumption(verdict.get("confidence_score"), "PortfolioManagerAgent weighted mean of agent scores", as_of, decimals=0))
    v.add("allocation", assumption(verdict.get("allocation_pct"), "PortfolioManagerAgent (capped by CRO)", as_of, unit="%", decimals=1))
    v.add("target price", assumption(verdict.get("target_price"), "PortfolioManagerAgent fixed multiple of price", as_of))
    v.add("stop-loss price", assumption(verdict.get("stop_loss_price"), "CRO stop, exchange-tick rounded", as_of))
    v.text("degraded mode", "yes" if verdict.get("degraded_mode") else "no")
    if verdict.get("thesis_summary"):
        v.text("thesis (model prose)", str(verdict["thesis_summary"])[:600])


def _risk_metric_rows(sec: Section, det: Dict[str, Any], src: str, as_of: str) -> None:
    sec.add("volatility 20d (ann.)", fact(det.get("volatility_20d_annualized_pct"), src, as_of, unit="%", decimals=1))
    sec.add("max drawdown 1y", fact(det.get("max_drawdown_pct"), src, as_of, unit="%", decimals=1))
    sec.add("Sharpe 1y (rf assumption 4%)", fact(det.get("sharpe_ratio_1y"), src, as_of))
    sec.add("RSI 14", fact(det.get("rsi_14"), src, as_of, decimals=1))
    sec.add("VaR 95% 1d (historical)", fact(det.get("var_95_daily_pct"), src, as_of, unit="%"))
    sec.add("52w high", fact(det.get("high_52w"), src, as_of))
    sec.add("52w low", fact(det.get("low_52w"), src, as_of))


# ---------------------------------------------------------------------------
# Live council result
# ---------------------------------------------------------------------------

def build_from_council(ai_res: Dict[str, Any]) -> Report:
    from core.llm_mode import get_llm_mode
    sd = ai_res.get("stock_data", {}) or {}
    sym = ai_res.get("symbol") or sd.get("symbol", "?")
    as_of = str(sd.get("fetched_at") or ai_res.get("timestamp") or "")[:10] or "1970-01-01"
    rep = Report(f"Council report — {sym}", as_of, header_notes=[
        "Live mode: market data are snapshots fetched at report time (yfinance Ticker.info). "
        "Not point-in-time; do not use for backtesting."])
    info = "yfinance Ticker.info"
    hist = "computed from yfinance 1y daily history"
    m = rep.section("Market & fundamentals — SOURCED FACT")
    m.add("price", fact(ai_res.get("current_price") or sd.get("current_price"), info, as_of))
    m.text("currency", str(sd.get("currency", "")))
    m.add("market cap", fact(sd.get("market_cap"), info, as_of, decimals=0))
    m.add("P/E (trailing)", fact(sd.get("pe_trailing"), info, as_of, decimals=1))
    m.add("P/B", fact(sd.get("pb_ratio"), info, as_of))
    m.add("ROE", fact(sd.get("roe"), info, as_of, unit="%", decimals=1))
    m.add("revenue growth (YoY)", fact(sd.get("revenue_growth"), info, as_of, unit="%", decimals=1))
    m.add("dividend yield", fact(sd.get("dividend_yield"), info, as_of, unit="%"))
    hm = sd.get("history_metrics", {}) or {}
    m.add("ATR(14) % of price", fact(hm.get("atr_pct"), hist, as_of))
    det = (ai_res.get("deterministic_metrics") or {})
    if det:
        _risk_metric_rows(rep.section("Risk metrics — SOURCED FACT (deterministic)"), det, "DeterministicMetrics on yfinance history", as_of)
    f = rep.section("Forecasts — MODEL ASSUMPTION",
                    note="'TimesFM' here is a momentum + analyst-target heuristic, not Google TimesFM; LightGBM gate is trained on synthetic data.")
    tf = ai_res.get("timesfm_forecast", {}) or {}
    ch = ai_res.get("chronos_forecast", {}) or {}
    f.add("heuristic 'TimesFM' expected 5d return", assumption(tf.get("expected_return_pct"), "timesfm_forecaster (heuristic drift)", as_of, unit="%"))
    f.add("heuristic 'TimesFM' downside probability", assumption(tf.get("downside_risk_prob"), "timesfm_forecaster", as_of, unit="%", decimals=1))
    f.add("Chronos expected 5d return", assumption(ch.get("expected_return_pct"), "chronos_forecaster (model or heuristic fallback)", as_of, unit="%"))
    lg = (ai_res.get("dual_quantum", {}) or {}).get("lightgbm_gate") or ai_res.get("lightgbm_gatekeeper") or {}
    if lg:
        f.add("LightGBM 'win probability' (synthetic calibration)", assumption(lg.get("win_probability"), "lightgbm_gatekeeper (non-empirical)", as_of, unit="%", decimals=1))
    dialogues = [d for d in ai_res.get("council_dialogues", []) if d.get("agent_id") != "risk_manager"]
    risk = next((d for d in ai_res.get("council_dialogues", []) if d.get("agent_id") == "risk_manager"), {})
    _council_sections(rep, dialogues, risk, ai_res.get("verdict", {}) or {}, as_of, get_llm_mode())
    return rep


# ---------------------------------------------------------------------------
# Offline point-in-time report from the walk-forward snapshot
# ---------------------------------------------------------------------------

def build_from_pit(snapshot_root: str, ticker: str, event_index: int = -1) -> Report:
    import pandas as pd
    from backtest import walkforward as wf
    from backtest.pit import Snapshot, decision_session
    from core.ai_hedge_fund.agents import ALL_ANALYST_AGENTS, PortfolioManagerAgent, RiskManagerAgent

    snap = Snapshot.load(snapshot_root)
    ev = snap.events[ticker][event_index]
    D = decision_session(snap.sessions(ticker), ev["announced_at_et"])
    inp = wf.build_inputs(snap, ticker, D, ev["announced_at_et"])
    asof = inp["features_through"]
    sid = snap.snapshot_id
    rep = Report(f"Point-in-time council report — {ticker} before earnings {ev['announced_at_et']} ET", asof, header_notes=[
        f"Built from frozen snapshot {sid}: prices through the close of {asof}; filings accepted before the announcement.",
        "LLM mode: mock (deterministic persona rules)."])
    px_src = f"yfinance adjusted close (snapshot {sid})"
    m = rep.section("Market & fundamentals — SOURCED FACT")
    m.add("price (adjusted close, D-1)", fact(inp["stock"]["current_price"], px_src, asof))
    tags = inp["fund_tags"]
    for key, label, unit, dec in (("pe_trailing", "P/E (TTM)", "", 1), ("pb_ratio", "P/B", "", 2),
                                  ("roe", "ROE (TTM)", "%", 1), ("revenue_growth", "revenue growth (YoY YTD)", "%", 1)):
        tg = tags.get(key, {})
        m.add(label, fact(inp["stock"][key], tg.get("source", "finnhub financials-reported (missing)"),
                          tg.get("as_of", asof), unit=unit, decimals=dec))
    m.add("VIX close (D-1)", fact(inp["vix"], px_src.replace("adjusted close", "^VIX close"), asof))
    m.add("ATR(14) % of price", fact(inp["stock"]["history_metrics"].get("atr_pct"), "computed from snapshot OHLC", asof))
    _risk_metric_rows(rep.section("Risk metrics — SOURCED FACT (deterministic)"), inp["det"],
                      "DeterministicMetrics on snapshot prices", asof)
    q = rep.section("Alpha158 factors — SOURCED FACT (deterministic)")
    for k in ("ROC5", "ROC20", "ROC60", "MA20", "STD20", "RSV20", "RSQR20", "CORR20"):
        q.add(k, fact(inp["alpha158"].get(k), "Alpha158Engine on snapshot OHLCV", asof, decimals=4))
    stock, ctx = dict(inp["stock"]), dict(inp["context"])
    with wf.pit_market_turbulence(inp["vix"]), wf._quiet():
        analysts = [a.evaluate(stock, ctx) for a in ALL_ANALYST_AGENTS]
        risk = RiskManagerAgent.evaluate_risk(stock, analysts, ctx)
        syn = PortfolioManagerAgent.synthesize_verdict(stock, analysts, risk, ctx)
    _council_sections(rep, analysts, risk, syn["verdict"], asof, "mock")
    # Outcome after the fact — clearly separated, for post-mortem only
    o = rep.section("Outcome (after decision; post-mortem only) — SOURCED FACT")
    sessions = snap.sessions(ticker)
    i0 = sessions.get_loc(D)
    for h in (1, 5, 20):
        if i0 + h < len(sessions):
            d_exit = sessions[i0 + h]
            r = (snap.close_on(ticker, d_exit) / snap.close_on(ticker, D) - 1) * 100
            o.add(f"return close D → D+{h}", fact(r, px_src, str(d_exit.date()), unit="%"))
    return rep
