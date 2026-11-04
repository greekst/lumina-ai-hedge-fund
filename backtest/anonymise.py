# -*- coding: utf-8 -*-
"""
backtest/anonymise.py — what an LLM may see in the Session 2 live-council test.

The prompt never contains: ticker, company name, CIK, product names, absolute prices or price
levels, absolute dates, calendar quarters, news, or raw VIX. It contains: a stable code
(CO-###), the GICS sector, valuation ratios, return/volatility features and a VIX regime label,
all computed point-in-time by the harness (backtest.walkforward.build_inputs).

Levels (strengthened only if the leakage check fails):
  1  ratios rounded (P/E, ROE, growth to integers; technicals to one decimal)
  2  fundamentals in coarse bands; technicals rounded to integers; 52-week position banded
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

BANDS = {
    "pe_trailing": [(None, 0, "negative earnings"), (0, 12, "below 12"), (12, 18, "12 to 18"), (18, 25, "18 to 25"),
                    (25, 40, "25 to 40"), (40, None, "above 40")],
    "pb_ratio": [(None, 1.5, "below 1.5"), (1.5, 4, "1.5 to 4"), (4, 10, "4 to 10"), (10, None, "above 10")],
    "roe": [(None, 0, "negative"), (0, 10, "0 to 10 percent"), (10, 20, "10 to 20 percent"),
            (20, 35, "20 to 35 percent"), (35, None, "above 35 percent")],
    "revenue_growth": [(None, -5, "shrinking more than 5 percent"), (-5, 3, "roughly flat (-5 to 3 percent)"),
                       (3, 10, "3 to 10 percent"), (10, 25, "10 to 25 percent"), (25, None, "above 25 percent")],
}


def company_code(ticker: str, universe: List[str]) -> str:
    """Stable, non-alphabetical code: rank of sha256(salt+ticker) within the universe."""
    order = sorted(universe, key=lambda t: hashlib.sha256(f"lumina-s2|{t}".encode()).hexdigest())
    return f"CO-{order.index(ticker) + 1:03d}"


def _band(name: str, v: Optional[float]) -> str:
    if v is None:
        return "not available"
    for lo, hi, label in BANDS[name]:
        if (lo is None or v >= lo) and (hi is None or v < hi):
            return label
    return "not available"


def _r(v: Any, nd: int) -> str:
    if v is None:
        return "not available"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "not available"
    return f"{x:.{nd}f}" if nd > 0 else f"{x:.0f}"


def features(inp: Dict[str, Any], level: int) -> Dict[str, str]:
    st, hm, det, a = inp["stock"], inp["stock"].get("history_metrics", {}), inp["det"], inp["alpha158"]
    px = st.get("current_price") or 0.0

    def dist(ma: Optional[float]) -> Optional[float]:
        return (px / ma - 1.0) * 100.0 if ma and px else None

    tech_nd = 1 if level == 1 else 0
    f: Dict[str, str] = {}
    if level == 1:
        f["Trailing P/E"] = _r(st.get("pe_trailing"), 0)
        f["Price/Book"] = _r(st.get("pb_ratio"), 1)
        f["ROE (TTM, %)"] = _r(st.get("roe"), 0)
        f["Revenue growth YoY (%)"] = _r(st.get("revenue_growth"), 0)
    else:
        f["Trailing P/E"] = _band("pe_trailing", st.get("pe_trailing"))
        f["Price/Book"] = _band("pb_ratio", st.get("pb_ratio"))
        f["ROE (TTM)"] = _band("roe", st.get("roe"))
        f["Revenue growth YoY"] = _band("revenue_growth", st.get("revenue_growth"))
    f["Return over last 20 sessions (%)"] = _r(hm.get("return_20d_pct"), tech_nd)
    f["Return over last 60 sessions (%)"] = _r((a.get("ROC60") or 0.0) * 100.0 if "ROC60" in a else None, tech_nd)
    f["Price vs 20-session average (%)"] = _r(dist(hm.get("sma_20")), tech_nd)
    f["Price vs 50-session average (%)"] = _r(dist(hm.get("sma_50")), tech_nd)
    f["Price vs 200-session average (%)"] = _r(dist(hm.get("sma_200")), tech_nd)
    f["Annualised volatility, 1 year (%)"] = _r(hm.get("volatility_annualized_pct"), 0)
    f["Average true range, 14 sessions (% of price)"] = _r(hm.get("atr_pct"), tech_nd)
    f["RSI (14)"] = _r(det.get("rsi_14"), 0)
    f["Max drawdown over 1 year (%)"] = _r(det.get("max_drawdown_pct"), 0)
    f["Sharpe ratio, 1 year"] = _r(det.get("sharpe_ratio_1y"), 1)
    d52 = det.get("dist_from_52w_high_pct")
    if level == 1:
        f["Distance from 52-week high (%)"] = _r(d52, 0)
    else:
        f["Distance from 52-week high"] = ("not available" if d52 is None else
                                           "within 5 percent" if d52 > -5 else "5 to 15 percent below" if d52 > -15
                                           else "more than 15 percent below")
    v = inp.get("vix")
    f["Market volatility regime (VIX on D-1)"] = ("not available" if v is None else "calm (below 15)" if v < 15
                                                 else "normal (15 to 25)" if v < 25 else "stressed (above 25)")
    return f


def data_block(inp: Dict[str, Any], code: str, sector: str, level: int) -> str:
    lines = [f"Company: {code} (anonymised; identity, product names, prices and dates removed)",
             f"Sector: {sector}",
             "Timing: day D is the last trading session before this company's next quarterly earnings release. "
             "All data below are as of the close of D-1. The position, if any, is opened at the close of D.",
             "Data:"]
    lines += [f"- {k}: {v}" for k, v in features(inp, level).items()]
    lines.append("- Recent news: none available")
    return "\n".join(lines)


LEAK_SYSTEM = ("You are an equity analyst. Answer with JSON only. Always give your best guesses even when unsure.")


def leak_prompt(block: str) -> str:
    return (block + "\n\nThis profile describes a real US-listed large-cap company at a real point in time. "
            "Identify it. Return JSON: {\"guesses\": [{\"ticker\": \"...\", \"company\": \"...\"}, ... three guesses, "
            "most likely first], \"year\": 2024, \"quarter\": \"Q1\"} where year/quarter is your best guess of the "
            "calendar quarter in which day D falls.")


def persona_prompt(block: str) -> str:
    return (block + "\n\n上記の匿名化データのみを元に、あなたの投資哲学に基づき、この銘柄に D の終値で新規の買いポジションを"
            "取るべきか審査してください。指定のJSONフォーマットのみで回答してください（stance は "
            "BULLISH / ACCUMULATE / NEUTRAL / BEARISH / CAUTION のいずれか）。")
