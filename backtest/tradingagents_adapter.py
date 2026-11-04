# -*- coding: utf-8 -*-
"""
Adapter for TauricResearch/TradingAgents as a walk-forward baseline — NOT RUN.

Assessment (2026-11-04, vendor/TradingAgents @ shallow clone):
  * Every decision is produced by LLM agents (langchain chat models: OpenAI/Anthropic/Google/...);
    there is no offline, mock or rule-based mode. A fake chat model would only test plumbing,
    not the baseline, so it would be a misleading number.
  * Its data layer fetches live data (yfinance/Alpha Vantage/news) itself; feeding it this
    harness's frozen snapshot would require patching its dataflow vendors.
  * Requires Python >= 3.11 and pandas >= 3.0.6, conflicting with this repo's pin (pandas 2.3.3);
    it must run in its own virtualenv / subprocess.
  * LLM backtests over 2023-2026 also carry *training-data look-ahead*: the model may already
    know how each earnings event played out.
Per the brief ("if it can't run in mock mode, document and skip rather than spend on live
LLM calls") the baseline is skipped. To enable it later, implement `decide()` to call
`TradingAgentsGraph(config).propagate(ticker, str(D_minus_1))` in a separate venv with a
date-capped data vendor, map its BUY/HOLD/SELL to long/flat, and register it in
`walkforward.DECIDERS`.
"""

AVAILABLE = False
REASON = "TradingAgents has no offline/mock mode (LLM-only); skipped to avoid live LLM spend and LLM look-ahead."


def decide(_inputs):
    raise NotImplementedError(REASON)
