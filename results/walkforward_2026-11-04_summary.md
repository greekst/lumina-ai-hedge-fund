# Walk-forward earnings backtest — snapshot 2026-11-04

All figures: SOURCED FACT inputs from the snapshot (prices: yfinance adjusted; fundamentals: Finnhub as-reported, PIT by acceptedDate; events: yfinance earnings dates) — source: `backtest/snapshots/2026-11-04`, as_of: 2026-11-04. Strategy outputs are MODEL ASSUMPTION / backtest results.

Costs: 5 bps commission + 5 bps slippage per side (long-only). Council runs with LUMINA_LLM_MODE=mock (deterministic persona rules; no LLM calls).

| strategy | h | events | longs | hit rate | long hit | avg net | avg excess vs SPY | Sharpe (q, ann.) | max DD (q) |
|---|---|---|---|---|---|---|---|---|---|
| council | T+1 | 120 | 102 | 48.33% | 45.10% | +0.03% | -0.01% | 0.04 | -5.16% |
| council | T+5 | 120 | 102 | 52.50% | 53.92% | +0.37% | -0.09% | 0.31 | -6.73% |
| council | T+20 | 120 | 102 | 50.83% | 52.94% | +1.99% | -0.39% | 1.12 | -3.84% |
| factors_only | T+1 | 120 | 63 | 45.83% | 39.68% | +0.00% | +0.02% | 0.00 | -3.14% |
| factors_only | T+5 | 120 | 63 | 43.33% | 47.62% | +0.06% | -0.22% | 0.08 | -3.14% |
| factors_only | T+20 | 120 | 63 | 46.67% | 50.79% | +1.09% | -0.04% | 0.87 | -3.44% |
| buy_and_hold | T+1 | 120 | 120 | 43.33% | 43.33% | +0.18% | +0.16% | 0.23 | -3.40% |
| buy_and_hold | T+5 | 120 | 120 | 54.17% | 54.17% | +0.47% | -0.04% | 0.38 | -5.66% |
| buy_and_hold | T+20 | 120 | 120 | 54.17% | 54.17% | +2.40% | -0.43% | 1.38 | -3.31% |

## Council marginal contribution vs factors-only (paired by event)

| h | mean(council − factors) | 95% bootstrap CI | decisions differ |
|---|---|---|---|
| T+1 | +0.03% | [-0.63%, +0.72%] | 51% |
| T+5 | +0.31% | [-0.57%, +1.27%] | 51% |
| T+20 | +0.90% | [-0.15%, +2.01%] | 51% |

## By quarter (T+5 avg net return / hit rate)

| quarter | council | factors_only | buy_and_hold |
|---|---|---|---|
| 2023Q4 | +0.74% / 50% (n=10, long=9) | -1.46% / 20% (n=10, long=2) | +1.07% / 60% (n=10, long=10) |
| 2024Q1 | +3.99% / 70% (n=10, long=8) | +3.72% / 50% (n=10, long=8) | +4.12% / 70% (n=10, long=10) |
| 2024Q2 | +2.09% / 60% (n=10, long=8) | +1.09% / 40% (n=10, long=4) | +1.93% / 60% (n=10, long=10) |
| 2024Q3 | -2.54% / 30% (n=10, long=7) | -1.38% / 70% (n=10, long=5) | -3.70% / 40% (n=10, long=10) |
| 2024Q4 | +0.64% / 50% (n=10, long=9) | +0.24% / 30% (n=10, long=7) | +0.90% / 60% (n=10, long=10) |
| 2025Q1 | -2.37% / 30% (n=10, long=9) | -1.29% / 40% (n=10, long=6) | -1.85% / 40% (n=10, long=10) |
| 2025Q2 | +0.97% / 70% (n=10, long=9) | +0.30% / 20% (n=10, long=2) | +2.12% / 80% (n=10, long=10) |
| 2025Q3 | +1.35% / 60% (n=10, long=8) | -0.21% / 50% (n=10, long=7) | +1.23% / 60% (n=10, long=10) |
| 2025Q4 | -1.42% / 50% (n=10, long=8) | +0.58% / 70% (n=10, long=6) | -1.47% / 30% (n=10, long=10) |
| 2026Q1 | -3.45% / 40% (n=10, long=9) | -1.39% / 40% (n=10, long=5) | -2.88% / 50% (n=10, long=10) |
| 2026Q2 | +0.71% / 60% (n=10, long=9) | +1.49% / 70% (n=10, long=6) | +0.39% / 50% (n=10, long=10) |
| 2026Q3 | +3.77% / 60% (n=10, long=9) | -0.92% / 20% (n=10, long=5) | +3.82% / 50% (n=10, long=10) |

TradingAgents baseline: **skipped** — no offline/mock mode (LLM-only); see `backtest/tradingagents_adapter.py`.
